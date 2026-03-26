# Chunk Audit: apple-calendar-backend

**User-facing feature**: Apple Calendar / iCloud calendar access (list, get, create, update, delete, search events)
**Risk Level**: Medium
**Files Audited**:
- `apple_calendar/eventkit.py` (422 lines)
- `connectors/providers/apple_provider.py` (127 lines)

**Status**: Complete

## Purpose (as understood from reading the code)

`CalendarStore` wraps macOS EventKit via PyObjC to provide calendar CRUD operations, returning plain Python dicts (never raw PyObjC objects). It handles lazy initialization, permission requests, calendar alias resolution, and event UID lookup with a fallback scan. `AppleCalendarProvider` adapts `CalendarStore` to the `CalendarProvider` ABC, tagging every returned dict with `provider`, `source_account`, `native_id`, and `unified_uid` fields for the unified calendar service to consume. No divergence from the intent map description.

## Runtime Probe Results
- **Tests found**: Yes (`tests/test_calendar_eventkit.py`)
- **Tests run**: 43 passed, 0 failed
- **Import/load check**: OK for both modules
- **Type check**: Not applicable (no mypy/pyright in project config)
- **Edge case probes**: Skipped -- all public methods have side effects (EventKit I/O)
- **Key observation**: No runtime issues detected. Test suite covers all CRUD paths, permission denial, EventKit unavailability, alias resolution, and alarm handling.

## Dimension Assessments

### Implemented

All functions declared in the intent map are implemented with real logic:

- `CalendarStore`: `__init__`, `_ensure_store`, `_request_access`, `_check_access`, `_get_calendar_by_name`, `_find_event_by_uid`, `list_calendars`, `get_events`, `create_event`, `update_event`, `delete_event`, `search_events` -- all present with non-trivial bodies.
- `AppleCalendarProvider`: `is_connected`, `list_calendars`, `get_events`, `create_event`, `update_event`, `delete_event`, `search_events`, `_contains_error`, `_tag_calendar`, `_tag_event` -- all present.
- `_event_to_dict` and `_ns_date` module-level helpers -- present and used.
- No stubs, no TODOs, no `raise NotImplementedError`.

### Correct

The happy-path logic is sound across all operations. Specific observations:

1. **`_find_event_by_uid` (eventkit.py:157-178)**: Uses `calendarItemWithIdentifier_` first, then falls back to a brute-force predicate scan over a 4-year window. The fallback uses the *internal* identifier API for the primary lookup but compares against `calendarItemExternalIdentifier()` in the scan. This is correct -- `calendarItemWithIdentifier_` takes the *internal* identifier, but the UID parameter passed in from callers originates from `calendarItemExternalIdentifier()` (set in `_event_to_dict`). This means the primary lookup at line 159 will always fail for externally-sourced UIDs, and the code will always fall through to the expensive scan. See Warning below.

2. **Alarm offset sign handling (eventkit.py:49)**: `int(abs(offset_seconds) / 60)` -- correctly converts negative seconds to positive minutes. The `abs()` is important because EventKit stores alarm offsets as negative values.

3. **`_check_access` (eventkit.py:120-133)**: When `_access_granted` is already `True`, returns `None` immediately (fast path). When `False`, re-checks via `authorizationStatusForEntityType_`. The magic numbers `3` and `4` correspond to `EKAuthorizationStatusAuthorized` and `EKAuthorizationStatusFullAccess` -- correct for iOS 17+ / macOS 14+.

4. **`AppleCalendarProvider._tag_event` (apple_provider.py:112-127)**: Lazy-refreshes `_calendar_source_map` if the calendar name is not found. This handles the case where `get_events` is called before `list_calendars`. Correct but has efficiency implications (see below).

5. **`AppleCalendarProvider.is_connected` (apple_provider.py:19-20)**: Always returns `True` regardless of actual EventKit status. This is unusual but appears intentional -- the `_ensure_store` / `_check_access` pattern in `CalendarStore` handles actual availability checks at call time rather than at connection-check time.

### Efficient

1. **`_find_event_by_uid` scan window (eventkit.py:165-166)**: The fallback scans a 4-year window (`now - 2y` to `now + 2y`). On a busy calendar this could load thousands of events into memory for a single UID lookup. This runs on every update/delete operation. For typical personal/work calendar sizes this is acceptable, but it is a linear scan.

2. **`_tag_event` lazy refresh (apple_provider.py:118)**: Calls `self.list_calendars()` (which calls EventKit) every time a calendar name is missing from the map. If many events reference an unknown calendar, this re-fetches for each event. In practice, the first call populates the map and subsequent events hit the cache, so this is a one-time cost per session.

3. **`search_events` (eventkit.py:405-422)**: Loads all events in the date range into memory, then filters by title substring client-side. EventKit's predicate API does not support title filtering natively, so this is the only option. Acceptable.

### Robust

1. **Error handling pattern is consistent**: Every public method follows `_ensure_store` -> `_check_access` -> `try/except (AttributeError, TypeError, RuntimeError)`. Errors are returned as dicts, never raised. This is clean and defensive.

2. **`_request_access` timeout (eventkit.py:117)**: `granted_flag.wait(timeout=30)` -- if the OS never calls the completion handler (e.g., permission dialog is dismissed), the method returns `False` (the default in `result`). This is correct.

3. **Alarm validation (eventkit.py:291-295, 352-356)**: Validates `isinstance(minutes, int)`, bounds `0..40320` (28 days), and caps at 10 alarms. Good input validation.

4. **No validation on `start_dt` / `end_dt`**: The code does not check that `end_dt > start_dt` or that dates are timezone-aware. `_ns_date` calls `.timestamp()` which works on both naive and aware datetimes but will interpret naive datetimes in the local timezone. This is acceptable for a macOS-only module but could produce surprising results if passed UTC datetimes without timezone info.

5. **`saveEvent_span_error_` span parameter (eventkit.py:308, 360, 383)**: Hardcoded to `0` (`EKSpanThisEvent`). This means updates/deletes to recurring events only affect the single occurrence, not the series. This is the safe default but is not configurable by the caller.

### Architecture

1. **Clean separation**: `CalendarStore` handles all PyObjC interaction. `AppleCalendarProvider` handles only tagging/normalization. Neither contains business logic or transport code.

2. **Provider interface compliance**: `AppleCalendarProvider` correctly implements all 6 abstract methods from `CalendarProvider`. The `_contains_error` helper is a sensible pattern for the dict-based error return convention.

3. **Import guard (eventkit.py:9-15)**: `try/except ImportError` for `EventKit` and `Foundation` -- correct pattern for macOS-only dependencies.

4. **`from config import CALENDAR_ALIASES` inside method (eventkit.py:142)**: Import inside `_get_calendar_by_name` avoids circular import issues but runs on every call. Since `_get_calendar_by_name` is called per-calendar-name, not in a tight loop, this is fine.

5. **No test coverage for `AppleCalendarProvider`**: The test file covers `CalendarStore` thoroughly but `AppleCalendarProvider` has no dedicated tests. The tagging logic and error propagation in the adapter layer are untested.

6. **Magic numbers**: `0` for `EKEntityTypeEvent` (eventkit.py:129, 149, 194), `3/4` for auth status (eventkit.py:130). These are EventKit constants and are documented via comments. Acceptable but named constants would improve readability.

## Findings

### Critical

None.

### Warning

- **eventkit.py:159** -- `_find_event_by_uid` calls `calendarItemWithIdentifier_(uid)` but `uid` contains an *external* identifier (from `calendarItemExternalIdentifier()` in `_event_to_dict`). The `calendarItemWithIdentifier_` method expects the *local/internal* identifier. This means the primary lookup always returns `None` for externally-sourced UIDs, and every update/delete falls through to the 4-year brute-force scan. Functional but unnecessarily slow. Fix: use `calendarItemsWithExternalIdentifier_` (returns an array) for the primary lookup, or store/pass the internal identifier alongside the external one.

- **apple_provider.py (entire file)** -- No dedicated unit tests. The `_tag_event`, `_tag_calendar`, `_contains_error`, and `is_connected` logic is only exercised indirectly through integration-level calendar_unified tests (if any). A bug in tagging (e.g., missing `unified_uid`) would not be caught by the current test suite.

- **eventkit.py:130** -- `_check_access` checks for auth statuses `3` and `4` (Authorized and FullAccess). On older macOS versions (pre-14), status `3` means Authorized and `4` does not exist. On macOS 14+, status `3` is deprecated in favor of `4` (FullAccess). The code handles both correctly, but the hardcoded integers are fragile if Apple adds new status values.

### Note

- `is_connected()` always returns `True` in `AppleCalendarProvider`. The upstream `ProviderRouter` may use this to decide whether to route to Apple. If EventKit is unavailable or permissions are denied, errors will surface at call time rather than at routing time. This is acceptable but means the router cannot pre-filter unavailable providers.

- `saveEvent_span_error_` hardcoded to span `0` (this event only). Users cannot modify recurring event series through this API. This is a safe default but limits functionality.

- The `_event_to_dict` output always uses UTC for start/end times (line 57-58: `tz=timezone.utc`). This is good for consistency but means the caller must handle timezone display.

## Verdict

This chunk is well-implemented, well-tested (43 tests, all passing), and architecturally clean. The most significant issue is the UID mismatch in `_find_event_by_uid` (line 159) where the external identifier is passed to an internal-identifier API, causing every update/delete to fall through to a brute-force scan. This is functionally correct but introduces unnecessary latency on write operations. The lack of tests for `AppleCalendarProvider` is a gap worth closing. Overall, this is solid production code with no correctness bugs found.
