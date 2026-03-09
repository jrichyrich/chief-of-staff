# Chunk Audit: mcp-tool-handler

**User-facing feature**: Calendar availability analysis (find_my_open_slots MCP tool)
**Risk Level**: High
**Files Audited**:
- `/Users/jasricha/Documents/GitHub/chief_of_staff/mcp_tools/calendar_tools.py` (465 lines, focus on lines 263-371)
- `/Users/jasricha/Documents/GitHub/chief_of_staff/scheduler/availability.py` (501 lines, downstream dependency)
- `/Users/jasricha/Documents/GitHub/chief_of_staff/connectors/calendar_unified.py` (491 lines, upstream dependency)
- `/Users/jasricha/Documents/GitHub/chief_of_staff/mcp_tools/decorators.py` (38 lines, error handling wrapper)
**Status**: Complete

## Purpose (as understood from reading the code)

`find_my_open_slots` is an MCP tool handler that orchestrates calendar availability analysis. It fetches events from all configured calendar providers (Apple + M365), checks for provider errors/partial failures, then delegates to `find_available_slots()` in the availability engine to compute open time slots within working hours. The availability engine normalizes heterogeneous event formats, classifies events as soft/hard blocks, and computes gaps. Results are returned as JSON with raw slots, formatted text, and count.

No divergence from intent map description.

## Runtime Probe Results

- **Tests found**: Yes
- **Tests run**: 37 passed (test_mcp_calendar.py), 38 passed (test_scheduler.py) -- 75 total, 0 failed
- **Import/load check**: OK (py_compile passes for both files)
- **Type check**: Not applicable (no mypy/pyright configured in project)
- **Edge case probes**: Skipped -- side effects (calendar store interaction). Pure functions in availability.py covered by test_scheduler.py.
- **Key observation**: `find_my_open_slots` has only 4 tests (3 async + 1 registration check). The availability engine (`find_available_slots`) has 38 thorough tests. The gap is in the MCP tool handler layer -- error handling, input validation, and the handoff between the two layers.

## Dimension Assessments

### Implemented

All functions are fully implemented with real logic. No stubs, no TODOs, no empty bodies.

- `find_my_open_slots` (calendar_tools.py:265-371): Complete implementation
- `find_available_slots` (availability.py:219-439): Complete, thorough implementation
- `classify_event_softness` (availability.py:128-216): Complete
- `normalize_event_for_scheduler` (availability.py:13-125): Complete
- `format_slots_for_sharing` (availability.py:442-501): Complete
- `find_group_availability` (calendar_tools.py:373-453): Implemented as a guidance-only tool (returns instructions, not results). This is intentional per the docstring.

### Correct

The core logic is correct for the happy path and the tested error paths. However, there are correctness issues in edge cases:

**1. user_email not passed to availability engine (calendar_tools.py:352)**

`find_my_open_slots` calls `find_available_slots()` without passing `user_email`. The availability engine's `classify_event_softness()` accepts `user_email` to scope tentative-status checks to only the user's response. Without it, if ANY attendee on a meeting has status "tentative", the entire event is classified as soft/available -- even if the user accepted and intends to attend. This inflates available slots.

In `find_available_slots` (availability.py:289), `user_email` defaults to `None`, which causes `classify_event_softness` (availability.py:185-186) to check ALL attendees instead of just the user.

**2. Error payload check only inspects events[0] (calendar_tools.py:329)**

The error check `events[0].get("error")` only catches errors when the first element is an error dict. However, examining the upstream `_read_from_providers` (calendar_unified.py:205-245), this is actually **not a real bug in practice** because:
- When `require_all_success=False`, the unified service separates errors from rows internally and only returns rows (or errors if no rows). Errors are never mixed with valid events.
- The `events[0].get("error")` pattern matches the dual-read error envelope format (a single-element list with the error dict).

The availability engine also has a secondary defense at availability.py:278-283 that filters out any dict with an `"error"` key from the events list before processing.

**3. Working hours parse has no input validation (calendar_tools.py:305-306)**

`working_hours_start.split(":")` will raise `ValueError` on malformed input like "abc" or "25:00". The `@tool_errors` decorator catches `ValueError` (via `_EXPECTED`), so this surfaces as a user-friendly error, but the error message would be cryptic (e.g., "Calendar error: not enough values to unpack").

### Efficient

No significant inefficiencies. The availability engine iterates events once per day in range, which is appropriate. Event normalization is O(n) per event. No N+1 queries or unnecessary re-computation.

One minor note: `find_my_open_slots` calls `calendar_store.get_events()` directly (not through `_retry_on_transient`), unlike all other read tools in the same file (e.g., `get_calendar_events` at line 89 uses `_retry_on_transient`). This means transient SQLite/OS errors during the event fetch are not retried.

### Robust

**Error handling strengths:**
- `@tool_errors` decorator provides a consistent safety net for all exceptions
- The error payload check at line 329 handles provider partial failures gracefully
- The availability engine filters error payloads at line 278-283 as a secondary defense
- The availability engine handles missing start/end times, unparseable datetimes, naive datetimes, zero-duration events, and cancelled events

**Error handling gaps:**

1. **No retry on transient errors** (calendar_tools.py:322-326): `get_events()` is called directly on the calendar store without `_retry_on_transient`. Every other read tool in this file wraps the store call with `_retry_on_transient`. If the SQLite ownership DB has a brief lock contention (`sqlite3.OperationalError`), this call fails immediately rather than retrying.

2. **No observability into fetched events** (calendar_tools.py:322-371): The tool does not log how many events were fetched, from which providers, or what was passed to the availability engine. When availability results are wrong, there is no way to diagnose whether the issue was in event fetching or slot computation without adding debug logging.

3. **duration_minutes=0 or negative** (calendar_tools.py:268): No validation. `duration_minutes=0` would return every gap regardless of size. `duration_minutes=-1` would return all gaps. The availability engine simply checks `gap_duration >= duration_minutes` (availability.py:425), so negative values pass through.

4. **start_date after end_date**: No validation at the MCP tool level. The availability engine would produce an empty result (the while loop at line 298 wouldn't execute), which is arguably correct but gives no diagnostic feedback to the user.

### Architecture

**Strengths:**
- Clean separation: MCP tool handler (data fetch + error handling) vs. availability engine (pure computation)
- The availability engine is well-structured with normalize -> classify -> compute gaps pipeline
- Event normalization handles both Apple and M365 formats defensively
- The `@tool_errors` decorator eliminates boilerplate try/except in every handler

**Concerns:**

1. **`find_my_open_slots` is 107 lines** (265-371) -- on the edge of "doing too many things". It handles: working hours parsing, soft keywords parsing, event fetching, error payload inspection, partial result extraction, slot computation, and formatting. The error handling block (lines 328-349) could be extracted into a helper.

2. **Hardcoded timezone "America/Denver"** (calendar_tools.py:359, 365): The timezone is hardcoded in two places within the function body, not as a configurable parameter or config constant. While the function signature documents it, a user in a different timezone has no way to change it without modifying code. Other tools in this file don't have this limitation.

3. **No `block_ooo_all_day` parameter exposed**: The availability engine supports `block_ooo_all_day` (availability.py:230, 253) but the MCP tool doesn't expose it. This means PTO/OOO all-day events are always skipped, and the tool may report the user as available on vacation days.

## Findings

### Critical

- **calendar_tools.py:352** -- `user_email` not passed to `find_available_slots()` -- When `include_soft_blocks=True` (the default), tentative status checks scan ALL attendees. If colleague Bob is tentative on a meeting that the user accepted, the meeting is incorrectly classified as soft/available. This causes the tool to report the user as free during meetings they plan to attend. The `user_email` parameter exists on `find_available_slots` and `classify_event_softness` but is never populated from the MCP layer.

### Warning

- **calendar_tools.py:322** -- No `_retry_on_transient` wrapper on `calendar_store.get_events()` -- Every other read tool in this file (`list_calendars`, `get_calendar_events`, `search_calendar_events`) wraps store calls with `_retry_on_transient`. This tool calls the store directly, making it vulnerable to transient SQLite lock contention that the other tools handle gracefully.

- **calendar_tools.py:268** -- No validation on `duration_minutes` -- Values of 0 or negative are silently accepted. Zero returns every micro-gap; negative values return all gaps. Should reject `duration_minutes < 1`.

- **calendar_tools.py:359,365** -- Hardcoded timezone `"America/Denver"` -- Not configurable by the user or via config.py. A user in a different timezone gets incorrect availability windows. Should be a parameter with a config-backed default.

- **calendar_tools.py:265-371** -- `block_ooo_all_day` not exposed as MCP parameter -- The availability engine supports blocking entire days for PTO/OOO events, but the MCP tool always passes the default (`False`). Users on vacation will be reported as having a full day of open slots.

### Note

- The error payload check at line 329 (`events[0].get("error")`) appears fragile at first glance, but is actually safe because the upstream `_read_from_providers` never mixes errors into the events list when `require_all_success=False`. The availability engine also has a secondary filter. The defense-in-depth is adequate, though the pattern is not self-documenting.

- No observability logging between event fetch and slot computation. Adding a `logger.info("find_my_open_slots: fetched %d events from %s", len(events), provider_preference)` would significantly improve debuggability.

- The `find_group_availability` tool (lines 373-453) is a guidance-only tool that returns JSON instructions rather than executing anything. This is intentional but could confuse automated consumers that expect actual availability data.

- Tests for `find_my_open_slots` cover basic happy path, error-with-partial, and error-without-partial. Missing test cases: soft block classification, custom working hours, custom soft keywords, duration_minutes edge cases, multi-day ranges, and the user_email gap.

## Verdict

The `find_my_open_slots` tool handler is functional and handles the primary happy path and provider failure scenarios correctly. The availability engine it delegates to is well-tested (38 tests) and robust. However, the MCP tool layer has one critical gap: `user_email` is never passed to the availability engine, causing incorrect soft-block classification when other attendees are tentative. There are also several medium-severity gaps: missing retry wrapper (inconsistent with sibling tools), no input validation on `duration_minutes`, hardcoded timezone, and unexposed `block_ooo_all_day`. The most impactful fix is wiring `user_email` through -- the availability engine already supports it, it just needs the MCP tool to provide it.
