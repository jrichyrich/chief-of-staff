# Graph Calendar Write Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add calendar event creation with attendees and recurrence via direct Microsoft Graph API, enabling meeting invites from Jarvis.

**Architecture:** Dual-path in MCP tool handlers — when `state.graph_client` is available and target is M365, call Graph directly (async); otherwise fall back to existing sync provider chain. Graph calendar methods follow the same `_request()` pattern as existing Teams/Mail methods.

**Tech Stack:** Python, httpx (async HTTP), MSAL (auth), Microsoft Graph API v1.0

**Spec:** `docs/superpowers/specs/2026-03-18-graph-calendar-write-design.md`

---

### Task 1: Add Calendar Scope to Config

**Files:**
- Modify: `config.py` (M365_GRAPH_SCOPES list)
- Modify: `connectors/graph_client.py:79-90` (_DEFAULT_SCOPES list)

- [ ] **Step 1: Add `Calendars.ReadWrite` to `M365_GRAPH_SCOPES` in `config.py`**

Find the `M365_GRAPH_SCOPES` list and add `"Calendars.ReadWrite"` as the first entry:

```python
M365_GRAPH_SCOPES = [
    "Calendars.ReadWrite",
    "Channel.ReadBasic.All",
    # ... rest unchanged
]
```

- [ ] **Step 2: Add `Calendars.ReadWrite` to `_DEFAULT_SCOPES` in `connectors/graph_client.py`**

Find `_DEFAULT_SCOPES` (line 79) and add `"Calendars.ReadWrite"` as the first entry:

```python
_DEFAULT_SCOPES = [
    "Calendars.ReadWrite",
    "Channel.ReadBasic.All",
    # ... rest unchanged
]
```

- [ ] **Step 3: Run existing tests to confirm no regressions**

Run: `pytest tests/test_graph_client.py -v`
Expected: All existing tests pass (scopes are not tested directly in most tests).

- [ ] **Step 4: Commit**

```bash
git add config.py connectors/graph_client.py
git commit -m "feat: add Calendars.ReadWrite scope for Graph calendar write"
```

---

### Task 2: GraphClient Calendar Helpers (Private)

**Files:**
- Modify: `connectors/graph_client.py` (add helpers)
- Create: `tests/test_graph_calendar.py` (new test file)

- [ ] **Step 1: Write failing tests for `_format_event_datetime`**

Create `tests/test_graph_calendar.py`:

```python
"""Tests for GraphClient calendar methods."""

import pytest


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph_calendar.py::TestFormatEventDatetime -v`
Expected: FAIL — `_format_event_datetime` does not exist.

- [ ] **Step 3: Implement `_format_event_datetime`**

Add to `GraphClient` class in `connectors/graph_client.py`:

```python
@staticmethod
def _format_event_datetime(
    dt_str: str, timezone: str, is_all_day: bool
) -> dict[str, str]:
    """Format a datetime string for Graph API event payload.

    Timed events: {"dateTime": "2026-04-15T09:00:00", "timeZone": "America/Denver"}
    All-day events: {"dateTime": "2026-04-15", "timeZone": "UTC"}
    """
    if is_all_day:
        # Extract date portion only
        return {"dateTime": dt_str[:10], "timeZone": "UTC"}
    return {"dateTime": dt_str, "timeZone": timezone}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_graph_calendar.py::TestFormatEventDatetime -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for `_build_attendees_payload`**

Add to `tests/test_graph_calendar.py`:

```python
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
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_graph_calendar.py::TestBuildAttendeesPayload -v`
Expected: FAIL

- [ ] **Step 7: Implement `_build_attendees_payload`**

Add to `GraphClient` class:

```python
@staticmethod
def _build_attendees_payload(
    attendees: list[dict] | None,
) -> list[dict] | None:
    """Convert simplified attendee list to Graph API format.

    Input:  [{"email": "a@b.com", "name": "A", "type": "required"}]
    Output: [{"emailAddress": {"address": "a@b.com", "name": "A"}, "type": "required"}]
    """
    if attendees is None:
        return None
    result = []
    for att in attendees:
        email = att["email"]
        name = att.get("name") or email.split("@")[0]
        att_type = att.get("type", "required")
        result.append({
            "emailAddress": {"address": email, "name": name},
            "type": att_type,
        })
    return result
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_graph_calendar.py::TestBuildAttendeesPayload -v`
Expected: PASS

- [ ] **Step 9: Write failing tests for `_build_recurrence_payload`**

Add to `tests/test_graph_calendar.py`:

```python
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
        assert result["range"]["startDate"] == ""  # filled by caller
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
```

- [ ] **Step 10: Run tests to verify they fail**

Run: `pytest tests/test_graph_calendar.py::TestBuildRecurrencePayload -v`
Expected: FAIL

- [ ] **Step 11: Implement `_build_recurrence_payload`**

Add to `GraphClient` class:

```python
@staticmethod
def _build_recurrence_payload(recurrence: dict | None) -> dict | None:
    """Convert simplified recurrence dict to Graph API format.

    Input:  {"type": "weekly", "interval": 1, "days_of_week": ["tuesday"], "end_date": "2026-12-31"}
    Output: {"pattern": {...}, "range": {...}}
    """
    if recurrence is None:
        return None

    rec_type = recurrence["type"]
    interval = recurrence.get("interval", 1)

    pattern: dict[str, Any] = {"type": rec_type, "interval": interval}
    if "days_of_week" in recurrence:
        pattern["daysOfWeek"] = recurrence["days_of_week"]
    if "day_of_month" in recurrence:
        pattern["dayOfMonth"] = recurrence["day_of_month"]
    if "month" in recurrence:
        pattern["month"] = recurrence["month"]

    # Range
    if "end_date" in recurrence:
        rec_range = {
            "type": "endDate",
            "startDate": "",  # Will be set from event start
            "endDate": recurrence["end_date"],
        }
    elif "occurrences" in recurrence:
        rec_range = {
            "type": "numbered",
            "startDate": "",
            "numberOfOccurrences": recurrence["occurrences"],
        }
    else:
        rec_range = {"type": "noEnd", "startDate": ""}

    return {"pattern": pattern, "range": rec_range}
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `pytest tests/test_graph_calendar.py::TestBuildRecurrencePayload -v`
Expected: PASS

- [ ] **Step 13: Write failing tests for `_normalize_event`**

Add to `tests/test_graph_calendar.py`:

```python
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
```

- [ ] **Step 14: Run tests to verify they fail**

Run: `pytest tests/test_graph_calendar.py::TestNormalizeEvent -v`
Expected: FAIL

- [ ] **Step 15: Implement `_normalize_event`**

Add to `GraphClient` class:

```python
@staticmethod
def _normalize_event(graph_event: dict) -> dict:
    """Normalize a Graph API event to internal format.

    Maps Graph field names to the internal dict format used by
    CalendarProvider, UnifiedCalendarService, and MCP tools.
    """
    location = graph_event.get("location")
    body = graph_event.get("body")
    attendees_raw = graph_event.get("attendees") or []
    response_status = graph_event.get("responseStatus")

    return {
        "uid": graph_event.get("id", ""),
        "title": graph_event.get("subject", ""),
        "start": (graph_event.get("start") or {}).get("dateTime", ""),
        "end": (graph_event.get("end") or {}).get("dateTime", ""),
        "location": location.get("displayName") if isinstance(location, dict) else None,
        "notes": body.get("content") if isinstance(body, dict) else None,
        "is_all_day": graph_event.get("isAllDay", False),
        "showAs": graph_event.get("showAs", ""),
        "isCancelled": graph_event.get("isCancelled", False),
        "responseStatus": response_status.get("response", "") if isinstance(response_status, dict) else "",
        "attendees": [
            att["emailAddress"]["address"]
            for att in attendees_raw
            if isinstance(att, dict) and "emailAddress" in att
        ],
        "recurrence": graph_event.get("recurrence"),
    }
```

- [ ] **Step 16: Run tests to verify they pass**

Run: `pytest tests/test_graph_calendar.py::TestNormalizeEvent -v`
Expected: PASS

- [ ] **Step 17: Commit**

```bash
git add connectors/graph_client.py tests/test_graph_calendar.py
git commit -m "feat: add Graph calendar helper methods — datetime, attendees, recurrence, normalization"
```

---

### Task 3: GraphClient Calendar CRUD Methods

**Files:**
- Modify: `connectors/graph_client.py` (add public async methods)
- Modify: `tests/test_graph_calendar.py` (add tests)

- [ ] **Step 1: Write failing tests for `create_calendar_event`**

Add to `tests/test_graph_calendar.py`:

```python
import json
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
class TestGraphCalendarCreate:
    """Test GraphClient.create_calendar_event."""

    async def test_create_basic_event(self):
        """Create event without attendees or recurrence."""
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

        # Verify the POST payload
        call_kwargs = client._request.call_args
        assert call_kwargs[0] == ("POST", "/me/events")
        payload = call_kwargs[1]["json"]
        assert payload["subject"] == "COE Review"
        assert "attendees" not in payload

    async def test_create_event_with_attendees(self):
        """Create event with attendees sends proper Graph format."""
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
        """Create recurring event sends recurrence payload."""
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
        """Create event in specific calendar uses correct endpoint."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph_calendar.py::TestGraphCalendarCreate -v`
Expected: FAIL

- [ ] **Step 3: Implement `create_calendar_event`**

Add to `GraphClient` class in `connectors/graph_client.py`:

```python
# Calendar name→ID cache (populated on first use)
_calendar_name_cache: dict[str, str]

async def resolve_calendar_id(self, calendar_name: str) -> str | None:
    """Resolve a human-readable calendar name to a Graph API calendar ID.

    Uses a session-scoped cache. Returns None if no match found.
    """
    if not hasattr(self, "_calendar_name_cache"):
        self._calendar_name_cache = {}
    if not self._calendar_name_cache:
        calendars = await self._request("GET", "/me/calendars")
        for cal in calendars.get("value", []):
            name = cal.get("name", "")
            self._calendar_name_cache[name.lower()] = cal["id"]
    return self._calendar_name_cache.get(calendar_name.lower())

async def create_calendar_event(
    self,
    subject: str,
    start: str,
    end: str,
    timezone: str = "America/Denver",
    attendees: list[dict] | None = None,
    recurrence: dict | None = None,
    calendar_id: str | None = None,
    location: str | None = None,
    body: str | None = None,
    is_all_day: bool = False,
    reminder_minutes: int | None = 15,
) -> dict:
    """Create a calendar event via Graph API.

    Sends standard Exchange meeting invites to all attendees.
    """
    payload: dict[str, Any] = {
        "subject": subject,
        "start": self._format_event_datetime(start, timezone, is_all_day),
        "end": self._format_event_datetime(end, timezone, is_all_day),
    }

    if location:
        payload["location"] = {"displayName": location}
    if body:
        payload["body"] = {"contentType": "text", "content": body}
    if is_all_day:
        payload["isAllDay"] = True
    if reminder_minutes is not None:
        payload["isReminderOn"] = True
        payload["reminderMinutesBeforeStart"] = reminder_minutes

    graph_attendees = self._build_attendees_payload(attendees)
    if graph_attendees:
        payload["attendees"] = graph_attendees

    graph_recurrence = self._build_recurrence_payload(recurrence)
    if graph_recurrence:
        # Set recurrence startDate from event start
        graph_recurrence["range"]["startDate"] = start[:10]
        payload["recurrence"] = graph_recurrence

    endpoint = f"/me/calendars/{calendar_id}/events" if calendar_id else "/me/events"
    response = await self._request("POST", endpoint, json=payload)
    return self._normalize_event(response)
```

Also initialize `_calendar_name_cache = {}` in `__init__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_graph_calendar.py::TestGraphCalendarCreate -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for `update_calendar_event` and `delete_calendar_event`**

Add to `tests/test_graph_calendar.py`:

```python
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
        """Updating attendees sends full replacement list."""
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
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_graph_calendar.py::TestGraphCalendarUpdate tests/test_graph_calendar.py::TestGraphCalendarDelete -v`
Expected: FAIL

- [ ] **Step 7: Implement `update_calendar_event` and `delete_calendar_event`**

Add to `GraphClient` class:

```python
async def update_calendar_event(self, event_id: str, **kwargs) -> dict:
    """Update a calendar event via Graph API.

    Accepts any combination of: subject, start, end, timezone, location,
    body, is_all_day, attendees, recurrence, reminder_minutes.

    Note: attendees is a FULL REPLACEMENT — omitted attendees are removed
    and receive cancellation notices.
    """
    timezone = kwargs.pop("timezone", "America/Denver")
    is_all_day = kwargs.pop("is_all_day", None)

    payload: dict[str, Any] = {}

    if "subject" in kwargs:
        payload["subject"] = kwargs["subject"]
    if "start" in kwargs:
        payload["start"] = self._format_event_datetime(
            kwargs["start"], timezone, is_all_day or False
        )
    if "end" in kwargs:
        payload["end"] = self._format_event_datetime(
            kwargs["end"], timezone, is_all_day or False
        )
    if "location" in kwargs:
        payload["location"] = {"displayName": kwargs["location"]}
    if "body" in kwargs:
        payload["body"] = {"contentType": "text", "content": kwargs["body"]}
    if is_all_day is not None:
        payload["isAllDay"] = is_all_day
    if "reminder_minutes" in kwargs:
        payload["isReminderOn"] = True
        payload["reminderMinutesBeforeStart"] = kwargs["reminder_minutes"]

    if "attendees" in kwargs:
        graph_attendees = self._build_attendees_payload(kwargs["attendees"])
        if graph_attendees is not None:
            payload["attendees"] = graph_attendees

    if "recurrence" in kwargs:
        graph_recurrence = self._build_recurrence_payload(kwargs["recurrence"])
        if graph_recurrence:
            if "start" in kwargs:
                graph_recurrence["range"]["startDate"] = kwargs["start"][:10]
            payload["recurrence"] = graph_recurrence

    response = await self._request("PATCH", f"/me/events/{event_id}", json=payload)
    return self._normalize_event(response)

async def delete_calendar_event(self, event_id: str) -> dict:
    """Delete a calendar event via Graph API."""
    return await self._request("DELETE", f"/me/events/{event_id}")
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_graph_calendar.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add connectors/graph_client.py tests/test_graph_calendar.py
git commit -m "feat: add GraphClient calendar CRUD methods — create, update, delete with attendees and recurrence"
```

---

### Task 4: Update Provider Chain Signatures

**Files:**
- Modify: `connectors/provider_base.py:30-42` (create_event signature)
- Modify: `connectors/providers/apple_provider.py:44-54` (create_event signature)
- Modify: `connectors/providers/m365_provider.py:97-124` (create_event signature, add graph_client)
- Modify: `connectors/calendar_unified.py:453-497` (create_event signature + passthrough)

- [ ] **Step 1: Update `CalendarProvider.create_event` abstract signature**

In `connectors/provider_base.py`, add `attendees` and `recurrence` to `create_event`:

```python
@abstractmethod
def create_event(
    self,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    calendar_name: Optional[str] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    is_all_day: bool = False,
    alarms: Optional[list[int]] = None,
    attendees: Optional[list[dict]] = None,
    recurrence: Optional[dict] = None,
) -> dict:
    """Create an event."""
```

- [ ] **Step 2: Update `AppleCalendarProvider.create_event` to accept and ignore new params**

In `connectors/providers/apple_provider.py`:

```python
def create_event(
    self,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    calendar_name: Optional[str] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    is_all_day: bool = False,
    alarms: Optional[list[int]] = None,
    attendees: Optional[list[dict]] = None,
    recurrence: Optional[dict] = None,
) -> dict:
    # attendees and recurrence intentionally ignored — Apple EventKit path
    result = self.store.create_event(
        title=title,
        start_dt=start_dt,
        end_dt=end_dt,
        calendar_name=calendar_name,
        location=location,
        notes=notes,
        is_all_day=is_all_day,
        alarms=alarms,
    )
    if result.get("error"):
        return result
    return self._tag_event(dict(result))
```

- [ ] **Step 3: Update `Microsoft365CalendarProvider.__init__` and `create_event`**

In `connectors/providers/m365_provider.py`, add `graph_client` param to `__init__` and update `create_event`:

```python
def __init__(
    self,
    connected: bool = False,
    graph_client=None,  # NEW
    list_calendars_fn=None,
    # ... rest unchanged
):
    self._connected = bool(connected)
    self._graph = graph_client  # Stored for future async callers
    # ... rest unchanged

def create_event(
    self,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    calendar_name: Optional[str] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    is_all_day: bool = False,
    alarms: Optional[list[int]] = None,
    attendees: Optional[list[dict]] = None,
    recurrence: Optional[dict] = None,
) -> dict:
    # Primary Graph path is in MCP tool handler (async).
    # This sync method is the bridge fallback — no attendee/recurrence support.
    if not self.is_connected():
        return self._not_connected_error()
    hook = self._hooks["create_event"]
    if hook is None:
        return self._not_configured_error("create events")
    row = hook(
        title=title,
        start_dt=start_dt,
        end_dt=end_dt,
        calendar_name=calendar_name,
        location=location,
        notes=notes,
        is_all_day=is_all_day,
    )
    if row.get("error"):
        return row
    return self._tag_event(dict(row))
```

- [ ] **Step 4: Update `UnifiedCalendarService.create_event` to pass through new params**

In `connectors/calendar_unified.py`, update the signature and the `provider.create_event()` call:

```python
def create_event(
    self,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    calendar_name: Optional[str] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    is_all_day: bool = False,
    target_provider: str = "",
    provider_preference: str = "auto",
    alarms: Optional[list[int]] = None,
    attendees: Optional[list[dict]] = None,
    recurrence: Optional[dict] = None,
) -> dict:
```

And update the `provider.create_event()` call inside the for loop (~line 479):

```python
result = provider.create_event(
    title=title,
    start_dt=start_dt,
    end_dt=end_dt,
    calendar_name=calendar_name,
    location=location,
    notes=notes,
    is_all_day=is_all_day,
    alarms=alarms,
    attendees=attendees,
    recurrence=recurrence,
)
```

- [ ] **Step 5: Run existing calendar tests to confirm no regressions**

Run: `pytest tests/ -k "calendar" -v`
Expected: All existing tests pass — new params have `None` defaults.

- [ ] **Step 6: Commit**

```bash
git add connectors/provider_base.py connectors/providers/apple_provider.py connectors/providers/m365_provider.py connectors/calendar_unified.py
git commit -m "feat: add attendees and recurrence params to calendar provider chain"
```

---

### Task 5: MCP Tool Dual-Path with Attendees & Recurrence

**Files:**
- Modify: `mcp_tools/calendar_tools.py:96-150` (create_calendar_event)
- Modify: `mcp_tools/calendar_tools.py:152-208` (update_calendar_event)
- Create: `tests/test_calendar_attendees.py` (new)

- [ ] **Step 1: Write failing tests for attendee/recurrence JSON parsing**

Create `tests/test_calendar_attendees.py`:

```python
"""Tests for calendar attendee and recurrence support in MCP tools."""

import json
import pytest

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
        assert "error" in result

    def test_missing_email_returns_error(self):
        from mcp_tools.calendar_tools import _parse_attendees

        result = _parse_attendees('[{"name": "A"}]')
        assert isinstance(result, str)
        assert "error" in result


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
        assert "error" in result

    def test_invalid_type_returns_error(self):
        from mcp_tools.calendar_tools import _parse_recurrence

        result = _parse_recurrence('{"type": "biweekly"}')
        assert isinstance(result, str)
        assert "error" in result

    def test_both_end_date_and_occurrences_returns_error(self):
        from mcp_tools.calendar_tools import _parse_recurrence

        result = _parse_recurrence('{"type": "daily", "end_date": "2026-12-31", "occurrences": 10}')
        assert isinstance(result, str)
        assert "error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_calendar_attendees.py -v`
Expected: FAIL — `_parse_attendees` and `_parse_recurrence` don't exist.

- [ ] **Step 3: Add `_parse_attendees` and `_parse_recurrence` helpers to `calendar_tools.py`**

Add inside the `register()` function in `mcp_tools/calendar_tools.py`, after `_parse_alerts`:

```python
_VALID_RECURRENCE_TYPES = {
    "daily", "weekly", "absoluteMonthly", "relativeMonthly",
    "absoluteYearly", "relativeYearly",
}

def _parse_attendees(attendees_json: str) -> list[dict] | str | None:
    """Parse and validate attendees JSON string.

    Returns list[dict] on success, None if empty, or JSON error string on failure.
    """
    if not attendees_json:
        return None
    try:
        attendees = json.loads(attendees_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid attendees JSON: {e}"})
    if not isinstance(attendees, list):
        return json.dumps({"error": "attendees must be a JSON array"})
    for att in attendees:
        if not isinstance(att, dict) or "email" not in att:
            return json.dumps({"error": "Each attendee must have an 'email' field"})
        att.setdefault("name", att["email"].split("@")[0])
        att.setdefault("type", "required")
    return attendees

def _parse_recurrence(recurrence_json: str) -> dict | str | None:
    """Parse and validate recurrence JSON string.

    Returns dict on success, None if empty, or JSON error string on failure.
    """
    if not recurrence_json:
        return None
    try:
        recurrence = json.loads(recurrence_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid recurrence JSON: {e}"})
    if not isinstance(recurrence, dict):
        return json.dumps({"error": "recurrence must be a JSON object"})
    rec_type = recurrence.get("type")
    if not rec_type or rec_type not in _VALID_RECURRENCE_TYPES:
        return json.dumps({"error": f"recurrence type must be one of: {sorted(_VALID_RECURRENCE_TYPES)}"})
    if "end_date" in recurrence and "occurrences" in recurrence:
        return json.dumps({"error": "Specify end_date or occurrences, not both"})
    return recurrence
```

Also expose them at module level for test imports (same pattern as other tools):

```python
import sys
# At end of register():
mod = sys.modules[__name__]
mod._parse_attendees = _parse_attendees
mod._parse_recurrence = _parse_recurrence
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_calendar_attendees.py -v`
Expected: PASS

- [ ] **Step 5: Update `create_calendar_event` MCP tool with dual path**

Modify the `create_calendar_event` tool handler in `mcp_tools/calendar_tools.py`:

```python
@mcp.tool()
@tool_errors("Calendar error", expected=_EXPECTED)
async def create_calendar_event(
    title: str,
    start_date: str,
    end_date: str,
    calendar_name: str = "",
    location: str = "",
    notes: str = "",
    is_all_day: bool = False,
    alerts: str = "",
    attendees: str = "",
    recurrence: str = "",
    target_provider: str = "",
    provider_preference: str = "auto",
) -> str:
    """Create a new calendar event using routing policy.

    Args:
        title: Event title (required)
        start_date: Start date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        end_date: End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        calendar_name: Calendar to create the event in (uses default if empty)
        location: Event location
        notes: Event notes/description
        is_all_day: Whether this is an all-day event (default: False)
        alerts: JSON list of alert times in minutes before event (e.g. "[15, 30]")
        attendees: JSON array of attendees (e.g. '[{"email": "user@chg.com", "name": "User"}]'). Sends Exchange meeting invites. Only works with Microsoft 365 provider.
        recurrence: JSON object for recurring events (e.g. '{"type": "weekly", "interval": 1, "days_of_week": ["tuesday"], "end_date": "2026-12-31"}'). Valid types: daily, weekly, absoluteMonthly, relativeMonthly, absoluteYearly, relativeYearly.
        target_provider: Optional explicit provider override (apple or microsoft_365)
        provider_preference: Optional provider hint (default: auto)
    """
    calendar_store = state.calendar_store
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)

    # Parse alerts
    alarms = None
    if alerts:
        parsed = _parse_alerts(alerts)
        if isinstance(parsed, str):
            return parsed
        alarms = parsed or None

    # Parse attendees
    attendees_list = None
    if attendees:
        parsed_att = _parse_attendees(attendees)
        if isinstance(parsed_att, str):
            return parsed_att
        attendees_list = parsed_att

    # Parse recurrence
    recurrence_dict = None
    if recurrence:
        parsed_rec = _parse_recurrence(recurrence)
        if isinstance(parsed_rec, str):
            return parsed_rec
        recurrence_dict = parsed_rec

    # Dual path: Graph direct (async) vs provider chain (sync)
    from connectors.router import ProviderRouter
    use_graph = (
        state.graph_client
        and (
            attendees_list
            or recurrence_dict
            or target_provider == "microsoft_365"
            or ProviderRouter._looks_work_calendar(calendar_name)
        )
    )

    if use_graph:
        # Resolve calendar_name → Graph calendar ID
        calendar_id = None
        if calendar_name:
            calendar_id = await state.graph_client.resolve_calendar_id(calendar_name)

        result = await state.graph_client.create_calendar_event(
            subject=title,
            start=start_date,
            end=end_date,
            attendees=attendees_list,
            recurrence=recurrence_dict,
            calendar_id=calendar_id,
            location=location or None,
            body=notes or None,
            is_all_day=is_all_day,
            reminder_minutes=alarms[0] if alarms else 15,
        )

        # Track ownership
        if calendar_store and not result.get("error"):
            try:
                calendar_store._upsert_ownership({
                    "unified_uid": f"microsoft_365:{result.get('uid', '')}",
                    "provider": "microsoft_365",
                    "native_id": result.get("uid", ""),
                    "calendar": calendar_name or "",
                })
            except Exception:
                logger.debug("Ownership tracking failed", exc_info=True)

        result["provider_used"] = "microsoft_365"
        return json.dumps({"status": "created", "event": result})

    # Sync fallback path
    kwargs = {}
    if target_provider:
        kwargs["target_provider"] = target_provider
    if provider_preference and provider_preference != "auto":
        kwargs["provider_preference"] = provider_preference
    result = _retry_on_transient(
        calendar_store.create_event,
        title=title,
        start_dt=start_dt,
        end_dt=end_dt,
        calendar_name=calendar_name or None,
        location=location or None,
        notes=notes or None,
        is_all_day=is_all_day,
        alarms=alarms,
        attendees=attendees_list,
        recurrence=recurrence_dict,
        **kwargs,
    )
    return json.dumps({"status": "created", "event": result})
```

- [ ] **Step 6: Similarly update `update_calendar_event` with attendees, recurrence, and dual path**

Add `attendees: str = ""` and `recurrence: str = ""` parameters. Add dual-path logic similar to `create_calendar_event`. Docstring must note: "attendees is a FULL REPLACEMENT — omitted attendees are removed and receive cancellation notices."

- [ ] **Step 7: Run all calendar tests**

Run: `pytest tests/ -k "calendar" -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add mcp_tools/calendar_tools.py tests/test_calendar_attendees.py
git commit -m "feat: add attendees and recurrence to MCP calendar tools with Graph dual-path"
```

---

### Task 6: Verify Wiring — Graph Client Accessible from MCP Tools

**Files:**
- Verify: `mcp_server.py` (no changes needed)

**Note:** The M365 provider is constructed at `mcp_server.py:~84`, before `_state.graph_client` is initialized at `~204`. This means we cannot pass `graph_client` to the provider constructor at init time. This is fine because:
- The **primary path** (MCP tool → GraphClient) accesses `state.graph_client` at call time, not construction time
- The provider constructor's `graph_client` param (added in Task 4) is for future async callers only
- `state.graph_client` is already set on `ServerState` and accessible from all MCP tool handlers

- [ ] **Step 1: Verify `state.graph_client` is accessible from calendar tool handlers**

Check `mcp_server.py` to confirm that `_state.graph_client` is set during lifespan init and that `state` (the `ServerState` instance) is passed to `calendar_tools.register()`.

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v --timeout=60`
Expected: All tests pass, no regressions.

- [ ] **Step 3: Commit if any changes were needed**

```bash
git add mcp_server.py
git commit -m "feat: verify graph_client wiring for calendar tools"
```

---

### Task 7: Integration Test — End-to-End MCP → Graph

**Files:**
- Modify: `tests/test_calendar_attendees.py` (add integration tests)

- [ ] **Step 1: Write integration test — create event with attendees via MCP tool**

Add to `tests/test_calendar_attendees.py`:

```python
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
class TestMCPCalendarIntegration:
    """Integration tests using the existing mcp_server._state injection pattern.

    Tool functions capture `state` via closure from register(mcp, state),
    so we must mutate `mcp_server._state` directly — NOT patch module attrs.
    """

    async def test_create_with_attendees_uses_graph(self, tmp_path):
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

        # Save originals, inject mocks via mcp_server._state
        import mcp_server
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

    async def test_no_attendees_no_graph_uses_sync_path(self, tmp_path):
        """Without attendees and non-work calendar, uses sync provider chain."""
        from mcp_tools.calendar_tools import create_calendar_event

        import mcp_server
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
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_calendar_attendees.py::TestMCPCalendarIntegration -v`
Expected: PASS

- [ ] **Step 3: Run full test suite for final validation**

Run: `pytest tests/ -v --timeout=60`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_calendar_attendees.py
git commit -m "test: add integration tests for calendar attendee dual-path routing"
```

---

### Task 8: Re-Auth and Manual Verification

**Files:** None (manual steps)

- [ ] **Step 1: Re-authenticate to get new calendar scope**

Run: `python scripts/bootstrap_secrets.py --reauth`

Follow the device code flow to grant `Calendars.ReadWrite` permission.

- [ ] **Step 2: Verify with a test event**

Use the MCP tool to create a test event with an attendee (yourself) and verify:
- Event appears on your CHG calendar
- You receive a meeting invite email
- Delete the test event after verification

- [ ] **Step 3: Final commit with any fixes from manual testing**

```bash
git add -A
git commit -m "fix: adjustments from manual calendar write verification"
```
