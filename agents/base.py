# agents/base.py
import inspect
import json
from datetime import date
from typing import Any, Optional

import anthropic

import config as app_config
from config import MAX_TOOL_ROUNDS
from agents.loop_detector import LoopDetector
from agents.mixins import (
    CalendarMixin,
    LifecycleMixin,
    MailMixin,
    NotificationMixin,
    ReminderMixin,
    WebBrowserMixin,
)
from memory.models import AgentResultStatus


class AgentResult(str):
    """Agent execution result that behaves as a str for backward compat.

    Adds .status, .is_success, .is_error, .metadata properties so callers
    can distinguish successful text from error JSON without parsing.
    """

    def __new__(cls, text: str, *, status: AgentResultStatus = AgentResultStatus.success, metadata: dict | None = None):
        instance = super().__new__(cls, text)
        instance._status = AgentResultStatus(status)
        instance._metadata = metadata or {}
        return instance

    @property
    def status(self) -> AgentResultStatus:
        return self._status

    @property
    def is_success(self) -> bool:
        return self._status == AgentResultStatus.success

    @property
    def is_error(self) -> bool:
        return self._status != AgentResultStatus.success

    @property
    def metadata(self) -> dict:
        return self._metadata

MAX_TOOL_RESULT_LENGTH = 10000
from agents.registry import AgentConfig
from capabilities.registry import get_tools_for_capabilities
from documents.store import DocumentStore
from memory.store import MemoryStore
from tools.executor import execute_query_memory, execute_store_memory, execute_search_documents
from utils.retry import retry_api_call

class BaseExpertAgent(
    LifecycleMixin,
    CalendarMixin,
    ReminderMixin,
    NotificationMixin,
    MailMixin,
    WebBrowserMixin,
):
    """Expert agent with capability-gated tool dispatch.

    Domain-specific tool handlers are provided by mixins:
    - LifecycleMixin: decisions, delegations, alert rules
    - CalendarMixin: calendar events
    - ReminderMixin: reminders
    - NotificationMixin: macOS notifications
    - MailMixin: mail read/send/manage
    - WebBrowserMixin: general-purpose web browsing via agent-browser
    """

    def __init__(
        self,
        config: AgentConfig,
        memory_store: MemoryStore,
        document_store: DocumentStore,
        client: Optional[anthropic.AsyncAnthropic] = None,
        calendar_store=None,
        reminder_store=None,
        notifier=None,
        mail_store=None,
        hook_registry=None,
        agent_browser=None,
    ):
        self.config = config
        self.name = config.name
        self.memory_store = memory_store
        self.document_store = document_store
        self.calendar_store = calendar_store
        self.reminder_store = reminder_store
        self.notifier = notifier
        self.mail_store = mail_store
        self.hook_registry = hook_registry
        self.agent_browser = agent_browser
        self.client = client or anthropic.AsyncAnthropic(api_key=app_config.ANTHROPIC_API_KEY)
        self._dispatch_cache: dict | None = None

    def build_system_prompt(self) -> str:
        prompt = self.config.system_prompt

        # Inject runtime context: agent identity and current date
        today = date.today().isoformat()
        prompt += f"\n\n## Runtime Context\n- Agent name: {self.name}\n- Today's date: {today}"

        try:
            memories = self.memory_store.get_agent_memories(self.name)
        except Exception:
            memories = []
        if memories:
            lines = ["\n\n## Agent Memory (retained from previous runs)"]
            for m in memories:
                lines.append(f"- {m.key}: {m.value}")
            prompt += "\n".join(lines)

        # Inject shared namespace memories
        for ns in getattr(self.config, "namespaces", []):
            try:
                shared = self.memory_store.get_shared_memories(ns)
            except Exception:
                shared = []
            if shared:
                lines = [f"\n\n## Shared Memory [{ns}]"]
                for m in shared:
                    lines.append(f"- {m.key}: {m.value}")
                prompt += "\n".join(lines)
        return prompt

    def get_tools(self) -> list[dict]:
        return get_tools_for_capabilities(self.config.capabilities)

    async def execute(self, task: str) -> str:
        messages = [{"role": "user", "content": task}]
        tools = self.get_tools()
        loop_detector = LoopDetector()

        for _round in range(MAX_TOOL_ROUNDS):
            response = await self._call_api(messages, tools)

            # Check if the model wants to use a tool
            if response.stop_reason == "tool_use":
                # Process tool calls
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                should_break = False
                for block in assistant_content:
                    if block.type == "tool_use":
                        signal = loop_detector.record(block.name, block.input)
                        if signal == "break":
                            should_break = True
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"error": "Loop detected — repeated identical tool call. Stopping."}),
                            })
                            continue

                        result = self._handle_tool_call(block.name, block.input)
                        if inspect.isawaitable(result):
                            result = await result
                        result_str = json.dumps(result)
                        if len(result_str) > MAX_TOOL_RESULT_LENGTH:
                            result_str = result_str[:MAX_TOOL_RESULT_LENGTH] + "... [truncated]"

                        if signal == "warning":
                            result_str += "\n[SYSTEM: You are repeating the same tool call. Try a different approach.]"

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })

                if should_break:
                    messages.append({"role": "user", "content": tool_results})
                    text = json.dumps({"status": "loop_detected", "rounds": _round + 1, "message": "Agent terminated early: repetitive tool call loop detected"})
                    return AgentResult(text, status=AgentResultStatus.loop_detected, metadata={"rounds": _round + 1})

                messages.append({"role": "user", "content": tool_results})
                continue

            # Extract text response
            for block in response.content:
                if block.type == "text":
                    return AgentResult(block.text, status=AgentResultStatus.success)

            return AgentResult("", status=AgentResultStatus.success)

        text = json.dumps({"status": "max_rounds_reached", "rounds": MAX_TOOL_ROUNDS, "message": "Agent reached maximum tool rounds without producing a final response"})
        return AgentResult(text, status=AgentResultStatus.max_rounds_reached, metadata={"rounds": MAX_TOOL_ROUNDS})

    @retry_api_call
    async def _call_api(self, messages: list, tools: list) -> Any:
        model_id = app_config.MODEL_TIERS.get(
            self.config.model,
            app_config.MODEL_TIERS[app_config.DEFAULT_MODEL_TIER],
        )
        kwargs = {
            "model": model_id,
            "max_tokens": self.config.max_tokens,
            "system": self.build_system_prompt(),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        return await self.client.messages.create(**kwargs)

    def _fire_hooks(self, event_type: str, context: dict) -> list:
        """Fire hooks if a hook_registry is available. Error-isolated."""
        if self.hook_registry is None:
            return []
        try:
            return self.hook_registry.fire_hooks(event_type, context)
        except Exception:
            return []

    def _handle_tool_call(self, tool_name: str, tool_input: dict) -> Any:
        from hooks.registry import build_tool_context, extract_transformed_args

        # Fire before_tool_call hooks
        before_ctx = build_tool_context(
            tool_name=tool_name,
            tool_args=tool_input,
            agent_name=self.name,
        )
        hook_results = self._fire_hooks("before_tool_call", before_ctx)

        # Apply arg transformations from before_tool_call hooks
        transformed = extract_transformed_args(hook_results)
        if transformed is not None:
            tool_input = transformed

        # Enforce capability boundaries
        allowed_tools = {t["name"] for t in self.get_tools()}
        if tool_name not in allowed_tools:
            result = {"error": f"Tool '{tool_name}' not permitted for agent '{self.name}'"}
            after_ctx = build_tool_context(
                tool_name=tool_name,
                tool_args=tool_input,
                agent_name=self.name,
                result=result,
            )
            # Carry timestamp from before context so timing hooks can correlate
            after_ctx["timestamp"] = before_ctx["timestamp"]
            self._fire_hooks("after_tool_call", after_ctx)
            return result

        result = self._dispatch_tool(tool_name, tool_input)

        # Async handlers (e.g. web browser) return coroutines — bubble them
        # up to execute() which will await them. Skip after hooks here;
        # they'll fire with raw coroutine but that's acceptable since hooks
        # only use result for logging context.
        after_ctx = build_tool_context(
            tool_name=tool_name,
            tool_args=tool_input,
            agent_name=self.name,
            result=result,
        )
        # Carry timestamp from before context so timing hooks can correlate
        after_ctx["timestamp"] = before_ctx["timestamp"]
        self._fire_hooks("after_tool_call", after_ctx)

        return result

    def _get_dispatch_table(self) -> dict:
        """Build and cache a dispatch table mapping tool names to handlers."""
        if self._dispatch_cache is not None:
            return self._dispatch_cache

        table: dict[str, Any] = {
            # Memory & document tools
            "query_memory": lambda ti: execute_query_memory(
                self.memory_store, ti["query"], ti.get("category")
            ),
            "store_memory": lambda ti: execute_store_memory(
                self.memory_store, ti["category"], ti["key"], ti["value"],
                source=self.name,
            ),
            "search_documents": lambda ti: execute_search_documents(
                self.document_store, ti["query"], ti.get("top_k", 5)
            ),
            # Lifecycle — decisions (from LifecycleMixin)
            "create_decision": self._handle_create_decision,
            "search_decisions": self._handle_search_decisions,
            "update_decision": self._handle_update_decision,
            "list_pending_decisions": self._handle_list_pending_decisions,
            "delete_decision": self._handle_delete_decision,
            # Lifecycle — delegations (from LifecycleMixin)
            "create_delegation": self._handle_create_delegation,
            "list_delegations": self._handle_list_delegations,
            "update_delegation": self._handle_update_delegation,
            "check_overdue_delegations": self._handle_check_overdue_delegations,
            "delete_delegation": self._handle_delete_delegation,
            # Lifecycle — alerts (from LifecycleMixin)
            "create_alert_rule": self._handle_create_alert_rule,
            "list_alert_rules": self._handle_list_alert_rules,
            "check_alerts": self._handle_check_alerts,
            "dismiss_alert": self._handle_dismiss_alert,
            # Calendar (from CalendarMixin)
            "get_calendar_events": self._handle_calendar_get_events,
            "search_calendar_events": self._handle_calendar_search,
            # Reminders (from ReminderMixin)
            "list_reminders": self._handle_reminder_list,
            "search_reminders": self._handle_reminder_search,
            "create_reminder": self._handle_reminder_create,
            "complete_reminder": self._handle_reminder_complete,
            # Notifications (from NotificationMixin)
            "send_notification": self._handle_send_notification,
            # Mail (from MailMixin)
            "get_mail_messages": self._handle_mail_get_messages,
            "get_mail_message": self._handle_mail_get_message,
            "search_mail": self._handle_mail_search,
            "get_unread_count": self._handle_mail_get_unread_count,
            "send_email": self._handle_mail_send,
            "mark_mail_read": self._handle_mail_mark_read,
            "mark_mail_flagged": self._handle_mail_mark_flagged,
            "move_mail_message": self._handle_mail_move_message,
            # Web browser (from WebBrowserMixin) — async handlers
            "web_open": self._handle_web_open,
            "web_snapshot": self._handle_web_snapshot,
            "web_click": self._handle_web_click,
            "web_fill": self._handle_web_fill,
            "web_get_text": self._handle_web_get_text,
            "web_screenshot": self._handle_web_screenshot,
            "web_execute_js": self._handle_web_execute_js,
        }

        self._dispatch_cache = table
        return table

    def _dispatch_tool(self, tool_name: str, tool_input: dict) -> Any:
        """Route a tool call to the appropriate handler.

        Sync handlers return results directly. Async handlers (e.g. web
        browser) return coroutines that execute() will await.
        """
        table = self._get_dispatch_table()
        handler = table.get(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}
        return handler(tool_input)
