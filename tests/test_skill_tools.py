# tests/test_skill_tools.py
import json
from unittest.mock import MagicMock, patch

import pytest

from agents.registry import AgentConfig, AgentRegistry
from memory.store import MemoryStore


@pytest.fixture
def shared_state(tmp_path):
    memory_store = MemoryStore(tmp_path / "test.db")
    configs_dir = tmp_path / "agent_configs"
    configs_dir.mkdir()
    agent_registry = AgentRegistry(configs_dir)

    state = {
        "memory_store": memory_store,
        "agent_registry": agent_registry,
    }
    yield state
    memory_store.close()


class TestRecordToolUsage:
    @pytest.mark.asyncio
    async def test_record_usage(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import record_tool_usage

        mcp_server._state.update(shared_state)
        try:
            result = await record_tool_usage("query_memory", "search work")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "recorded"
        assert data["tool_name"] == "query_memory"
        assert data["query_pattern"] == "search work"

    @pytest.mark.asyncio
    async def test_record_increments_count(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import record_tool_usage

        mcp_server._state.update(shared_state)
        try:
            await record_tool_usage("query_memory", "search work")
            await record_tool_usage("query_memory", "search work")
        finally:
            mcp_server._state.clear()

        # Verify count incremented
        store = shared_state["memory_store"]
        patterns = store.get_skill_usage_patterns()
        assert len(patterns) == 1
        assert patterns[0]["count"] == 2


class TestAnalyzeSkillPatterns:
    @pytest.mark.asyncio
    async def test_no_patterns(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import analyze_skill_patterns

        mcp_server._state.update(shared_state)
        try:
            result = await analyze_skill_patterns()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["suggestions_created"] == 0

    @pytest.mark.asyncio
    async def test_creates_suggestions(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import analyze_skill_patterns

        store = shared_state["memory_store"]
        # Record enough usage to trigger a pattern
        for _ in range(10):
            store.record_skill_usage("query_memory", "search work tasks")

        mcp_server._state.update(shared_state)
        try:
            result = await analyze_skill_patterns()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["suggestions_created"] >= 1
        assert len(data["patterns"]) >= 1

    @pytest.mark.asyncio
    async def test_below_threshold_no_suggestions(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import analyze_skill_patterns

        store = shared_state["memory_store"]
        # Only 2 usages -- below SKILL_MIN_OCCURRENCES (5)
        for _ in range(2):
            store.record_skill_usage("query_memory", "search work")

        mcp_server._state.update(shared_state)
        try:
            result = await analyze_skill_patterns()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["suggestions_created"] == 0


class TestListSkillSuggestions:
    @pytest.mark.asyncio
    async def test_empty_list(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import list_skill_suggestions

        mcp_server._state.update(shared_state)
        try:
            result = await list_skill_suggestions()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_list_with_suggestions(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import list_skill_suggestions
        from memory.models import SkillSuggestion

        store = shared_state["memory_store"]
        store.store_skill_suggestion(SkillSuggestion(
            description="Frequent memory searches",
            suggested_name="memory_specialist",
            suggested_capabilities="memory_read",
            confidence=0.85,
        ))

        mcp_server._state.update(shared_state)
        try:
            result = await list_skill_suggestions()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["suggested_name"] == "memory_specialist"
        assert data["results"][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_by_status(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import list_skill_suggestions
        from memory.models import SkillSuggestion

        store = shared_state["memory_store"]
        store.store_skill_suggestion(SkillSuggestion(
            description="Pending suggestion",
            suggested_name="pending_agent",
            confidence=0.8,
        ))
        s = store.store_skill_suggestion(SkillSuggestion(
            description="Accepted suggestion",
            suggested_name="accepted_agent",
            confidence=0.9,
        ))
        store.update_skill_suggestion_status(s.id, "accepted")

        mcp_server._state.update(shared_state)
        try:
            result_pending = await list_skill_suggestions("pending")
            result_accepted = await list_skill_suggestions("accepted")
        finally:
            mcp_server._state.clear()

        pending = json.loads(result_pending)
        accepted = json.loads(result_accepted)
        assert len(pending["results"]) == 1
        assert pending["results"][0]["suggested_name"] == "pending_agent"
        assert len(accepted["results"]) == 1
        assert accepted["results"][0]["suggested_name"] == "accepted_agent"


class TestAutoCreateSkill:
    @pytest.mark.asyncio
    async def test_auto_create_calls_factory(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import auto_create_skill
        from memory.models import SkillSuggestion

        store = shared_state["memory_store"]
        suggestion = store.store_skill_suggestion(SkillSuggestion(
            description="Repeated calendar lookups for team meetings",
            suggested_name="calendar_specialist",
            suggested_capabilities="calendar_read",
            confidence=0.9,
        ))

        mock_config = AgentConfig(
            name="calendar_specialist",
            description="Specializes in calendar lookups",
            system_prompt="You are a calendar specialist.",
            capabilities=["calendar_read"],
        )

        mcp_server._state.update(shared_state)
        try:
            with patch("agents.factory.AgentFactory") as MockFactory:
                mock_instance = MagicMock()
                mock_instance.create_agent.return_value = mock_config
                MockFactory.return_value = mock_instance

                result = await auto_create_skill(suggestion.id)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["agent_name"] == "calendar_specialist"
        assert data["suggestion_id"] == suggestion.id

        # Verify the suggestion was marked as accepted
        updated = store.get_skill_suggestion(suggestion.id)
        assert updated.status == "accepted"

        # Verify factory was called with the description
        mock_instance.create_agent.assert_called_once_with(suggestion.description)

    @pytest.mark.asyncio
    async def test_auto_create_nonexistent_suggestion(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import auto_create_skill

        mcp_server._state.update(shared_state)
        try:
            result = await auto_create_skill(9999)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data
        assert "not found" in data["error"]

    @pytest.mark.asyncio
    async def test_auto_create_already_accepted(self, shared_state):
        import mcp_server
        from mcp_tools.skill_tools import auto_create_skill
        from memory.models import SkillSuggestion

        store = shared_state["memory_store"]
        suggestion = store.store_skill_suggestion(SkillSuggestion(
            description="Already accepted",
            suggested_name="old_agent",
            confidence=0.8,
        ))
        store.update_skill_suggestion_status(suggestion.id, "accepted")

        mcp_server._state.update(shared_state)
        try:
            result = await auto_create_skill(suggestion.id)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data
        assert "already accepted" in data["error"]
