# agents/base.py
import json
from typing import Any, Optional

import anthropic

import config as app_config
from agents.registry import AgentConfig
from documents.store import DocumentStore
from memory.models import Fact
from memory.store import MemoryStore

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
}


class BaseExpertAgent:
    def __init__(
        self,
        config: AgentConfig,
        memory_store: MemoryStore,
        document_store: DocumentStore,
    ):
        self.config = config
        self.name = config.name
        self.memory_store = memory_store
        self.document_store = document_store
        self.client = anthropic.AsyncAnthropic(api_key=app_config.ANTHROPIC_API_KEY)

    def build_system_prompt(self) -> str:
        return self.config.system_prompt

    def get_tools(self) -> list[dict]:
        tools = []
        for capability in self.config.capabilities:
            if capability in CAPABILITY_TOOLS:
                tools.append(CAPABILITY_TOOLS[capability])
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
            query = tool_input["query"]
            category = tool_input.get("category")
            if category:
                facts = self.memory_store.get_facts_by_category(category)
                facts = [f for f in facts if query.lower() in f.value.lower() or query.lower() in f.key.lower()]
            else:
                facts = self.memory_store.search_facts(query)
            return [{"category": f.category, "key": f.key, "value": f.value} for f in facts]

        elif tool_name == "store_memory":
            fact = Fact(
                category=tool_input["category"],
                key=tool_input["key"],
                value=tool_input["value"],
                source=self.name,
            )
            self.memory_store.store_fact(fact)
            return {"status": "stored", "key": tool_input["key"]}

        elif tool_name == "search_documents":
            query = tool_input["query"]
            top_k = tool_input.get("top_k", 5)
            results = self.document_store.search(query, top_k=top_k)
            return [{"text": r["text"], "source": r["metadata"].get("source", "unknown")} for r in results]

        return {"error": f"Unknown tool: {tool_name}"}
