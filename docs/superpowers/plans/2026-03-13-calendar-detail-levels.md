# Calendar Detail Levels Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `detail` parameter to calendar tools that reduces response size by ~82% for the default tier, cutting the largest token cost in the system.

**Architecture:** New pure-function filter module (`connectors/event_filters.py`) sits between the unified calendar connector and MCP tool responses. The connector always returns full events; filtering happens at the MCP tool layer. Three tiers: `summary`, `normal` (default), `full`.

**Tech Stack:** Python, pytest, existing CalendarStore/MCP infrastructure

**Spec:** `docs/superpowers/specs/2026-03-13-calendar-detail-levels-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `connectors/event_filters.py` | Create | Pure filter functions: `filter_event_fields`, `prioritize_attendees`, `truncate_notes` |
| `tests/test_event_filters.py` | Create | Unit tests for all filter functions |
| `mcp_tools/calendar_tools.py` | Modify | Add `detail` param to `get_calendar_events` and `search_calendar_events`, apply filtering |
| `tests/test_mcp_calendar.py` | Modify | Integration tests for detail tiers |
| `agent_configs/meeting_prep.yaml` | Modify | Add `detail="full"` instruction to system prompt |

---

## Chunk 1: Filter Module (TDD)

### Task 1: `truncate_notes` — tests and implementation

**Files:**
- Create: `tests/test_event_filters.py`
- Create: `connectors/event_filters.py`

- [ ] **Step 1: Write failing tests for `truncate_notes`**

Create `tests/test_event_filters.py`:

```python
"""Tests for connectors/event_filters.py."""

from connectors.event_filters import truncate_notes


class TestTruncateNotes:
    def test_none_returns_none(self):
        assert truncate_notes(None) is None

    def test_empty_string_returns_empty(self):
        assert truncate_notes("") == ""

    def test_short_text_unchanged(self):
        assert truncate_notes("Hello world") == "Hello world"

    def test_exactly_200_chars_unchanged(self):
        text = "a" * 200
        assert truncate_notes(text) == text

    def test_over_200_truncated_with_ellipsis(self):
        text = "a" * 250
        result = truncate_notes(text)
        assert len(result) == 200
        assert result == "a" * 197 + "..."

    def test_201_chars_truncated(self):
        text = "a" * 201
        result = truncate_notes(text)
        assert len(result) == 200
        assert result.endswith("...")

    def test_custom_max_length(self):
        text = "a" * 50
        result = truncate_notes(text, max_length=20)
        assert len(result) == 20
        assert result == "a" * 17 + "..."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_event_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'connectors.event_filters'`

- [ ] **Step 3: Implement `truncate_notes`**

Create `connectors/event_filters.py`:

```python
"""Calendar event field filtering for MCP tool response size optimization.

Provides detail-level filtering (summary/normal/full) to reduce token
consumption. All functions return new dicts — inputs are never mutated.
"""

from __future__ import annotations


def truncate_notes(notes: str | None, max_length: int = 200) -> str | None:
    """Truncate notes to max_length characters.

    If truncated, final 3 chars are '...' (so content is max_length-3 chars).
    Returns None if input is None. Returns as-is if within limit.
    """
    if notes is None:
        return None
    if len(notes) <= max_length:
        return notes
    return notes[: max_length - 3] + "..."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_event_filters.py::TestTruncateNotes -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add connectors/event_filters.py tests/test_event_filters.py
git commit -m "feat: add truncate_notes filter function with tests"
```

---

### Task 2: `prioritize_attendees` — tests and implementation

**Files:**
- Modify: `tests/test_event_filters.py`
- Modify: `connectors/event_filters.py`

- [ ] **Step 1: Write failing tests for `prioritize_attendees`**

Append to `tests/test_event_filters.py`:

```python
from connectors.event_filters import prioritize_attendees


class TestPrioritizeAttendees:
    def test_empty_list(self):
        result, count = prioritize_attendees([], None, None)
        assert result == []
        assert count == 0

    def test_m365_strings_under_limit(self):
        attendees = ["charlie@ex.com", "alice@ex.com", "bob@ex.com"]
        result, count = prioritize_attendees(attendees, None, None, limit=5)
        assert count == 3
        assert result == ["alice@ex.com", "bob@ex.com", "charlie@ex.com"]

    def test_m365_strings_over_limit(self):
        attendees = [f"user{i}@ex.com" for i in range(10)]
        result, count = prioritize_attendees(attendees, None, None, limit=5)
        assert count == 10
        assert len(result) == 5

    def test_organizer_first(self):
        attendees = ["charlie@ex.com", "alice@ex.com", "org@ex.com"]
        result, count = prioritize_attendees(attendees, "org@ex.com", None, limit=5)
        assert result[0] == "org@ex.com"
        assert count == 3

    def test_user_second_after_organizer(self):
        attendees = ["charlie@ex.com", "alice@ex.com", "org@ex.com", "me@ex.com"]
        result, count = prioritize_attendees(attendees, "org@ex.com", "me@ex.com", limit=5)
        assert result[0] == "org@ex.com"
        assert result[1] == "me@ex.com"
        assert count == 4

    def test_user_first_when_no_organizer(self):
        attendees = ["charlie@ex.com", "alice@ex.com", "me@ex.com"]
        result, count = prioritize_attendees(attendees, None, "me@ex.com", limit=5)
        assert result[0] == "me@ex.com"
        assert count == 3

    def test_missing_user_email(self):
        attendees = ["charlie@ex.com", "alice@ex.com"]
        result, count = prioritize_attendees(attendees, None, None, limit=5)
        assert count == 2
        assert result == ["alice@ex.com", "charlie@ex.com"]

    def test_apple_object_attendees(self):
        attendees = [
            {"name": "Charlie", "email": "charlie@ex.com", "status": 1},
            {"name": "Alice", "email": "alice@ex.com", "status": 1},
            {"name": "Org", "email": "org@ex.com", "status": 0},
        ]
        result, count = prioritize_attendees(attendees, "org@ex.com", None, limit=5)
        assert result[0] == "org@ex.com"
        assert all(isinstance(e, str) for e in result)
        assert count == 3

    def test_mixed_format_not_expected_but_handled(self):
        """Edge case: mixed string and dict attendees."""
        attendees = [
            "bob@ex.com",
            {"name": "Alice", "email": "alice@ex.com", "status": 1},
        ]
        result, count = prioritize_attendees(attendees, None, None, limit=5)
        assert count == 2
        assert set(result) == {"alice@ex.com", "bob@ex.com"}

    def test_organizer_not_in_list(self):
        """Organizer email not found in attendees — skip, don't crash."""
        attendees = ["alice@ex.com", "bob@ex.com"]
        result, count = prioritize_attendees(attendees, "org@ex.com", None, limit=5)
        assert count == 2
        assert result == ["alice@ex.com", "bob@ex.com"]

    def test_user_not_in_list(self):
        """User email not found in attendees — skip, don't crash."""
        attendees = ["alice@ex.com", "bob@ex.com"]
        result, count = prioritize_attendees(attendees, None, "me@ex.com", limit=5)
        assert count == 2
        assert result == ["alice@ex.com", "bob@ex.com"]

    def test_cap_with_priority_users(self):
        """Organizer and user take 2 of the 5 slots; rest sorted alpha."""
        attendees = [f"user{i:02d}@ex.com" for i in range(10)]
        attendees.append("org@ex.com")
        attendees.append("me@ex.com")
        result, count = prioritize_attendees(attendees, "org@ex.com", "me@ex.com", limit=5)
        assert count == 12
        assert len(result) == 5
        assert result[0] == "org@ex.com"
        assert result[1] == "me@ex.com"
        # Remaining 3 are alphabetically first from the rest
        remaining = sorted(f"user{i:02d}@ex.com" for i in range(10))
        assert result[2:] == remaining[:3]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_event_filters.py::TestPrioritizeAttendees -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `prioritize_attendees`**

Add to `connectors/event_filters.py`:

```python
def _extract_email(attendee: str | dict) -> str:
    """Extract email from either a string or an Apple attendee dict."""
    if isinstance(attendee, dict):
        return attendee.get("email", "")
    return attendee


def prioritize_attendees(
    attendees: list[str | dict],
    organizer: str | None,
    user_email: str | None,
    limit: int = 5,
) -> tuple[list[str], int]:
    """Normalize attendees to emails, prioritize, and cap.

    Priority order: organizer first, user second, then alphabetical.
    Returns (prioritized_email_list, total_count).
    Handles both M365 string lists and Apple attendee object lists.
    """
    emails = [_extract_email(a) for a in attendees]
    emails = [e for e in emails if e]  # drop empty
    total = len(emails)

    if total == 0:
        return [], 0

    priority = []
    rest = set(emails)

    # Organizer first
    if organizer and organizer in rest:
        priority.append(organizer)
        rest.discard(organizer)

    # User second
    if user_email and user_email in rest:
        priority.append(user_email)
        rest.discard(user_email)

    # Remaining sorted alphabetically
    remaining = sorted(rest)

    combined = priority + remaining
    return combined[:limit], total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_event_filters.py::TestPrioritizeAttendees -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add connectors/event_filters.py tests/test_event_filters.py
git commit -m "feat: add prioritize_attendees filter function with tests"
```

---

### Task 3: `filter_event_fields` — tests and implementation

**Files:**
- Modify: `tests/test_event_filters.py`
- Modify: `connectors/event_filters.py`

- [ ] **Step 1: Create test fixtures and write failing tests**

Append to `tests/test_event_filters.py`:

```python
import pytest
from connectors.event_filters import filter_event_fields

# -- Fixtures --

SAMPLE_M365_EVENT = {
    "uid": "AAMkAG123",
    "title": "Team Standup",
    "start": "2026-03-13T15:00:00+00:00",
    "end": "2026-03-13T15:30:00+00:00",
    "calendar": "CHG",
    "location": "Room 4A",
    "is_all_day": False,
    "notes": "Discuss sprint progress and blockers. " * 20,  # ~720 chars
    "attendees": [f"user{i}@chg.com" for i in range(15)],
    "showAs": "busy",
    "responseStatus": "accepted",
    "isCancelled": False,
    "provider": "microsoft_365",
    "native_id": "native123",
    "unified_uid": "microsoft_365:native123",
    "source_account": "jason@chg.com",
    "calendar_id": "cal-id-123",
    "organizer": "user0@chg.com",
    "alarms": [15],
}

SAMPLE_APPLE_EVENT = {
    "uid": "apple-uid-456",
    "title": "Lunch",
    "start": "2026-03-13T18:00:00+00:00",
    "end": "2026-03-13T19:00:00+00:00",
    "calendar": "Calendar",
    "location": "",
    "is_all_day": False,
    "notes": None,
    "attendees": [
        {"name": "Alice", "email": "alice@ex.com", "status": 1},
        {"name": "Org", "email": "org@ex.com", "status": 0},
    ],
    "alarms": [10],
    "provider": "apple",
}


class TestFilterEventFieldsSummary:
    def test_summary_has_only_expected_fields(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "summary")
        assert set(result.keys()) == {"title", "start", "end", "calendar", "location", "is_all_day"}

    def test_summary_values_match_original(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "summary")
        assert result["title"] == "Team Standup"
        assert result["start"] == "2026-03-13T15:00:00+00:00"

    def test_summary_no_attendees(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "summary")
        assert "attendees" not in result

    def test_summary_apple_event(self):
        result = filter_event_fields(SAMPLE_APPLE_EVENT, "summary")
        assert set(result.keys()) == {"title", "start", "end", "calendar", "location", "is_all_day"}


class TestFilterEventFieldsNormal:
    def test_normal_has_expected_fields(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "normal", user_email="me@chg.com")
        expected_keys = {
            "title", "start", "end", "calendar", "location", "is_all_day",
            "attendees", "attendee_count", "notes", "showAs", "responseStatus",
            "provider", "uid",
        }
        assert set(result.keys()) == expected_keys

    def test_normal_attendees_capped_at_5(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "normal", user_email="me@chg.com")
        assert len(result["attendees"]) <= 5
        assert result["attendee_count"] == 15

    def test_normal_organizer_prioritized(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "normal", user_email="me@chg.com")
        # organizer is user0@chg.com
        assert result["attendees"][0] == "user0@chg.com"

    def test_normal_notes_truncated(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "normal")
        assert len(result["notes"]) <= 200

    def test_normal_m365_has_showas(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "normal")
        assert result["showAs"] == "busy"

    def test_normal_apple_showas_is_none(self):
        result = filter_event_fields(SAMPLE_APPLE_EVENT, "normal")
        assert result["showAs"] is None
        assert result["responseStatus"] is None

    def test_normal_apple_attendees_normalized_to_strings(self):
        result = filter_event_fields(SAMPLE_APPLE_EVENT, "normal")
        assert all(isinstance(a, str) for a in result["attendees"])

    def test_normal_no_attendees(self):
        event = {**SAMPLE_M365_EVENT, "attendees": []}
        result = filter_event_fields(event, "normal")
        assert result["attendees"] == []
        assert result["attendee_count"] == 0

    def test_normal_missing_attendees_key(self):
        event = {k: v for k, v in SAMPLE_M365_EVENT.items() if k != "attendees"}
        result = filter_event_fields(event, "normal")
        assert result["attendees"] == []
        assert result["attendee_count"] == 0


class TestFilterEventFieldsFull:
    def test_full_returns_all_fields(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "full")
        assert set(result.keys()) == set(SAMPLE_M365_EVENT.keys())

    def test_full_is_shallow_copy(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "full")
        assert result is not SAMPLE_M365_EVENT
        assert result == SAMPLE_M365_EVENT

    def test_full_does_not_truncate_notes(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "full")
        assert result["notes"] == SAMPLE_M365_EVENT["notes"]

    def test_full_does_not_cap_attendees(self):
        result = filter_event_fields(SAMPLE_M365_EVENT, "full")
        assert len(result["attendees"]) == 15


class TestFilterEventFieldsInvalid:
    def test_invalid_detail_raises_valueerror(self):
        with pytest.raises(ValueError, match="detail must be one of"):
            filter_event_fields(SAMPLE_M365_EVENT, "compact")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_event_filters.py -k "FilterEventFields" -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `filter_event_fields`**

Add to `connectors/event_filters.py`:

```python
_VALID_DETAILS = frozenset({"summary", "normal", "full"})

_SUMMARY_FIELDS = ("title", "start", "end", "calendar", "location", "is_all_day")

_NORMAL_FIELDS = _SUMMARY_FIELDS + (
    "attendees", "attendee_count", "notes",
    "showAs", "responseStatus", "provider", "uid",
)


def _detect_organizer(event: dict) -> str | None:
    """Extract organizer email from event metadata.

    M365: uses 'organizer' field.
    Apple: first attendee with status == 0.
    """
    org = event.get("organizer")
    if org:
        return _extract_email(org) if isinstance(org, dict) else org

    # Apple fallback: attendee with status 0
    for att in event.get("attendees", []):
        if isinstance(att, dict) and att.get("status") == 0:
            return att.get("email", "")
    return None


def filter_event_fields(
    event: dict,
    detail: str,
    user_email: str | None = None,
) -> dict:
    """Return a filtered copy of event appropriate for the detail level.

    Args:
        event: Full event dict from unified connector.
        detail: One of "summary", "normal", "full".
        user_email: Authenticated user email for attendee prioritization.

    Returns:
        Filtered event dict (shallow copy for full, new dict for others).

    Raises:
        ValueError: If detail is not one of the valid tiers.
    """
    if detail not in _VALID_DETAILS:
        raise ValueError(f"detail must be one of: {', '.join(sorted(_VALID_DETAILS))}")

    if detail == "full":
        return dict(event)

    if detail == "summary":
        return {k: event.get(k) for k in _SUMMARY_FIELDS}

    # normal tier
    organizer = _detect_organizer(event)
    raw_attendees = event.get("attendees", [])
    attendees, attendee_count = prioritize_attendees(
        raw_attendees, organizer, user_email,
    )

    return {
        "title": event.get("title"),
        "start": event.get("start"),
        "end": event.get("end"),
        "calendar": event.get("calendar"),
        "location": event.get("location"),
        "is_all_day": event.get("is_all_day"),
        "attendees": attendees,
        "attendee_count": attendee_count,
        "notes": truncate_notes(event.get("notes")),
        "showAs": event.get("showAs"),
        "responseStatus": event.get("responseStatus"),
        "provider": event.get("provider"),
        "uid": event.get("uid"),
    }
```

- [ ] **Step 4: Run all filter tests**

Run: `pytest tests/test_event_filters.py -v`
Expected: All tests PASS (7 truncate + 12 attendees + 18 filter = 37 total)

- [ ] **Step 5: Commit**

```bash
git add connectors/event_filters.py tests/test_event_filters.py
git commit -m "feat: add filter_event_fields with summary/normal/full tiers"
```

---

## Chunk 2: MCP Tool Integration

### Task 4: Add `detail` parameter to `get_calendar_events`

**Files:**
- Modify: `mcp_tools/calendar_tools.py:66-94`
- Modify: `tests/test_mcp_calendar.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_mcp_calendar.py`:

```python
class TestGetCalendarEventsDetail:
    """Tests for the detail parameter on get_calendar_events."""

    @pytest.mark.asyncio
    async def test_default_detail_is_normal(self, calendar_state):
        from mcp_tools.calendar_tools import get_calendar_events

        calendar_state.get_events.return_value = [{
            "uid": "AAMk123",
            "title": "Standup",
            "start": "2026-03-13T15:00:00+00:00",
            "end": "2026-03-13T15:30:00+00:00",
            "calendar": "CHG",
            "location": "Room 4A",
            "is_all_day": False,
            "notes": "x" * 300,
            "attendees": [f"user{i}@chg.com" for i in range(20)],
            "showAs": "busy",
            "responseStatus": "accepted",
            "provider": "microsoft_365",
            "native_id": "n123",
        }]

        result = json.loads(await get_calendar_events("2026-03-13", "2026-03-14"))
        event = result["results"][0]
        # Normal tier: attendees capped, notes truncated
        assert len(event["attendees"]) <= 5
        assert event["attendee_count"] == 20
        assert len(event["notes"]) <= 200
        # No extra fields like native_id
        assert "native_id" not in event

    @pytest.mark.asyncio
    async def test_detail_summary(self, calendar_state):
        from mcp_tools.calendar_tools import get_calendar_events

        calendar_state.get_events.return_value = [{
            "uid": "AAMk123",
            "title": "Standup",
            "start": "2026-03-13T15:00:00+00:00",
            "end": "2026-03-13T15:30:00+00:00",
            "calendar": "CHG",
            "location": "",
            "is_all_day": False,
            "notes": "Big agenda here",
            "attendees": ["a@ex.com"],
            "showAs": "busy",
            "provider": "microsoft_365",
        }]

        result = json.loads(await get_calendar_events("2026-03-13", "2026-03-14", detail="summary"))
        event = result["results"][0]
        assert set(event.keys()) == {"title", "start", "end", "calendar", "location", "is_all_day"}

    @pytest.mark.asyncio
    async def test_detail_full(self, calendar_state):
        from mcp_tools.calendar_tools import get_calendar_events

        full_event = {
            "uid": "AAMk123",
            "title": "Standup",
            "start": "2026-03-13T15:00:00+00:00",
            "end": "2026-03-13T15:30:00+00:00",
            "calendar": "CHG",
            "location": "",
            "is_all_day": False,
            "notes": "x" * 500,
            "attendees": [f"user{i}@chg.com" for i in range(20)],
            "showAs": "busy",
            "responseStatus": "accepted",
            "provider": "microsoft_365",
            "native_id": "n123",
        }
        calendar_state.get_events.return_value = [full_event]

        result = json.loads(await get_calendar_events("2026-03-13", "2026-03-14", detail="full"))
        event = result["results"][0]
        # Full: no truncation, no cap
        assert len(event["attendees"]) == 20
        assert len(event["notes"]) == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_calendar.py::TestGetCalendarEventsDetail -v`
Expected: FAIL (get_calendar_events doesn't accept `detail` parameter yet)

- [ ] **Step 3: Modify `get_calendar_events` in `mcp_tools/calendar_tools.py`**

Change the function at line 68-94 to:

```python
    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def get_calendar_events(
        start_date: str,
        end_date: str,
        calendar_name: str = "",
        provider_preference: str = "auto",
        source_filter: str = "",
        detail: str = "normal",
    ) -> str:
        """Get events in a date range across configured providers.

        Args:
            start_date: Start date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            end_date: End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            calendar_name: Optional calendar name to filter by
            provider_preference: auto | apple | microsoft_365 | both (default: auto)
            source_filter: Optional source/provider text filter (e.g. iCloud, Google, Exchange)
            detail: summary | normal | full — controls response verbosity (default: normal)
        """
        from connectors.event_filters import filter_event_fields

        calendar_store = state.calendar_store
        start_dt = _parse_date(start_date)
        end_dt = _parse_date(end_date)
        calendar_names = [calendar_name] if calendar_name else None
        kwargs = {"calendar_names": calendar_names}
        if provider_preference and provider_preference != "auto":
            kwargs["provider_preference"] = provider_preference
        if source_filter:
            kwargs["source_filter"] = source_filter
        events = _retry_on_transient(calendar_store.get_events, start_dt, end_dt, **kwargs)
        filtered = [filter_event_fields(e, detail, user_email=config.USER_EMAIL) for e in events]
        return json.dumps({"results": filtered})
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mcp_calendar.py::TestGetCalendarEventsDetail -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Run full calendar test suite to check for regressions**

Run: `pytest tests/test_mcp_calendar.py -v`
Expected: All existing tests PASS (existing tests may need minor field adjustments since default is now `normal`)

- [ ] **Step 6: Fix any regressions**

Existing tests that check for fields like `native_id` in default responses will fail because `normal` is now the default. Fix by adding `detail="full"` to those test calls, OR update assertions to match `normal` tier fields. Evaluate each test to determine which is correct.

- [ ] **Step 7: Commit**

```bash
git add mcp_tools/calendar_tools.py tests/test_mcp_calendar.py
git commit -m "feat: add detail parameter to get_calendar_events (default: normal)"
```

---

### Task 5: Add `detail` parameter to `search_calendar_events`

**Files:**
- Modify: `mcp_tools/calendar_tools.py:237-265`
- Modify: `tests/test_mcp_calendar.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_mcp_calendar.py`:

```python
class TestSearchCalendarEventsDetail:
    @pytest.mark.asyncio
    async def test_search_default_detail_is_normal(self, calendar_state):
        from mcp_tools.calendar_tools import search_calendar_events

        calendar_state.search_events.return_value = [{
            "uid": "AAMk123",
            "title": "Standup",
            "start": "2026-03-13T15:00:00+00:00",
            "end": "2026-03-13T15:30:00+00:00",
            "calendar": "CHG",
            "location": "",
            "is_all_day": False,
            "notes": "x" * 300,
            "attendees": [f"user{i}@chg.com" for i in range(20)],
            "showAs": "busy",
            "responseStatus": "accepted",
            "provider": "microsoft_365",
        }]

        result = json.loads(await search_calendar_events("Standup"))
        event = result["results"][0]
        assert len(event["attendees"]) <= 5
        assert event["attendee_count"] == 20
        assert len(event["notes"]) <= 200
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mcp_calendar.py::TestSearchCalendarEventsDetail -v`
Expected: FAIL

- [ ] **Step 3: Modify `search_calendar_events`**

Change at line 237-265 to add `detail: str = "normal"` parameter and apply filtering:

```python
    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def search_calendar_events(
        query: str,
        start_date: str = "",
        end_date: str = "",
        provider_preference: str = "auto",
        source_filter: str = "",
        detail: str = "normal",
    ) -> str:
        """Search events by title text. Defaults to +/- 30 days if no dates provided.

        Args:
            query: Text to search for in event titles (required)
            start_date: Start date in ISO format (defaults to 30 days ago)
            end_date: End date in ISO format (defaults to 30 days from now)
            provider_preference: auto | apple | microsoft_365 | both (default: auto)
            source_filter: Optional source/provider text filter (e.g. iCloud, Google, Exchange)
            detail: summary | normal | full — controls response verbosity (default: normal)
        """
        from datetime import timedelta
        from connectors.event_filters import filter_event_fields

        calendar_store = state.calendar_store
        now = datetime.now(tz=ZoneInfo(config.USER_TIMEZONE))
        start_dt = _parse_date(start_date) if start_date else now - timedelta(days=30)
        end_dt = _parse_date(end_date) if end_date else now + timedelta(days=30)
        kwargs = {}
        if provider_preference and provider_preference != "auto":
            kwargs["provider_preference"] = provider_preference
        if source_filter:
            kwargs["source_filter"] = source_filter
        events = _retry_on_transient(calendar_store.search_events, query, start_dt, end_dt, **kwargs)
        filtered = [filter_event_fields(e, detail, user_email=config.USER_EMAIL) for e in events]
        return json.dumps({"results": filtered})
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mcp_calendar.py::TestSearchCalendarEventsDetail -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_tools/calendar_tools.py tests/test_mcp_calendar.py
git commit -m "feat: add detail parameter to search_calendar_events"
```

---

### Task 6: Apply summary filtering to `find_my_open_slots`

**Files:**
- Modify: `mcp_tools/calendar_tools.py:378-390`
- Modify: `tests/test_mcp_calendar.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_mcp_calendar.py`:

```python
class TestFindMyOpenSlotsFiltering:
    @pytest.mark.asyncio
    async def test_events_passed_to_availability_are_filtered(self, calendar_state):
        """Verify find_my_open_slots doesn't pass full event payloads to analysis."""
        from mcp_tools.calendar_tools import find_my_open_slots
        from unittest.mock import patch

        big_event = {
            "uid": "AAMk123",
            "title": "Standup",
            "start": "2026-03-14T15:00:00-06:00",
            "end": "2026-03-14T15:30:00-06:00",
            "calendar": "CHG",
            "location": "",
            "is_all_day": False,
            "notes": "x" * 1000,
            "attendees": [f"user{i}@chg.com" for i in range(30)],
            "showAs": "busy",
            "provider": "microsoft_365",
        }
        calendar_state.get_events_with_routing.return_value = ([big_event], {
            "providers_requested": ["microsoft_365"],
            "providers_succeeded": ["microsoft_365"],
            "provider_preference": "both",
            "routing_reason": "auto",
            "is_fallback": False,
        })

        with patch("mcp_tools.calendar_tools.find_available_slots") as mock_slots:
            mock_slots.return_value = []
            await find_my_open_slots("2026-03-14", "2026-03-15")
            passed_events = mock_slots.call_args[1]["events"]
            # Events should be summary-filtered: no attendees, no notes
            for evt in passed_events:
                assert "attendees" not in evt
                assert "notes" not in evt
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mcp_calendar.py::TestFindMyOpenSlotsFiltering -v`
Expected: FAIL (events still have attendees/notes)

- [ ] **Step 3: Add summary filtering to `find_my_open_slots`**

In `mcp_tools/calendar_tools.py`, after line 342 (where events are fetched) and before the error check at line 355, add the import and filtering. After line 376 (end of error handling block), before `slots = find_available_slots(...)` at line 379, add:

```python
        # Filter events to summary tier to reduce token waste in availability analysis
        from connectors.event_filters import filter_event_fields
        events = [filter_event_fields(e, "summary") for e in events]
```

**Placement:** Insert these two lines at line 378, immediately before `slots = find_available_slots(` (line 379). This is AFTER the error-payload check (lines 355-376) since error payloads aren't real events.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mcp_calendar.py::TestFindMyOpenSlotsFiltering -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/test_mcp_calendar.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add mcp_tools/calendar_tools.py tests/test_mcp_calendar.py
git commit -m "perf: filter events to summary tier in find_my_open_slots"
```

---

## Chunk 3: Agent Config Update + Final Verification

### Task 7: Update meeting prep agent to use `detail="full"`

**Files:**
- Modify: `agent_configs/meeting_prep.yaml`

- [ ] **Step 1: Add instruction to meeting_prep system prompt**

In `agent_configs/meeting_prep.yaml`, find this line in the system prompt:
```
- **Calendar** (get_calendar_events, search_calendar_events): Pull the meeting event itself for
```

Add after the calendar bullet's description (before the `- **Email**` bullet):
```
     Always pass `detail="full"` when calling get_calendar_events or search_calendar_events to get complete attendee lists and full meeting notes.
```

- [ ] **Step 2: Commit**

```bash
git add agent_configs/meeting_prep.yaml
git commit -m "docs: instruct meeting_prep agent to use detail=full for calendar"
```

---

### Task 8: Run full test suite and verify

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Run only the new/modified test files**

Run: `pytest tests/test_event_filters.py tests/test_mcp_calendar.py -v`
Expected: All PASS

- [ ] **Step 3: Final commit if any fixups needed**

```bash
git add -A
git commit -m "chore: final fixups for calendar detail levels"
```
