# tests/test_usage_tracker.py
"""Tests for automatic tool usage tracking middleware."""
import pytest

from memory.store import MemoryStore
from mcp_tools.usage_tracker import _extract_query_pattern


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def tracked_mcp(memory_store):
    """Set up mcp_server state with a fresh memory_store.

    The tracker is already installed at import time via mcp_server.py,
    so we just need to point state.memory_store at our test DB.
    """
    import mcp_server

    mcp_server._state.memory_store = memory_store
    yield mcp_server.mcp
    mcp_server._state.clear()


class TestUsageTracker:
    """Tests for the install_usage_tracker middleware."""

    def test_tracker_is_installed(self):
        """mcp.call_tool should be wrapped after mcp_server import."""
        import mcp_server

        assert getattr(mcp_server.mcp.call_tool, "_usage_tracked", False)

    @pytest.mark.asyncio
    async def test_tool_call_is_recorded(self, tracked_mcp, memory_store):
        """A tool call should be recorded in skill_usage table."""
        await tracked_mcp.call_tool("list_locations", {})

        patterns = memory_store.get_skill_usage_patterns()
        tool_names = [p["tool_name"] for p in patterns]
        assert "list_locations" in tool_names

    @pytest.mark.asyncio
    async def test_repeated_calls_increment_count(self, tracked_mcp, memory_store):
        """Multiple calls to the same tool should increment the count."""
        await tracked_mcp.call_tool("list_locations", {})
        await tracked_mcp.call_tool("list_locations", {})
        await tracked_mcp.call_tool("list_locations", {})

        patterns = memory_store.get_skill_usage_patterns()
        loc_pattern = [p for p in patterns if p["tool_name"] == "list_locations"]
        assert len(loc_pattern) == 1
        assert loc_pattern[0]["count"] == 3

    @pytest.mark.asyncio
    async def test_different_tools_tracked_separately(self, tracked_mcp, memory_store):
        """Different tools should each get their own usage row."""
        await tracked_mcp.call_tool("list_locations", {})
        await tracked_mcp.call_tool("query_memory", {"query": "test"})

        patterns = memory_store.get_skill_usage_patterns()
        tool_names = {p["tool_name"] for p in patterns}
        assert "list_locations" in tool_names
        assert "query_memory" in tool_names

    @pytest.mark.asyncio
    async def test_skill_tools_excluded(self, tracked_mcp, memory_store):
        """Skill tracking tools should not track themselves."""
        await tracked_mcp.call_tool("record_tool_usage", {
            "tool_name": "test", "query_pattern": "test"
        })
        await tracked_mcp.call_tool("analyze_skill_patterns", {})
        await tracked_mcp.call_tool("list_skill_suggestions", {})

        patterns = memory_store.get_skill_usage_patterns()
        tool_names = {p["tool_name"] for p in patterns}
        # record_tool_usage creates its own row via the tool itself, not the tracker
        # The tracker should NOT have added entries for these tool names
        assert "analyze_skill_patterns" not in tool_names
        assert "list_skill_suggestions" not in tool_names

    @pytest.mark.asyncio
    async def test_tool_result_passes_through(self, tracked_mcp):
        """The wrapper should return the original tool's result unchanged."""
        result = await tracked_mcp.call_tool("list_locations", {})
        assert result is not None

    @pytest.mark.asyncio
    async def test_tool_error_still_raises(self, tracked_mcp):
        """If a tool raises an error, the wrapper should re-raise it."""
        with pytest.raises(Exception):
            await tracked_mcp.call_tool("nonexistent_tool", {})

    @pytest.mark.asyncio
    async def test_tracking_failure_does_not_break_tool(self, tracked_mcp):
        """If recording fails, the tool should still work."""
        from unittest.mock import patch

        import mcp_server

        with patch.object(
            mcp_server._state.memory_store,
            "record_skill_usage",
            side_effect=Exception("db error"),
        ):
            result = await tracked_mcp.call_tool("list_locations", {})
            assert result is not None

    @pytest.mark.asyncio
    async def test_no_memory_store_skips_tracking(self, memory_store):
        """If memory_store is None, tracking is skipped."""
        import mcp_server

        mcp_server._state.memory_store = None
        try:
            # list_locations will fail (needs memory_store), but the
            # tracker wrapper itself should not be the cause of failure
            with pytest.raises(Exception):
                await mcp_server.mcp.call_tool("list_locations", {})

            # Verify nothing was recorded
            patterns = memory_store.get_skill_usage_patterns()
            assert len(patterns) == 0
        finally:
            mcp_server._state.clear()

    def test_install_is_idempotent(self):
        """Calling install_usage_tracker twice should not double-wrap."""
        import mcp_server
        from mcp_tools.usage_tracker import install_usage_tracker

        wrapper = mcp_server.mcp.call_tool
        install_usage_tracker(mcp_server.mcp, mcp_server._state)
        assert mcp_server.mcp.call_tool is wrapper


class TestExtractQueryPattern:
    """Tests for _extract_query_pattern argument summarizer."""

    def test_returns_auto_for_empty_args(self):
        assert _extract_query_pattern("list_locations", {}) == "auto"
        assert _extract_query_pattern("list_locations", None) == "auto"

    def test_extracts_query_field(self):
        assert _extract_query_pattern("query_memory", {"query": "backlog"}) == "backlog"

    def test_extracts_name_field(self):
        assert _extract_query_pattern("get_agent", {"name": "researcher"}) == "researcher"

    def test_extracts_tool_name_field(self):
        assert _extract_query_pattern("record_tool_usage", {"tool_name": "search_mail"}) == "search_mail"

    def test_extracts_query_pattern_field(self):
        assert _extract_query_pattern("record_tool_usage", {"query_pattern": "weekly meeting"}) == "weekly meeting"

    def test_prefers_query_over_name(self):
        assert _extract_query_pattern("some_tool", {"query": "foo", "name": "bar"}) == "foo"

    def test_extracts_title_field(self):
        assert _extract_query_pattern("create_decision", {"title": "hire contractor"}) == "hire contractor"

    def test_extracts_canonical_name_field(self):
        assert _extract_query_pattern("get_identity", {"canonical_name": "John Smith"}) == "John Smith"

    def test_extracts_recipient_from_to_field(self):
        assert _extract_query_pattern("send_imessage_reply", {"to": "+15551234567", "body": "hello"}) == "+15551234567"

    def test_truncates_long_values(self):
        long_val = "x" * 200
        result = _extract_query_pattern("query_memory", {"query": long_val})
        assert len(result) <= 100

    def test_falls_back_to_auto_for_non_string_args(self):
        assert _extract_query_pattern("some_tool", {"limit": 10, "enabled": True}) == "auto"

    def test_extracts_start_date_as_fallback(self):
        result = _extract_query_pattern("get_calendar_events", {"start_date": "2026-02-25", "end_date": "2026-02-26"})
        assert "2026-02-25" in result
