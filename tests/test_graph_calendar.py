"""Tests for GraphClient calendar methods."""

import pytest
from unittest.mock import AsyncMock


class TestFormatEventDatetime:
    """Test _format_event_datetime helper."""

    def test_timed_event(self):
        from connectors.graph_client import GraphClient

        result = GraphClient._format_event_datetime(
            "2026-04-15T09:00:00", "America/Denver", is_all_day=False
        )
        assert result == {
            "dateTime": "2026-04-15T09:00:00",
            "timeZone": "America/Denver",
        }

    def test_all_day_event(self):
        from connectors.graph_client import GraphClient

        result = GraphClient._format_event_datetime(
            "2026-04-15T09:00:00", "America/Denver", is_all_day=True
        )
        assert result == {"dateTime": "2026-04-15", "timeZone": "UTC"}

    def test_date_only_input(self):
        from connectors.graph_client import GraphClient

        result = GraphClient._format_event_datetime(
            "2026-04-15", "America/Denver", is_all_day=True
        )
        assert result == {"dateTime": "2026-04-15", "timeZone": "UTC"}


class TestBuildAttendeesPayload:
    """Test _build_attendees_payload helper."""

    def test_basic_attendees(self):
        from connectors.graph_client import GraphClient

        result = GraphClient._build_attendees_payload([
            {"email": "shawn@chg.com", "name": "Shawn", "type": "required"},
        ])
        assert result == [
            {
                "emailAddress": {"address": "shawn@chg.com", "name": "Shawn"},
                "type": "required",
            }
        ]

    def test_defaults_type_to_required(self):
        from connectors.graph_client import GraphClient

        result = GraphClient._build_attendees_payload([
            {"email": "shawn@chg.com", "name": "Shawn"},
        ])
        assert result[0]["type"] == "required"

    def test_defaults_name_to_email_prefix(self):
        from connectors.graph_client import GraphClient

        result = GraphClient._build_attendees_payload([
            {"email": "shawn.farnworth@chg.com"},
        ])
        assert result[0]["emailAddress"]["name"] == "shawn.farnworth"

    def test_empty_list(self):
        from connectors.graph_client import GraphClient

        assert GraphClient._build_attendees_payload([]) == []

    def test_none_returns_none(self):
        from connectors.graph_client import GraphClient

        assert GraphClient._build_attendees_payload(None) is None


class TestBuildRecurrencePayload:
    """Test _build_recurrence_payload helper."""

    def test_weekly_with_end_date(self):
        from connectors.graph_client import GraphClient

        result = GraphClient._build_recurrence_payload({
            "type": "weekly",
            "interval": 1,
            "days_of_week": ["tuesday"],
            "end_date": "2026-12-31",
        })
        assert result["pattern"]["type"] == "weekly"
        assert result["pattern"]["interval"] == 1
        assert result["pattern"]["daysOfWeek"] == ["tuesday"]
        assert result["range"]["type"] == "endDate"
        assert result["range"]["startDate"] == ""
        assert result["range"]["endDate"] == "2026-12-31"

    def test_daily_with_occurrences(self):
        from connectors.graph_client import GraphClient

        result = GraphClient._build_recurrence_payload({
            "type": "daily",
            "interval": 2,
            "occurrences": 10,
        })
        assert result["pattern"]["type"] == "daily"
        assert result["pattern"]["interval"] == 2
        assert result["range"]["type"] == "numbered"
        assert result["range"]["numberOfOccurrences"] == 10

    def test_monthly_absolute(self):
        from connectors.graph_client import GraphClient

        result = GraphClient._build_recurrence_payload({
            "type": "absoluteMonthly",
            "interval": 3,
            "day_of_month": 15,
        })
        assert result["pattern"]["type"] == "absoluteMonthly"
        assert result["pattern"]["dayOfMonth"] == 15

    def test_no_end_defaults_to_no_end(self):
        from connectors.graph_client import GraphClient

        result = GraphClient._build_recurrence_payload({
            "type": "daily",
            "interval": 1,
        })
        assert result["range"]["type"] == "noEnd"

    def test_none_returns_none(self):
        from connectors.graph_client import GraphClient

        assert GraphClient._build_recurrence_payload(None) is None


class TestNormalizeEvent:
    """Test _normalize_event helper."""

    def test_basic_normalization(self):
        from connectors.graph_client import GraphClient

        graph_event = {
            "id": "AAMkAGE1",
            "subject": "Team Standup",
            "start": {"dateTime": "2026-04-15T09:00:00.0000000", "timeZone": "America/Denver"},
            "end": {"dateTime": "2026-04-15T09:30:00.0000000", "timeZone": "America/Denver"},
            "location": {"displayName": "Room A"},
            "body": {"content": "Weekly sync", "contentType": "text"},
            "isAllDay": False,
            "showAs": "busy",
            "isCancelled": False,
            "responseStatus": {"response": "accepted", "time": "2026-04-10T00:00:00Z"},
            "attendees": [
                {
                    "emailAddress": {"address": "shawn@chg.com", "name": "Shawn"},
                    "type": "required",
                    "status": {"response": "accepted"},
                }
            ],
        }

        result = GraphClient._normalize_event(graph_event)
        assert result["uid"] == "AAMkAGE1"
        assert result["title"] == "Team Standup"
        assert result["start"] == "2026-04-15T09:00:00.0000000"
        assert result["end"] == "2026-04-15T09:30:00.0000000"
        assert result["location"] == "Room A"
        assert result["notes"] == "Weekly sync"
        assert result["is_all_day"] is False
        assert result["attendees"] == ["shawn@chg.com"]
        assert result["showAs"] == "busy"

    def test_missing_optional_fields(self):
        from connectors.graph_client import GraphClient

        graph_event = {
            "id": "AAMkAGE1",
            "subject": "Quick Chat",
            "start": {"dateTime": "2026-04-15T09:00:00"},
            "end": {"dateTime": "2026-04-15T09:30:00"},
        }
        result = GraphClient._normalize_event(graph_event)
        assert result["uid"] == "AAMkAGE1"
        assert result["location"] is None
        assert result["notes"] is None
        assert result["attendees"] == []


@pytest.mark.asyncio
class TestGraphCalendarCreate:
    """Test GraphClient.create_calendar_event."""

    async def test_create_basic_event(self):
        from connectors.graph_client import GraphClient

        mock_response = {
            "id": "AAMkNew123",
            "subject": "COE Review",
            "start": {"dateTime": "2026-04-15T09:00:00", "timeZone": "America/Denver"},
            "end": {"dateTime": "2026-04-15T10:00:00", "timeZone": "America/Denver"},
            "isAllDay": False,
            "location": {"displayName": ""},
            "body": {"content": "", "contentType": "text"},
            "attendees": [],
        }

        client = GraphClient.__new__(GraphClient)
        client._calendar_name_cache = {}
        client._request = AsyncMock(return_value=mock_response)

        result = await client.create_calendar_event(
            subject="COE Review",
            start="2026-04-15T09:00:00",
            end="2026-04-15T10:00:00",
        )

        assert result["uid"] == "AAMkNew123"
        assert result["title"] == "COE Review"

        call_kwargs = client._request.call_args
        assert call_kwargs[0] == ("POST", "/me/events")
        payload = call_kwargs[1]["json"]
        assert payload["subject"] == "COE Review"
        assert "attendees" not in payload

    async def test_create_event_with_attendees(self):
        from connectors.graph_client import GraphClient

        mock_response = {
            "id": "AAMkNew456",
            "subject": "COE Deadline",
            "start": {"dateTime": "2026-04-11T09:00:00", "timeZone": "America/Denver"},
            "end": {"dateTime": "2026-04-11T09:30:00", "timeZone": "America/Denver"},
            "isAllDay": False,
            "location": {"displayName": ""},
            "body": {"content": "", "contentType": "text"},
            "attendees": [
                {"emailAddress": {"address": "shawn@chg.com", "name": "Shawn"}, "type": "required"},
            ],
        }

        client = GraphClient.__new__(GraphClient)
        client._calendar_name_cache = {}
        client._request = AsyncMock(return_value=mock_response)

        result = await client.create_calendar_event(
            subject="COE Deadline",
            start="2026-04-11T09:00:00",
            end="2026-04-11T09:30:00",
            attendees=[{"email": "shawn@chg.com", "name": "Shawn"}],
        )

        payload = client._request.call_args[1]["json"]
        assert len(payload["attendees"]) == 1
        assert payload["attendees"][0]["emailAddress"]["address"] == "shawn@chg.com"
        assert payload["attendees"][0]["type"] == "required"

    async def test_create_event_with_recurrence(self):
        from connectors.graph_client import GraphClient

        mock_response = {
            "id": "AAMkRec789",
            "subject": "Weekly COE",
            "start": {"dateTime": "2026-04-15T09:00:00", "timeZone": "America/Denver"},
            "end": {"dateTime": "2026-04-15T10:00:00", "timeZone": "America/Denver"},
            "isAllDay": False,
            "location": {"displayName": ""},
            "body": {"content": "", "contentType": "text"},
            "attendees": [],
            "recurrence": {
                "pattern": {"type": "weekly", "interval": 1, "daysOfWeek": ["tuesday"]},
                "range": {"type": "endDate", "endDate": "2026-12-31"},
            },
        }

        client = GraphClient.__new__(GraphClient)
        client._calendar_name_cache = {}
        client._request = AsyncMock(return_value=mock_response)

        result = await client.create_calendar_event(
            subject="Weekly COE",
            start="2026-04-15T09:00:00",
            end="2026-04-15T10:00:00",
            recurrence={"type": "weekly", "interval": 1, "days_of_week": ["tuesday"], "end_date": "2026-12-31"},
        )

        payload = client._request.call_args[1]["json"]
        assert payload["recurrence"]["pattern"]["type"] == "weekly"
        assert payload["recurrence"]["range"]["startDate"] == "2026-04-15"

    async def test_create_event_with_calendar_id(self):
        from connectors.graph_client import GraphClient

        mock_response = {
            "id": "AAMkCal",
            "subject": "Test",
            "start": {"dateTime": "2026-04-15T09:00:00"},
            "end": {"dateTime": "2026-04-15T10:00:00"},
        }

        client = GraphClient.__new__(GraphClient)
        client._calendar_name_cache = {}
        client._request = AsyncMock(return_value=mock_response)

        await client.create_calendar_event(
            subject="Test",
            start="2026-04-15T09:00:00",
            end="2026-04-15T10:00:00",
            calendar_id="cal123",
        )

        call_args = client._request.call_args[0]
        assert call_args == ("POST", "/me/calendars/cal123/events")


@pytest.mark.asyncio
class TestGraphCalendarUpdate:

    async def test_update_event_title(self):
        from connectors.graph_client import GraphClient

        mock_response = {
            "id": "AAMkExist",
            "subject": "Updated Title",
            "start": {"dateTime": "2026-04-15T09:00:00"},
            "end": {"dateTime": "2026-04-15T10:00:00"},
        }

        client = GraphClient.__new__(GraphClient)
        client._request = AsyncMock(return_value=mock_response)

        result = await client.update_calendar_event("AAMkExist", subject="Updated Title")

        call_args = client._request.call_args
        assert call_args[0] == ("PATCH", "/me/events/AAMkExist")
        assert call_args[1]["json"]["subject"] == "Updated Title"

    async def test_update_event_attendees_replaces(self):
        from connectors.graph_client import GraphClient

        mock_response = {
            "id": "AAMkExist",
            "subject": "Meeting",
            "start": {"dateTime": "2026-04-15T09:00:00"},
            "end": {"dateTime": "2026-04-15T10:00:00"},
            "attendees": [
                {"emailAddress": {"address": "new@chg.com", "name": "New"}, "type": "required"},
            ],
        }

        client = GraphClient.__new__(GraphClient)
        client._request = AsyncMock(return_value=mock_response)

        await client.update_calendar_event(
            "AAMkExist",
            attendees=[{"email": "new@chg.com", "name": "New"}],
        )

        payload = client._request.call_args[1]["json"]
        assert len(payload["attendees"]) == 1


@pytest.mark.asyncio
class TestGraphCalendarDelete:

    async def test_delete_event(self):
        from connectors.graph_client import GraphClient

        client = GraphClient.__new__(GraphClient)
        client._request = AsyncMock(return_value={"status": "success"})

        result = await client.delete_calendar_event("AAMkDel")

        call_args = client._request.call_args[0]
        assert call_args == ("DELETE", "/me/events/AAMkDel")
        assert result["status"] == "success"


@pytest.mark.asyncio
class TestResolveCalendarId:

    async def test_resolves_name_case_insensitive(self):
        from connectors.graph_client import GraphClient

        client = GraphClient.__new__(GraphClient)
        client._calendar_name_cache = {}
        client._request = AsyncMock(return_value={
            "value": [
                {"id": "cal-abc", "name": "CHG"},
                {"id": "cal-def", "name": "Personal"},
            ]
        })

        result = await client.resolve_calendar_id("chg")
        assert result == "cal-abc"

    async def test_returns_none_for_unknown(self):
        from connectors.graph_client import GraphClient

        client = GraphClient.__new__(GraphClient)
        client._calendar_name_cache = {}
        client._request = AsyncMock(return_value={"value": []})

        result = await client.resolve_calendar_id("nonexistent")
        assert result is None

    async def test_caches_after_first_call(self):
        from connectors.graph_client import GraphClient

        client = GraphClient.__new__(GraphClient)
        client._calendar_name_cache = {}
        client._request = AsyncMock(return_value={
            "value": [{"id": "cal-abc", "name": "CHG"}]
        })

        await client.resolve_calendar_id("chg")
        await client.resolve_calendar_id("chg")

        # Only one API call despite two lookups
        assert client._request.call_count == 1
