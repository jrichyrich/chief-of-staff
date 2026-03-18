# Direct Graph API Calendar Write with Attendees & Recurrence

**Date**: 2026-03-18
**Status**: Draft
**Scope**: Add calendar write capabilities (attendees, recurrence) via direct Microsoft Graph API, replacing the Claude M365 Bridge for calendar operations.

## Problem

The current calendar write path goes through `ClaudeM365Bridge`, which invokes a Claude CLI subprocess to proxy Graph API calls. This is:
- **Slow**: 100–300ms per call due to subprocess overhead
- **Limited**: No attendee or recurrence support in the prompt templates
- **Fragile**: Prompt-dependent — changes in Claude's M365 connector behavior can break operations

Meanwhile, `GraphClient` already handles Teams and Mail via direct httpx calls to Graph API. Calendar should follow the same pattern.

## Requirements

- Create calendar events with attendees (internal CHG employees) that send standard Exchange meeting invites
- Create recurring events (daily, weekly, monthly, yearly patterns)
- Update existing events to add/modify attendees and recurrence
- Route calendar writes through direct Graph API, not the Claude CLI bridge
- Backward compatibility: bridge hooks still work if GraphClient is unavailable

## Non-Goals

- Apple Calendar attendee support (EventKit attendees are read-only for our purposes)
- External attendee invites (internal CHG only)
- Online meeting/Teams link generation (future enhancement)
- Calendar read migration off the bridge (separate effort)

## Design

### 1. Scope & Auth

Add `Calendars.ReadWrite` to both scope lists:

- `M365_GRAPH_SCOPES` in `config.py` (runtime scopes passed to GraphClient)
- `_DEFAULT_SCOPES` in `connectors/graph_client.py` (fallback if no explicit scopes)

```python
# config.py
M365_GRAPH_SCOPES = [
    "Calendars.ReadWrite",   # NEW
    "Channel.ReadBasic.All",
    "ChannelMessage.Send",
    # ... existing scopes
]
```

One-time re-auth required: `python scripts/bootstrap_secrets.py --reauth`

### 2. GraphClient Calendar Methods

Add to `connectors/graph_client.py`, following the existing Teams/Mail pattern:

```python
async def list_calendars(self) -> list[dict]:
    """GET /me/calendars → list of {id, name, color, isDefaultCalendar}"""

async def get_calendar_events(
    self, start: str, end: str, calendar_id: str | None = None
) -> list[dict]:
    """GET /me/calendarView?startDateTime=&endDateTime=
    Returns events with attendees, recurrence, location, body."""

async def create_calendar_event(
    self,
    subject: str,
    start: str,           # ISO datetime
    end: str,             # ISO datetime
    timezone: str = "America/Denver",
    attendees: list[dict] | None = None,
    recurrence: dict | None = None,
    calendar_id: str | None = None,
    location: str | None = None,
    body: str | None = None,
    is_all_day: bool = False,
    reminder_minutes: int | None = 15,
) -> dict:
    """POST /me/events (or /me/calendars/{id}/events)
    Sends standard Exchange invite to all attendees."""

async def update_calendar_event(
    self, event_id: str, **kwargs
) -> dict:
    """PATCH /me/events/{id}
    Partial update — only sends fields that changed."""

async def delete_calendar_event(self, event_id: str) -> dict:
    """DELETE /me/events/{id}"""
```

#### Calendar ID Resolution

The MCP tool accepts `calendar_name` (human-readable, e.g. "CHG") but Graph API needs a calendar ID for `POST /me/calendars/{id}/events`. Strategy:

- On first use, call `GET /me/calendars` and cache the name→ID mapping for the session
- Match `calendar_name` case-insensitively against Graph calendar `name` field
- If no match or no `calendar_name` specified, use `POST /me/events` (default calendar)
- Cache lives on the GraphClient instance (cleared on reconnect)

#### All-Day Event Datetime Handling

Graph API requires different datetime formats for all-day vs timed events:
- **Timed**: `{"dateTime": "2026-03-20T09:00:00", "timeZone": "America/Denver"}`
- **All-day**: `{"dateTime": "2026-03-20", "timeZone": "UTC"}`

A private helper `_format_event_datetime(dt_str: str, timezone: str, is_all_day: bool) -> dict` handles this conversion.

#### Graph API Response Normalization

Graph API returns different field names than the internal event dict format. GraphClient methods normalize responses before returning:

| Graph API field | Internal field |
|----------------|---------------|
| `subject` | `title` |
| `id` | `uid` |
| `start.dateTime` | `start` (ISO string) |
| `end.dateTime` | `end` (ISO string) |
| `location.displayName` | `location` |
| `body.content` | `notes` |
| `isAllDay` | `is_all_day` |
| `attendees[].emailAddress.address` | `attendees[]` (email strings for read compat) |
| `showAs` | `showAs` |
| `isCancelled` | `isCancelled` |
| `responseStatus.response` | `responseStatus` |
| `recurrence` | `recurrence` (passed through as-is) |

A private helper `_normalize_event(graph_event: dict) -> dict` handles this. This ensures the unified calendar service's ownership tracking, tagging, and deduplication work correctly.

#### Attendee Update Semantics

When updating attendees via `PATCH /me/events/{id}`, Graph API **replaces the entire attendee list**. This means:
- Omitting `attendees` from an update leaves existing attendees unchanged
- Providing `attendees` replaces all existing attendees — removed attendees receive cancellation notices
- The MCP tool docstring must clearly state this is a **full replacement**, not a delta

#### Attendee Input Format

Simplified input accepted by GraphClient methods:

```python
[
    {"email": "shawn.farnworth@chghealthcare.com", "name": "Shawn Farnworth", "type": "required"},
    {"email": "heather.allen@chghealthcare.com", "name": "Heather Allen", "type": "optional"},
]
```

Converted internally to Graph API format:

```json
{
    "attendees": [
        {
            "emailAddress": {"address": "shawn.farnworth@chghealthcare.com", "name": "Shawn Farnworth"},
            "type": "required"
        }
    ]
}
```

Default `type` is `"required"` if omitted.

#### Recurrence Input Format

Simplified input:

```python
{
    "type": "weekly",              # daily | weekly | absoluteMonthly | relativeMonthly | absoluteYearly | relativeYearly
    "interval": 1,                 # every N periods
    "days_of_week": ["tuesday"],   # for weekly type
    "day_of_month": 15,            # for absoluteMonthly/absoluteYearly
    "month": 3,                    # for yearly types
    "end_date": "2026-12-31",      # optional: end by date
    "occurrences": 10,             # optional: end after N occurrences (mutually exclusive with end_date)
}
```

Converted internally to Graph API `recurrence` object with `pattern` and `range`.

Conversion logic lives in a private helper `_build_recurrence_payload(recurrence: dict) -> dict` inside `graph_client.py`.

### 3. Sync/Async Strategy: Dual Path in MCP Tool Handlers

**Critical context**: The existing provider layer (`CalendarProvider`, `UnifiedCalendarService`, `Microsoft365CalendarProvider`) is entirely **synchronous**. The MCP tool handlers are `async def` running on the event loop. `GraphClient` methods are `async def`. You **cannot** call `run_until_complete()` from within a running event loop — it raises `RuntimeError`.

**Strategy**: Dual path in the MCP tool handlers. When `state.graph_client` is available and the target is M365, call GraphClient directly from the async MCP tool handler, bypassing the sync provider chain entirely. Fall back to the sync provider chain (via `_retry_on_transient` → `UnifiedCalendarService`) when GraphClient is unavailable or the target is Apple.

```python
# In mcp_tools/calendar_tools.py — create_calendar_event handler
async def create_calendar_event(...):
    # Parse attendees/recurrence JSON...

    # Dual path: Graph direct (async) vs provider chain (sync)
    use_graph = (
        state.graph_client
        and (attendees_list or recurrence_dict or target_provider == "microsoft_365"
             or _looks_work_calendar(calendar_name))
    )

    if use_graph:
        result = await state.graph_client.create_calendar_event(
            subject=title, start=start_date, end=end_date,
            attendees=attendees_list, recurrence=recurrence_dict,
            location=location, body=notes, is_all_day=is_all_day,
            calendar_id=resolved_calendar_id,
        )
        # Track ownership in unified calendar service
        calendar_store.track_ownership(result["uid"], "microsoft_365", ...)
        return result
    else:
        # Existing sync path — no attendee/recurrence support
        return _retry_on_transient(lambda: calendar_store.create_event(...))
```

**Why this is the right approach**:
- MCP tool handlers are already the async boundary — calling `await graph_client.method()` is natural
- No changes to the sync provider chain — it continues to work for Apple and bridge fallback
- The provider chain refactor to async can happen later as a separate effort
- Attendees/recurrence only work via Graph anyway, so the dual path matches the capability split

**The M365 provider still gets `graph_client` wired in** (Section 4) for cases where code calls the provider directly (e.g., daemon/autonomous paths that may become async in the future), but the primary interactive path goes MCP tool → GraphClient directly.

### 4. Rewire M365 Calendar Provider

Update `connectors/providers/m365_provider.py` to store `graph_client` for future async callers:

```python
class Microsoft365CalendarProvider(CalendarProvider):
    def __init__(self, graph_client=None, **bridge_hooks):
        self._graph = graph_client  # Stored for future async callers
        # Keep bridge hooks for sync path
        self._list_calendars_fn = bridge_hooks.get("list_calendars_fn")
        # ... etc

    def create_event(self, title, start_dt, end_dt, calendar_name=None,
                     location=None, notes=None, is_all_day=False,
                     alarms=None, attendees=None, recurrence=None):
        # Note: The primary Graph path is handled at the MCP tool layer (Section 3).
        # This sync method is the bridge fallback path.
        if self._create_event_fn:
            return self._create_event_fn(
                title=title, start_dt=start_dt, end_dt=end_dt,
                calendar_name=calendar_name, location=location,
                notes=notes, is_all_day=is_all_day,
            )
        else:
            return {"error": "No M365 calendar backend available"}
```

The provider accepts `attendees` and `recurrence` in its signature (Section 5) but the bridge fallback ignores them — those features only work via the direct Graph path in the MCP tool handler.

### 5. Update Signatures Across Provider Chain

The `attendees` and `recurrence` parameters must be added explicitly to method signatures — not passed as `**kwargs` — because the provider chain uses fixed signatures.

**Files requiring signature updates:**

1. **`connectors/provider_base.py`** — `CalendarProvider.create_event()` and `update_event()` abstract methods: add `attendees=None, recurrence=None` as optional parameters
2. **`connectors/calendar_unified.py`** — `UnifiedCalendarService.create_event()` and `update_event()`: add `attendees=None, recurrence=None`, pass through to provider calls
3. **`connectors/providers/apple_provider.py`** — `AppleCalendarProvider.create_event()` and `update_event()`: add `attendees=None, recurrence=None` to match the abstract signature, but **ignore them** (Apple EventKit attendees are out of scope)
4. **`connectors/providers/m365_provider.py`** — as shown in Section 4 above

This is a cascading signature change but low risk — the new params are all optional with `None` defaults, so existing callers are unaffected.

### 6. Update MCP Tools

`mcp_tools/calendar_tools.py` — add two parameters:

```python
@mcp.tool()
async def create_calendar_event(
    title: str,
    start_date: str,
    end_date: str,
    calendar_name: str = "",
    location: str = "",
    notes: str = "",
    is_all_day: bool = False,
    alerts: str = "",
    attendees: str = "",       # NEW — JSON array
    recurrence: str = "",      # NEW — JSON object
    target_provider: str = "",
    provider_preference: str = "auto",
) -> dict:
```

**`attendees`**: JSON string — `'[{"email": "user@chg.com", "name": "User Name"}]'`
- Validate: must be a JSON array of objects, each with at least `email`
- Default `name` to email prefix if omitted
- Default `type` to `"required"` if omitted

**`recurrence`**: JSON string — `'{"type": "weekly", "interval": 1, "days_of_week": ["tuesday"], "end_date": "2026-12-31"}'`
- Validate: `type` is required, must be one of the six Graph recurrence types
- Validate: `end_date` or `occurrences` (not both)
- Validate: `days_of_week` required for weekly, `day_of_month` required for absoluteMonthly/absoluteYearly

Same additions for `update_calendar_event`.

**Auto-routing**: When `attendees` is provided and no `target_provider` is set, automatically route to `microsoft_365` (attendee invites are an Exchange concept).

### 7. Wiring in mcp_server.py

In the lifespan initialization:

```python
# When building Microsoft365CalendarProvider, pass graph_client
m365_cal_provider = Microsoft365CalendarProvider(
    graph_client=_state.graph_client,  # NEW — direct Graph
    list_calendars_fn=bridge.list_calendars,  # fallback
    get_events_fn=bridge.get_events,
    create_event_fn=bridge.create_event,
    # ...
)
```

### 8. Testing Strategy

| Test Area | Approach |
|-----------|----------|
| GraphClient calendar methods | Mock httpx responses, verify request payloads match Graph API spec |
| Attendee format conversion | Unit test: simplified input → Graph `attendees[]` payload |
| Recurrence format conversion | Unit test: simplified input → Graph `recurrence.pattern` + `recurrence.range` |
| MCP tool JSON parsing | Unit test: valid/invalid JSON strings for attendees and recurrence |
| Provider routing | Unit test: graph_client present → uses it; absent → falls back to bridge |
| Auto-routing with attendees | Unit test: attendees provided + no target_provider → routes to M365 |
| Response normalization | Unit test: Graph API response → internal event dict format |
| Calendar ID resolution | Unit test: name→ID cache lookup, default calendar fallback |
| All-day datetime format | Unit test: timed vs all-day datetime conversion |
| Attendee update semantics | Unit test: verify full replacement behavior, cancellation on removal |
| Invite sending | Verify no `sendInvitations: false` is set — default invite behavior confirmed |
| End-to-end MCP → Graph | Integration test: mocked GraphClient, verify full flow |

## File Changes

| File | Change |
|------|--------|
| `config.py` | Add `Calendars.ReadWrite` to `M365_GRAPH_SCOPES` |
| `connectors/graph_client.py` | Add calendar methods, response normalization, attendee/recurrence/datetime helpers, `_DEFAULT_SCOPES` update |
| `connectors/provider_base.py` | Add `attendees=None, recurrence=None` to abstract `create_event`/`update_event` |
| `connectors/providers/m365_provider.py` | Accept `graph_client`, prefer over bridge hooks, sync→async bridge |
| `connectors/providers/apple_provider.py` | Add `attendees=None, recurrence=None` to signatures (ignored) |
| `connectors/calendar_unified.py` | Add `attendees`/`recurrence` to `create_event`/`update_event` signatures, pass through |
| `mcp_tools/calendar_tools.py` | Add `attendees` and `recurrence` parameters, auto-routing logic |
| `mcp_server.py` | Wire `graph_client` into M365 calendar provider |
| `tests/test_graph_calendar.py` | New — GraphClient calendar methods, response normalization, datetime handling |
| `tests/test_calendar_attendees.py` | New — attendee/recurrence parsing, format conversion, routing, update semantics |

## Migration

1. Deploy code changes
2. Run `bootstrap_secrets.py --reauth` to acquire token with `Calendars.ReadWrite` scope
3. Verify with a test event creation (with attendee)
4. Bridge hooks remain as fallback — no breaking changes
