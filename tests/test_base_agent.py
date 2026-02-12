# tests/test_base_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.base import BaseExpertAgent
from agents.registry import AgentConfig
from memory.store import MemoryStore
from documents.store import DocumentStore


@pytest.fixture
def agent_config():
    return AgentConfig(
        name="test_agent",
        description="A test agent",
        system_prompt="You are a test agent. Be helpful.",
        capabilities=["memory_read", "document_search"],
        temperature=0.3,
        max_tokens=4096,
    )


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def doc_store(tmp_path):
    return DocumentStore(persist_dir=tmp_path / "chroma")


class TestBaseExpertAgent:
    def test_agent_creation(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        assert agent.name == "test_agent"
        assert agent.config.temperature == 0.3

    def test_agent_builds_system_prompt(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        system = agent.build_system_prompt()
        assert "You are a test agent" in system

    def test_agent_gets_tools_from_capabilities(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        tools = agent.get_tools()
        tool_names = [t["name"] for t in tools]
        assert "query_memory" in tool_names
        assert "search_documents" in tool_names
        # memory_write not in capabilities, so store_memory should not be present
        assert "store_memory" not in tool_names

    @pytest.mark.asyncio
    async def test_agent_execute_calls_api(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Test response")]
        mock_response.stop_reason = "end_turn"

        with patch.object(agent, "_call_api", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.execute("Hello, test agent")
            assert result == "Test response"
