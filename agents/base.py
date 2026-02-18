# agents/base.py
import json
from typing import Any, Optional

import anthropic

import config as app_config
from config import MAX_TOOL_ROUNDS
from agents.registry import AgentConfig
from capabilities.registry import get_tools_for_capabilities
from documents.store import DocumentStore
from memory.store import MemoryStore
from tools import lifecycle as lifecycle_tools
from tools.executor import execute_query_memory, execute_store_memory, execute_search_documents
from utils.retry import retry_api_call

class BaseExpertAgent:
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
    ):
        self.config = config
        self.name = config.name
        self.memory_store = memory_store
        self.document_store = document_store
        self.calendar_store = calendar_store
        self.reminder_store = reminder_store
        self.notifier = notifier
        self.mail_store = mail_store
        self.client = client or anthropic.AsyncAnthropic(api_key=app_config.ANTHROPIC_API_KEY)

    def build_system_prompt(self) -> str:
        return self.config.system_prompt

    def get_tools(self) -> list[dict]:
        return get_tools_for_capabilities(self.config.capabilities)

    async def execute(self, task: str) -> str:
        messages = [{"role": "user", "content": task}]
        tools = self.get_tools()

        for _round in range(MAX_TOOL_ROUNDS):
            response = await self._call_api(messages, tools)

            # Check if the model wants to use a tool
            if response.stop_reason == "tool_use":
                # Process tool calls
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        result = self._handle_tool_call(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            # Extract text response
            for block in response.content:
                if block.type == "text":
                    return block.text

            return ""

        return "[Agent reached maximum tool rounds without producing a final response]"

    @retry_api_call
    async def _call_api(self, messages: list, tools: list) -> Any:
        kwargs = {
            "model": app_config.DEFAULT_MODEL,
            "max_tokens": self.config.max_tokens,
            "system": self.build_system_prompt(),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        return await self.client.messages.create(**kwargs)

    def _handle_tool_call(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name == "query_memory":
            return execute_query_memory(
                self.memory_store, tool_input["query"], tool_input.get("category")
            )

        elif tool_name == "store_memory":
            return execute_store_memory(
                self.memory_store,
                tool_input["category"],
                tool_input["key"],
                tool_input["value"],
                source=self.name,
            )

        elif tool_name == "search_documents":
            return execute_search_documents(
                self.document_store, tool_input["query"], tool_input.get("top_k", 5)
            )

        elif tool_name == "create_decision":
            return self._handle_create_decision(tool_input)

        elif tool_name == "search_decisions":
            return self._handle_search_decisions(tool_input)

        elif tool_name == "update_decision":
            return self._handle_update_decision(tool_input)

        elif tool_name == "list_pending_decisions":
            return self._handle_list_pending_decisions()

        elif tool_name == "delete_decision":
            return self._handle_delete_decision(tool_input)

        elif tool_name == "create_delegation":
            return self._handle_create_delegation(tool_input)

        elif tool_name == "list_delegations":
            return self._handle_list_delegations(tool_input)

        elif tool_name == "update_delegation":
            return self._handle_update_delegation(tool_input)

        elif tool_name == "check_overdue_delegations":
            return self._handle_check_overdue_delegations()

        elif tool_name == "delete_delegation":
            return self._handle_delete_delegation(tool_input)

        elif tool_name == "create_alert_rule":
            return self._handle_create_alert_rule(tool_input)

        elif tool_name == "list_alert_rules":
            return self._handle_list_alert_rules(tool_input)

        elif tool_name == "check_alerts":
            return self._handle_check_alerts()

        elif tool_name == "dismiss_alert":
            return self._handle_dismiss_alert(tool_input)

        elif tool_name == "get_calendar_events":
            return self._handle_calendar_get_events(tool_input)

        elif tool_name == "search_calendar_events":
            return self._handle_calendar_search(tool_input)

        elif tool_name == "list_reminders":
            return self._handle_reminder_list(tool_input)

        elif tool_name == "search_reminders":
            return self._handle_reminder_search(tool_input)

        elif tool_name == "create_reminder":
            return self._handle_reminder_create(tool_input)

        elif tool_name == "complete_reminder":
            return self._handle_reminder_complete(tool_input)

        elif tool_name == "send_notification":
            return self._handle_send_notification(tool_input)

        elif tool_name == "get_mail_messages":
            return self._handle_mail_get_messages(tool_input)

        elif tool_name == "get_mail_message":
            return self._handle_mail_get_message(tool_input)

        elif tool_name == "search_mail":
            return self._handle_mail_search(tool_input)

        elif tool_name == "get_unread_count":
            return self._handle_mail_get_unread_count(tool_input)

        elif tool_name == "send_email":
            return self._handle_mail_send(tool_input)

        elif tool_name == "mark_mail_read":
            return self._handle_mail_mark_read(tool_input)

        elif tool_name == "mark_mail_flagged":
            return self._handle_mail_mark_flagged(tool_input)

        elif tool_name == "move_mail_message":
            return self._handle_mail_move_message(tool_input)

        return {"error": f"Unknown tool: {tool_name}"}

    def _handle_create_decision(self, tool_input: dict) -> Any:
        return lifecycle_tools.create_decision(
            self.memory_store,
            title=tool_input["title"],
            description=tool_input.get("description", ""),
            context=tool_input.get("context", ""),
            decided_by=tool_input.get("decided_by", ""),
            owner=tool_input.get("owner", ""),
            status=tool_input.get("status", "pending_execution"),
            follow_up_date=tool_input.get("follow_up_date", ""),
            tags=tool_input.get("tags", ""),
            source=tool_input.get("source", self.name),
        )

    def _handle_search_decisions(self, tool_input: dict) -> Any:
        return lifecycle_tools.search_decisions(
            self.memory_store,
            query=tool_input.get("query", ""),
            status=tool_input.get("status", ""),
        )

    def _handle_update_decision(self, tool_input: dict) -> Any:
        return lifecycle_tools.update_decision(
            self.memory_store,
            decision_id=tool_input["decision_id"],
            status=tool_input.get("status", ""),
            notes=tool_input.get("notes", ""),
        )

    def _handle_list_pending_decisions(self) -> Any:
        return lifecycle_tools.list_pending_decisions(self.memory_store)

    def _handle_delete_decision(self, tool_input: dict) -> Any:
        return lifecycle_tools.delete_decision(
            self.memory_store,
            decision_id=tool_input["decision_id"],
        )

    def _handle_create_delegation(self, tool_input: dict) -> Any:
        return lifecycle_tools.create_delegation(
            self.memory_store,
            task=tool_input["task"],
            delegated_to=tool_input["delegated_to"],
            description=tool_input.get("description", ""),
            due_date=tool_input.get("due_date", ""),
            priority=tool_input.get("priority", "medium"),
            source=tool_input.get("source", self.name),
        )

    def _handle_list_delegations(self, tool_input: dict) -> Any:
        return lifecycle_tools.list_delegations(
            self.memory_store,
            status=tool_input.get("status", ""),
            delegated_to=tool_input.get("delegated_to", ""),
        )

    def _handle_update_delegation(self, tool_input: dict) -> Any:
        return lifecycle_tools.update_delegation(
            self.memory_store,
            delegation_id=tool_input["delegation_id"],
            status=tool_input.get("status", ""),
            notes=tool_input.get("notes", ""),
        )

    def _handle_check_overdue_delegations(self) -> Any:
        return lifecycle_tools.check_overdue_delegations(self.memory_store)

    def _handle_delete_delegation(self, tool_input: dict) -> Any:
        return lifecycle_tools.delete_delegation(
            self.memory_store,
            delegation_id=tool_input["delegation_id"],
        )

    def _handle_create_alert_rule(self, tool_input: dict) -> Any:
        return lifecycle_tools.create_alert_rule(
            self.memory_store,
            name=tool_input["name"],
            alert_type=tool_input["alert_type"],
            description=tool_input.get("description", ""),
            condition=tool_input.get("condition", ""),
            enabled=tool_input.get("enabled", True),
        )

    def _handle_list_alert_rules(self, tool_input: dict) -> Any:
        return lifecycle_tools.list_alert_rules(
            self.memory_store,
            enabled_only=tool_input.get("enabled_only", False),
        )

    def _handle_check_alerts(self) -> Any:
        return lifecycle_tools.check_alerts(self.memory_store)

    def _handle_dismiss_alert(self, tool_input: dict) -> Any:
        return lifecycle_tools.dismiss_alert(
            self.memory_store,
            rule_id=tool_input["rule_id"],
        )

    def _handle_calendar_get_events(self, tool_input: dict) -> Any:
        if self.calendar_store is None:
            return {"error": "Calendar not available (macOS only)"}
        from datetime import datetime
        start_dt = datetime.fromisoformat(tool_input["start_date"])
        end_dt = datetime.fromisoformat(tool_input["end_date"])
        calendar_names = [tool_input["calendar_name"]] if tool_input.get("calendar_name") else None
        return self.calendar_store.get_events(
            start_dt,
            end_dt,
            calendar_names=calendar_names,
            provider_preference=tool_input.get("provider_preference", "auto"),
            source_filter=tool_input.get("source_filter", ""),
        )

    def _handle_calendar_search(self, tool_input: dict) -> Any:
        if self.calendar_store is None:
            return {"error": "Calendar not available (macOS only)"}
        from datetime import datetime, timedelta
        now = datetime.now()
        start_dt = datetime.fromisoformat(tool_input["start_date"]) if tool_input.get("start_date") else now - timedelta(days=30)
        end_dt = datetime.fromisoformat(tool_input["end_date"]) if tool_input.get("end_date") else now + timedelta(days=30)
        return self.calendar_store.search_events(
            tool_input["query"],
            start_dt,
            end_dt,
            provider_preference=tool_input.get("provider_preference", "auto"),
            source_filter=tool_input.get("source_filter", ""),
        )

    def _handle_reminder_list(self, tool_input: dict) -> Any:
        if self.reminder_store is None:
            return {"error": "Reminders not available (macOS only)"}
        return self.reminder_store.list_reminders(
            list_name=tool_input.get("list_name"),
            completed=tool_input.get("completed"),
        )

    def _handle_reminder_search(self, tool_input: dict) -> Any:
        if self.reminder_store is None:
            return {"error": "Reminders not available (macOS only)"}
        return self.reminder_store.search_reminders(
            query=tool_input["query"],
            include_completed=tool_input.get("include_completed", False),
        )

    def _handle_reminder_create(self, tool_input: dict) -> Any:
        if self.reminder_store is None:
            return {"error": "Reminders not available (macOS only)"}
        return self.reminder_store.create_reminder(
            title=tool_input["title"],
            list_name=tool_input.get("list_name"),
            due_date=tool_input.get("due_date"),
            priority=tool_input.get("priority"),
            notes=tool_input.get("notes"),
        )

    def _handle_reminder_complete(self, tool_input: dict) -> Any:
        if self.reminder_store is None:
            return {"error": "Reminders not available (macOS only)"}
        return self.reminder_store.complete_reminder(tool_input["reminder_id"])

    def _handle_send_notification(self, tool_input: dict) -> Any:
        if self.notifier is None:
            return {"error": "Notifications not available (macOS only)"}
        return self.notifier.send(
            title=tool_input["title"],
            message=tool_input["message"],
            subtitle=tool_input.get("subtitle"),
            sound=tool_input.get("sound", "default"),
        )

    def _handle_mail_get_messages(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.get_messages(
            mailbox=tool_input.get("mailbox", "INBOX"),
            account=tool_input.get("account", ""),
            limit=tool_input.get("limit", 25),
        )

    def _handle_mail_get_message(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.get_message(tool_input["message_id"])

    def _handle_mail_search(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.search_messages(
            query=tool_input["query"],
            mailbox=tool_input.get("mailbox", "INBOX"),
            account=tool_input.get("account", ""),
            limit=tool_input.get("limit", 25),
        )

    def _handle_mail_get_unread_count(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        mailbox = tool_input.get("mailbox", "INBOX")
        account = tool_input.get("account", "")
        mailboxes = self.mail_store.list_mailboxes()
        for mb in mailboxes:
            if isinstance(mb, dict) and mb.get("name") == mailbox:
                if account and mb.get("account") != account:
                    continue
                return {"mailbox": mailbox, "unread_count": mb.get("unread_count", 0)}
        return {"mailbox": mailbox, "unread_count": 0}

    def _handle_mail_send(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        to_list = [a.strip() for a in tool_input["to"].split(",") if a.strip()]
        cc_list = [a.strip() for a in tool_input.get("cc", "").split(",") if a.strip()] or None
        bcc_list = [a.strip() for a in tool_input.get("bcc", "").split(",") if a.strip()] or None
        return self.mail_store.send_message(
            to=to_list,
            subject=tool_input["subject"],
            body=tool_input["body"],
            cc=cc_list,
            bcc=bcc_list,
            confirm_send=tool_input.get("confirm_send", False),
        )

    def _handle_mail_mark_read(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.mark_read(
            message_id=tool_input["message_id"],
            read=tool_input.get("read", True),
        )

    def _handle_mail_mark_flagged(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.mark_flagged(
            message_id=tool_input["message_id"],
            flagged=tool_input.get("flagged", True),
        )

    def _handle_mail_move_message(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.move_message(
            message_id=tool_input["message_id"],
            target_mailbox=tool_input["target_mailbox"],
            target_account=tool_input.get("target_account", ""),
        )
