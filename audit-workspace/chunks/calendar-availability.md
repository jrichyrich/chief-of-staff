# Chunk Audit: Calendar & Availability

**User-facing feature**: Calendar CRUD (create/read/update/delete events), event search, open slot finding, group availability scheduling
**Risk Level**: High
**Files Audited**:
- `apple_calendar/__init__.py` (empty)
- `apple_calendar/eventkit.py` (422 lines)
- `connectors/__init__.py` (7 lines)
- `connectors/calendar_unified.py` (571 lines)
- `connectors/claude_m365_bridge.py` (482 lines)
- `connectors/graph_client.py` (1118 lines)
- `connectors/provider_base.py` (68 lines)
- `connectors/router.py` (140 lines)
- `connectors/providers/__init__.py` (6 lines)
- `connectors/providers/apple_provider.py` (132 lines)
- `connectors/providers/m365_provider.py` (211 lines)
- `mcp_tools/calendar_tools.py` (987 lines)
- `scheduler/availability.py` (694 lines)
- `scheduler/slot_ranker.py` (231 lines)

**Status**: Complete

## Purpose (as understood from reading the code)

This chunk implements a unified dual-provider calendar system (Apple EventKit + Microsoft 365) accessible through MCP tools. It provides full calendar CRUD, event search, and availability analysis (open slots, group scheduling) behind a routing layer that selects providers based on connectivity and user preference, with ownership tracking in SQLite.

The code matches the stated intent with one architectural wrinkle: there are **two active M365 write paths** — a legacy `ClaudeM365Bridge` subprocess path and a newer `GraphClient` async path. Both coexist and are selected by conditional logic at the tool layer.

## Runtime Probe Results

- **Tests found**: Yes — 15 test files covering this chunk
- **Tests run**: 229 passed, 0 failed (all relevant test files executed)
- **Import/load check**: All 14 files pass `py_compile` syntax check
- **Type check**: Not applicable — mypy not installed in this environment
- **Edge case probes**: Run on `find_available_slots`, `_parse_preferred_range`, `_score_buffer`, OOO logic, empty uid upsert
- **Key observation**: `_parse_preferred_range("25:00-26:00")` raises an unhandled `ValueError` — a user-supplied string from the `schedule_meeting` or `find_group_availability` tools crashes the process. Also confirmed: `AppleCalendarProvider.is_connected()` always returns `True` regardless of EventKit availability.

## Dimension Assessments

### Implemented

All declared functions exist with real logic. Every `CalendarProvider` abstract method is implemented in both `AppleCalendarProvider` and `Microsoft365CalendarProvider`. The `UnifiedCalendarService` orchestrates routing, deduplication, and ownership tracking. Availability analysis (`find_available_slots`, `find_mutual_availability`, `format_slots_for_sharing`) and slot ranking (`rank_slots`) are fully implemented.

No stubs or TODOs found. The `pass` statements in `graph_client.py` are in exception handlers (`except Exception: pass`) in the SSL context builder, not in business logic.

`ClaudeM365Bridge` does not implement `attendees` or `recurrence` on `create_event` — this is consistent with the comment "Bridge fallback ignores attendees/recurrence — Graph path is at MCP tool layer" but is a silent capability gap with no warning when the bridge path is taken.

### Correct

**Main happy path traces correctly.** Read flow: `get_calendar_events` → `UnifiedCalendarService.get_events` → `_read_from_providers` → per-provider `get_events` → tag → dedupe → ownership upsert → return. Write flow: `create_calendar_event` either dispatches to `GraphClient.create_calendar_event` (async, when attendees/recurrence/work calendar detected) or falls back to the sync `UnifiedCalendarService.create_event` chain.

**Bug confirmed**: `connectors/graph_client.py:1040-1041` — `update_calendar_event` patches `graph_recurrence["range"]["startDate"]` only when `"start" in kwargs`. If a caller updates recurrence without changing the start date (a normal use case: "change this weekly meeting to biweekly"), `startDate` remains `""` (empty string). The Graph API will reject this with a 400. Confirmed by reading `_build_recurrence_payload` which sets `"startDate": ""` as placeholder.

**Bug confirmed**: `scheduler/slot_ranker.py:128-132` — `_parse_preferred_range` with a custom time range such as `"25:00-26:00"` raises an uncaught `ValueError: hour must be in 0..23`. This propagates through `rank_slots` in `find_group_availability` and `schedule_meeting`. User-supplied `preferred_times` is never sanitized before this call.

**Warning**: `connectors/providers/apple_provider.py:19` — `is_connected()` unconditionally returns `True`. On non-macOS or when PyObjC is absent, every `get_events` call returns `[{"error": "EventKit is only available on macOS..."}]`. The router includes Apple in read decisions, the error propagates as a read failure, and with `require_all_read_providers_success=True` (default), a single-provider M365 setup that happens to have an `AppleCalendarProvider` wired up will return a dual-read policy error instead of M365 data.

**Warning**: `connectors/router.py:135-140` and `mcp_tools/calendar_tools.py:98-104` — two independent implementations of `_looks_work_calendar` with divergent keyword lists. The router version omits `"chg"` (the company name), meaning the routing layer does not recognize CHG-branded calendars as work calendars, even though the tool layer does. This creates a routing inconsistency: the tool dispatches to Graph but the ownership/routing DB may record the wrong provider.

**Note**: `mcp_tools/calendar_tools.py:239` — when using the Graph path for `create_calendar_event`, only the first alarm is forwarded: `reminder_minutes=alarms[0] if alarms else 15`. Multiple alarms are silently dropped. This is not a crash but is a silent data loss for users who specify multiple alerts.

**Note**: `mcp_tools/calendar_tools.py:506` — `working_hours_start.split(":")` with `map(int, ...)` has no error handling. A user passing `"8am"` or `"8:00:00"` will get an unhandled `ValueError`. The `@tool_errors` decorator wraps this, so it surfaces as an error response rather than a crash, but the error message will be generic.

### Efficient

**N+1 on calendar name resolution**: `connectors/graph_client.py:944-949` — `resolve_calendar_id` lazily builds its cache on first call, but the cache is per-session and not shared across requests. In a long-running MCP server, this is fine (cached after first call). No N+1 issues in the availability loop.

**In-memory event processing**: `find_available_slots` normalizes and classifies every event for every day in the range. For large date ranges with many events, this is O(days × events). Acceptable at typical calendar scale but could be slow for month-spanning queries with 200+ events.

**`_tag_event` triggers `list_calendars` lazily**: `connectors/providers/apple_provider.py:122-124` — if `_calendar_source_map` is empty when events are fetched, `_tag_event` calls `list_calendars()` on every event until the map is populated. This means the first event in a fresh result set triggers a full calendar list refresh. Subsequent events in the same batch use the now-populated map. Not an N+1 for a single batch, but it's a hidden side-effectful call inside a tagging function.

### Robust

**No timeout on EventKit access request**: `apple_calendar/eventkit.py:117` — `granted_flag.wait(timeout=30)` caps the wait at 30 seconds. If the OS does not respond (e.g., in a headless/daemon context), `_request_access` returns `False` after 30s. Acceptable.

**Exception swallowing in identity/Graph resolution**: `mcp_tools/calendar_tools.py:646-663` — bare `except Exception: pass` in `_resolve_participant_emails` silently discards identity store and Graph user resolution errors. A DB connection failure looks identical to "user not found."

**Graph 401 retry clears ALL cached accounts**: `connectors/graph_client.py:454-456` — on a 401, all MSAL accounts are removed before re-authenticating. In a multi-account scenario (unlikely but possible), this discards all other cached tokens. In the single-account case it is correct.

**`_parse_output_json` and fallback chain in bridge**: `connectors/claude_m365_bridge.py:351-408` — `_invoke_structured` has a three-level fallback: `structured_output` → `result` text field → raw stdout regex extraction. The fallback warnings are logged, but callers receive the extracted data without knowing parsing fell through. This is intentionally defensive but can mask systematic Claude output format regressions.

**No input validation on `working_hours_start/end`** in `find_my_open_slots` and `find_group_availability`: the `split(":")` + `map(int, ...)` pattern is used without a try/except. The `@tool_errors` decorator catches it, so it will not crash the server, but the user receives a generic error.

**`_parse_preferred_range` crash on invalid custom range**: Confirmed above — unhandled `ValueError` on invalid hour values. The `@tool_errors` decorator at the tool layer catches this, but if `rank_slots` is called directly from library code (e.g., scheduled tasks), the exception propagates uncaught.

### Architecture

**Dual write path complexity**: The `create_calendar_event` and `update_calendar_event` tools contain an explicit `use_graph` branch that bypasses the `UnifiedCalendarService` entirely, calling `state.graph_client` directly. The ownership tracking in the Graph path calls `calendar_store._upsert_ownership(...)` as an internal method (prefixed `_`). This tightly couples the tool layer to the service's internal implementation. The Graph path is also missing the fallback behavior the sync path provides.

**Duplicated `_looks_work_calendar`**: Logic exists independently in `connectors/router.py:135-140` and `mcp_tools/calendar_tools.py:98-104`. These are the divergent keyword lists noted above. The router should be the single source of truth.

**`ClaudeM365Bridge` subprocess architecture**: Spawning a full Claude CLI subprocess to make an M365 API call is architecturally unusual — it adds process spawn overhead, JSON parsing of LLM output, and a multi-level fallback chain. The newer `GraphClient` path eliminates this, but the bridge remains in use for the sync fallback path. There is no documentation of the intended migration timeline.

**`AppleCalendarProvider.is_connected()` hardcoded to `True`**: Forces the router to always believe Apple is available. A proper implementation would check `_EVENTKIT_AVAILABLE` and the authorization status. This makes the router's connection-aware routing logic ineffective for the Apple provider.

**Test coverage is solid** for unit paths. Integration tests for the dual-write path (Graph + ownership tracking) are not present in the reviewed test files — the Graph path in `calendar_tools.py` line 224-255 is exercised only via `test_graph_calendar.py` which was not in the reviewed set.

## Findings

### 🔴 Critical

- **`connectors/graph_client.py:1040-1041`** — `update_calendar_event` leaves `recurrence.range.startDate` as `""` when recurrence is updated without also changing the start date. The Graph API requires a valid `startDate` in the recurrence range. Any call to update a recurring event's pattern (e.g., change interval, add/remove days) without explicitly passing `start_date` will generate a Graph 400 error. The user sees a cryptic API failure with no actionable message.

- **`scheduler/slot_ranker.py:128-132`** — `_parse_preferred_range` raises an unhandled `ValueError` on custom time ranges with out-of-range hours (e.g., `"25:00-26:00"`). This crashes `rank_slots`, which is called by `find_group_availability` and `schedule_meeting`. The `@tool_errors` decorator at the MCP layer catches it, preventing a server crash, but returns a generic error with no hint that the `preferred_times` parameter caused the issue. A malformed but plausible-looking input `"9:00-17:00"` works fine while `"08:00-18:00"` with single-digit hours also works, making this a subtle failure mode.

### 🟡 Warning

- **`connectors/providers/apple_provider.py:19`** — `is_connected()` always returns `True`. On non-macOS environments or when PyObjC is absent, the router treats Apple as connected, includes it in multi-provider reads, and the resulting error dict causes a dual-read policy failure, blocking M365 data from being returned. Should check `_EVENTKIT_AVAILABLE` and current authorization status before claiming connectivity.

- **`connectors/router.py:139` vs `mcp_tools/calendar_tools.py:103`** — Two independent `_looks_work_calendar` implementations with divergent keyword lists. The router omits `"chg"` while the tool layer includes it. A calendar named "CHG Calendar" routes correctly at the tool layer (dispatched to Graph) but the router's ownership/routing logic does not recognize it as a work calendar. Consolidate into a single function in `connectors/router.py`.

- **`mcp_tools/calendar_tools.py:239`** — When using the Graph path for `create_calendar_event`, multiple alarms are silently truncated to the first one: `reminder_minutes=alarms[0] if alarms else 15`. Users who pass `alerts='[5,15,30]'` will only get the 5-minute reminder. No warning is returned.

- **`mcp_tools/calendar_tools.py:506` and `mcp_tools/calendar_tools.py:730-733`** — `working_hours_start.split(":")` with bare `map(int, ...)` has no input validation. Inputs like `"8am"`, `"8:00:00"`, or `"8"` raise `ValueError`. The `@tool_errors` decorator catches it at the MCP layer but the user receives an opaque error with no indication which parameter was invalid.

- **`mcp_tools/calendar_tools.py:244-252`** — The Graph create path calls `calendar_store._upsert_ownership(...)` — a private method, bypassing the service's public interface. This is fragile: renaming or refactoring the internal method breaks the tool without a compiler warning.

- **`connectors/claude_m365_bridge.py:270-300`** — `create_event` via the bridge silently ignores `attendees` and `recurrence` parameters even though the `CalendarProvider` interface accepts them. The M365 provider constructor accepts these hooks but the bridge's `create_event` does not pass them through. A caller who uses the bridge path (not the Graph path) will create an event without attendees or recurrence, with no error.

### 🟢 Note

- `scheduler/availability.py:517-521` — `tz_abbr` is set inside a `for slot in date_slots` loop but used outside it (`lines.append(...tz_abbr)`). If `date_slots` somehow became empty (structurally impossible since the outer dict is built from non-empty slot lists), this would be a `NameError`. Not a practical bug but a fragile pattern.

- `format_slots_for_sharing` uses `%-I` format for 12-hour time (removes zero-padding). This works on Linux/macOS but raises `ValueError` on Windows. Not a concern for this macOS-targeted system but worth noting.

- `connectors/graph_client.py:629-630` — `resolve_user_email` escapes single quotes by doubling (`''`), which is a basic OData injection defense. More robust would be to use `$search` or `startsWith` rather than an exact `eq` filter.

- `connectors/graph_client.py:944-949` — `resolve_calendar_id` session cache is never invalidated. If a calendar is renamed or created after the first call, the stale cache will be used for the rest of the MCP session.

- The `ClaudeM365Bridge._sanitize_for_prompt` method (line 72-85) provides reasonable prompt-injection mitigation for the subprocess LLM path. The use of `<user_*>` XML tags and the `_BRIDGE_SYSTEM_PROMPT` with explicit injection instructions is a good defense-in-depth pattern.

- All 229 tests pass cleanly, with solid coverage of routing decisions, deduplication, provider connectivity refresh, mutual availability, and slot ranking.

## Verdict

The chunk is largely working and well-tested. The most dangerous confirmed bug is in `GraphClient.update_calendar_event`: updating a recurring event's recurrence pattern without simultaneously passing a start date sends an empty `startDate` to the Graph API, causing a silent 400 failure. The second confirmed crash is `_parse_preferred_range` raising `ValueError` on invalid custom time ranges, though this is caught by the tool error decorator.

The architectural concern with the highest operational risk is `AppleCalendarProvider.is_connected()` always returning `True`: on any system where EventKit is absent or auth is denied, the dual-read policy will fail closed (returning an error) rather than failing over to M365 data. The duplicated `_looks_work_calendar` with divergent keyword lists is a maintenance hazard that will cause subtle routing bugs as the organization's calendar naming evolves.
