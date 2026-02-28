# tests/test_mcp_server.py
import json

import pytest

from memory.models import AlertRule, Decision, Delegation, Fact, Location
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
        from mcp_tools.memory_tools import store_fact

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
        from mcp_tools.memory_tools import store_fact

        mcp_server._state.update(shared_state)
        try:
            await store_fact("personal", "name", "Jason")
            result = await store_fact("personal", "name", "Jay")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["value"] == "Jay"


class TestStorePinnedFact:
    @pytest.mark.asyncio
    async def test_store_pinned_fact(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import store_fact

        mcp_server._state.update(shared_state)
        try:
            result = await store_fact("personal", "name", "Jason", pinned=True)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "stored"
        # Verify it persisted as pinned
        fact = shared_state["memory_store"].get_fact("personal", "name")
        assert fact.pinned is True

    @pytest.mark.asyncio
    async def test_store_fact_default_not_pinned(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import store_fact

        mcp_server._state.update(shared_state)
        try:
            await store_fact("personal", "name", "Jason")
        finally:
            mcp_server._state.clear()

        fact = shared_state["memory_store"].get_fact("personal", "name")
        assert fact.pinned is False


class TestQueryMemoryHalfLife:
    @pytest.mark.asyncio
    async def test_query_with_custom_half_life(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import query_memory

        shared_state["memory_store"].store_fact(
            Fact(category="personal", key="name", value="Jason")
        )

        mcp_server._state.update(shared_state)
        try:
            result = await query_memory("Jason", half_life_days=30)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) >= 1
        assert data["results"][0]["value"] == "Jason"

    @pytest.mark.asyncio
    async def test_query_with_category_and_half_life(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import query_memory

        shared_state["memory_store"].store_fact(
            Fact(category="work", key="title", value="Engineer")
        )

        mcp_server._state.update(shared_state)
        try:
            result = await query_memory("Engineer", category="work", half_life_days=365)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1


class TestQueryMemory:
    @pytest.mark.asyncio
    async def test_query_by_search(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import query_memory

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
        from mcp_tools.memory_tools import query_memory

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
        from mcp_tools.memory_tools import query_memory

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
        from mcp_tools.memory_tools import query_memory

        mcp_server._state.update(shared_state)
        try:
            result = await query_memory("nonexistent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_query_memory_diverse_param(self, shared_state):
        """Verify query_memory passes diverse parameter to search_facts_hybrid."""
        import mcp_server
        from mcp_tools.memory_tools import query_memory

        shared_state["memory_store"].store_fact(
            Fact(category="work", key="proj_a", value="project alpha deadline friday")
        )
        shared_state["memory_store"].store_fact(
            Fact(category="work", key="proj_b", value="project beta deadline friday")
        )
        shared_state["memory_store"].store_fact(
            Fact(category="personal", key="hobby", value="likes hiking outdoors")
        )

        mcp_server._state.update(shared_state)
        try:
            result_diverse = await query_memory("project deadline", diverse=True)
            result_no_diverse = await query_memory("project deadline", diverse=False)
        finally:
            mcp_server._state.clear()

        data_diverse = json.loads(result_diverse)
        data_no_diverse = json.loads(result_no_diverse)
        # Both should return results
        assert len(data_diverse["results"]) >= 2
        assert len(data_no_diverse["results"]) >= 2


class TestSkillUsageRecording:
    @pytest.mark.asyncio
    async def test_query_memory_does_not_record_skill_usage_directly(self, shared_state):
        """Verify query_memory does NOT record skill_usage inline (handled by middleware)."""
        import mcp_server
        from mcp_tools.memory_tools import query_memory

        shared_state["memory_store"].store_fact(
            Fact(category="personal", key="name", value="Jason")
        )

        mcp_server._state.update(shared_state)
        try:
            await query_memory("Jason")
        finally:
            mcp_server._state.clear()

        patterns = shared_state["memory_store"].get_skill_usage_patterns()
        assert not any(p["tool_name"] == "query_memory" for p in patterns)

    @pytest.mark.asyncio
    async def test_query_memory_no_recording_on_empty_results(self, shared_state):
        """Verify query_memory does NOT record usage when there are no results."""
        import mcp_server
        from mcp_tools.memory_tools import query_memory

        mcp_server._state.update(shared_state)
        try:
            await query_memory("nonexistent")
        finally:
            mcp_server._state.clear()

        patterns = shared_state["memory_store"].get_skill_usage_patterns()
        assert not any(p["tool_name"] == "query_memory" for p in patterns)


class TestStoreLocation:
    @pytest.mark.asyncio
    async def test_store_location(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import store_location

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
        from mcp_tools.memory_tools import list_locations

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
        from mcp_tools.memory_tools import store_location, list_locations

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
        from mcp_tools.document_tools import ingest_documents

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
        from mcp_tools.document_tools import ingest_documents

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
        from mcp_tools.document_tools import ingest_documents

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
        from mcp_tools.document_tools import ingest_documents

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
        from mcp_tools.document_tools import search_documents

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
        from mcp_tools.document_tools import ingest_documents, search_documents

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
        from mcp_tools.agent_tools import list_agents

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
        from mcp_tools.agent_tools import list_agents

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
        from mcp_tools.agent_tools import get_agent

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
        from mcp_tools.agent_tools import get_agent

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
        from mcp_tools.agent_tools import create_agent, get_agent

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
        from mcp_tools.agent_tools import create_agent

        mcp_server._state.update(shared_state)
        try:
            result = await create_agent("basic", "Basic agent", "You are helpful.")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["capabilities"] == []

    @pytest.mark.asyncio
    async def test_create_agent_rejects_unknown_capability(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import create_agent

        mcp_server._state.update(shared_state)
        try:
            result = await create_agent(
                "invalid_agent",
                "Invalid",
                "You are invalid.",
                "memory_read,not_real",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data
        assert "Unknown capability" in data["error"]


# --- Resource Tests ---


class TestResources:
    @pytest.mark.asyncio
    async def test_get_all_facts_empty(self, shared_state):
        import mcp_server
        from mcp_tools.resources import get_all_facts

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
        from mcp_tools.resources import get_all_facts

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
        from mcp_tools.resources import get_facts_by_category

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
        from mcp_tools.resources import get_facts_by_category

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
        from mcp_tools.resources import get_agents_list

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
        from mcp_tools.resources import get_agents_list

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
        from mcp_tools.memory_tools import store_fact

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
        from mcp_tools.memory_tools import store_fact

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
        from mcp_tools.document_tools import ingest_documents

        mcp_server._state.update(shared_state)
        try:
            result = await ingest_documents("/etc/passwd")
        finally:
            mcp_server._state.clear()

        assert "Access denied" in result

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, shared_state):
        import mcp_server
        from mcp_tools.document_tools import ingest_documents

        mcp_server._state.update(shared_state)
        try:
            result = await ingest_documents("/tmp/../etc/passwd")
        finally:
            mcp_server._state.clear()

        assert "Access denied" in result

    @pytest.mark.asyncio
    async def test_rejects_sibling_directory_prefix_match(self, shared_state, tmp_path):
        """Ensure /allowed_root_malicious doesn't match /allowed_root via string prefix."""
        import mcp_server
        from mcp_tools.document_tools import ingest_documents

        allowed = tmp_path / "safe"
        allowed.mkdir()
        sibling = tmp_path / "safe_malicious"
        sibling.mkdir()
        secret = sibling / "secret.txt"
        secret.write_text("secret data")

        shared_state["allowed_ingest_roots"] = [allowed.resolve()]
        mcp_server._state.update(shared_state)
        try:
            result = await ingest_documents(str(secret))
        finally:
            mcp_server._state.clear()

        assert "Access denied" in result


# --- Decision Log Tool Tests ---


class TestLogDecision:
    @pytest.mark.asyncio
    async def test_log_decision_minimal(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision

        mcp_server._state.update(shared_state)
        try:
            result = await log_decision("Migrate to AWS")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "logged"
        assert data["title"] == "Migrate to AWS"
        assert data["decision_status"] == "pending_execution"
        assert isinstance(data["id"], int)

    @pytest.mark.asyncio
    async def test_log_decision_full(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision

        mcp_server._state.update(shared_state)
        try:
            result = await log_decision(
                title="Switch to PostgreSQL",
                description="Moving from SQLite to PostgreSQL for production",
                context="Growing data volume",
                decided_by="CTO",
                owner="Platform team",
                status="pending_execution",
                follow_up_date="2026-03-01",
                tags="infrastructure,database",
                source="Architecture review meeting",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "logged"
        assert data["title"] == "Switch to PostgreSQL"


class TestSearchDecisions:
    @pytest.mark.asyncio
    async def test_search_empty(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import search_decisions

        mcp_server._state.update(shared_state)
        try:
            result = await search_decisions(query="anything")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_search_by_query(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision, search_decisions

        mcp_server._state.update(shared_state)
        try:
            await log_decision("Migrate to AWS")
            await log_decision("Hire frontend dev")
            result = await search_decisions(query="AWS")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Migrate to AWS"

    @pytest.mark.asyncio
    async def test_search_by_status(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision, search_decisions

        mcp_server._state.update(shared_state)
        try:
            await log_decision("Decision A", status="executed")
            await log_decision("Decision B", status="pending_execution")
            result = await search_decisions(status="executed")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Decision A"

    @pytest.mark.asyncio
    async def test_search_by_query_and_status(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision, search_decisions

        mcp_server._state.update(shared_state)
        try:
            await log_decision("Migrate DB", status="pending_execution")
            await log_decision("Migrate API", status="executed")
            result = await search_decisions(query="Migrate", status="executed")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Migrate API"

    @pytest.mark.asyncio
    async def test_search_all(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision, search_decisions

        mcp_server._state.update(shared_state)
        try:
            await log_decision("Decision A")
            await log_decision("Decision B")
            result = await search_decisions()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 2


class TestUpdateDecision:
    @pytest.mark.asyncio
    async def test_update_status(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision, update_decision

        mcp_server._state.update(shared_state)
        try:
            logged = json.loads(await log_decision("Test decision"))
            result = await update_decision(logged["id"], status="executed")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "updated"
        assert data["decision_status"] == "executed"

    @pytest.mark.asyncio
    async def test_update_notes(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision, update_decision

        mcp_server._state.update(shared_state)
        try:
            logged = json.loads(await log_decision("Test decision"))
            result = await update_decision(logged["id"], notes="Completed successfully")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "updated"

    @pytest.mark.asyncio
    async def test_update_not_found(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import update_decision

        mcp_server._state.update(shared_state)
        try:
            result = await update_decision(9999, status="executed")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_update_no_fields(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision, update_decision

        mcp_server._state.update(shared_state)
        try:
            logged = json.loads(await log_decision("Test decision"))
            result = await update_decision(logged["id"])
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data


class TestListPendingDecisions:
    @pytest.mark.asyncio
    async def test_no_pending(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import list_pending_decisions

        mcp_server._state.update(shared_state)
        try:
            result = await list_pending_decisions()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_with_pending(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision, list_pending_decisions

        mcp_server._state.update(shared_state)
        try:
            await log_decision("Pending one", status="pending_execution")
            await log_decision("Done one", status="executed")
            result = await list_pending_decisions()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Pending one"


class TestDeleteDecision:
    @pytest.mark.asyncio
    async def test_delete_existing(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_decision as log_decision, delete_decision

        mcp_server._state.update(shared_state)
        try:
            created = json.loads(await log_decision("To delete"))
            result = await delete_decision(created["id"])
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import delete_decision

        mcp_server._state.update(shared_state)
        try:
            result = await delete_decision(9999)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data


# --- Delegation Tracker Tool Tests ---


class TestAddDelegation:
    @pytest.mark.asyncio
    async def test_add_delegation_minimal(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation

        mcp_server._state.update(shared_state)
        try:
            result = await add_delegation("Review PR", "Alice")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["task"] == "Review PR"
        assert data["delegated_to"] == "Alice"
        assert isinstance(data["id"], int)

    @pytest.mark.asyncio
    async def test_add_delegation_full(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation

        mcp_server._state.update(shared_state)
        try:
            result = await add_delegation(
                task="Deploy v2.0",
                delegated_to="Bob",
                description="Full production deployment",
                due_date="2026-02-20",
                priority="high",
                source="Sprint planning",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["due_date"] == "2026-02-20"


class TestListDelegations:
    @pytest.mark.asyncio
    async def test_list_empty(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import list_delegations

        mcp_server._state.update(shared_state)
        try:
            result = await list_delegations()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_list_all(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation, list_delegations

        mcp_server._state.update(shared_state)
        try:
            await add_delegation("Task A", "Alice")
            await add_delegation("Task B", "Bob")
            result = await list_delegations()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 2

    @pytest.mark.asyncio
    async def test_list_by_status(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation, update_delegation, list_delegations

        mcp_server._state.update(shared_state)
        try:
            created = json.loads(await add_delegation("Task A", "Alice"))
            await add_delegation("Task B", "Bob")
            await update_delegation(created["id"], status="completed")
            result = await list_delegations(status="active")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["task"] == "Task B"

    @pytest.mark.asyncio
    async def test_list_by_delegated_to(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation, list_delegations

        mcp_server._state.update(shared_state)
        try:
            await add_delegation("Task A", "Alice")
            await add_delegation("Task B", "Bob")
            result = await list_delegations(delegated_to="Alice")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["delegated_to"] == "Alice"


class TestUpdateDelegation:
    @pytest.mark.asyncio
    async def test_update_status(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation, update_delegation

        mcp_server._state.update(shared_state)
        try:
            created = json.loads(await add_delegation("Task", "Alice"))
            result = await update_delegation(created["id"], status="completed")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "updated"
        assert data["delegation_status"] == "completed"

    @pytest.mark.asyncio
    async def test_update_notes(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation, update_delegation

        mcp_server._state.update(shared_state)
        try:
            created = json.loads(await add_delegation("Task", "Alice"))
            result = await update_delegation(created["id"], notes="In progress")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "updated"

    @pytest.mark.asyncio
    async def test_update_not_found(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import update_delegation

        mcp_server._state.update(shared_state)
        try:
            result = await update_delegation(9999, status="completed")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_update_no_fields(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation, update_delegation

        mcp_server._state.update(shared_state)
        try:
            created = json.loads(await add_delegation("Task", "Alice"))
            result = await update_delegation(created["id"])
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data


class TestCheckOverdueDelegations:
    @pytest.mark.asyncio
    async def test_no_overdue(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import check_overdue_delegations

        mcp_server._state.update(shared_state)
        try:
            result = await check_overdue_delegations()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_with_overdue(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation, check_overdue_delegations

        mcp_server._state.update(shared_state)
        try:
            await add_delegation("Overdue task", "Alice", due_date="2020-01-01")
            await add_delegation("Future task", "Bob", due_date="2099-12-31")
            result = await check_overdue_delegations()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["task"] == "Overdue task"


class TestDeleteDelegation:
    @pytest.mark.asyncio
    async def test_delete_existing(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation, delete_delegation

        mcp_server._state.update(shared_state)
        try:
            created = json.loads(await add_delegation("To delete", "Alice"))
            result = await delete_delegation(created["id"])
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import delete_delegation

        mcp_server._state.update(shared_state)
        try:
            result = await delete_delegation(9999)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data


# --- Alert Tool Tests ---


class TestCreateAlertRule:
    @pytest.mark.asyncio
    async def test_create_rule(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_alert_rule

        mcp_server._state.update(shared_state)
        try:
            result = await create_alert_rule("overdue_check", "overdue_delegation", description="Check overdue items")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["name"] == "overdue_check"
        assert data["alert_type"] == "overdue_delegation"
        assert data["enabled"] is True

    @pytest.mark.asyncio
    async def test_create_disabled_rule(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_alert_rule

        mcp_server._state.update(shared_state)
        try:
            result = await create_alert_rule("test_rule", "pending_decision", enabled=False)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["enabled"] is False


class TestListAlertRules:
    @pytest.mark.asyncio
    async def test_list_empty(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import list_alert_rules

        mcp_server._state.update(shared_state)
        try:
            result = await list_alert_rules()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_list_all(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_alert_rule, list_alert_rules

        mcp_server._state.update(shared_state)
        try:
            await create_alert_rule("rule_a", "overdue_delegation")
            await create_alert_rule("rule_b", "pending_decision", enabled=False)
            result = await list_alert_rules()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 2

    @pytest.mark.asyncio
    async def test_list_enabled_only(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_alert_rule, list_alert_rules

        mcp_server._state.update(shared_state)
        try:
            await create_alert_rule("enabled_rule", "overdue_delegation")
            await create_alert_rule("disabled_rule", "pending_decision", enabled=False)
            result = await list_alert_rules(enabled_only=True)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "enabled_rule"


class TestCheckAlerts:
    @pytest.mark.asyncio
    async def test_check_no_alerts(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import check_alerts

        mcp_server._state.update(shared_state)
        try:
            result = await check_alerts()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["total_alerts"] == 0

    @pytest.mark.asyncio
    async def test_check_overdue_delegation_alert(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation, check_alerts

        mcp_server._state.update(shared_state)
        try:
            await add_delegation("Past due task", "Alice", due_date="2020-01-01")
            result = await check_alerts()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["total_alerts"] >= 1
        assert len(data["alerts"]["overdue_delegations"]) == 1

    @pytest.mark.asyncio
    async def test_check_stale_decision_alert(self, shared_state):
        """Decisions pending > 7 days should show as stale."""
        import mcp_server
        from mcp_tools.lifecycle_tools import check_alerts
        from datetime import datetime, timedelta

        # Directly insert an old decision
        memory_store = shared_state["memory_store"]
        old_date = (datetime.now() - timedelta(days=10)).isoformat()
        memory_store.conn.execute(
            """INSERT INTO decisions (title, status, created_at, updated_at)
               VALUES (?, ?, ?, ?)""",
            ("Old pending decision", "pending_execution", old_date, old_date),
        )
        memory_store.conn.commit()

        mcp_server._state.update(shared_state)
        try:
            result = await check_alerts()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["alerts"]["stale_decisions"]) == 1
        assert data["alerts"]["stale_decisions"][0]["title"] == "Old pending decision"

    @pytest.mark.asyncio
    async def test_check_upcoming_deadline_alert(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_delegation as add_delegation, check_alerts
        from datetime import date, timedelta

        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        mcp_server._state.update(shared_state)
        try:
            await add_delegation("Due soon", "Bob", due_date=tomorrow)
            result = await check_alerts()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["alerts"]["upcoming_deadlines"]) == 1
        assert data["alerts"]["upcoming_deadlines"][0]["task"] == "Due soon"


# --- Tool Registration Tests (new tools) ---


class TestDismissAlert:
    @pytest.mark.asyncio
    async def test_dismiss_existing_rule(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import create_alert_rule, dismiss_alert

        mcp_server._state.update(shared_state)
        try:
            created = json.loads(await create_alert_rule("my_rule", "overdue_delegation"))
            assert created["enabled"] is True
            result = await dismiss_alert(created["id"])
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "dismissed"
        assert data["name"] == "my_rule"
        assert data["enabled"] is False

    @pytest.mark.asyncio
    async def test_dismiss_not_found(self, shared_state):
        import mcp_server
        from mcp_tools.lifecycle_tools import dismiss_alert

        mcp_server._state.update(shared_state)
        try:
            result = await dismiss_alert(9999)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data


class TestNewToolsRegistered:
    def test_new_mcp_tools_registered(self):
        """Verify new MCP tools are registered."""
        import mcp_server
        tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
        expected = [
            "create_decision", "search_decisions", "update_decision", "list_pending_decisions", "delete_decision",
            "create_delegation", "list_delegations", "update_delegation", "check_overdue_delegations", "delete_delegation",
            "create_alert_rule", "list_alert_rules", "check_alerts", "dismiss_alert",
        ]
        for name in expected:
            assert name in tool_names, f"Tool '{name}' not registered"

