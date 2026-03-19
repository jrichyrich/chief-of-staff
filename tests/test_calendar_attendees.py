"""Tests for calendar attendee and recurrence support in MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

import mcp_server  # noqa: F401 — triggers register()


class TestParseAttendees:
    """Test attendee JSON parsing in create_calendar_event."""

    def test_valid_attendees(self):
        from mcp_tools.calendar_tools import _parse_attendees

        result = _parse_attendees('[{"email": "a@chg.com", "name": "A"}]')
        assert result == [{"email": "a@chg.com", "name": "A", "type": "required"}]

    def test_empty_string_returns_none(self):
        from mcp_tools.calendar_tools import _parse_attendees

        assert _parse_attendees("") is None

    def test_defaults_type_and_name(self):
        from mcp_tools.calendar_tools import _parse_attendees

        result = _parse_attendees('[{"email": "a@chg.com"}]')
        assert result[0]["type"] == "required"
        assert result[0]["name"] == "a"

    def test_invalid_json_returns_error(self):
        from mcp_tools.calendar_tools import _parse_attendees

        result = _parse_attendees("not json")
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_missing_email_returns_error(self):
        from mcp_tools.calendar_tools import _parse_attendees

        result = _parse_attendees('[{"name": "A"}]')
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_not_array_returns_error(self):
        from mcp_tools.calendar_tools import _parse_attendees

        result = _parse_attendees('{"email": "a@chg.com"}')
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_multiple_attendees(self):
        from mcp_tools.calendar_tools import _parse_attendees

        result = _parse_attendees(
            '[{"email": "a@chg.com", "type": "required"}, {"email": "b@chg.com", "type": "optional"}]'
        )
        assert len(result) == 2
        assert result[0]["type"] == "required"
        assert result[1]["type"] == "optional"


class TestParseRecurrence:
    """Test recurrence JSON parsing."""

    def test_valid_weekly(self):
        from mcp_tools.calendar_tools import _parse_recurrence

        result = _parse_recurrence('{"type": "weekly", "interval": 1, "days_of_week": ["tuesday"]}')
        assert result["type"] == "weekly"

    def test_empty_string_returns_none(self):
        from mcp_tools.calendar_tools import _parse_recurrence

        assert _parse_recurrence("") is None

    def test_missing_type_returns_error(self):
        from mcp_tools.calendar_tools import _parse_recurrence

        result = _parse_recurrence('{"interval": 1}')
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_invalid_type_returns_error(self):
        from mcp_tools.calendar_tools import _parse_recurrence

        result = _parse_recurrence('{"type": "biweekly"}')
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_both_end_date_and_occurrences_returns_error(self):
        from mcp_tools.calendar_tools import _parse_recurrence

        result = _parse_recurrence('{"type": "daily", "end_date": "2026-12-31", "occurrences": 10}')
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_valid_daily(self):
        from mcp_tools.calendar_tools import _parse_recurrence

        result = _parse_recurrence('{"type": "daily", "interval": 2}')
        assert result["type"] == "daily"
        assert result["interval"] == 2

    def test_invalid_json_returns_error(self):
        from mcp_tools.calendar_tools import _parse_recurrence

        result = _parse_recurrence("not json")
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_not_object_returns_error(self):
        from mcp_tools.calendar_tools import _parse_recurrence

        result = _parse_recurrence('["daily"]')
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "error" in parsed


@pytest.mark.asyncio
class TestMCPCalendarIntegration:
    """Integration tests for calendar attendee dual-path routing.

    Tool functions capture `state` via closure from register(mcp, state),
    so we must mutate `mcp_server._state` directly.
    """

    async def test_create_with_attendees_uses_graph(self):
        """When attendees provided + graph_client available, uses Graph path."""
        from mcp_tools.calendar_tools import create_calendar_event

        mock_graph = AsyncMock()
        mock_graph.resolve_calendar_id = AsyncMock(return_value="cal123")
        mock_graph.create_calendar_event = AsyncMock(return_value={
            "uid": "AAMkNew",
            "title": "COE Heads-Up",
            "start": "2026-04-01T09:00:00",
            "end": "2026-04-01T09:30:00",
            "attendees": ["shawn@chg.com"],
        })

        orig_graph = mcp_server._state.graph_client
        orig_cal = mcp_server._state.calendar_store
        try:
            mcp_server._state.graph_client = mock_graph
            mock_cal_store = MagicMock()
            mock_cal_store._upsert_ownership = MagicMock()
            mcp_server._state.calendar_store = mock_cal_store

            result = await create_calendar_event(
                title="COE Heads-Up",
                start_date="2026-04-01T09:00:00",
                end_date="2026-04-01T09:30:00",
                calendar_name="CHG",
                attendees='[{"email": "shawn@chg.com", "name": "Shawn"}]',
            )
        finally:
            mcp_server._state.graph_client = orig_graph
            mcp_server._state.calendar_store = orig_cal

        result_data = json.loads(result)
        assert result_data["status"] == "created"
        assert result_data["event"]["uid"] == "AAMkNew"
        mock_graph.create_calendar_event.assert_called_once()

    async def test_no_attendees_no_graph_uses_sync_path(self):
        """Without attendees and no graph_client, uses sync provider chain."""
        from mcp_tools.calendar_tools import create_calendar_event

        orig_graph = mcp_server._state.graph_client
        orig_cal = mcp_server._state.calendar_store
        try:
            mcp_server._state.graph_client = None
            mock_cal_store = MagicMock()
            mock_cal_store.create_event = MagicMock(return_value={
                "uid": "apple123",
                "title": "Lunch",
            })
            mcp_server._state.calendar_store = mock_cal_store

            result = await create_calendar_event(
                title="Lunch",
                start_date="2026-04-01T12:00:00",
                end_date="2026-04-01T13:00:00",
            )
        finally:
            mcp_server._state.graph_client = orig_graph
            mcp_server._state.calendar_store = orig_cal

        result_data = json.loads(result)
        assert result_data["status"] == "created"
        mock_cal_store.create_event.assert_called_once()

    async def test_work_calendar_routes_to_graph(self):
        """Work calendar name routes to Graph even without attendees."""
        from mcp_tools.calendar_tools import create_calendar_event

        mock_graph = AsyncMock()
        mock_graph.resolve_calendar_id = AsyncMock(return_value="cal-work")
        mock_graph.create_calendar_event = AsyncMock(return_value={
            "uid": "AAMkWork",
            "title": "Sprint Planning",
            "start": "2026-04-01T10:00:00",
            "end": "2026-04-01T11:00:00",
            "attendees": [],
        })

        orig_graph = mcp_server._state.graph_client
        orig_cal = mcp_server._state.calendar_store
        try:
            mcp_server._state.graph_client = mock_graph
            mock_cal_store = MagicMock()
            mock_cal_store._upsert_ownership = MagicMock()
            mcp_server._state.calendar_store = mock_cal_store

            result = await create_calendar_event(
                title="Sprint Planning",
                start_date="2026-04-01T10:00:00",
                end_date="2026-04-01T11:00:00",
                calendar_name="CHG",
            )
        finally:
            mcp_server._state.graph_client = orig_graph
            mcp_server._state.calendar_store = orig_cal

        result_data = json.loads(result)
        assert result_data["status"] == "created"
        mock_graph.create_calendar_event.assert_called_once()

    async def test_invalid_attendees_returns_error(self):
        """Invalid attendees JSON returns error without calling any backend."""
        from mcp_tools.calendar_tools import create_calendar_event

        orig_graph = mcp_server._state.graph_client
        orig_cal = mcp_server._state.calendar_store
        try:
            mcp_server._state.graph_client = AsyncMock()
            mcp_server._state.calendar_store = MagicMock()

            result = await create_calendar_event(
                title="Test",
                start_date="2026-04-01T09:00:00",
                end_date="2026-04-01T10:00:00",
                attendees="not valid json",
            )
        finally:
            mcp_server._state.graph_client = orig_graph
            mcp_server._state.calendar_store = orig_cal

        parsed = json.loads(result)
        assert "error" in parsed

    async def test_update_with_attendees_uses_graph(self):
        """Update with attendees routes to Graph path."""
        from mcp_tools.calendar_tools import update_calendar_event

        mock_graph = AsyncMock()
        mock_graph.update_calendar_event = AsyncMock(return_value={
            "uid": "AAMkExist",
            "title": "Updated Meeting",
            "start": "2026-04-01T09:00:00",
            "end": "2026-04-01T10:00:00",
            "attendees": ["new@chg.com"],
        })

        orig_graph = mcp_server._state.graph_client
        orig_cal = mcp_server._state.calendar_store
        try:
            mcp_server._state.graph_client = mock_graph
            mcp_server._state.calendar_store = MagicMock()

            result = await update_calendar_event(
                event_uid="microsoft_365:AAMkExist",
                attendees='[{"email": "new@chg.com", "name": "New"}]',
            )
        finally:
            mcp_server._state.graph_client = orig_graph
            mcp_server._state.calendar_store = orig_cal

        result_data = json.loads(result)
        assert result_data["status"] == "updated"
        mock_graph.update_calendar_event.assert_called_once()
        # Verify native ID was extracted from unified UID
        call_args = mock_graph.update_calendar_event.call_args
        assert call_args[0][0] == "AAMkExist"
