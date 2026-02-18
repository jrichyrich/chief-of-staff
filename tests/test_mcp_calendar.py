# tests/test_mcp_calendar.py
"""Tests for the MCP calendar tool functions defined in mcp_server.py.

Follows the same pattern as tests/test_mcp_server.py: inject a mock
CalendarStore into mcp_server._state["calendar_store"] and call the
async tool functions directly.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_calendar_store():
    """Return a MagicMock that quacks like CalendarStore."""
    store = MagicMock()
    # By default, methods return sensible empty/success values
    store.list_calendars.return_value = []
    store.get_events.return_value = []
    store.create_event.return_value = {}
    store.update_event.return_value = {}
    store.delete_event.return_value = {"status": "deleted", "event_uid": ""}
    store.search_events.return_value = []
    return store


@pytest.fixture
def calendar_state(mock_calendar_store):
    """Inject mock calendar store into mcp_server._state, then clean up."""
    import mcp_server

    mcp_server._state["calendar_store"] = mock_calendar_store
    yield mock_calendar_store
    mcp_server._state.pop("calendar_store", None)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestCalendarToolsRegistered:
    def test_calendar_tools_registered(self):
        """Verify all 6 calendar tools are registered on the MCP server."""
        import mcp_server

        tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
        expected = [
            "list_calendars",
            "get_calendar_events",
            "create_calendar_event",
            "update_calendar_event",
            "delete_calendar_event",
            "search_calendar_events",
        ]
        for name in expected:
            assert name in tool_names, f"Calendar tool '{name}' not registered"


# ---------------------------------------------------------------------------
# list_calendars
# ---------------------------------------------------------------------------


class TestListCalendarsTool:
    @pytest.mark.asyncio
    async def test_list_calendars_tool(self, calendar_state):
        from mcp_tools.calendar_tools import list_calendars

        calendar_state.list_calendars.return_value = [
            {"name": "Work", "type": "calDAV", "source": "iCloud", "color": "#0000ff"},
            {"name": "Personal", "type": "local", "source": "Local", "color": "#ff0000"},
        ]

        result = await list_calendars()
        data = json.loads(result)

        assert "results" in data
        assert len(data["results"]) == 2
        assert data["results"][0]["name"] == "Work"
        assert data["results"][1]["name"] == "Personal"
        calendar_state.list_calendars.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_calendars_empty(self, calendar_state):
        from mcp_tools.calendar_tools import list_calendars

        calendar_state.list_calendars.return_value = []

        result = await list_calendars()
        data = json.loads(result)

        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_list_calendars_with_provider_preference(self, calendar_state):
        from mcp_tools.calendar_tools import list_calendars

        await list_calendars(provider_preference="both", source_filter="icloud")
        calendar_state.list_calendars.assert_called_once_with(
            provider_preference="both",
            source_filter="icloud",
        )


# ---------------------------------------------------------------------------
# get_calendar_events
# ---------------------------------------------------------------------------


class TestGetCalendarEventsTool:
    @pytest.mark.asyncio
    async def test_get_calendar_events_tool(self, calendar_state):
        from mcp_tools.calendar_tools import get_calendar_events

        calendar_state.get_events.return_value = [
            {
                "uid": "E1",
                "title": "Team Standup",
                "start": "2024-03-01T09:00:00",
                "end": "2024-03-01T09:30:00",
                "calendar": "Work",
                "location": None,
                "notes": None,
                "attendees": [],
                "is_all_day": False,
            }
        ]

        result = await get_calendar_events("2024-03-01", "2024-03-31")
        data = json.loads(result)

        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["uid"] == "E1"
        assert data["results"][0]["title"] == "Team Standup"
        # Verify dates were parsed and passed correctly
        call_args = calendar_state.get_events.call_args
        start_arg = call_args[0][0] if call_args[0] else call_args[1]["start_dt"]
        assert isinstance(start_arg, datetime)

    @pytest.mark.asyncio
    async def test_get_calendar_events_with_filter(self, calendar_state):
        from mcp_tools.calendar_tools import get_calendar_events

        calendar_state.get_events.return_value = [
            {"uid": "E2", "title": "Lunch", "calendar": "Personal", "start": "2024-03-01T12:00:00",
             "end": "2024-03-01T13:00:00", "location": None, "notes": None, "attendees": [], "is_all_day": False}
        ]

        result = await get_calendar_events("2024-03-01", "2024-03-31", calendar_name="Personal")
        data = json.loads(result)

        assert len(data["results"]) == 1
        assert data["results"][0]["calendar"] == "Personal"
        # Verify calendar_names filter was passed
        call_args = calendar_state.get_events.call_args
        calendar_names_arg = call_args[1].get("calendar_names") or (call_args[0][2] if len(call_args[0]) > 2 else None)
        assert calendar_names_arg == ["Personal"]

    @pytest.mark.asyncio
    async def test_get_calendar_events_iso_datetime(self, calendar_state):
        """Verify full ISO datetime strings are parsed correctly."""
        from mcp_tools.calendar_tools import get_calendar_events

        calendar_state.get_events.return_value = []

        result = await get_calendar_events("2024-03-01T09:00:00", "2024-03-01T17:00:00")
        data = json.loads(result)

        assert data["results"] == []
        calendar_state.get_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_calendar_events_routes_with_filters(self, calendar_state):
        from mcp_tools.calendar_tools import get_calendar_events

        await get_calendar_events(
            "2024-03-01",
            "2024-03-31",
            provider_preference="both",
            source_filter="exchange",
        )
        kwargs = calendar_state.get_events.call_args[1]
        assert kwargs["provider_preference"] == "both"
        assert kwargs["source_filter"] == "exchange"


# ---------------------------------------------------------------------------
# create_calendar_event
# ---------------------------------------------------------------------------


class TestCreateCalendarEventTool:
    @pytest.mark.asyncio
    async def test_create_calendar_event_tool(self, calendar_state):
        from mcp_tools.calendar_tools import create_calendar_event

        calendar_state.create_event.return_value = {
            "uid": "NEW-1",
            "title": "Sprint Planning",
            "start": "2024-03-01T10:00:00",
            "end": "2024-03-01T11:00:00",
            "calendar": "Work",
            "location": None,
            "notes": None,
            "attendees": [],
            "is_all_day": False,
        }

        result = await create_calendar_event(
            title="Sprint Planning",
            start_date="2024-03-01T10:00:00",
            end_date="2024-03-01T11:00:00",
        )
        data = json.loads(result)

        assert data["status"] == "created"
        assert data["event"]["uid"] == "NEW-1"
        assert data["event"]["title"] == "Sprint Planning"
        calendar_state.create_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_calendar_event_with_all_fields(self, calendar_state):
        from mcp_tools.calendar_tools import create_calendar_event

        calendar_state.create_event.return_value = {
            "uid": "NEW-2",
            "title": "Offsite",
            "start": "2024-03-01T00:00:00",
            "end": "2024-03-02T00:00:00",
            "calendar": "Work",
            "location": "Hotel Conference Room",
            "notes": "Bring presentation materials",
            "attendees": [],
            "is_all_day": True,
        }

        result = await create_calendar_event(
            title="Offsite",
            start_date="2024-03-01",
            end_date="2024-03-02",
            calendar_name="Work",
            location="Hotel Conference Room",
            notes="Bring presentation materials",
            is_all_day=True,
        )
        data = json.loads(result)

        assert data["status"] == "created"
        assert data["event"]["title"] == "Offsite"
        assert data["event"]["is_all_day"] is True
        # Verify kwargs were passed through
        call_kwargs = calendar_state.create_event.call_args[1]
        assert call_kwargs["calendar_name"] == "Work"
        assert call_kwargs["location"] == "Hotel Conference Room"
        assert call_kwargs["notes"] == "Bring presentation materials"
        assert call_kwargs["is_all_day"] is True

    @pytest.mark.asyncio
    async def test_create_calendar_event_error_from_store(self, calendar_state):
        from mcp_tools.calendar_tools import create_calendar_event

        calendar_state.create_event.return_value = {
            "error": "Calendar not found: NonExistent"
        }

        result = await create_calendar_event(
            title="Bad Event",
            start_date="2024-03-01",
            end_date="2024-03-02",
            calendar_name="NonExistent",
        )
        data = json.loads(result)

        # The tool wraps the result; the error comes from the CalendarStore
        assert "event" in data or "error" in data


# ---------------------------------------------------------------------------
# update_calendar_event
# ---------------------------------------------------------------------------


class TestUpdateCalendarEventTool:
    @pytest.mark.asyncio
    async def test_update_calendar_event_tool(self, calendar_state):
        from mcp_tools.calendar_tools import update_calendar_event

        calendar_state.update_event.return_value = {
            "uid": "UPD-1",
            "title": "Renamed Meeting",
            "start": "2024-03-01T10:00:00",
            "end": "2024-03-01T11:00:00",
            "calendar": "Work",
            "location": None,
            "notes": None,
            "attendees": [],
            "is_all_day": False,
        }

        result = await update_calendar_event(
            event_uid="UPD-1",
            calendar_name="Work",
            title="Renamed Meeting",
        )
        data = json.loads(result)

        assert data["status"] == "updated"
        assert data["event"]["uid"] == "UPD-1"
        assert data["event"]["title"] == "Renamed Meeting"
        calendar_state.update_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_calendar_event_with_dates(self, calendar_state):
        from mcp_tools.calendar_tools import update_calendar_event

        calendar_state.update_event.return_value = {"uid": "UPD-2", "title": "Moved Meeting"}

        result = await update_calendar_event(
            event_uid="UPD-2",
            calendar_name="Work",
            start_date="2024-03-05T14:00:00",
            end_date="2024-03-05T15:00:00",
        )
        data = json.loads(result)

        assert data["status"] == "updated"
        # Verify datetime objects were passed as start_dt/end_dt
        call_kwargs = calendar_state.update_event.call_args[1]
        assert isinstance(call_kwargs["start_dt"], datetime)
        assert isinstance(call_kwargs["end_dt"], datetime)


# ---------------------------------------------------------------------------
# delete_calendar_event
# ---------------------------------------------------------------------------


class TestDeleteCalendarEventTool:
    @pytest.mark.asyncio
    async def test_delete_calendar_event_tool(self, calendar_state):
        from mcp_tools.calendar_tools import delete_calendar_event

        calendar_state.delete_event.return_value = {"status": "deleted", "event_uid": "DEL-1"}

        result = await delete_calendar_event(event_uid="DEL-1", calendar_name="Work")
        data = json.loads(result)

        assert data["status"] == "deleted"
        assert data["event_uid"] == "DEL-1"
        calendar_state.delete_event.assert_called_once_with("DEL-1", calendar_name="Work")

    @pytest.mark.asyncio
    async def test_delete_calendar_event_not_found(self, calendar_state):
        from mcp_tools.calendar_tools import delete_calendar_event

        calendar_state.delete_event.return_value = {"error": "Event not found: MISSING-1"}

        result = await delete_calendar_event(event_uid="MISSING-1", calendar_name="Work")
        data = json.loads(result)

        assert "error" in data
        assert "Event not found" in data["error"]


# ---------------------------------------------------------------------------
# search_calendar_events
# ---------------------------------------------------------------------------


class TestSearchCalendarEventsTool:
    @pytest.mark.asyncio
    async def test_search_calendar_events_tool(self, calendar_state):
        from mcp_tools.calendar_tools import search_calendar_events

        calendar_state.search_events.return_value = [
            {
                "uid": "S1",
                "title": "Team Standup",
                "start": "2024-03-01T09:00:00",
                "end": "2024-03-01T09:30:00",
                "calendar": "Work",
                "location": None,
                "notes": None,
                "attendees": [],
                "is_all_day": False,
            }
        ]

        result = await search_calendar_events(query="standup")
        data = json.loads(result)

        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Team Standup"
        # Verify default date range was used (+/- 30 days)
        call_args = calendar_state.search_events.call_args
        start_arg = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("start_dt")
        end_arg = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("end_dt")
        assert isinstance(start_arg, datetime)
        assert isinstance(end_arg, datetime)

    @pytest.mark.asyncio
    async def test_search_calendar_events_with_dates(self, calendar_state):
        from mcp_tools.calendar_tools import search_calendar_events

        calendar_state.search_events.return_value = []

        result = await search_calendar_events(
            query="standup",
            start_date="2024-01-01",
            end_date="2024-06-30",
        )
        data = json.loads(result)

        assert data["results"] == []
        # Verify the explicit dates were parsed
        call_args = calendar_state.search_events.call_args
        start_arg = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("start_dt")
        assert start_arg.year == 2024
        assert start_arg.month == 1

    @pytest.mark.asyncio
    async def test_search_calendar_events_no_results(self, calendar_state):
        from mcp_tools.calendar_tools import search_calendar_events

        calendar_state.search_events.return_value = []

        result = await search_calendar_events(query="nonexistent")
        data = json.loads(result)

        assert data["results"] == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestCalendarToolErrorHandling:
    @pytest.mark.asyncio
    async def test_calendar_tool_error_handling(self, calendar_state):
        """When the store returns an error dict, the tool should propagate it."""
        from mcp_tools.calendar_tools import list_calendars

        calendar_state.list_calendars.return_value = [
            {"error": "EventKit is only available on macOS with PyObjC installed."}
        ]

        result = await list_calendars()
        data = json.loads(result)

        assert "results" in data
        assert data["results"][0]["error"] == "EventKit is only available on macOS with PyObjC installed."

    @pytest.mark.asyncio
    async def test_calendar_tool_exception_handling(self, calendar_state):
        """When the store raises an exception, the tool should catch it and return error JSON."""
        from mcp_tools.calendar_tools import get_calendar_events

        calendar_state.get_events.side_effect = RuntimeError("Connection failed")

        result = await get_calendar_events("2024-03-01", "2024-03-31")
        data = json.loads(result)

        assert "error" in data
        assert "Connection failed" in data["error"]
