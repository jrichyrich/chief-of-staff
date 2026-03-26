# Calendar Event Detail Levels

**Date:** 2026-03-13
**Status:** Draft
**Problem:** `get_calendar_events` averages 143KB per response (3.9MB total across 107 calls), driven by full attendee arrays, unbounded notes, and redundant metadata. This is the single largest token cost driver in the system.

## Design

Add a `detail` parameter to `get_calendar_events` and `search_calendar_events` with three tiers: `summary`, `normal`, and `full`. Default is `normal`.

### Detail Tiers

#### `summary` — availability and conflict detection

Returns only time-block essentials. ~150-200 bytes per event (~90% reduction).

Fields: `title`, `start`, `end`, `calendar`, `location`, `is_all_day`.

#### `normal` (default) — briefings and ad-hoc queries

Adds attendees (capped), truncated notes, and key status fields. ~400-600 bytes per event (~70% reduction).

Fields: everything in `summary`, plus:
- `attendees` — up to 5 email strings, prioritized: organizer first, authenticated user second, then remaining alphabetically (see Attendee Normalization below)
- `attendee_count` — total attendee count (so callers know if the list was truncated)
- `notes` — truncated to 200 characters (see Notes Truncation below)
- `showAs` — free/busy/tentative/oof (M365 events only; `null` for Apple events)
- `responseStatus` — accepted/declined/tentative/none (M365 events only; `null` for Apple events)
- `provider` — `"microsoft_365"` or `"apple"`
- `uid` — event identifier

**Provider-specific field handling:** M365-only fields (`showAs`, `responseStatus`) are always present in the `normal` tier dict. For Apple events, their value is `null`. This gives consumers a stable schema regardless of provider.

#### `full` — meeting prep and deep context

Returns a shallow copy of the event dict unchanged — all provider-native fields, no truncation. Apple events include `alarms` and attendee objects; M365 events include `showAs`, `isCancelled`, `responseStatus`, full attendee arrays, etc. No fields are added or removed.

### Attendee Normalization

Both providers return attendees differently:
- **Apple Calendar**: list of objects `{"name": str, "email": str, "status": int}`
- **M365 Bridge**: list of email strings `["email@example.com", ...]`

For `summary` and `normal` tiers, attendees are **always normalized to email strings**. The `prioritize_attendees` function handles both input formats:

```python
def _extract_email(attendee: str | dict) -> str:
    """Extract email from either a string or an Apple attendee dict."""
    if isinstance(attendee, dict):
        return attendee.get("email", "")
    return attendee
```

For `full` tier, attendees are returned in their provider-native format (objects for Apple, strings for M365).

### Attendee Prioritization (normal tier)

When capping attendees to 5:

1. **Organizer** — M365: use `organizer` field from event metadata if present. Apple: first attendee with `status == 0` (organizer participation status), or skip if ambiguous.
2. **Authenticated user** — sourced from `config.USER_EMAIL` (`jason.richards@chghealthcare.com`)
3. Remaining attendees, sorted alphabetically by email
4. Truncate at 5

If organizer cannot be identified, skip step 1 and start with the authenticated user. The `attendee_count` field always reflects the true total regardless of truncation.

### Notes Truncation

For `normal` tier, notes are truncated by character count (not bytes):
- If `len(notes) > 200`: return `notes[:197] + "..."` (total length = 200)
- If `len(notes) <= 200`: return as-is
- If `notes` is `None`: return `None`

### Updated Tool Signatures

```python
async def get_calendar_events(
    start_date: str,
    end_date: str,
    calendar_name: str = "",
    provider_preference: str = "auto",
    source_filter: str = "",
    detail: str = "normal",  # NEW: "summary", "normal", or "full"
) -> str:
    """Get calendar events. detail controls response verbosity:
    summary (time blocks only), normal (default, capped attendees/notes),
    full (all fields, no truncation)."""

async def search_calendar_events(
    query: str,
    start_date: str = "",
    end_date: str = "",
    calendar_name: str = "",
    provider_preference: str = "auto",
    detail: str = "normal",  # NEW
) -> str:
```

### Implementation

#### New file: `connectors/event_filters.py`

Pure utility functions. All return new dicts (never mutate input).

```python
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

def prioritize_attendees(
    attendees: list[str | dict],
    organizer: str | None,
    user_email: str | None,
    limit: int = 5,
) -> tuple[list[str], int]:
    """Normalize attendees to emails, prioritize, and cap.

    Returns (prioritized_email_list, total_count).
    Handles both M365 string lists and Apple attendee object lists.
    """

def truncate_notes(notes: str | None, max_length: int = 200) -> str | None:
    """Truncate notes to max_length characters.

    If truncated, final 3 chars are '...' (so content is max_length-3 chars).
    Returns None if input is None. Returns as-is if within limit.
    """
```

#### Modified: `mcp_tools/calendar_tools.py`

- `get_calendar_events`: add `detail: str = "normal"` parameter. After receiving full events from the unified connector, apply `filter_event_fields(event, detail, user_email=config.USER_EMAIL)` to each event before returning.
- `search_calendar_events`: same treatment.
- `find_my_open_slots` and `find_group_availability`: after receiving full events from the unified connector, apply `filter_event_fields(event, "summary")` to each event before passing to availability analysis. The connector is NOT modified — filtering always happens at the MCP tool layer.

#### Modified: agent callers

The meeting prep agent (`agent_configs/meeting_prep.yaml`) currently calls `get_calendar_events` via the `calendar_read` capability. Since `normal` is the new default and meeting prep needs full attendee lists and notes, its system prompt should instruct it to pass `detail="full"` when calling calendar tools. No YAML schema change needed — the parameter is passed through the tool call.

#### Not modified

- `connectors/calendar_unified.py` — always returns full events; filtering is at the MCP tool layer
- `connectors/providers/apple_provider.py`, `connectors/providers/m365_provider.py`, `connectors/claude_m365_bridge.py` — untouched
- No database or schema changes

### Testing

- **Unit tests for `connectors/event_filters.py`:**
  - `filter_event_fields` returns correct field sets for `summary` tier
  - `filter_event_fields` returns correct field sets for `normal` tier
  - `filter_event_fields` with `detail="full"` returns shallow copy of full event
  - `filter_event_fields` with invalid detail raises `ValueError("detail must be one of: 'summary', 'normal', 'full'")`
  - `filter_event_fields` sets `showAs`/`responseStatus` to `null` for Apple events in `normal` tier
  - `prioritize_attendees` puts organizer first, user second, sorts rest alphabetically, caps at limit
  - `prioritize_attendees` handles M365 string attendees
  - `prioritize_attendees` handles Apple object attendees (extracts emails)
  - `prioritize_attendees` handles missing organizer (skips to user)
  - `prioritize_attendees` handles missing user email
  - `prioritize_attendees` handles empty attendee list → returns `([], 0)`
  - `prioritize_attendees` with fewer than limit returns all without truncation
  - `truncate_notes` with text > 200 chars returns 197 chars + `...`
  - `truncate_notes` with text exactly 200 chars returns as-is
  - `truncate_notes` with text < 200 chars returns as-is
  - `truncate_notes` with `None` returns `None`
  - `truncate_notes` with empty string returns empty string
- **Integration tests in `tests/test_calendar_tools.py`:**
  - `get_calendar_events` with default detail returns `normal`-tier fields
  - `get_calendar_events` with `detail="summary"` returns only summary fields
  - `get_calendar_events` with `detail="full"` returns all provider-native fields
  - `find_my_open_slots` results do not contain attendee arrays or full notes
  - Mixed-provider results: M365 events have `showAs`; Apple events have `showAs: null`
  - Events with no attendees: `attendees: []`, `attendee_count: 0`

### Estimated Impact

| Tier | Avg bytes/event | 50-event response | Reduction |
|------|----------------|-------------------|-----------|
| `summary` | ~175 | ~9 KB | ~94% |
| `normal` | ~500 | ~25 KB | ~82% |
| `full` | ~2,850 | ~143 KB | 0% |

With `normal` as default, the 107 historical calls would drop from ~3.9MB to ~0.7MB in tool response data. Factoring in context replay (3-5x multiplier), estimated token savings: **~800K-1.3M input tokens (~$2.40-$3.90 on Sonnet).**

### Migration

No breaking changes. Existing callers that don't pass `detail` get `normal` (smaller responses). Callers that need full data add `detail="full"`. The parameter is optional with a sensible default.
