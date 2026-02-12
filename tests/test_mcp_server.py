# tests/test_mcp_server.py
import pytest
from unittest.mock import patch, MagicMock


def test_mcp_server_imports():
    """Verify mcp_server module can be imported."""
    import mcp_server
    assert hasattr(mcp_server, "mcp")
    assert hasattr(mcp_server, "app_lifespan")


def test_mcp_server_has_tools():
    """Verify the MCP server registers the expected tools."""
    import mcp_server
    # FastMCP registers tools internally; check they exist by name
    tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
    assert "chief_of_staff_ask" in tool_names
    assert "ingest_documents" in tool_names


def test_mcp_server_has_resources():
    """Verify the MCP server registers the expected resources."""
    import mcp_server
    resource_manager = mcp_server.mcp._resource_manager

    # Concrete resources
    resources = resource_manager.list_resources()
    resource_uris = [str(r.uri) for r in resources]
    assert "memory://facts" in resource_uris
    assert "agents://list" in resource_uris

    # Resource templates
    templates = resource_manager.list_templates()
    template_uris = [str(t.uri_template) for t in templates]
    assert "memory://facts/{category}" in template_uris


# --- Resource Tests ---

import json
from memory.store import MemoryStore
from memory.models import Fact
from documents.store import DocumentStore
from agents.registry import AgentRegistry, AgentConfig
from chief.orchestrator import ChiefOfStaff


@pytest.fixture
def shared_state(tmp_path):
    """Create the shared state dict that lifespan would provide."""
    memory_store = MemoryStore(tmp_path / "test.db")
    document_store = DocumentStore(persist_dir=tmp_path / "chroma")
    configs_dir = tmp_path / "agent_configs"
    configs_dir.mkdir()
    agent_registry = AgentRegistry(configs_dir)
    chief = ChiefOfStaff(
        memory_store=memory_store,
        document_store=document_store,
        agent_registry=agent_registry,
    )

    state = {
        "chief": chief,
        "memory_store": memory_store,
        "document_store": document_store,
        "agent_registry": agent_registry,
    }

    yield state
    memory_store.close()


class TestResources:
    @pytest.mark.asyncio
    async def test_get_all_facts_empty(self, shared_state):
        from mcp_server import get_all_facts

        with patch("mcp_server.mcp.get_context", return_value=shared_state):
            result = await get_all_facts()

        data = json.loads(result)
        assert "message" in data  # "No facts stored yet."

    @pytest.mark.asyncio
    async def test_get_all_facts_with_data(self, shared_state):
        from mcp_server import get_all_facts

        shared_state["memory_store"].store_fact(
            Fact(category="personal", key="name", value="Jason")
        )
        shared_state["memory_store"].store_fact(
            Fact(category="preference", key="color", value="blue")
        )

        with patch("mcp_server.mcp.get_context", return_value=shared_state):
            result = await get_all_facts()

        data = json.loads(result)
        assert "personal" in data
        assert data["personal"][0]["key"] == "name"
        assert "preference" in data

    @pytest.mark.asyncio
    async def test_get_facts_by_category(self, shared_state):
        from mcp_server import get_facts_by_category

        shared_state["memory_store"].store_fact(
            Fact(category="work", key="title", value="Engineer")
        )

        with patch("mcp_server.mcp.get_context", return_value=shared_state):
            result = await get_facts_by_category("work")

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["key"] == "title"

    @pytest.mark.asyncio
    async def test_get_facts_by_category_empty(self, shared_state):
        from mcp_server import get_facts_by_category

        with patch("mcp_server.mcp.get_context", return_value=shared_state):
            result = await get_facts_by_category("personal")

        data = json.loads(result)
        assert data == []

    @pytest.mark.asyncio
    async def test_get_agents_list_empty(self, shared_state):
        from mcp_server import get_agents_list

        with patch("mcp_server.mcp.get_context", return_value=shared_state):
            result = await get_agents_list()

        data = json.loads(result)
        assert "message" in data  # "No agents configured yet."

    @pytest.mark.asyncio
    async def test_get_agents_list_with_agents(self, shared_state):
        from mcp_server import get_agents_list

        shared_state["agent_registry"].save_agent(AgentConfig(
            name="researcher",
            description="Research expert",
            system_prompt="You are a researcher.",
            capabilities=["web_search", "memory_read"],
        ))

        with patch("mcp_server.mcp.get_context", return_value=shared_state):
            result = await get_agents_list()

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["name"] == "researcher"
        assert "web_search" in data[0]["capabilities"]
