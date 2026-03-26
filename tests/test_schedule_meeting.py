"""Tests for schedule_meeting and related MCP tools.

Tests the end-to-end scheduling flow: name resolution → parallel fetch →
mutual availability → ranking → JSON response.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import mcp_server  # noqa: F401 — triggers register() calls

from mcp_tools.calendar_tools import (
    find_group_availability,
    get_people_availability,
    schedule_meeting,
    _resolve_participant_emails,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_graph_client():
    """Mock GraphClient with getSchedule, resolve_user_email."""
    graph = AsyncMock()
    graph.get_schedule = AsyncMock(return_value=[
        {
            "email": "jonas@chg.com",
            "availability_view": "0000220000",
            "schedule_items": [
                {
                    "status": "busy",
                    "start": "2026-03-23T10:00:00",
                    "end": "2026-03-23T11:00:00",
                },
            ],
        },
    ])
    graph.resolve_user_email = AsyncMock(return_value="jonas@chg.com")
    return graph


@pytest.fixture()
def mock_calendar_store():
    """Mock CalendarStore with get_events_with_routing."""
    cal_store = MagicMock()
    cal_store.get_events_with_routing = MagicMock(return_value=(
        [
            {
                "title": "Standup",
                "start": "2026-03-23T09:00:00",
                "end": "2026-03-23T09:30:00",
                "is_all_day": False,
            },
        ],
        {"is_fallback": False, "providers_requested": ["both"]},
    ))
    return cal_store


@pytest.fixture()
def mock_memory_store():
    """Mock MemoryStore with search_identity."""
    mem = MagicMock()
    mem.search_identity = MagicMock(return_value=[
        {"email": "jonas@chg.com", "display_name": "Jonas Test", "canonical_name": "Jonas Test"},
    ])
    return mem


@pytest.fixture()
def scheduling_state(mock_graph_client, mock_calendar_store, mock_memory_store):
    """Inject all mocks into mcp_server._state and clean up after."""
    mcp_server._state["graph_client"] = mock_graph_client
    mcp_server._state["calendar_store"] = mock_calendar_store
    mcp_server._state["memory_store"] = mock_memory_store
    yield {
        "graph_client": mock_graph_client,
        "calendar_store": mock_calendar_store,
        "memory_store": mock_memory_store,
    }
    mcp_server._state.pop("graph_client", None)
    mcp_server._state.pop("calendar_store", None)
    mcp_server._state.pop("memory_store", None)


# ---------------------------------------------------------------------------
# get_people_availability tests
# ---------------------------------------------------------------------------


class TestGetPeopleAvailability:
    @pytest.mark.asyncio
    async def test_basic_call(self, scheduling_state):
        result = json.loads(await get_people_availability(
            emails="jonas@chg.com",
            start_date="2026-03-23",
            end_date="2026-03-27",
        ))
        assert result["count"] == 1
        assert result["results"][0]["email"] == "jonas@chg.com"
        scheduling_state["graph_client"].get_schedule.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_graph_client(self, scheduling_state):
        mcp_server._state["graph_client"] = None
        result = json.loads(await get_people_availability(
            emails="jonas@chg.com",
            start_date="2026-03-23",
            end_date="2026-03-27",
        ))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_empty_emails(self, scheduling_state):
        result = json.loads(await get_people_availability(
            emails="",
            start_date="2026-03-23",
            end_date="2026-03-27",
        ))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_multiple_emails(self, scheduling_state):
        scheduling_state["graph_client"].get_schedule = AsyncMock(return_value=[
            {"email": "a@chg.com", "availability_view": "000", "schedule_items": []},
            {"email": "b@chg.com", "availability_view": "000", "schedule_items": []},
        ])
        result = json.loads(await get_people_availability(
            emails="a@chg.com, b@chg.com",
            start_date="2026-03-23",
            end_date="2026-03-27",
        ))
        assert result["count"] == 2


# ---------------------------------------------------------------------------
# _resolve_participant_emails tests
# ---------------------------------------------------------------------------


class TestResolveParticipants:
    @pytest.mark.asyncio
    async def test_email_passthrough(self, scheduling_state):
        resolved, errors = await _resolve_participant_emails("jonas@chg.com")
        assert len(resolved) == 1
        assert resolved[0]["email"] == "jonas@chg.com"
        assert not errors

    @pytest.mark.asyncio
    async def test_name_via_identity(self, scheduling_state):
        resolved, errors = await _resolve_participant_emails("Jonas Test")
        assert len(resolved) == 1
        assert resolved[0]["email"] == "jonas@chg.com"
        assert not errors

    @pytest.mark.asyncio
    async def test_name_via_graph_fallback(self, scheduling_state):
        scheduling_state["memory_store"].search_identity = MagicMock(return_value=[])
        resolved, errors = await _resolve_participant_emails("Jonas Test")
        assert len(resolved) == 1
        assert resolved[0]["email"] == "jonas@chg.com"

    @pytest.mark.asyncio
    async def test_unresolvable_name(self, scheduling_state):
        scheduling_state["memory_store"].search_identity = MagicMock(return_value=[])
        scheduling_state["graph_client"].resolve_user_email = AsyncMock(return_value=None)
        resolved, errors = await _resolve_participant_emails("Unknown Person")
        assert not resolved
        assert "Unknown Person" in errors

    @pytest.mark.asyncio
    async def test_mixed_resolved_and_unresolved(self, scheduling_state):
        scheduling_state["memory_store"].search_identity = MagicMock(side_effect=[
            [{"email": "jonas@chg.com", "display_name": "Jonas"}],
            [],
        ])
        scheduling_state["graph_client"].resolve_user_email = AsyncMock(return_value=None)
        resolved, errors = await _resolve_participant_emails("Jonas, Ghost Person")
        assert len(resolved) == 1
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# schedule_meeting tests
# ---------------------------------------------------------------------------


class TestScheduleMeeting:
    @pytest.mark.asyncio
    async def test_full_flow_with_suggestions(self, scheduling_state):
        with patch("mcp_tools.calendar_tools.config") as mock_config:
            mock_config.USER_EMAIL = "me@chg.com"
            mock_config.USER_TIMEZONE = "America/Denver"
            result = json.loads(await schedule_meeting(
                title="Sync with Jonas",
                participants="jonas@chg.com",
                duration_minutes=30,
                start_date="2026-03-23",
                end_date="2026-03-27",
            ))

        assert result["status"] == "suggestions"
        assert result["confirmation_required"] is True
        assert len(result["suggestions"]) > 0
        assert result["meeting_details"]["title"] == "Sync with Jonas"
        assert result["participants"][0]["email"] == "jonas@chg.com"
        for s in result["suggestions"]:
            assert "score" in s

    @pytest.mark.asyncio
    async def test_no_graph_client_error(self, scheduling_state):
        mcp_server._state["graph_client"] = None
        result = json.loads(await schedule_meeting(
            title="Meeting",
            participants="jonas@chg.com",
        ))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unresolvable_participants_error(self, scheduling_state):
        scheduling_state["memory_store"].search_identity = MagicMock(return_value=[])
        scheduling_state["graph_client"].resolve_user_email = AsyncMock(return_value=None)
        with patch("mcp_tools.calendar_tools.config") as mock_config:
            mock_config.USER_EMAIL = "me@chg.com"
            mock_config.USER_TIMEZONE = "America/Denver"
            result = json.loads(await schedule_meeting(
                title="Meeting",
                participants="Unknown Person",
            ))
        assert result["status"] == "error"
        assert "Unknown Person" in result["unresolved"]

    @pytest.mark.asyncio
    async def test_default_date_range(self, scheduling_state):
        with patch("mcp_tools.calendar_tools.config") as mock_config:
            mock_config.USER_EMAIL = "me@chg.com"
            mock_config.USER_TIMEZONE = "America/Denver"
            result = json.loads(await schedule_meeting(
                title="Meeting",
                participants="jonas@chg.com",
            ))
        assert result["status"] in ("suggestions", "no_slots")
        assert "date_range" in result

    @pytest.mark.asyncio
    async def test_focus_time_treated_as_available(self, scheduling_state):
        """Focus Time on your calendar should NOT block suggestions."""
        # Your calendar has Focus Time 9-11 and a real meeting 11-12
        scheduling_state["calendar_store"].get_events_with_routing = MagicMock(return_value=(
            [
                {
                    "title": "Focus Time",
                    "start": "2026-03-23T09:00:00",
                    "end": "2026-03-23T11:00:00",
                    "is_all_day": False,
                },
                {
                    "title": "Team Standup",
                    "start": "2026-03-23T11:00:00",
                    "end": "2026-03-23T11:30:00",
                    "is_all_day": False,
                },
            ],
            {"is_fallback": False, "providers_requested": ["both"]},
        ))
        # Jonas is free all day
        scheduling_state["graph_client"].get_schedule = AsyncMock(return_value=[
            {"email": "jonas@chg.com", "availability_view": "0000000000", "schedule_items": []},
        ])
        with patch("mcp_tools.calendar_tools.config") as mock_config:
            mock_config.USER_EMAIL = "me@chg.com"
            mock_config.USER_TIMEZONE = "America/Denver"
            result = json.loads(await schedule_meeting(
                title="Sync",
                participants="jonas@chg.com",
                start_date="2026-03-23",
                end_date="2026-03-23",
            ))
        assert result["status"] == "suggestions"
        # The 9-11 Focus Time window should be INSIDE one of the suggested slots.
        # Since there are no hard blocks before 11:00 (Focus Time is soft), we expect
        # a morning slot starting at 8:00 that extends through the Focus Time window.
        morning_slot = next(
            (s for s in result["suggestions"] if "08:00:00" in s["start"]),
            None,
        )
        assert morning_slot is not None, (
            f"Expected a morning slot starting at 8:00 AM. Got: "
            f"{[s['start'] for s in result['suggestions']]}"
        )
        # Morning slot must cover through at least 10:30 (Focus Time 9-11 is available)
        assert morning_slot["duration_minutes"] >= 150, (
            f"Morning slot should span 8:00-11:00 (180 min) but was {morning_slot['duration_minutes']} min"
        )
        # The standup at 11:00-11:30 must create a gap — no slot should span 11:00-11:30
        for s in result["suggestions"]:
            s_start = s["start"]
            s_end = s["end"]
            if "10:" in s_start or "08:" in s_start:
                # Slot must end at or before 11:00 (standup start)
                assert "11:00:00" in s_end or "10:" in s_end or "09:" in s_end or "08:" in s_end

    @pytest.mark.asyncio
    async def test_zero_mutual_slots(self, scheduling_state):
        # Other person is busy all day every day
        scheduling_state["graph_client"].get_schedule = AsyncMock(return_value=[
            {
                "email": "jonas@chg.com",
                "availability_view": "2222222222",
                "schedule_items": [
                    {"status": "busy", "start": "2026-03-23T08:00:00", "end": "2026-03-23T18:00:00"},
                    {"status": "busy", "start": "2026-03-24T08:00:00", "end": "2026-03-24T18:00:00"},
                    {"status": "busy", "start": "2026-03-25T08:00:00", "end": "2026-03-25T18:00:00"},
                    {"status": "busy", "start": "2026-03-26T08:00:00", "end": "2026-03-26T18:00:00"},
                    {"status": "busy", "start": "2026-03-27T08:00:00", "end": "2026-03-27T18:00:00"},
                ],
            },
        ])
        with patch("mcp_tools.calendar_tools.config") as mock_config:
            mock_config.USER_EMAIL = "me@chg.com"
            mock_config.USER_TIMEZONE = "America/Denver"
            result = json.loads(await schedule_meeting(
                title="Meeting",
                participants="jonas@chg.com",
                start_date="2026-03-23",
                end_date="2026-03-27",
            ))
        assert result["status"] == "no_slots"
        assert "meeting_details" in result

    @pytest.mark.asyncio
    async def test_preferred_times_passed_through(self, scheduling_state):
        with patch("mcp_tools.calendar_tools.config") as mock_config:
            mock_config.USER_EMAIL = "me@chg.com"
            mock_config.USER_TIMEZONE = "America/Denver"
            result = json.loads(await schedule_meeting(
                title="Morning Sync",
                participants="jonas@chg.com",
                preferred_times="morning",
                start_date="2026-03-23",
                end_date="2026-03-27",
            ))
        if result["status"] == "suggestions":
            assert all("score" in s for s in result["suggestions"])

    @pytest.mark.asyncio
    async def test_partial_name_resolution(self, scheduling_state):
        """Some names resolve, some don't — still returns suggestions with warning."""
        scheduling_state["memory_store"].search_identity = MagicMock(side_effect=[
            [{"email": "jonas@chg.com", "display_name": "Jonas"}],
            [],
        ])
        scheduling_state["graph_client"].resolve_user_email = AsyncMock(return_value=None)
        with patch("mcp_tools.calendar_tools.config") as mock_config:
            mock_config.USER_EMAIL = "me@chg.com"
            mock_config.USER_TIMEZONE = "America/Denver"
            result = json.loads(await schedule_meeting(
                title="Group Meeting",
                participants="Jonas, Ghost Person",
                start_date="2026-03-23",
                end_date="2026-03-27",
            ))
        assert result["status"] in ("suggestions", "no_slots")
        assert "unresolved_participants" in result
        assert "Ghost Person" in result["unresolved_participants"]


# ---------------------------------------------------------------------------
# find_group_availability tests
# ---------------------------------------------------------------------------


class TestFindGroupAvailability:
    @pytest.mark.asyncio
    async def test_returns_ranked_suggestions(self, scheduling_state):
        with patch("mcp_tools.calendar_tools.config") as mock_config:
            mock_config.USER_EMAIL = "me@chg.com"
            mock_config.USER_TIMEZONE = "America/Denver"
            result = json.loads(await find_group_availability(
                participants="jonas@chg.com",
                start_date="2026-03-23",
                end_date="2026-03-27",
                duration_minutes=30,
            ))
        assert result["status"] == "suggestions"
        assert result["count"] > 0

    @pytest.mark.asyncio
    async def test_no_graph_client(self, scheduling_state):
        mcp_server._state["graph_client"] = None
        result = json.loads(await find_group_availability(
            participants="jonas@chg.com",
            start_date="2026-03-23",
            end_date="2026-03-27",
        ))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_max_suggestions_limit(self, scheduling_state):
        with patch("mcp_tools.calendar_tools.config") as mock_config:
            mock_config.USER_EMAIL = "me@chg.com"
            mock_config.USER_TIMEZONE = "America/Denver"
            result = json.loads(await find_group_availability(
                participants="jonas@chg.com",
                start_date="2026-03-23",
                end_date="2026-03-27",
                max_suggestions=2,
            ))
        if result["status"] == "suggestions":
            assert result["count"] <= 2
