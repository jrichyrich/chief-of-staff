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
}


class BaseExpertAgent:
    def __init__(
        self,
        config: AgentConfig,
        memory_store: MemoryStore,
        document_store: DocumentStore,
        client: Optional[anthropic.AsyncAnthropic] = None,
        calendar_store=None,
    ):
        self.config = config
        self.name = config.name
        self.memory_store = memory_store
        self.document_store = document_store
        self.calendar_store = calendar_store
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
