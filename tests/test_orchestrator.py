# tests/test_orchestrator.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from chief.orchestrator import ChiefOfStaff
from memory.store import MemoryStore
from memory.models import Fact
from documents.store import DocumentStore
from agents.registry import AgentRegistry


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

        with patch.object(chief, "_call_api", return_value=mock_response):
            result = await chief.process("Hello")
            assert "Hello" in result or "help" in result.lower()
