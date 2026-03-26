# Chunk Audit: availability-engine

**User-facing feature**: "Find my open slots", availability sharing text
**Risk Level**: Medium
**Files Audited**: `scheduler/availability.py` (523 lines)
**Status**: Complete

## Purpose (as understood from reading the code)

Provides four pure functions for calendar availability analysis: (1) `normalize_event_for_scheduler` unifies Apple Calendar and M365 event formats into a canonical dict, (2) `classify_event_softness` tags events as soft (movable) or hard (fixed) based on keywords, showAs, and attendee response status, (3) `find_available_slots` computes free gaps in working hours across a date range by normalizing events, classifying softness, merging overlapping hard blocks, and filtering by minimum duration, (4) `format_slots_for_sharing` renders slot lists as human-readable grouped text. No divergence from the intent map description.

## Runtime Probe Results

- **Tests found**: Yes -- `tests/test_scheduler.py` (56 tests)
- **Tests run**: 56 passed, 0 failed (0.94s)
- **Import/load check**: OK
- **Type check**: Not applicable (no mypy/pyright in project)
- **Edge case probes**: All pure functions probed with empty dicts, None fields, non-dict events, 0/negative durations, reversed date ranges, reversed event times, and truthy-but-non-boolean values. All handled gracefully (no crashes). One type-safety concern noted below.
- **Key observation**: No runtime issues detected. The code is defensive and handles garbage input without crashing.

## Dimension Assessments

### Implemented

All four functions declared in the intent map are fully implemented with real logic:

- `normalize_event_for_scheduler` (lines 15-134): Complete. Handles UID, title, time (including M365 nested `{dateTime, timeZone}`), calendar, provider, all-day, showAs, cancelled (including title-based detection), response status (string and dict), attendees (Apple, M365 nested, M365 string), location (string and dict), notes/body (string and dict).
- `classify_event_softness` (lines 137-234): Complete. Checks showAs=tentative, keyword matching in title/notes, attendee tentative status (Apple numeric + M365 string), user-scoped filtering.
- `find_available_slots` (lines 237-461): Complete. Full day-by-day iteration with event filtering (cancelled, free, declined, soft), all-day OOO blocking, timezone conversion, block merging, gap computation, duration filtering.
- `format_slots_for_sharing` (lines 464-523): Complete. Groups by date, formats human-readable time ranges with timezone abbreviation.

No stubs, TODOs, or unimplemented markers found.

### Correct

The core logic is correct. Happy-path tracing confirms:

1. Events are normalized, classified, filtered, clipped to working hours, sorted, merged, and gaps extracted correctly.
2. The block-merging algorithm (lines 421-430) correctly handles overlapping and adjacent blocks.
3. The gap-computation algorithm (lines 433-442) correctly tracks `current_gap_start` advancing past block ends.
4. Cancelled/declined/free events are correctly excluded before gap computation.

**Minor correctness concerns:**

- **Lines 63, 67**: Boolean fields (`is_all_day`, `is_cancelled`) use `or` chains (`event.get("is_all_day") or event.get("isAllDay") or False`). This works because downstream checks use truthiness (`if normalized.get("is_all_day")`), but the normalized dict may contain non-boolean truthy values (e.g., string `"true"` or int `1`). Not a bug in practice, but violates the documented return type.
- **Line 517**: `tz_abbr = start_dt.strftime("%Z")` references `start_dt` from the inner loop's last iteration. Works due to Python's loop variable scoping, but would break if a date group somehow had zero slots (impossible given the outer loop guard, but fragile).
- **Lines 280-293**: `datetime.fromisoformat` accepts various formats but does not validate that `start_date`/`end_date` are date-only strings. Passing a full ISO datetime with timezone works but may produce unexpected day boundaries. This is acceptable given the documented interface.

### Efficient

Clean. No inefficiencies at production scale:

- Events are normalized once (O(n)), then iterated per day. For typical calendar usage (tens of events over days/weeks), this is negligible.
- Block sorting and merging are O(n log n) per day, which is optimal.
- No N+1 queries, no re-computation in loops, no unnecessary data loading.

### Robust

Solid defensive coding throughout:

- Non-dict events filtered (line 298-300)
- Error payload dicts filtered (line 301-303)
- Missing start/end times logged and skipped (lines 360-365)
- Unparseable datetimes caught with try/except (lines 367-375)
- Naive datetimes handled with event timezone fallback, then user timezone fallback (lines 378-397)
- Zero-duration events skipped (line 404)
- Empty slot list returns "No available slots found." (line 480)

**One gap:**

- **No validation on `duration_minutes`**: Passing 0 or negative values returns a full working day as a single slot (the gap computation doesn't care about minimum duration when `gap_duration >= 0`). The MCP tool layer (`calendar_tools.py`) does validate this (returns error for <= 0), so this is defense-in-depth missing at the engine layer, not a user-facing bug.

### Architecture

Well-structured:

- **Single responsibility**: Each function does one thing. `normalize` handles format differences, `classify` handles soft/hard logic, `find_available_slots` computes gaps, `format` handles presentation.
- **Pure functions**: All four functions are side-effect-free (only logging). Easy to test, easy to reason about.
- **No coupling to stores or transport**: Takes plain dicts and returns plain dicts. No imports from MCP framework, no database access.
- **Config dependency minimal**: Only `USER_TIMEZONE` from `config.py`, used as default parameter value.
- **`find_available_slots` is 225 lines** (lines 237-461): This is long, but the logic is inherently sequential (parse dates, normalize events, iterate days, collect blocks, merge, compute gaps, filter). Extracting sub-functions would not improve readability and would scatter the day-processing logic.
- **`_OOO_KEYWORDS` module constant** (line 12): Appropriately extracted as a module-level constant rather than hardcoded inline.

## Findings

### Critical

None.

### Warning

- **[availability.py:63,67]** -- Boolean fields use `or` chains that pass through non-boolean truthy values. `normalize_event_for_scheduler({"is_all_day": "true"})` returns `is_all_day="true"` (string) instead of `True` (bool). Works in practice because downstream checks use truthiness, but violates the documented return type and could surprise callers doing `isinstance` or `is True` checks. Fix: `is_all_day = bool(event.get("is_all_day") or event.get("isAllDay"))`.
- **[availability.py:237]** -- No input validation on `duration_minutes`. Values of 0 or negative return slots, which is semantically wrong (a 0-minute slot is not useful). The MCP layer validates this, but the engine function's contract is unclear. A `ValueError` for `duration_minutes < 1` would be clearer.

### Note

- **[availability.py:517]** -- `tz_abbr` relies on Python loop variable scoping from the inner `for slot in date_slots` loop. Correct but fragile. Moving `tz_abbr` computation inside the loop body or computing it from the timezone directly (`datetime.now(tz).strftime("%Z")`) would be more explicit.
- **No tests for `format_slots_for_sharing` with multiple timezone abbreviations** (e.g., slots spanning a DST transition). The current implementation uses the last slot's timezone abbreviation for the entire line, which could show "MDT" for a line containing a slot that falls in "MST". Edge case unlikely in practice.
- Test coverage is excellent: 56 tests covering normalization, classification, slot finding (gaps, overlaps, soft/hard, OOO, cancelled, declined, free, tentative, error payloads, multi-day), and formatting. No coverage gaps identified for the main execution paths.

### Nothing to flag

- **Efficiency**: Clean. No concerns.
- **Architecture**: Well-factored pure functions with minimal coupling. No issues.

## Verdict

This chunk is fully implemented, correct, and well-tested. The availability engine is a clean set of pure functions with strong defensive coding and 56 passing tests covering all major paths. The two warnings (boolean type safety in normalization and missing duration validation) are low-impact because the MCP tool layer provides the missing guardrails, but fixing them would improve the engine's standalone contract. No critical issues found.
