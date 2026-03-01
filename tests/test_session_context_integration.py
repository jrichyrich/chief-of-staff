"""Integration tests for session context in session_tools.py."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import mcp_server
from mcp_tools.session_tools import get_session_status, refresh_session_context
from mcp_tools.state import SessionHealth
from session.context_loader import SessionContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_manager():
    """Create a mock SessionManager with sensible defaults."""
    mgr = MagicMock()
    mgr.session_id = "test-session-123"
    mgr.estimate_tokens.return_value = 5000
    mgr.interaction_count = 10
    mgr.extract_structured_data.return_value = {
        "decisions": [],
        "action_items": [],
        "key_facts": [],
        "general": [],
    }
    return mgr


def _make_session_context(**overrides) -> SessionContext:
    """Create a SessionContext with defaults."""
    return SessionContext(
        loaded_at=overrides.get("loaded_at", datetime.now().isoformat()),
        calendar_events=overrides.get("calendar_events", [{"title": "Standup"}]),
        unread_mail_count=overrides.get("unread_mail_count", 3),
        overdue_delegations=overrides.get("overdue_delegations", []),
        pending_decisions=overrides.get("pending_decisions", []),
        due_reminders=overrides.get("due_reminders", []),
        session_brain_summary=overrides.get("session_brain_summary", {}),
        errors=overrides.get("errors", {}),
    )


@pytest.fixture(autouse=True)
def wire_state():
    """Inject mock state into MCP server state for each test."""
    old_sm = mcp_server._state.session_manager
    old_sh = mcp_server._state.session_health
    old_sc = mcp_server._state.session_context

    mcp_server._state.session_manager = _make_session_manager()
    mcp_server._state.session_health = SessionHealth()
    mcp_server._state.session_context = None

    yield

    mcp_server._state.session_manager = old_sm
    mcp_server._state.session_health = old_sh
    mcp_server._state.session_context = old_sc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetSessionStatusContextBundle:
    @pytest.mark.asyncio
    async def test_includes_context_bundle(self):
        """get_session_status includes context_bundle when session_context is set."""
        mcp_server._state.session_context = _make_session_context()

        result_json = await get_session_status()
        result = json.loads(result_json)

        assert "context_bundle" in result
        bundle = result["context_bundle"]
        assert bundle is not None
        assert bundle["calendar_event_count"] == 1
        assert bundle["unread_mail_count"] == 3
        assert bundle["loaded_at"] is not None
        assert "is_stale" in bundle
        assert "errors" in bundle

    @pytest.mark.asyncio
    async def test_no_context_returns_null(self):
        """get_session_status returns context_bundle=null when no context loaded."""
        mcp_server._state.session_context = None

        result_json = await get_session_status()
        result = json.loads(result_json)

        assert "context_bundle" in result
        assert result["context_bundle"] is None

    @pytest.mark.asyncio
    async def test_context_bundle_caps_events_at_10(self):
        """context_bundle only includes first 10 calendar events."""
        mcp_server._state.session_context = _make_session_context(
            calendar_events=[{"title": f"Event {i}"} for i in range(20)],
        )

        result_json = await get_session_status()
        result = json.loads(result_json)
        bundle = result["context_bundle"]
        assert bundle["calendar_event_count"] == 20
        assert len(bundle["calendar_events"]) == 10

    @pytest.mark.asyncio
    async def test_context_bundle_includes_all_fields(self):
        """context_bundle includes all expected fields."""
        mcp_server._state.session_context = _make_session_context(
            overdue_delegations=[{"id": 1, "task": "Review"}],
            pending_decisions=[{"id": 2, "title": "Pick DB"}],
            due_reminders=[{"name": "Submit report"}],
            session_brain_summary={"active_workstreams": ["Security"]},
            errors={"mail": "Timeout"},
        )

        result_json = await get_session_status()
        result = json.loads(result_json)
        bundle = result["context_bundle"]

        assert bundle["overdue_delegation_count"] == 1
        assert bundle["overdue_delegations"] == [{"id": 1, "task": "Review"}]
        assert bundle["pending_decision_count"] == 1
        assert bundle["pending_decisions"] == [{"id": 2, "title": "Pick DB"}]
        assert bundle["due_reminder_count"] == 1
        assert bundle["due_reminders"] == [{"name": "Submit report"}]
        assert bundle["brain_summary"] == {"active_workstreams": ["Security"]}
        assert bundle["errors"] == {"mail": "Timeout"}


class TestRefreshSessionContext:
    @pytest.mark.asyncio
    async def test_replaces_cache(self):
        """refresh_session_context replaces state.session_context."""
        assert mcp_server._state.session_context is None

        new_ctx = _make_session_context(unread_mail_count=7)

        with patch("session.context_loader.load_session_context", return_value=new_ctx):
            result_json = await refresh_session_context()

        result = json.loads(result_json)

        assert result["status"] == "refreshed"
        assert result["unread_mail_count"] == 7
        assert mcp_server._state.session_context is new_ctx

    @pytest.mark.asyncio
    async def test_handles_failure(self):
        """refresh_session_context returns error JSON on failure."""
        with patch("session.context_loader.load_session_context", side_effect=RuntimeError("DB locked")):
            result_json = await refresh_session_context()

        result = json.loads(result_json)

        assert "error" in result
        assert "DB locked" in result["error"]

    @pytest.mark.asyncio
    async def test_refresh_returns_counts(self):
        """refresh_session_context returns counts for all source types."""
        ctx = _make_session_context(
            calendar_events=[{"title": "A"}, {"title": "B"}],
            unread_mail_count=5,
            overdue_delegations=[{"id": 1}],
            pending_decisions=[{"id": 2}, {"id": 3}],
            due_reminders=[{"name": "R1"}],
        )

        with patch("session.context_loader.load_session_context", return_value=ctx):
            result_json = await refresh_session_context()

        result = json.loads(result_json)

        assert result["calendar_event_count"] == 2
        assert result["unread_mail_count"] == 5
        assert result["overdue_delegation_count"] == 1
        assert result["pending_decision_count"] == 2
        assert result["due_reminder_count"] == 1
