# tests/test_integration.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path

from chief.orchestrator import ChiefOfStaff
from memory.store import MemoryStore
from memory.models import Fact
from documents.store import DocumentStore
from agents.registry import AgentRegistry, AgentConfig


@pytest.fixture
def full_system(tmp_path):
    memory = MemoryStore(tmp_path / "memory.db")
    docs = DocumentStore(persist_dir=tmp_path / "chroma")
    configs_dir = tmp_path / "agent_configs"
    configs_dir.mkdir()
    registry = AgentRegistry(configs_dir)

    # Pre-create an agent
    registry.save_agent(AgentConfig(
        name="test_researcher",
        description="Research assistant for testing",
        system_prompt="You are a test research assistant.",
        capabilities=["memory_read", "document_search"],
    ))

    chief = ChiefOfStaff(memory_store=memory, document_store=docs, agent_registry=registry)

    yield {"chief": chief, "memory": memory, "docs": docs, "registry": registry}
    memory.close()


class TestIntegration:
    def test_memory_persists_across_agents(self, full_system):
        """Facts stored by one component are visible to others."""
        memory = full_system["memory"]
        memory.store_fact(Fact(category="personal", key="name", value="Jason", source="test"))
        chief = full_system["chief"]
        result = chief.handle_tool_call("query_memory", {"query": "Jason"})
        assert len(result) >= 1
        assert result[0]["value"] == "Jason"

    def test_document_ingest_and_search(self, full_system, tmp_path):
        """Ingested documents are searchable."""
        docs = full_system["docs"]
        docs.add_documents(
            texts=["Machine learning is a subset of artificial intelligence"],
            metadatas=[{"source": "ml_guide.txt"}],
            ids=["test_chunk_1"],
        )
        result = full_system["chief"].handle_tool_call(
            "search_documents", {"query": "machine learning"}
        )
        assert len(result) >= 1
        assert "machine learning" in result[0]["text"].lower()

    def test_agent_registry_visible_to_chief(self, full_system):
        """Chief can list agents from the registry."""
        result = full_system["chief"].handle_tool_call("list_agents", {})
        assert len(result) >= 1
        names = [a["name"] for a in result]
        assert "test_researcher" in names

    @pytest.mark.asyncio
    async def test_chief_end_to_end_with_mock_api(self, full_system):
        """Full message processing with mocked Claude API."""
        chief = full_system["chief"]

        # Mock a simple text response (no tool use)
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="I'm your Chief of Staff. How can I help?")]
        mock_response.stop_reason = "end_turn"

        with patch.object(chief, "_call_api", return_value=mock_response):
            response = await chief.process("Hello, who are you?")
            assert "Chief of Staff" in response

    @pytest.mark.asyncio
    async def test_chief_stores_memory_via_tool(self, full_system):
        """Chief processes a tool_use response to store memory."""
        chief = full_system["chief"]

        # First response: Claude wants to use store_memory tool
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "store_memory"
        tool_use_block.id = "tool_123"
        tool_use_block.input = {"category": "personal", "key": "pet", "value": "dog named Max"}

        tool_response = MagicMock()
        tool_response.content = [tool_use_block]
        tool_response.stop_reason = "tool_use"

        # Second response: final text
        text_response = MagicMock()
        text_response.content = [MagicMock(type="text", text="Got it! You have a dog named Max.")]
        text_response.stop_reason = "end_turn"

        with patch.object(chief, "_call_api", side_effect=[tool_response, text_response]):
            response = await chief.process("I have a dog named Max")
            assert "Max" in response

        # Verify fact was stored
        fact = full_system["memory"].get_fact("personal", "pet")
        assert fact is not None
        assert fact.value == "dog named Max"
