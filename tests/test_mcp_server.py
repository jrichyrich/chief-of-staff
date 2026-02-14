# tests/test_mcp_server.py
import json

import pytest

from memory.models import Fact, Location
from memory.store import MemoryStore
from documents.store import DocumentStore
from agents.registry import AgentRegistry, AgentConfig


def test_mcp_server_imports():
    """Verify mcp_server module can be imported."""
    import mcp_server
    assert hasattr(mcp_server, "mcp")
    assert hasattr(mcp_server, "app_lifespan")


def test_mcp_server_has_tools():
    """Verify the MCP server registers the expected tools."""
    import mcp_server
    tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
    assert "store_fact" in tool_names
    assert "query_memory" in tool_names
    assert "store_location" in tool_names
    assert "list_locations" in tool_names
    assert "search_documents" in tool_names
    assert "ingest_documents" in tool_names
    assert "list_agents" in tool_names
    assert "get_agent" in tool_names
    assert "create_agent" in tool_names
    # Old tool should NOT be present
    assert "chief_of_staff_ask" not in tool_names


def test_mcp_server_has_resources():
    """Verify the MCP server registers the expected resources."""
    import mcp_server
    resource_manager = mcp_server.mcp._resource_manager

    resources = resource_manager.list_resources()
    resource_uris = [str(r.uri) for r in resources]
    assert "memory://facts" in resource_uris
    assert "agents://list" in resource_uris

    templates = resource_manager.list_templates()
    template_uris = [str(t.uri_template) for t in templates]
    assert "memory://facts/{category}" in template_uris


@pytest.fixture
def shared_state(tmp_path):
    """Create the shared state dict that lifespan would provide."""
    memory_store = MemoryStore(tmp_path / "test.db")
    document_store = DocumentStore(persist_dir=tmp_path / "chroma")
    configs_dir = tmp_path / "agent_configs"
    configs_dir.mkdir()
    agent_registry = AgentRegistry(configs_dir)

    state = {
        "memory_store": memory_store,
        "document_store": document_store,
        "agent_registry": agent_registry,
    }

    yield state
    memory_store.close()


# --- Memory Tool Tests ---


class TestStoreFact:
    @pytest.mark.asyncio
    async def test_store_new_fact(self, shared_state):
        import mcp_server
        from mcp_server import store_fact

        mcp_server._state.update(shared_state)
        try:
            result = await store_fact("personal", "name", "Jason")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "stored"
        assert data["category"] == "personal"
        assert data["key"] == "name"
        assert data["value"] == "Jason"

    @pytest.mark.asyncio
    async def test_store_fact_overwrites(self, shared_state):
        import mcp_server
        from mcp_server import store_fact

        mcp_server._state.update(shared_state)
        try:
            await store_fact("personal", "name", "Jason")
            result = await store_fact("personal", "name", "Jay")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["value"] == "Jay"


class TestQueryMemory:
    @pytest.mark.asyncio
    async def test_query_by_search(self, shared_state):
        import mcp_server
        from mcp_server import query_memory

        shared_state["memory_store"].store_fact(
            Fact(category="personal", key="name", value="Jason")
        )

        mcp_server._state.update(shared_state)
        try:
            result = await query_memory("Jason")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) >= 1
        assert data["results"][0]["value"] == "Jason"

    @pytest.mark.asyncio
    async def test_query_by_category(self, shared_state):
        import mcp_server
        from mcp_server import query_memory

        shared_state["memory_store"].store_fact(
            Fact(category="work", key="title", value="Engineer")
        )

        mcp_server._state.update(shared_state)
        try:
            result = await query_memory("Engineer", category="work")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["key"] == "title"

    @pytest.mark.asyncio
    async def test_query_category_filters_by_query_text(self, shared_state):
        """When both category and query are provided, filter by both."""
        import mcp_server
        from mcp_server import query_memory

        shared_state["memory_store"].store_fact(
            Fact(category="work", key="title", value="Engineer")
        )
        shared_state["memory_store"].store_fact(
            Fact(category="work", key="company", value="Acme Corp")
        )

        mcp_server._state.update(shared_state)
        try:
            result = await query_memory("Engineer", category="work")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["key"] == "title"

    @pytest.mark.asyncio
    async def test_query_no_results(self, shared_state):
        import mcp_server
        from mcp_server import query_memory

        mcp_server._state.update(shared_state)
        try:
            result = await query_memory("nonexistent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["results"] == []


class TestStoreLocation:
    @pytest.mark.asyncio
    async def test_store_location(self, shared_state):
        import mcp_server
        from mcp_server import store_location

        mcp_server._state.update(shared_state)
        try:
            result = await store_location("office", address="123 Main St", notes="Building A")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "stored"
        assert data["name"] == "office"
        assert data["address"] == "123 Main St"


class TestListLocations:
    @pytest.mark.asyncio
    async def test_list_locations_empty(self, shared_state):
        import mcp_server
        from mcp_server import list_locations

        mcp_server._state.update(shared_state)
        try:
            result = await list_locations()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_list_locations_with_data(self, shared_state):
        import mcp_server
        from mcp_server import store_location, list_locations

        mcp_server._state.update(shared_state)
        try:
            await store_location("home", address="456 Oak Ave")
            await store_location("office", address="123 Main St")
            result = await list_locations()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 2


# --- Document Tool Tests ---


class TestIngestDocumentsTool:
    @pytest.mark.asyncio
    async def test_ingest_single_file(self, shared_state, tmp_path):
        import mcp_server
        from mcp_server import ingest_documents

        test_file = tmp_path / "test.txt"
        test_file.write_text("This is a test document about machine learning.")

        shared_state["allowed_ingest_roots"] = [tmp_path.resolve()]
        mcp_server._state.update(shared_state)
        try:
            result = await ingest_documents(str(test_file))
        finally:
            mcp_server._state.clear()

        assert "1 file(s)" in result
        assert "chunk" in result

    @pytest.mark.asyncio
    async def test_ingest_directory(self, shared_state, tmp_path):
        import mcp_server
        from mcp_server import ingest_documents

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "a.txt").write_text("Document A content")
        (docs_dir / "b.md").write_text("# Document B\nContent here")

        shared_state["allowed_ingest_roots"] = [tmp_path.resolve()]
        mcp_server._state.update(shared_state)
        try:
            result = await ingest_documents(str(docs_dir))
        finally:
            mcp_server._state.clear()

        assert "2 file(s)" in result

    @pytest.mark.asyncio
    async def test_ingest_nonexistent_path(self, shared_state, tmp_path):
        import mcp_server
        from mcp_server import ingest_documents

        shared_state["allowed_ingest_roots"] = [tmp_path.resolve()]
        mcp_server._state.update(shared_state)
        try:
            result = await ingest_documents(str(tmp_path / "nonexistent"))
        finally:
            mcp_server._state.clear()

        assert "Path not found" in result

    @pytest.mark.asyncio
    async def test_ingest_empty_directory(self, shared_state, tmp_path):
        import mcp_server
        from mcp_server import ingest_documents

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        shared_state["allowed_ingest_roots"] = [tmp_path.resolve()]
        mcp_server._state.update(shared_state)
        try:
            result = await ingest_documents(str(empty_dir))
        finally:
            mcp_server._state.clear()

        assert "No supported files" in result


class TestSearchDocuments:
    @pytest.mark.asyncio
    async def test_search_empty(self, shared_state):
        import mcp_server
        from mcp_server import search_documents

        mcp_server._state.update(shared_state)
        try:
            result = await search_documents("machine learning")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_search_after_ingest(self, shared_state, tmp_path):
        import mcp_server
        from mcp_server import ingest_documents, search_documents

        test_file = tmp_path / "ml.txt"
        test_file.write_text("Deep learning is a subset of machine learning that uses neural networks.")

        shared_state["allowed_ingest_roots"] = [tmp_path.resolve()]
        mcp_server._state.update(shared_state)
        try:
            await ingest_documents(str(test_file))
            result = await search_documents("neural networks")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) >= 1


# --- Agent Tool Tests ---


class TestListAgents:
    @pytest.mark.asyncio
    async def test_list_agents_empty(self, shared_state):
        import mcp_server
        from mcp_server import list_agents

        mcp_server._state.update(shared_state)
        try:
            result = await list_agents()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "message" in data

    @pytest.mark.asyncio
    async def test_list_agents_with_data(self, shared_state):
        import mcp_server
        from mcp_server import list_agents

        shared_state["agent_registry"].save_agent(AgentConfig(
            name="researcher",
            description="Research expert",
            system_prompt="You are a researcher.",
            capabilities=["web_search", "memory_read"],
        ))

        mcp_server._state.update(shared_state)
        try:
            result = await list_agents()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "researcher"


class TestGetAgent:
    @pytest.mark.asyncio
    async def test_get_existing_agent(self, shared_state):
        import mcp_server
        from mcp_server import get_agent

        shared_state["agent_registry"].save_agent(AgentConfig(
            name="researcher",
            description="Research expert",
            system_prompt="You are a researcher.",
            capabilities=["web_search"],
        ))

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent("researcher")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["name"] == "researcher"
        assert data["system_prompt"] == "You are a researcher."

    @pytest.mark.asyncio
    async def test_get_nonexistent_agent(self, shared_state):
        import mcp_server
        from mcp_server import get_agent

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent("does_not_exist")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data


class TestCreateAgent:
    @pytest.mark.asyncio
    async def test_create_agent(self, shared_state):
        import mcp_server
        from mcp_server import create_agent, get_agent

        mcp_server._state.update(shared_state)
        try:
            result = await create_agent(
                "writer", "Writing expert", "You are a writer.", "writing,editing"
            )
            verify = await get_agent("writer")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["capabilities"] == ["writing", "editing"]

        detail = json.loads(verify)
        assert detail["name"] == "writer"

    @pytest.mark.asyncio
    async def test_create_agent_no_capabilities(self, shared_state):
        import mcp_server
        from mcp_server import create_agent

        mcp_server._state.update(shared_state)
        try:
            result = await create_agent("basic", "Basic agent", "You are helpful.")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["capabilities"] == []


# --- Resource Tests ---


class TestResources:
    @pytest.mark.asyncio
    async def test_get_all_facts_empty(self, shared_state):
        import mcp_server
        from mcp_server import get_all_facts

        mcp_server._state.update(shared_state)
        try:
            result = await get_all_facts()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "message" in data

    @pytest.mark.asyncio
    async def test_get_all_facts_with_data(self, shared_state):
        import mcp_server
        from mcp_server import get_all_facts

        shared_state["memory_store"].store_fact(
            Fact(category="personal", key="name", value="Jason")
        )
        shared_state["memory_store"].store_fact(
            Fact(category="preference", key="color", value="blue")
        )

        mcp_server._state.update(shared_state)
        try:
            result = await get_all_facts()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "personal" in data
        assert data["personal"][0]["key"] == "name"
        assert "preference" in data

    @pytest.mark.asyncio
    async def test_get_facts_by_category(self, shared_state):
        import mcp_server
        from mcp_server import get_facts_by_category

        shared_state["memory_store"].store_fact(
            Fact(category="work", key="title", value="Engineer")
        )

        mcp_server._state.update(shared_state)
        try:
            result = await get_facts_by_category("work")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["key"] == "title"

    @pytest.mark.asyncio
    async def test_get_facts_by_category_empty(self, shared_state):
        import mcp_server
        from mcp_server import get_facts_by_category

        mcp_server._state.update(shared_state)
        try:
            result = await get_facts_by_category("personal")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data == []

    @pytest.mark.asyncio
    async def test_get_agents_list_empty(self, shared_state):
        import mcp_server
        from mcp_server import get_agents_list

        mcp_server._state.update(shared_state)
        try:
            result = await get_agents_list()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "message" in data

    @pytest.mark.asyncio
    async def test_get_agents_list_with_agents(self, shared_state):
        import mcp_server
        from mcp_server import get_agents_list

        shared_state["agent_registry"].save_agent(AgentConfig(
            name="researcher",
            description="Research expert",
            system_prompt="You are a researcher.",
            capabilities=["web_search", "memory_read"],
        ))

        mcp_server._state.update(shared_state)
        try:
            result = await get_agents_list()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["name"] == "researcher"
        assert "web_search" in data[0]["capabilities"]


# --- Security Fix Tests ---


class TestStoreFactValidation:
    @pytest.mark.asyncio
    async def test_rejects_invalid_category(self, shared_state):
        import mcp_server
        from mcp_server import store_fact

        mcp_server._state.update(shared_state)
        try:
            result = await store_fact("invalid_cat", "key", "value")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data
        assert "Invalid category" in data["error"]

    @pytest.mark.asyncio
    async def test_accepts_valid_categories(self, shared_state):
        import mcp_server
        from mcp_server import store_fact

        mcp_server._state.update(shared_state)
        try:
            for cat in ("personal", "preference", "work", "relationship"):
                result = await store_fact(cat, "test_key", "test_value")
                data = json.loads(result)
                assert data["status"] == "stored", f"Failed for category: {cat}"
        finally:
            mcp_server._state.clear()


class TestIngestDocumentsSecurity:
    @pytest.mark.asyncio
    async def test_rejects_path_outside_home(self, shared_state):
        import mcp_server
        from mcp_server import ingest_documents

        mcp_server._state.update(shared_state)
        try:
            result = await ingest_documents("/etc/passwd")
        finally:
            mcp_server._state.clear()

        assert "Access denied" in result

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, shared_state):
        import mcp_server
        from mcp_server import ingest_documents

        mcp_server._state.update(shared_state)
        try:
            result = await ingest_documents("/tmp/../etc/passwd")
        finally:
            mcp_server._state.clear()

        assert "Access denied" in result
