# agents/base.py
import json
from typing import Any, Optional

import anthropic

import config as app_config
from agents.registry import AgentConfig
from documents.store import DocumentStore
from memory.store import MemoryStore
from tools.executor import execute_query_memory, execute_store_memory, execute_search_documents
from utils.retry import retry_api_call

MAX_TOOL_ROUNDS = 25

CAPABILITY_TOOLS = {
    "memory_read": {
        "name": "query_memory",
        "description": "Look up facts, locations, or personal details from shared memory",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term to look up in memory"},
                "category": {"type": "string", "description": "Optional category filter (personal, preference, work, relationship)"},
            },
            "required": ["query"],
        },
    },
    "memory_write": {
        "name": "store_memory",
        "description": "Save a new fact to shared memory",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Fact category (personal, preference, work, relationship)"},
                "key": {"type": "string", "description": "Fact key (e.g., 'name', 'favorite_food')"},
                "value": {"type": "string", "description": "Fact value"},
            },
            "required": ["category", "key", "value"],
        },
    },
    "document_search": {
        "name": "search_documents",
        "description": "Semantic search over ingested documents",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "description": "Number of results to return", "default": 5},
            },
            "required": ["query"],
        },
    },
    "calendar_read": [
        {
            "name": "get_calendar_events",
            "description": "Get calendar events within a date range. Returns events from all synced calendars (Exchange/Outlook, iCloud, Google) including title, time, location, attendees, and calendar name.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"},
                    "end_date": {"type": "string", "description": "End date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"},
                    "calendar_name": {"type": "string", "description": "Optional: filter to a specific calendar name"},
                },
                "required": ["start_date", "end_date"],
            },
        },
        {
            "name": "search_calendar_events",
            "description": "Search calendar events by title text within a date range.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for in event titles"},
                    "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD), defaults to 30 days ago"},
                    "end_date": {"type": "string", "description": "End date (YYYY-MM-DD), defaults to 30 days from now"},
                },
                "required": ["query"],
            },
        },
    ],
    "reminders_read": [
        {
            "name": "get_reminders",
            "description": "Get reminders, optionally filtered by list name and completion status.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "list_name": {"type": "string", "description": "Optional: filter to a specific reminder list"},
                    "completed": {"type": "boolean", "description": "Optional: true for completed only, false for incomplete only, omit for all"},
                },
            },
        },
        {
            "name": "search_reminders",
            "description": "Search reminders by title text.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for in reminder titles"},
                    "include_completed": {"type": "boolean", "description": "Whether to include completed reminders (default: false)"},
                },
                "required": ["query"],
            },
        },
    ],
    "reminders_write": [
        {
            "name": "create_reminder",
            "description": "Create a new reminder in Apple Reminders.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Reminder title"},
                    "list_name": {"type": "string", "description": "Which reminder list to add to (uses default if omitted)"},
                    "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"},
                    "priority": {"type": "integer", "description": "Priority: 0=none, 1=high, 4=medium, 9=low"},
                    "notes": {"type": "string", "description": "Notes/description for the reminder"},
                },
                "required": ["title"],
            },
        },
        {
            "name": "complete_reminder",
            "description": "Mark a reminder as completed by its ID.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "The ID of the reminder to complete"},
                },
                "required": ["reminder_id"],
            },
        },
    ],
    "notifications": [
        {
            "name": "send_notification",
            "description": "Send a macOS notification to the user.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Notification title"},
                    "message": {"type": "string", "description": "Notification body text"},
                    "subtitle": {"type": "string", "description": "Optional subtitle"},
                    "sound": {"type": "string", "description": "Sound name (default: 'default')"},
                },
                "required": ["title", "message"],
            },
        },
    ],
    "mail_read": [
        {
            "name": "get_mail_messages",
            "description": "Get recent email messages from a mailbox (headers only).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "mailbox": {"type": "string", "description": "Mailbox name (default: INBOX)"},
                    "account": {"type": "string", "description": "Account name filter"},
                    "limit": {"type": "integer", "description": "Max messages (default: 25)"},
                },
            },
        },
        {
            "name": "get_mail_message",
            "description": "Get full email content including body by Message-ID.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Message-ID of the email"},
                },
                "required": ["message_id"],
            },
        },
        {
            "name": "search_mail",
            "description": "Search emails by subject and sender text.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for"},
                    "mailbox": {"type": "string", "description": "Mailbox to search (default: INBOX)"},
                    "account": {"type": "string", "description": "Account name filter"},
                    "limit": {"type": "integer", "description": "Max results (default: 25)"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_unread_count",
            "description": "Get unread email count for a mailbox.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "mailbox": {"type": "string", "description": "Mailbox name (default: INBOX)"},
                    "account": {"type": "string", "description": "Account name filter"},
                },
            },
        },
    ],
    "mail_write": [
        {
            "name": "send_email",
            "description": "Send an email. REQUIRES confirm_send=True after explicit user confirmation.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Comma-separated recipient addresses"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body text"},
                    "cc": {"type": "string", "description": "Comma-separated CC addresses"},
                    "bcc": {"type": "string", "description": "Comma-separated BCC addresses"},
                    "confirm_send": {"type": "boolean", "description": "MUST be true — confirm with user first"},
                },
                "required": ["to", "subject", "body", "confirm_send"],
            },
        },
        {
            "name": "mark_mail_read",
            "description": "Mark an email as read or unread.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Message-ID"},
                    "read": {"type": "boolean", "description": "True for read, false for unread"},
                },
                "required": ["message_id"],
            },
        },
        {
            "name": "mark_mail_flagged",
            "description": "Flag or unflag an email.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Message-ID"},
                    "flagged": {"type": "boolean", "description": "True to flag, false to unflag"},
                },
                "required": ["message_id"],
            },
        },
        {
            "name": "move_mail_message",
            "description": "Move an email to a different mailbox.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Message-ID"},
                    "target_mailbox": {"type": "string", "description": "Target mailbox name"},
                    "target_account": {"type": "string", "description": "Target account name"},
                },
                "required": ["message_id", "target_mailbox"],
            },
        },
    ],
}


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
        tools = []
        for capability in self.config.capabilities:
            if capability in CAPABILITY_TOOLS:
                entry = CAPABILITY_TOOLS[capability]
                if isinstance(entry, list):
                    tools.extend(entry)
                else:
                    tools.append(entry)
        return tools

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

        elif tool_name == "get_calendar_events":
            return self._handle_calendar_get_events(tool_input)

        elif tool_name == "search_calendar_events":
            return self._handle_calendar_search(tool_input)

        elif tool_name == "get_reminders":
            return self._handle_reminder_get(tool_input)

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

    def _handle_calendar_get_events(self, tool_input: dict) -> Any:
        if self.calendar_store is None:
            return {"error": "Calendar not available (macOS only)"}
        from datetime import datetime
        start_dt = datetime.fromisoformat(tool_input["start_date"])
        end_dt = datetime.fromisoformat(tool_input["end_date"])
        calendar_names = [tool_input["calendar_name"]] if tool_input.get("calendar_name") else None
        return self.calendar_store.get_events(start_dt, end_dt, calendar_names)

    def _handle_calendar_search(self, tool_input: dict) -> Any:
        if self.calendar_store is None:
            return {"error": "Calendar not available (macOS only)"}
        from datetime import datetime, timedelta
        now = datetime.now()
        start_dt = datetime.fromisoformat(tool_input["start_date"]) if tool_input.get("start_date") else now - timedelta(days=30)
        end_dt = datetime.fromisoformat(tool_input["end_date"]) if tool_input.get("end_date") else now + timedelta(days=30)
        return self.calendar_store.search_events(tool_input["query"], start_dt, end_dt)

    def _handle_reminder_get(self, tool_input: dict) -> Any:
        if self.reminder_store is None:
            return {"error": "Reminders not available (macOS only)"}
        return self.reminder_store.get_reminders(
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
