# tests/test_usage_tracker.py
"""Tests for automatic tool usage tracking middleware."""
import json

import pytest

from memory.store import MemoryStore
from mcp_tools.usage_tracker import _extract_query_pattern



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
        """ToolManager.call_tool should be wrapped after mcp_server import."""
        import mcp_server

        assert getattr(mcp_server.mcp._tool_manager.call_tool, "_usage_tracked", False)

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

    @pytest.mark.asyncio
    async def test_tracks_query_argument(self, tracked_mcp, memory_store):
        """Tools with a 'query' arg should record the query value, not 'auto'."""
        await tracked_mcp.call_tool("query_memory", {"query": "weekly priorities"})

        patterns = memory_store.get_skill_usage_patterns()
        qm = [p for p in patterns if p["tool_name"] == "query_memory"]
        assert any(p["query_pattern"] == "weekly priorities" for p in qm)

    @pytest.mark.asyncio
    async def test_no_args_still_tracks_auto(self, tracked_mcp, memory_store):
        """Tools with no meaningful args should still record 'auto'."""
        await tracked_mcp.call_tool("list_locations", {})

        patterns = memory_store.get_skill_usage_patterns()
        loc = [p for p in patterns if p["tool_name"] == "list_locations"]
        assert any(p["query_pattern"] == "auto" for p in loc)

    @pytest.mark.asyncio
    async def test_invocation_logged_to_temporal_table(self, tracked_mcp, memory_store):
        """Each tool call should create a row in tool_usage_log."""
        await tracked_mcp.call_tool("list_locations", {})
        await tracked_mcp.call_tool("list_locations", {})

        log = memory_store.get_tool_usage_log(tool_name="list_locations")
        assert len(log) == 2  # Two separate rows, not aggregated
        assert all(row["success"] is True for row in log)

    @pytest.mark.asyncio
    async def test_invocation_log_captures_duration(self, tracked_mcp, memory_store):
        """Invocation log should include duration_ms."""
        await tracked_mcp.call_tool("list_locations", {})

        log = memory_store.get_tool_usage_log(tool_name="list_locations")
        assert len(log) == 1
        assert log[0]["duration_ms"] is not None
        assert log[0]["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_invocation_log_records_failure(self, tracked_mcp, memory_store):
        """Failed tool calls should be logged with success=False."""
        try:
            await tracked_mcp.call_tool("nonexistent_tool", {})
        except Exception:
            pass

        log = memory_store.get_tool_usage_log(tool_name="nonexistent_tool")
        assert len(log) == 1
        assert log[0]["success"] is False

    def test_install_is_idempotent(self):
        """Calling install_usage_tracker twice should not double-wrap."""
        import mcp_server
        from mcp_tools.usage_tracker import install_usage_tracker

        wrapper = mcp_server.mcp._tool_manager.call_tool
        install_usage_tracker(mcp_server.mcp, mcp_server._state)
        assert mcp_server.mcp._tool_manager.call_tool is wrapper


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


class TestToolUsageLog:
    """Tests for the tool_usage_log table."""

    def test_log_invocation(self, memory_store):
        memory_store.log_tool_invocation(
            tool_name="query_memory",
            query_pattern="backlog",
            success=True,
            duration_ms=42,
            session_id="sess-001",
        )
        rows = memory_store.get_tool_usage_log(tool_name="query_memory")
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "query_memory"
        assert rows[0]["query_pattern"] == "backlog"
        assert rows[0]["success"] is True
        assert rows[0]["duration_ms"] == 42
        assert rows[0]["session_id"] == "sess-001"

    def test_multiple_invocations_stored_separately(self, memory_store):
        for i in range(3):
            memory_store.log_tool_invocation(
                tool_name="search_mail",
                query_pattern=f"query-{i}",
                success=True,
                duration_ms=10 * i,
            )
        rows = memory_store.get_tool_usage_log(tool_name="search_mail")
        assert len(rows) == 3

    def test_log_with_defaults(self, memory_store):
        memory_store.log_tool_invocation(tool_name="list_locations")
        rows = memory_store.get_tool_usage_log(tool_name="list_locations")
        assert len(rows) == 1
        assert rows[0]["query_pattern"] == "auto"
        assert rows[0]["success"] is True
        assert rows[0]["duration_ms"] is None
        assert rows[0]["session_id"] is None

    def test_get_log_with_limit(self, memory_store):
        for i in range(10):
            memory_store.log_tool_invocation(tool_name="search_mail", query_pattern=f"q{i}")
        rows = memory_store.get_tool_usage_log(tool_name="search_mail", limit=5)
        assert len(rows) == 5

    def test_get_log_all_tools(self, memory_store):
        memory_store.log_tool_invocation(tool_name="query_memory")
        memory_store.log_tool_invocation(tool_name="search_mail")
        rows = memory_store.get_tool_usage_log()
        assert len(rows) == 2

    def test_get_tool_stats_summary(self, memory_store):
        memory_store.log_tool_invocation(tool_name="query_memory", success=True, duration_ms=10)
        memory_store.log_tool_invocation(tool_name="query_memory", success=True, duration_ms=20)
        memory_store.log_tool_invocation(tool_name="query_memory", success=False, duration_ms=5)
        memory_store.log_tool_invocation(tool_name="search_mail", success=True, duration_ms=30)

        stats = memory_store.get_tool_stats_summary()
        assert len(stats) == 2

        qm = next(s for s in stats if s["tool_name"] == "query_memory")
        assert qm["total_calls"] == 3
        assert qm["success_count"] == 2
        assert qm["failure_count"] == 1
        assert qm["avg_duration_ms"] == pytest.approx(11.67, abs=0.1)

    def test_get_top_patterns_by_tool(self, memory_store):
        memory_store.log_tool_invocation("query_memory", "backlog")
        memory_store.log_tool_invocation("query_memory", "backlog")
        memory_store.log_tool_invocation("query_memory", "OKR")
        memory_store.log_tool_invocation("search_mail", "budget")

        patterns = memory_store.get_top_patterns_by_tool(limit_per_tool=5)
        assert "query_memory" in patterns
        assert "search_mail" in patterns
        assert patterns["query_memory"][0]["pattern"] == "backlog"
        assert patterns["query_memory"][0]["count"] == 2


class TestGetToolStatistics:
    """Tests for the get_tool_statistics MCP tool."""

    @pytest.fixture
    def setup_state(self, memory_store):
        import mcp_server
        mcp_server._state.memory_store = memory_store
        yield mcp_server._state
        mcp_server._state.clear()

    @pytest.mark.asyncio
    async def test_returns_summary_stats(self, setup_state, memory_store):
        from mcp_tools.skill_tools import get_tool_statistics

        # Seed some log data
        memory_store.log_tool_invocation("query_memory", "backlog", True, 10)
        memory_store.log_tool_invocation("query_memory", "OKR", True, 20)
        memory_store.log_tool_invocation("search_mail", "budget", True, 50)

        result = json.loads(await get_tool_statistics())
        assert result["total_unique_tools"] == 2
        assert result["total_invocations"] == 3
        assert len(result["tools"]) == 2
        qm = next(t for t in result["tools"] if t["tool_name"] == "query_memory")
        assert qm["total_calls"] == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data(self, setup_state):
        from mcp_tools.skill_tools import get_tool_statistics

        result = json.loads(await get_tool_statistics())
        assert result["total_unique_tools"] == 0
        assert result["total_invocations"] == 0
        assert result["tools"] == []

    @pytest.mark.asyncio
    async def test_includes_top_patterns(self, setup_state, memory_store):
        from mcp_tools.skill_tools import get_tool_statistics

        memory_store.log_tool_invocation("query_memory", "backlog", True, 10)
        memory_store.log_tool_invocation("query_memory", "backlog", True, 15)
        memory_store.log_tool_invocation("query_memory", "OKR", True, 20)

        result = json.loads(await get_tool_statistics(tool_name="query_memory"))
        assert "top_patterns" in result
        patterns = result["top_patterns"]
        assert len(patterns) >= 1
        # "backlog" used twice should be first
        assert patterns[0]["query_pattern"] == "backlog"
        assert patterns[0]["count"] == 2


class TestPatternDetectorWithLog:
    """Tests for pattern detection using the invocation log."""

    def test_detect_patterns_from_log(self, memory_store):
        from skills.pattern_detector import PatternDetector

        # Create enough invocations to trigger pattern detection
        for _ in range(6):
            memory_store.log_tool_invocation("query_memory", "backlog")
        for _ in range(4):
            memory_store.log_tool_invocation("query_memory", "OKR")
        # Also seed the aggregated skill_usage table
        for _ in range(6):
            memory_store.record_skill_usage("query_memory", "backlog")
        for _ in range(4):
            memory_store.record_skill_usage("query_memory", "OKR")

        detector = PatternDetector(memory_store)
        patterns = detector.detect_patterns(min_occurrences=5, confidence_threshold=0.5)
        assert len(patterns) >= 1
        # Should find the query_memory pattern
        tool_names = [p["tool_name"] for p in patterns]
        assert "query_memory" in tool_names
