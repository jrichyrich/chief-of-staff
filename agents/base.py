# agents/base.py
import inspect
import json
import time
from datetime import date, datetime
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
        self._system_prompt_cache: str | None = None

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
        # Cache system prompt once per execute() — avoids rebuilding (and
        # re-querying the DB) on every API round.
        self._system_prompt_cache = self.build_system_prompt()

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
            "system": self._system_prompt_cache or self.build_system_prompt(),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        start = time.monotonic()
        response = await self.client.messages.create(**kwargs)
        duration_ms = int((time.monotonic() - start) * 1000)

        # Log API usage — never break the agent on failure
        try:
            if self.memory_store is not None:
                usage = response.usage
                self.memory_store.log_api_call(
                    model_id=model_id,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_input_tokens=getattr(usage, 'cache_creation_input_tokens', 0) or 0,
                    cache_read_input_tokens=getattr(usage, 'cache_read_input_tokens', 0) or 0,
                    duration_ms=duration_ms,
                    agent_name=self.name,
                    caller="base_agent",
                )
        except Exception:
            pass  # Never break agent execution

        return response

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
            "web_scroll": self._handle_web_scroll,
            "web_find": self._handle_web_find,
            "web_state_save": self._handle_web_state_save,
            "web_state_load": self._handle_web_state_load,
            # Scheduling (calendar availability)
            "find_my_open_slots": self._handle_find_my_open_slots,
            "find_group_availability": self._handle_find_group_availability,
            # Teams (browser-based)
            "open_teams_browser": self._handle_open_teams_browser,
            "post_teams_message": self._handle_post_teams_message,
            "confirm_teams_post": self._handle_confirm_teams_post,
            "cancel_teams_post": self._handle_cancel_teams_post,
            "close_teams_browser": self._handle_close_teams_browser,
            # Agent memory
            "get_agent_memory": self._handle_get_agent_memory,
            "clear_agent_memory": self._handle_clear_agent_memory,
            # Channel tools
            "list_inbound_events": self._handle_list_inbound_events,
            "get_event_summary": self._handle_get_event_summary,
            # Proactive tools
            "get_proactive_suggestions": self._handle_get_proactive_suggestions,
            "dismiss_suggestion": self._handle_dismiss_suggestion,
            # Webhook tools
            "list_webhook_events": self._handle_list_webhook_events,
            "get_webhook_event": self._handle_get_webhook_event,
            "process_webhook_event": self._handle_process_webhook_event,
            # Scheduler tools
            "list_scheduled_tasks": self._handle_list_scheduled_tasks,
            "get_scheduler_status": self._handle_get_scheduler_status,
            "create_scheduled_task": self._handle_create_scheduled_task,
            "update_scheduled_task": self._handle_update_scheduled_task,
            "delete_scheduled_task": self._handle_delete_scheduled_task,
            "run_scheduled_task": self._handle_run_scheduled_task,
            # Skill tools
            "list_skill_suggestions": self._handle_list_skill_suggestions,
            "record_tool_usage": self._handle_record_tool_usage,
            "analyze_skill_patterns": self._handle_analyze_skill_patterns,
            "auto_create_skill": self._handle_auto_create_skill,
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

    # ------------------------------------------------------------------
    # Scheduling handlers
    # ------------------------------------------------------------------

    def _handle_find_my_open_slots(self, tool_input: dict) -> Any:
        if self.calendar_store is None:
            return {"error": "Calendar not available (macOS only)"}
        from datetime import time as dt_time
        from scheduler.availability import find_available_slots, format_slots_for_sharing

        start_date = tool_input["start_date"]
        end_date = tool_input["end_date"]
        duration_minutes = tool_input.get("duration_minutes", 30)
        include_soft_blocks = tool_input.get("include_soft_blocks", True)
        soft_keywords_raw = tool_input.get("soft_keywords", "")
        calendar_name = tool_input.get("calendar_name", "")
        wh_start = tool_input.get("working_hours_start", "08:00")
        wh_end = tool_input.get("working_hours_end", "18:00")
        provider_preference = tool_input.get("provider_preference", "both")

        sh, sm = map(int, wh_start.split(":"))
        eh, em = map(int, wh_end.split(":"))
        working_start = dt_time(sh, sm)
        working_end = dt_time(eh, em)
        keywords = None
        if soft_keywords_raw:
            keywords = [kw.strip() for kw in soft_keywords_raw.split(",") if kw.strip()]

        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
        calendar_names = [calendar_name] if calendar_name else None
        kwargs = {"calendar_names": calendar_names}
        if provider_preference and provider_preference != "auto":
            kwargs["provider_preference"] = provider_preference
        events = self.calendar_store.get_events(start_dt, end_dt, **kwargs)

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=duration_minutes,
            working_hours_start=working_start,
            working_hours_end=working_end,
            timezone_name=app_config.USER_TIMEZONE,
            include_soft_blocks=include_soft_blocks,
            soft_keywords=keywords,
        )
        formatted_text = format_slots_for_sharing(slots, timezone_name=app_config.USER_TIMEZONE)
        return {"slots": slots, "formatted_text": formatted_text, "count": len(slots)}

    def _handle_find_group_availability(self, tool_input: dict) -> Any:
        participants = tool_input["participants"]
        start_date = tool_input["start_date"]
        end_date = tool_input["end_date"]
        duration_minutes = tool_input.get("duration_minutes", 30)
        include_my_soft_blocks = tool_input.get("include_my_soft_blocks", True)
        max_suggestions = tool_input.get("max_suggestions", 5)
        return {
            "status": "guidance",
            "message": "This is a guidance tool. Follow the workflow below:",
            "workflow": [
                {
                    "step": 1,
                    "description": "Check group availability via Microsoft 365 MCP",
                    "tool": "mcp__claude_ai_Microsoft_365__find_meeting_availability",
                    "parameters": {
                        "attendees": participants,
                        "isOrganizerOptional": True,
                        "duration": duration_minutes,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                },
                {
                    "step": 2,
                    "description": "Check your REAL availability with soft block logic",
                    "tool": "find_my_open_slots",
                    "parameters": {
                        "start_date": start_date,
                        "end_date": end_date,
                        "duration_minutes": duration_minutes,
                        "include_soft_blocks": include_my_soft_blocks,
                    },
                },
                {
                    "step": 3,
                    "description": "Cross-reference the two result sets",
                    "suggestion": f"Return the top {max_suggestions} matching slots",
                },
            ],
            "parameters_provided": {
                "participants": participants,
                "start_date": start_date,
                "end_date": end_date,
                "duration_minutes": duration_minutes,
                "include_my_soft_blocks": include_my_soft_blocks,
                "max_suggestions": max_suggestions,
            },
        }

    # ------------------------------------------------------------------
    # Teams handlers (async — browser-based)
    # ------------------------------------------------------------------

    async def _handle_open_teams_browser(self, tool_input: dict = None) -> Any:
        from mcp_tools.teams_browser_tools import _get_send_backend, _get_ab, _get_manager, _wait_for_teams
        backend = _get_send_backend()
        if backend == "agent-browser":
            ab = _get_ab()
            try:
                await ab.open("https://teams.microsoft.com")
                return {"status": "running", "backend": "agent-browser"}
            except Exception as exc:
                return {"status": "error", "error": str(exc)}
        else:
            mgr = _get_manager()
            result = mgr.launch()
            if result["status"] in ("launched", "already_running"):
                nav = await _wait_for_teams(mgr)
                if nav["ok"]:
                    result["status"] = "running"
                else:
                    result["status"] = "awaiting_action"
                    result["detail"] = nav.get("detail", "Teams navigation incomplete")
            return result

    async def _handle_post_teams_message(self, tool_input: dict) -> Any:
        from mcp_tools.teams_browser_tools import _get_poster
        poster = _get_poster()
        target = tool_input["target"]
        message = tool_input["message"]
        parsed_target = target
        if "," in target:
            names = [n.strip() for n in target.split(",") if n.strip()]
            if len(names) > 1:
                parsed_target = names
        result = await poster.prepare_message(parsed_target, message)
        return result

    async def _handle_confirm_teams_post(self, tool_input: dict = None) -> Any:
        from mcp_tools.teams_browser_tools import _get_poster
        poster = _get_poster()
        return await poster.send_prepared_message()

    async def _handle_cancel_teams_post(self, tool_input: dict = None) -> Any:
        from mcp_tools.teams_browser_tools import _get_poster
        poster = _get_poster()
        return await poster.cancel_prepared_message()

    async def _handle_close_teams_browser(self, tool_input: dict = None) -> Any:
        from mcp_tools.teams_browser_tools import _get_send_backend, _get_ab, _get_manager
        backend = _get_send_backend()
        if backend == "agent-browser":
            ab = _get_ab()
            try:
                await ab.close()
                return {"status": "closed", "backend": "agent-browser"}
            except Exception as exc:
                return {"status": "closed", "detail": str(exc)}
        else:
            mgr = _get_manager()
            return mgr.close()

    # ------------------------------------------------------------------
    # Agent memory handlers
    # ------------------------------------------------------------------

    def _handle_get_agent_memory(self, tool_input: dict) -> Any:
        agent_name = tool_input["agent_name"]
        try:
            memories = self.memory_store.get_agent_memories(agent_name)
        except Exception:
            memories = []
        if not memories:
            return {"message": f"No memories found for agent '{agent_name}'.", "results": []}
        return {
            "results": [
                {"key": m.key, "value": m.value, "memory_type": m.memory_type, "confidence": m.confidence}
                for m in memories
            ]
        }

    def _handle_clear_agent_memory(self, tool_input: dict) -> Any:
        agent_name = tool_input["agent_name"]
        try:
            self.memory_store.clear_agent_memories(agent_name)
            return {"status": "cleared", "agent_name": agent_name}
        except Exception as exc:
            return {"error": f"Failed to clear memories for '{agent_name}': {exc}"}

    # ------------------------------------------------------------------
    # Channel handlers
    # ------------------------------------------------------------------

    def _handle_list_inbound_events(self, tool_input: dict) -> Any:
        channel = tool_input.get("channel", "")
        event_type = tool_input.get("event_type", "")
        limit = max(1, min(tool_input.get("limit", 25), 100))

        from channels.adapter import adapt_event

        channels_to_query = [channel] if channel else ["imessage", "mail", "webhook"]
        all_events = []
        for ch in channels_to_query:
            raw_events = self._fetch_channel_events(ch, limit)
            for raw in raw_events:
                if "error" in raw:
                    continue
                try:
                    event = adapt_event(ch, raw)
                except (ValueError, KeyError):
                    continue
                if event_type and event.event_type != event_type:
                    continue
                all_events.append({
                    "channel": event.channel,
                    "source": event.source,
                    "event_type": event.event_type,
                    "content_preview": event.content[:200] if event.content else "",
                    "received_at": event.received_at,
                    "raw_id": event.raw_id,
                    "metadata": event.metadata,
                })
        all_events.sort(key=lambda e: e.get("received_at", ""), reverse=True)
        return {"results": all_events[:limit], "count": len(all_events)}

    def _handle_get_event_summary(self, tool_input: dict = None) -> Any:
        summary = {}
        for ch in ("imessage", "mail", "webhook"):
            raw_events = self._fetch_channel_events(ch, limit=100)
            summary[ch] = len([e for e in raw_events if "error" not in e])
        return {"summary": summary, "total": sum(summary.values())}

    def _fetch_channel_events(self, channel: str, limit: int) -> list:
        """Fetch raw events from a channel for agent dispatch."""
        try:
            if channel == "webhook":
                events = self.memory_store.list_webhook_events(limit=limit)
                return [
                    {
                        "id": e.id, "source": e.source, "event_type": e.event_type,
                        "payload": e.payload, "status": e.status, "received_at": e.received_at,
                    }
                    for e in events
                ]
            # iMessage and mail require platform stores the agent may not have
            return []
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Proactive handlers
    # ------------------------------------------------------------------

    def _handle_get_proactive_suggestions(self, tool_input: dict = None) -> Any:
        from proactive.engine import ProactiveSuggestionEngine
        try:
            engine = ProactiveSuggestionEngine(self.memory_store)
            suggestions = engine.generate_suggestions()
            if not suggestions:
                return {"message": "No suggestions at this time.", "suggestions": []}
            return {
                "suggestions": [
                    {
                        "category": s.category,
                        "priority": s.priority,
                        "title": s.title,
                        "description": s.description,
                        "action": s.action,
                        "created_at": s.created_at,
                    }
                    for s in suggestions
                ],
                "total": len(suggestions),
            }
        except Exception as exc:
            return {"error": f"Failed to generate suggestions: {exc}"}

    def _handle_dismiss_suggestion(self, tool_input: dict) -> Any:
        return {
            "status": "dismissed",
            "category": tool_input["category"],
            "title": tool_input["title"],
            "message": "Suggestion dismissed (note: persistent dismiss not yet implemented)",
        }

    # ------------------------------------------------------------------
    # Webhook handlers
    # ------------------------------------------------------------------

    def _handle_list_webhook_events(self, tool_input: dict) -> Any:
        status = tool_input.get("status", "")
        source = tool_input.get("source", "")
        limit = max(1, min(tool_input.get("limit", 50), 500))
        events = self.memory_store.list_webhook_events(
            status=status or None,
            source=source or None,
            limit=limit,
        )
        if not events:
            return {"message": "No webhook events found.", "results": []}
        return {
            "results": [
                {
                    "id": e.id, "source": e.source, "event_type": e.event_type,
                    "status": e.status, "received_at": e.received_at,
                    "processed_at": e.processed_at,
                }
                for e in events
            ],
            "count": len(events),
        }

    def _handle_get_webhook_event(self, tool_input: dict) -> Any:
        event_id = tool_input["event_id"]
        event = self.memory_store.get_webhook_event(event_id)
        if event is None:
            return {"error": f"Webhook event {event_id} not found"}
        payload = event.payload
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            pass
        return {
            "id": event.id, "source": event.source, "event_type": event.event_type,
            "payload": payload, "status": event.status, "received_at": event.received_at,
            "processed_at": event.processed_at,
        }

    def _handle_process_webhook_event(self, tool_input: dict) -> Any:
        event_id = tool_input["event_id"]
        event = self.memory_store.get_webhook_event(event_id)
        if event is None:
            return {"error": f"Webhook event {event_id} not found"}
        if event.status == "processed":
            return {"status": "already_processed", "id": event_id}
        updated = self.memory_store.update_webhook_event_status(event_id, "processed")
        return {"status": "processed", "id": updated.id, "processed_at": updated.processed_at}

    # ------------------------------------------------------------------
    # Scheduler handlers
    # ------------------------------------------------------------------

    def _handle_list_scheduled_tasks(self, tool_input: dict) -> Any:
        enabled_only = tool_input.get("enabled_only", False)
        tasks = self.memory_store.list_scheduled_tasks(enabled_only=enabled_only)
        return {
            "count": len(tasks),
            "tasks": [
                {
                    "id": t.id, "name": t.name, "description": t.description,
                    "schedule_type": t.schedule_type, "handler_type": t.handler_type,
                    "enabled": t.enabled, "last_run_at": t.last_run_at,
                    "next_run_at": t.next_run_at, "delivery_channel": t.delivery_channel,
                }
                for t in tasks
            ],
        }

    def _handle_get_scheduler_status(self, tool_input: dict = None) -> Any:
        tasks = self.memory_store.list_scheduled_tasks()
        now = datetime.now().isoformat()
        summary = []
        for t in tasks:
            overdue = bool(t.enabled and t.next_run_at and t.next_run_at <= now)
            summary.append({
                "id": t.id, "name": t.name, "enabled": t.enabled,
                "last_run_at": t.last_run_at, "next_run_at": t.next_run_at,
                "overdue": overdue,
            })
        return {"tasks": summary, "count": len(summary)}

    def _handle_create_scheduled_task(self, tool_input: dict) -> Any:
        from memory.models import ScheduleType, HandlerType, ScheduledTask
        from scheduler.engine import calculate_next_run
        name = tool_input["name"]
        schedule_type = tool_input["schedule_type"]
        schedule_config = tool_input["schedule_config"]
        handler_type = tool_input["handler_type"]
        handler_config = tool_input.get("handler_config", "")
        description = tool_input.get("description", "")
        enabled = tool_input.get("enabled", True)
        try:
            next_run = calculate_next_run(schedule_type, schedule_config)
        except ValueError as exc:
            return {"error": str(exc)}
        task = ScheduledTask(
            name=name,
            description=description,
            schedule_type=schedule_type,
            schedule_config=schedule_config,
            handler_type=handler_type,
            handler_config=handler_config,
            enabled=enabled,
            next_run_at=next_run,
        )
        stored = self.memory_store.store_scheduled_task(task)
        return {
            "status": "created",
            "task": {
                "id": stored.id, "name": stored.name,
                "schedule_type": stored.schedule_type,
                "handler_type": stored.handler_type,
                "enabled": stored.enabled,
                "next_run_at": stored.next_run_at,
            },
        }

    def _handle_update_scheduled_task(self, tool_input: dict) -> Any:
        from scheduler.engine import calculate_next_run
        task_id = tool_input["task_id"]
        task = self.memory_store.get_scheduled_task(task_id)
        if task is None:
            return {"error": f"Task {task_id} not found"}
        kwargs = {}
        if tool_input.get("enabled") is not None:
            kwargs["enabled"] = tool_input["enabled"]
        schedule_config = tool_input.get("schedule_config", "")
        if schedule_config:
            kwargs["schedule_config"] = schedule_config
            try:
                kwargs["next_run_at"] = calculate_next_run(task.schedule_type, schedule_config)
            except ValueError as exc:
                return {"error": str(exc)}
        handler_config = tool_input.get("handler_config", "")
        if handler_config:
            kwargs["handler_config"] = handler_config
        if not kwargs:
            return {"error": "No fields to update"}
        updated = self.memory_store.update_scheduled_task(task_id, **kwargs)
        if updated is None:
            return {"error": f"Task {task_id} not found"}
        return {
            "status": "updated",
            "task": {
                "id": updated.id, "name": updated.name,
                "enabled": updated.enabled, "next_run_at": updated.next_run_at,
            },
        }

    def _handle_delete_scheduled_task(self, tool_input: dict) -> Any:
        task_id = tool_input["task_id"]
        deleted = self.memory_store.delete_scheduled_task(task_id)
        return {"status": "deleted" if deleted else "not_found", "task_id": task_id}

    def _handle_run_scheduled_task(self, tool_input: dict) -> Any:
        task_id = tool_input["task_id"]
        task = self.memory_store.get_scheduled_task(task_id)
        if task is None:
            return {"error": f"Task {task_id} not found"}
        from scheduler.engine import execute_handler, calculate_next_run
        now = datetime.now()
        try:
            handler_result = execute_handler(
                task.handler_type, task.handler_config, self.memory_store,
            )
            next_run = calculate_next_run(task.schedule_type, task.schedule_config, from_time=now)
            self.memory_store.update_scheduled_task(
                task.id, last_run_at=now.isoformat(), next_run_at=next_run, last_result=handler_result,
            )
            return {"status": "executed", "task_id": task.id, "name": task.name, "result": handler_result, "next_run_at": next_run}
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            try:
                self.memory_store.update_scheduled_task(
                    task.id, last_run_at=now.isoformat(),
                    last_result=json.dumps({"status": "error", "error": error_msg}),
                )
            except Exception:
                pass
            return {"status": "error", "task_id": task.id, "error": error_msg}

    # ------------------------------------------------------------------
    # Skill handlers
    # ------------------------------------------------------------------

    def _handle_list_skill_suggestions(self, tool_input: dict) -> Any:
        status = tool_input.get("status", "pending")
        try:
            suggestions = self.memory_store.list_skill_suggestions(status)
            if not suggestions:
                return {"message": f"No {status} skill suggestions.", "results": []}
            return {
                "results": [
                    {
                        "id": s.id, "description": s.description,
                        "suggested_name": s.suggested_name,
                        "suggested_capabilities": s.suggested_capabilities,
                        "confidence": s.confidence, "status": s.status,
                        "created_at": s.created_at,
                    }
                    for s in suggestions
                ]
            }
        except Exception as exc:
            return {"error": f"Failed to list suggestions: {exc}"}

    def _handle_record_tool_usage(self, tool_input: dict) -> Any:
        try:
            self.memory_store.record_skill_usage(
                tool_input["tool_name"], tool_input["query_pattern"],
            )
            return {"status": "recorded", "tool_name": tool_input["tool_name"]}
        except Exception as exc:
            return {"error": f"Failed to record usage: {exc}"}

    def _handle_analyze_skill_patterns(self, tool_input: dict = None) -> Any:
        from skills.pattern_detector import PatternDetector
        from memory.models import SkillSuggestion
        import config as cfg
        try:
            detector = PatternDetector(self.memory_store)
            patterns = detector.detect_patterns(
                min_occurrences=cfg.SKILL_MIN_OCCURRENCES,
                confidence_threshold=cfg.SKILL_SUGGESTION_THRESHOLD,
            )
            if not patterns:
                return {"message": "No significant patterns detected.", "suggestions_created": 0}
            created = 0
            for pattern in patterns:
                suggestion = SkillSuggestion(
                    description=pattern["description"],
                    suggested_name=pattern["tool_name"].replace(" ", "_") + "_specialist",
                    suggested_capabilities=pattern["tool_name"],
                    confidence=pattern["confidence"],
                )
                self.memory_store.store_skill_suggestion(suggestion)
                created += 1
            return {"suggestions_created": created, "patterns": patterns}
        except Exception as exc:
            return {"error": f"Failed to analyze patterns: {exc}"}

    def _handle_auto_create_skill(self, tool_input: dict) -> Any:
        from agents.factory import AgentFactory
        from agents.registry import AgentRegistry
        suggestion_id = tool_input["suggestion_id"]
        try:
            suggestion = self.memory_store.get_skill_suggestion(suggestion_id)
            if not suggestion:
                return {"error": f"Suggestion {suggestion_id} not found."}
            if suggestion.status != "pending":
                return {"error": f"Suggestion {suggestion_id} is already {suggestion.status}."}
            # Build a temporary registry for the factory
            registry = AgentRegistry()
            factory = AgentFactory(registry, memory_store=self.memory_store)
            config = factory.create_agent(suggestion.description)
            self.memory_store.update_skill_suggestion_status(suggestion_id, "accepted")
            return {
                "status": "created",
                "agent_name": config.name,
                "description": config.description,
                "capabilities": config.capabilities,
                "suggestion_id": suggestion_id,
            }
        except Exception as exc:
            return {"error": f"Failed to create skill: {exc}"}
