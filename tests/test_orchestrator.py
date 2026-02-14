# tests/test_orchestrator.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from chief.orchestrator import ChiefOfStaff
from chief.dispatcher import DispatchResult
from memory.store import MemoryStore
from memory.models import Fact
from documents.store import DocumentStore
from agents.registry import AgentConfig, AgentRegistry


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def doc_store(tmp_path):
    return DocumentStore(persist_dir=tmp_path / "chroma")


@pytest.fixture
def registry(tmp_path):
    return AgentRegistry(tmp_path / "agent_configs")


@pytest.fixture
def chief(memory_store, doc_store, registry):
    return ChiefOfStaff(
        memory_store=memory_store,
        document_store=doc_store,
        agent_registry=registry,
    )


class TestChiefOfStaff:
    def test_creation(self, chief):
        assert chief.memory_store is not None
        assert chief.document_store is not None
        assert chief.agent_registry is not None
        assert chief.conversation_history == []

    def test_handle_tool_query_memory(self, chief, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        result = chief.handle_tool_call("query_memory", {"query": "Jason"})
        assert len(result) >= 1
        assert result[0]["value"] == "Jason"

    def test_handle_tool_store_memory(self, chief, memory_store):
        result = chief.handle_tool_call(
            "store_memory",
            {"category": "personal", "key": "city", "value": "San Francisco"},
        )
        assert result["status"] == "stored"
        fact = memory_store.get_fact("personal", "city")
        assert fact.value == "San Francisco"

    def test_handle_tool_list_agents(self, chief):
        result = chief.handle_tool_call("list_agents", {})
        assert isinstance(result, list)

    def test_handle_tool_search_documents(self, chief, doc_store):
        doc_store.add_documents(
            texts=["Python is great for AI"],
            metadatas=[{"source": "test.txt"}],
            ids=["chunk_1"],
        )
        result = chief.handle_tool_call("search_documents", {"query": "Python AI"})
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_process_simple_message(self, chief):
        """Chief should process a simple message and return a response."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Hello! How can I help?")]
        mock_response.stop_reason = "end_turn"

        with patch.object(chief, "_call_api", new_callable=AsyncMock, return_value=mock_response):
            result = await chief.process("Hello")
            assert "Hello" in result or "help" in result.lower()

    @pytest.mark.asyncio
    async def test_dispatch_parallel_reports_missing_agents(self, chief, registry):
        """dispatch_parallel should report missing agents instead of silently skipping."""
        # Register one real agent
        registry.save_agent(AgentConfig(
            name="real_agent",
            description="A real agent",
            system_prompt="You are a test agent.",
        ))

        mock_dispatch_result = DispatchResult(agent_name="real_agent", result="Done")
        with patch.object(chief.dispatcher, "dispatch", new_callable=AsyncMock, return_value=[mock_dispatch_result]):
            result = await chief._handle_async_tool("dispatch_parallel", {
                "tasks": [
                    {"agent_name": "real_agent", "task": "do something"},
                    {"agent_name": "ghost_agent", "task": "vanish"},
                    {"agent_name": "missing_agent", "task": "gone"},
                ],
            })

        assert isinstance(result, list)
        assert len(result) == 3

        real = [r for r in result if r["agent"] == "real_agent"]
        assert len(real) == 1
        assert real[0]["response"] == "Done"

        ghost = [r for r in result if r["agent"] == "ghost_agent"]
        assert len(ghost) == 1
        assert "not found" in ghost[0]["error"]

        missing = [r for r in result if r["agent"] == "missing_agent"]
        assert len(missing) == 1
        assert "not found" in missing[0]["error"]

    @pytest.mark.asyncio
    async def test_dispatch_parallel_all_missing_returns_error(self, chief):
        """dispatch_parallel with all missing agents returns an error dict."""
        result = await chief._handle_async_tool("dispatch_parallel", {
            "tasks": [
                {"agent_name": "nonexistent_1", "task": "task1"},
                {"agent_name": "nonexistent_2", "task": "task2"},
            ],
        })
        assert isinstance(result, dict)
        assert "error" in result
        assert "No valid agents" in result["error"]

    @pytest.mark.asyncio
    async def test_conversation_history_stores_full_content(self, chief):
        """After a simple message the assistant entry stores full content blocks."""
        text_block = MagicMock(type="text", text="Hi there")
        mock_response = MagicMock()
        mock_response.content = [text_block]
        mock_response.stop_reason = "end_turn"

        with patch.object(chief, "_call_api", new_callable=AsyncMock, return_value=mock_response):
            await chief.process("Hey")

        # History: user msg, then assistant with full content list
        assert len(chief.conversation_history) == 2
        assert chief.conversation_history[0] == {"role": "user", "content": "Hey"}
        assistant_entry = chief.conversation_history[1]
        assert assistant_entry["role"] == "assistant"
        # Content should be the list of content blocks, not a plain string
        assert assistant_entry["content"] is mock_response.content

    @pytest.mark.asyncio
    async def test_conversation_history_preserves_tool_messages(self, chief):
        """Intermediate tool call and tool result messages are stored in history."""
        tool_block = MagicMock(type="tool_use", name="list_agents", id="t1", input={})
        tool_response = MagicMock()
        tool_response.content = [tool_block]
        tool_response.stop_reason = "tool_use"

        text_block = MagicMock(type="text", text="Here are the agents.")
        final_response = MagicMock()
        final_response.content = [text_block]
        final_response.stop_reason = "end_turn"

        with patch.object(chief, "_call_api", new_callable=AsyncMock,
                          side_effect=[tool_response, final_response]):
            result = await chief.process("List my agents")

        assert result == "Here are the agents."
        # History: user, assistant (tool_use), user (tool_result), assistant (final)
        assert len(chief.conversation_history) == 4
        assert chief.conversation_history[0]["role"] == "user"
        assert chief.conversation_history[1]["role"] == "assistant"
        assert chief.conversation_history[1]["content"] is tool_response.content
        assert chief.conversation_history[2]["role"] == "user"
        assert chief.conversation_history[2]["content"][0]["type"] == "tool_result"
        assert chief.conversation_history[3]["role"] == "assistant"
        assert chief.conversation_history[3]["content"] is final_response.content

    def test_enrich_task_adds_user_context(self, chief):
        """_enrich_task prepends the user's original message."""
        chief.conversation_history.append({"role": "user", "content": "Plan my week"})
        enriched = chief._enrich_task("Create a schedule")
        assert "Plan my week" in enriched
        assert "Create a schedule" in enriched

    def test_enrich_task_without_history(self, chief):
        """_enrich_task returns the bare task when no user message exists."""
        result = chief._enrich_task("Do something")
        assert result == "Do something"
