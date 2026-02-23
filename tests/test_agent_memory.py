# tests/test_agent_memory.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.models import AgentMemory
from memory.store import MemoryStore


@pytest.fixture
def memory_store(tmp_path):
    return MemoryStore(tmp_path / "test.db")


class TestAgentMemoryCRUD:
    def test_store_and_get(self, memory_store):
        mem = AgentMemory(agent_name="researcher", memory_type="insight", key="api_limit", value="Rate limit is 100/min")
        result = memory_store.store_agent_memory(mem)
        assert result.id is not None
        assert result.agent_name == "researcher"
        assert result.memory_type == "insight"
        assert result.key == "api_limit"
        assert result.value == "Rate limit is 100/min"
        assert result.confidence == 1.0
        assert result.created_at is not None
        assert result.updated_at is not None

    def test_get_memories_by_agent(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="k1", value="v1"))
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="preference", key="k2", value="v2"))
        memory_store.store_agent_memory(AgentMemory(agent_name="planner", memory_type="insight", key="k3", value="v3"))

        researcher_mems = memory_store.get_agent_memories("researcher")
        assert len(researcher_mems) == 2
        assert all(m.agent_name == "researcher" for m in researcher_mems)

    def test_get_memories_by_type(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="k1", value="v1"))
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="preference", key="k2", value="v2"))

        insights = memory_store.get_agent_memories("researcher", memory_type="insight")
        assert len(insights) == 1
        assert insights[0].key == "k1"

    def test_upsert_same_key(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="api_limit", value="100/min"))
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="api_limit", value="200/min"))

        mems = memory_store.get_agent_memories("researcher")
        assert len(mems) == 1
        assert mems[0].value == "200/min"

    def test_upsert_updates_confidence(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="k1", value="v1", confidence=0.5))
        result = memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="k1", value="v1_updated", confidence=0.9))
        assert result.confidence == 0.9
        assert result.value == "v1_updated"

    def test_agent_scoped_isolation(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="agent_a", memory_type="insight", key="secret", value="a_secret"))
        memory_store.store_agent_memory(AgentMemory(agent_name="agent_b", memory_type="insight", key="secret", value="b_secret"))

        a_mems = memory_store.get_agent_memories("agent_a")
        b_mems = memory_store.get_agent_memories("agent_b")
        assert len(a_mems) == 1
        assert a_mems[0].value == "a_secret"
        assert len(b_mems) == 1
        assert b_mems[0].value == "b_secret"

    def test_search_agent_memories(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="rate_limit", value="API rate limit is 100/min"))
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="context", key="db_host", value="postgres on port 5432"))

        results = memory_store.search_agent_memories("researcher", "rate")
        assert len(results) == 1
        assert results[0].key == "rate_limit"

    def test_search_matches_value(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="k1", value="The postgres database is slow"))

        results = memory_store.search_agent_memories("researcher", "postgres")
        assert len(results) == 1

    def test_search_scoped_to_agent(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="agent_a", memory_type="insight", key="shared_key", value="shared_value"))
        memory_store.store_agent_memory(AgentMemory(agent_name="agent_b", memory_type="insight", key="shared_key", value="shared_value"))

        results = memory_store.search_agent_memories("agent_a", "shared")
        assert len(results) == 1
        assert results[0].agent_name == "agent_a"

    def test_delete_agent_memory(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="k1", value="v1"))
        assert memory_store.delete_agent_memory("researcher", "k1") is True
        assert memory_store.get_agent_memories("researcher") == []

    def test_delete_with_type(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="k1", value="v1"))
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="preference", key="k1", value="v2"))

        assert memory_store.delete_agent_memory("researcher", "k1", memory_type="insight") is True
        mems = memory_store.get_agent_memories("researcher")
        assert len(mems) == 1
        assert mems[0].memory_type == "preference"

    def test_delete_nonexistent(self, memory_store):
        assert memory_store.delete_agent_memory("researcher", "nonexistent") is False

    def test_clear_agent_memories(self, memory_store):
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="insight", key="k1", value="v1"))
        memory_store.store_agent_memory(AgentMemory(agent_name="researcher", memory_type="preference", key="k2", value="v2"))
        memory_store.store_agent_memory(AgentMemory(agent_name="planner", memory_type="insight", key="k3", value="v3"))

        count = memory_store.clear_agent_memories("researcher")
        assert count == 2
        assert memory_store.get_agent_memories("researcher") == []
        # planner memories are untouched
        assert len(memory_store.get_agent_memories("planner")) == 1

    def test_clear_empty(self, memory_store):
        count = memory_store.clear_agent_memories("nonexistent")
        assert count == 0

    def test_get_empty(self, memory_store):
        mems = memory_store.get_agent_memories("nonexistent")
        assert mems == []


class TestAgentMemoryInjection:
    def test_no_memories_returns_base_prompt(self, memory_store):
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from documents.store import DocumentStore

        config = AgentConfig(
            name="test_agent",
            description="Test",
            system_prompt="You are a test agent.",
            capabilities=[],
        )
        doc_store = DocumentStore(str(memory_store.db_path.parent / "chroma_test"))
        agent = BaseExpertAgent(config, memory_store, doc_store)
        prompt = agent.build_system_prompt()
        assert prompt.startswith("You are a test agent.")
        assert "## Runtime Context" in prompt
        assert "Agent name: test_agent" in prompt
        assert "Agent Memory" not in prompt

    def test_memories_injected_into_prompt(self, memory_store):
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from documents.store import DocumentStore

        memory_store.store_agent_memory(AgentMemory(agent_name="test_agent", memory_type="insight", key="api_limit", value="100 requests per minute"))
        memory_store.store_agent_memory(AgentMemory(agent_name="test_agent", memory_type="preference", key="output_format", value="JSON"))

        config = AgentConfig(
            name="test_agent",
            description="Test",
            system_prompt="You are a test agent.",
            capabilities=[],
        )
        doc_store = DocumentStore(str(memory_store.db_path.parent / "chroma_test2"))
        agent = BaseExpertAgent(config, memory_store, doc_store)
        prompt = agent.build_system_prompt()
        assert "## Agent Memory (retained from previous runs)" in prompt
        assert "- api_limit: 100 requests per minute" in prompt
        assert "- output_format: JSON" in prompt

    def test_other_agent_memories_not_injected(self, memory_store):
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from documents.store import DocumentStore

        memory_store.store_agent_memory(AgentMemory(agent_name="other_agent", memory_type="insight", key="secret", value="should not appear"))

        config = AgentConfig(
            name="test_agent",
            description="Test",
            system_prompt="You are a test agent.",
            capabilities=[],
        )
        doc_store = DocumentStore(str(memory_store.db_path.parent / "chroma_test3"))
        agent = BaseExpertAgent(config, memory_store, doc_store)
        prompt = agent.build_system_prompt()
        assert "secret" not in prompt
        assert "should not appear" not in prompt


class TestAgentMemoryMCPTools:
    @pytest.fixture
    def mcp_state(self, memory_store):
        """Create a mock MCP state with a memory store."""
        state = MagicMock()
        state.memory_store = memory_store
        state.agent_registry = MagicMock()
        return state

    @pytest.fixture
    def register_tools(self, mcp_state):
        """Register tools and return module with tool functions."""
        import mcp_server  # trigger registration
        from mcp_tools import agent_tools

        # Save original module-level functions to restore after test
        originals = {
            name: getattr(agent_tools, name)
            for name in dir(agent_tools)
            if callable(getattr(agent_tools, name, None)) and not name.startswith("_")
        }

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f  # no-op decorator
        agent_tools.register(mcp, mcp_state)
        yield agent_tools

        # Restore originals to prevent test pollution
        for name, fn in originals.items():
            setattr(agent_tools, name, fn)

    @pytest.mark.asyncio
    async def test_get_agent_memory_empty(self, register_tools):
        result = await register_tools.get_agent_memory("nonexistent")
        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_get_agent_memory_with_data(self, register_tools, mcp_state):
        mcp_state.memory_store.store_agent_memory(
            AgentMemory(agent_name="researcher", memory_type="insight", key="k1", value="v1")
        )
        result = await register_tools.get_agent_memory("researcher")
        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["key"] == "k1"
        assert data["agent_name"] == "researcher"

    @pytest.mark.asyncio
    async def test_clear_agent_memory(self, register_tools, mcp_state):
        mcp_state.memory_store.store_agent_memory(
            AgentMemory(agent_name="researcher", memory_type="insight", key="k1", value="v1")
        )
        mcp_state.memory_store.store_agent_memory(
            AgentMemory(agent_name="researcher", memory_type="preference", key="k2", value="v2")
        )
        result = await register_tools.clear_agent_memory("researcher")
        data = json.loads(result)
        assert data["deleted_count"] == 2
        assert data["agent_name"] == "researcher"

        # Verify cleared
        result2 = await register_tools.get_agent_memory("researcher")
        data2 = json.loads(result2)
        assert data2["results"] == []

    @pytest.mark.asyncio
    async def test_store_shared_memory(self, register_tools, mcp_state):
        result = await register_tools.store_shared_memory(
            namespace="research-team", memory_type="insight", key="api_url", value="https://api.example.com"
        )
        data = json.loads(result)
        assert data["status"] == "stored"
        assert data["namespace"] == "research-team"
        assert data["key"] == "api_url"

    @pytest.mark.asyncio
    async def test_get_shared_memory_empty(self, register_tools):
        result = await register_tools.get_shared_memory(namespace="nonexistent")
        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_get_shared_memory_with_data(self, register_tools, mcp_state):
        mcp_state.memory_store.store_shared_memory(
            namespace="research-team", memory_type="insight", key="k1", value="v1"
        )
        result = await register_tools.get_shared_memory(namespace="research-team")
        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["key"] == "k1"
        assert data["namespace"] == "research-team"

    @pytest.mark.asyncio
    async def test_get_shared_memory_filter_by_type(self, register_tools, mcp_state):
        mcp_state.memory_store.store_shared_memory(
            namespace="team", memory_type="insight", key="k1", value="v1"
        )
        mcp_state.memory_store.store_shared_memory(
            namespace="team", memory_type="preference", key="k2", value="v2"
        )
        result = await register_tools.get_shared_memory(namespace="team", memory_type="insight")
        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["key"] == "k1"


class TestSharedMemoryCRUD:
    def test_store_and_get(self, memory_store):
        result = memory_store.store_shared_memory("team-a", "insight", "finding", "Important discovery")
        assert result.id is not None
        assert result.agent_name == "__shared__:team-a"
        assert result.namespace == "team-a"
        assert result.key == "finding"
        assert result.value == "Important discovery"
        assert result.confidence == 1.0

    def test_get_shared_memories(self, memory_store):
        memory_store.store_shared_memory("team-a", "insight", "k1", "v1")
        memory_store.store_shared_memory("team-a", "preference", "k2", "v2")
        memory_store.store_shared_memory("team-b", "insight", "k3", "v3")

        team_a = memory_store.get_shared_memories("team-a")
        assert len(team_a) == 2
        assert all(m.namespace == "team-a" for m in team_a)

    def test_get_shared_memories_by_type(self, memory_store):
        memory_store.store_shared_memory("team-a", "insight", "k1", "v1")
        memory_store.store_shared_memory("team-a", "preference", "k2", "v2")

        insights = memory_store.get_shared_memories("team-a", memory_type="insight")
        assert len(insights) == 1
        assert insights[0].key == "k1"

    def test_namespace_isolation(self, memory_store):
        memory_store.store_shared_memory("team-a", "insight", "secret", "a_value")
        memory_store.store_shared_memory("team-b", "insight", "secret", "b_value")

        a_mems = memory_store.get_shared_memories("team-a")
        b_mems = memory_store.get_shared_memories("team-b")
        assert len(a_mems) == 1
        assert a_mems[0].value == "a_value"
        assert len(b_mems) == 1
        assert b_mems[0].value == "b_value"

    def test_search_shared_memories(self, memory_store):
        memory_store.store_shared_memory("team-a", "insight", "rate_limit", "API rate limit is 100/min")
        memory_store.store_shared_memory("team-a", "context", "db_host", "postgres on port 5432")

        results = memory_store.search_shared_memories("team-a", "rate")
        assert len(results) == 1
        assert results[0].key == "rate_limit"

    def test_search_shared_memories_namespace_isolation(self, memory_store):
        memory_store.store_shared_memory("team-a", "insight", "shared_key", "shared_value")
        memory_store.store_shared_memory("team-b", "insight", "shared_key", "shared_value")

        results = memory_store.search_shared_memories("team-a", "shared")
        assert len(results) == 1
        assert results[0].namespace == "team-a"

    def test_upsert_shared_memory(self, memory_store):
        memory_store.store_shared_memory("team-a", "insight", "k1", "old_value")
        memory_store.store_shared_memory("team-a", "insight", "k1", "new_value")

        mems = memory_store.get_shared_memories("team-a")
        assert len(mems) == 1
        assert mems[0].value == "new_value"

    def test_shared_and_agent_scoped_coexist(self, memory_store):
        """Shared memories don't interfere with agent-scoped memories."""
        memory_store.store_agent_memory(
            AgentMemory(agent_name="researcher", memory_type="insight", key="private", value="agent_only")
        )
        memory_store.store_shared_memory("team-a", "insight", "shared", "team_only")

        agent_mems = memory_store.get_agent_memories("researcher")
        shared_mems = memory_store.get_shared_memories("team-a")

        assert len(agent_mems) == 1
        assert agent_mems[0].value == "agent_only"
        assert len(shared_mems) == 1
        assert shared_mems[0].value == "team_only"

        # Shared memories should NOT appear in agent-scoped queries
        all_researcher = memory_store.get_agent_memories("researcher")
        assert all(m.agent_name == "researcher" for m in all_researcher)

    def test_get_shared_memories_empty(self, memory_store):
        mems = memory_store.get_shared_memories("nonexistent")
        assert mems == []

    def test_custom_confidence(self, memory_store):
        result = memory_store.store_shared_memory("team-a", "insight", "k1", "v1", confidence=0.7)
        assert result.confidence == 0.7


class TestSharedMemorySystemPrompt:
    def test_shared_memories_injected_into_prompt(self, memory_store):
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from documents.store import DocumentStore

        memory_store.store_shared_memory("research-team", "insight", "api_url", "https://api.example.com")

        config = AgentConfig(
            name="test_agent",
            description="Test",
            system_prompt="You are a test agent.",
            capabilities=[],
            namespaces=["research-team"],
        )
        doc_store = DocumentStore(str(memory_store.db_path.parent / "chroma_shared1"))
        agent = BaseExpertAgent(config, memory_store, doc_store)
        prompt = agent.build_system_prompt()
        assert "## Shared Memory [research-team]" in prompt
        assert "- api_url: https://api.example.com" in prompt

    def test_no_namespaces_no_shared_memory_section(self, memory_store):
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from documents.store import DocumentStore

        memory_store.store_shared_memory("research-team", "insight", "api_url", "https://api.example.com")

        config = AgentConfig(
            name="test_agent",
            description="Test",
            system_prompt="You are a test agent.",
            capabilities=[],
        )
        doc_store = DocumentStore(str(memory_store.db_path.parent / "chroma_shared2"))
        agent = BaseExpertAgent(config, memory_store, doc_store)
        prompt = agent.build_system_prompt()
        assert "Shared Memory" not in prompt

    def test_both_agent_and_shared_memories_in_prompt(self, memory_store):
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from documents.store import DocumentStore

        memory_store.store_agent_memory(
            AgentMemory(agent_name="test_agent", memory_type="insight", key="private_key", value="private_value")
        )
        memory_store.store_shared_memory("team-ns", "insight", "shared_key", "shared_value")

        config = AgentConfig(
            name="test_agent",
            description="Test",
            system_prompt="You are a test agent.",
            capabilities=[],
            namespaces=["team-ns"],
        )
        doc_store = DocumentStore(str(memory_store.db_path.parent / "chroma_shared3"))
        agent = BaseExpertAgent(config, memory_store, doc_store)
        prompt = agent.build_system_prompt()
        assert "## Agent Memory (retained from previous runs)" in prompt
        assert "- private_key: private_value" in prompt
        assert "## Shared Memory [team-ns]" in prompt
        assert "- shared_key: shared_value" in prompt

    def test_multiple_namespaces_in_prompt(self, memory_store):
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from documents.store import DocumentStore

        memory_store.store_shared_memory("ns-alpha", "insight", "k1", "v1")
        memory_store.store_shared_memory("ns-beta", "insight", "k2", "v2")

        config = AgentConfig(
            name="test_agent",
            description="Test",
            system_prompt="You are a test agent.",
            capabilities=[],
            namespaces=["ns-alpha", "ns-beta"],
        )
        doc_store = DocumentStore(str(memory_store.db_path.parent / "chroma_shared4"))
        agent = BaseExpertAgent(config, memory_store, doc_store)
        prompt = agent.build_system_prompt()
        assert "## Shared Memory [ns-alpha]" in prompt
        assert "- k1: v1" in prompt
        assert "## Shared Memory [ns-beta]" in prompt
        assert "- k2: v2" in prompt

    def test_empty_namespace_not_shown(self, memory_store):
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from documents.store import DocumentStore

        config = AgentConfig(
            name="test_agent",
            description="Test",
            system_prompt="You are a test agent.",
            capabilities=[],
            namespaces=["empty-ns"],
        )
        doc_store = DocumentStore(str(memory_store.db_path.parent / "chroma_shared5"))
        agent = BaseExpertAgent(config, memory_store, doc_store)
        prompt = agent.build_system_prompt()
        assert "Shared Memory" not in prompt
