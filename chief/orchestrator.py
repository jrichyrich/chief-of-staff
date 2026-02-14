# chief/orchestrator.py
import asyncio
import json
import uuid
from typing import Any

import anthropic

MAX_TOOL_ROUNDS = 25

import config as app_config
from agents.base import BaseExpertAgent
from agents.registry import AgentConfig, AgentRegistry
from chief.dispatcher import AgentDispatcher
from documents.store import DocumentStore
from memory.store import MemoryStore
from tools.definitions import get_chief_tools
from tools.executor import execute_query_memory, execute_store_memory, execute_search_documents

CHIEF_SYSTEM_PROMPT = """You are the Chief of Staff, an AI orchestrator that manages a team of expert agents.

Your responsibilities:
1. Understand user requests and decide the best way to handle them
2. Check shared memory for relevant context about the user
3. Delegate tasks to expert agents when specialized knowledge is needed
4. Create new expert agents when no existing agent has the right expertise
5. Dispatch multiple agents in parallel when a task benefits from multiple perspectives
6. Synthesize results from multiple agents into coherent responses
7. Store important facts and details in shared memory for future reference

Always check memory first for context. When you learn new facts about the user (name, preferences, etc.), store them.
When delegating, give agents clear, specific tasks. When creating new agents, describe the expertise needed clearly."""


class ChiefOfStaff:
    def __init__(
        self,
        memory_store: MemoryStore,
        document_store: DocumentStore,
        agent_registry: AgentRegistry,
    ):
        self.memory_store = memory_store
        self.document_store = document_store
        self.agent_registry = agent_registry
        self.dispatcher = AgentDispatcher(timeout_seconds=app_config.AGENT_TIMEOUT_SECONDS)
        self.client = anthropic.Anthropic(api_key=app_config.ANTHROPIC_API_KEY)
        self.conversation_history: list[dict] = []
        self.session_id = str(uuid.uuid4())[:8]

    async def process(self, user_message: str) -> str:
        self.conversation_history.append({"role": "user", "content": user_message})
        messages = list(self.conversation_history)
        tools = get_chief_tools()

        for _round in range(MAX_TOOL_ROUNDS):
            response = self._call_api(messages, tools)

            if response.stop_reason == "tool_use":
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        result = await self._handle_tool_call_async(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            # Extract final text response
            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text

            self.conversation_history.append({"role": "assistant", "content": text})
            return text

        fallback = "[Reached maximum tool rounds without a final response]"
        self.conversation_history.append({"role": "assistant", "content": fallback})
        return fallback

    def _call_api(self, messages: list, tools: list) -> Any:
        return self.client.messages.create(
            model=app_config.CHIEF_MODEL,
            max_tokens=4096,
            system=CHIEF_SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
        )

    async def _handle_tool_call_async(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name in ("dispatch_agent", "dispatch_parallel"):
            return await self._handle_async_tool(tool_name, tool_input)
        if tool_name == "create_agent":
            return self._handle_create_agent(tool_input)
        return self.handle_tool_call(tool_name, tool_input)

    def handle_tool_call(self, tool_name: str, tool_input: dict) -> Any:
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
                source="chief_of_staff",
            )

        elif tool_name == "search_documents":
            return execute_search_documents(
                self.document_store, tool_input["query"], tool_input.get("top_k", 5)
            )

        elif tool_name == "list_agents":
            agents = self.agent_registry.list_agents()
            return [{"name": a.name, "description": a.description} for a in agents]

        return {"error": f"Unknown tool: {tool_name}"}

    def _handle_create_agent(self, tool_input: dict) -> Any:
        config = AgentConfig(
            name=tool_input["name"],
            description=tool_input["description"],
            system_prompt=tool_input["system_prompt"],
            capabilities=tool_input.get("capabilities", ["memory_read"]),
        )
        self.agent_registry.save_agent(config)
        return {"status": "created", "name": config.name, "description": config.description}

    async def _handle_async_tool(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name == "dispatch_agent":
            agent_name = tool_input["agent_name"]
            task = tool_input["task"]
            config = self.agent_registry.get_agent(agent_name)
            if config is None:
                return {"error": f"Agent '{agent_name}' not found"}
            agent = BaseExpertAgent(config, self.memory_store, self.document_store)
            results = await self.dispatcher.dispatch([(agent_name, agent, task)])
            r = results[0]
            if r.error:
                return {"error": r.error}
            return {"agent": agent_name, "response": r.result}

        elif tool_name == "dispatch_parallel":
            tasks_to_dispatch = []
            for item in tool_input["tasks"]:
                config = self.agent_registry.get_agent(item["agent_name"])
                if config is None:
                    continue
                agent = BaseExpertAgent(config, self.memory_store, self.document_store)
                tasks_to_dispatch.append((item["agent_name"], agent, item["task"]))

            if not tasks_to_dispatch:
                return {"error": "No valid agents found for dispatch"}

            results = await self.dispatcher.dispatch(tasks_to_dispatch)
            return [
                {"agent": r.agent_name, "response": r.result, "error": r.error}
                for r in results
            ]

        return {"error": f"Unknown async tool: {tool_name}"}
