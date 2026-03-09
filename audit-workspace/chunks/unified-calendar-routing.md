# Chunk Audit: unified-calendar-routing

**User-facing feature**: Multi-provider calendar reads (Apple Calendar + Microsoft 365)
**Risk Level**: High
**Files Audited**:
- `/Users/jasricha/Documents/GitHub/chief_of_staff/connectors/calendar_unified.py` (490 lines)
- `/Users/jasricha/Documents/GitHub/chief_of_staff/connectors/router.py` (140 lines)

**Status**: Complete

## Purpose (as understood from reading the code)

`UnifiedCalendarService` is a facade that reads/writes calendar events across Apple Calendar and Microsoft 365 providers. For reads, it queries both providers, merges results, deduplicates events (by iCal UID or title+start+end fallback), tracks event ownership in a SQLite DB, and enforces a "dual-read policy" that can optionally require all providers to succeed. For writes, it resolves which provider owns an event (via prefixed UID, ownership DB lookup, or work-calendar heuristic) and falls back to the next provider on failure.

`ProviderRouter` handles provider selection policy: which providers to query for reads, which to target for writes, and alias normalization.

No divergence from the intent map description.

## Runtime Probe Results

- **Tests found**: Yes — `tests/test_calendar_unified.py`
- **Tests run**: 9 passed, 0 failed
- **Import/load check**: OK (both files compile cleanly)
- **Type check**: Not run (mypy/pyright not available in env)
- **Edge case probes**: Skipped — all public methods have side effects (DB writes, provider calls)
- **Key observation**: No runtime issues detected. All 9 tests pass covering core read merge, dedup, dual-read enforcement, write fallback, ownership resolution, alarm passthrough, and `require_all_success` parameter.

## Dimension Assessments

### Implemented

All declared functionality is implemented with real logic:

- **Read path**: `list_calendars`, `get_events`, `search_events` — all delegate to `_read_from_providers` with appropriate flags
- **Write path**: `create_event`, `update_event`, `delete_event` — all use `_resolve_write_provider` with fallback chain
- **Deduplication**: `_event_dedupe_key` (iCal UID preferred, title+start+end fallback) and `_dedupe_events`
- **Ownership tracking**: Full CRUD on `event_ownership` SQLite table
- **Provider routing**: `decide_read`, `decide_write` with alias normalization, connected-provider checks, work-calendar heuristic
- **Error detection**: `_is_error_payload` checks both dict and list[dict] error payloads
- **Dual-read policy**: `_build_dual_read_error` with partial results and provider detail

No stubs, TODOs, or dead code found.

### Correct

The core logic is correct. The `find_my_open_slots` caller passes `require_all_success=False` and the code correctly separates error payloads from valid events — error payloads go to the `errors` list, valid events go to `rows`. When `rows` is non-empty, rows are returned without error contamination. This was the primary concern raised in the assignment, and it works correctly.

**Confirmed correct behaviors:**
1. `require_all_success=False` with one provider failing returns only the successful provider's events (tested)
2. `require_all_success=True` (default) with one provider failing returns a single error dict with `partial_results` (tested)
3. Dedup first-writer-wins: M365 always comes first in provider iteration order (`decide_read` returns `["microsoft_365", "apple"]`), so M365's version of a duplicate event is kept. This is intentional — M365 is the primary work calendar.
4. Ownership DB correctly tracks provider+native_id for write routing.

**Suspected issue — dedup fragility with time format mismatch (see Warning below).**

### Efficient

Clean. No N+1 queries. Ownership upserts use `_batch_upsert_ownership` with a single DB connection for all events. Dedup is O(n) with dict lookup. Provider iteration is bounded to 2 providers max.

One minor note: `_open_ownership_db()` creates a new SQLite connection per call rather than reusing a connection pool, but given the low frequency of calendar operations this is not a real concern.

### Robust

**Error isolation is good**: Each provider call is wrapped in try/except (line 214), so one provider throwing an exception doesn't crash the whole read. The `busy_timeout=30000` on the ownership DB prevents SQLite locking issues.

**Ownership `_upsert_ownership`**: Correctly short-circuits if any of `unified_uid`, `provider`, or `native_id` is empty (line 61). Connection management is correct — caller-owned connections aren't closed in the finally block.

**Missing validation**: No validation that `start_dt < end_dt` in `get_events`/`search_events`. Both are passed straight through to providers. Not a bug in this layer (providers should validate), but a defense-in-depth gap.

### Architecture

Well-structured. Clear separation of concerns:
- `ProviderRouter` handles policy decisions (which providers, in what order)
- `UnifiedCalendarService` handles orchestration (call providers, merge, dedup, ownership)
- `CalendarProvider` ABC defines the provider contract

`_read_from_providers` is a well-designed shared read loop that accepts flags for tag/dedup/ownership behavior. Write methods follow a consistent pattern.

The `_resolve_write_provider` method (lines 330-374) is the most complex function at ~45 lines but each branch is a clear priority cascade (explicit target > prefixed UID > ownership lookup > default routing).

## Findings

### 🟡 Warning

- **`calendar_unified.py:248-255`** — **Dedup fallback key is fragile across providers**. When no `ical_uid` is present, dedup falls back to `(title, start, end)`. If Apple and M365 return the same event with different time string formats (e.g., `2026-02-16T09:00:00` vs `2026-02-16T09:00:00-07:00` vs `2026-02-16T16:00:00Z`), the fallback key won't match and the event appears twice. The `start` and `end` values are compared as raw strings with no datetime normalization. In practice, this matters when one provider returns timezone-aware strings and the other returns naive strings. This is mitigated when `ical_uid` is present (M365 events typically have one), but Apple Calendar events may not always propagate `ical_uid` through the provider layer.

- **`router.py:63-67`** — **Explicit provider preference still returns both providers for reads**. When `provider_preference="microsoft_365"`, `decide_read` returns `["microsoft_365", "apple"]`, meaning Apple events are included too. Combined with `require_all_success=True` (the default), this means asking for M365 events can fail if Apple is down. The `source_filter` parameter mitigates this for filtering results, but doesn't prevent the dual-read enforcement failure. Callers who want M365-only reads must pass both `provider_preference="microsoft_365"` AND `require_all_success=False` to avoid Apple failures blocking results.

- **`calendar_unified.py:146-147`** — **`_is_error_payload` only checks `payload[0]`**. If a provider returns a list where the first element is an error dict but subsequent elements are valid events, the entire response is treated as an error. Conversely, if the first element is valid but later elements contain errors, the errors silently become event rows. This is unlikely with current providers but is a latent correctness issue if provider behavior changes.

### 🟢 Note

- **Test coverage gap — no test for dedup with `ical_uid`**. The existing dedup test (`test_get_events_auto_merges_and_dedupes`) relies on title+start+end fallback matching. There's no test verifying that two events with the same `ical_uid` but different titles/times are correctly deduped, nor a test showing the `ical_uid` path vs the fallback path.

- **Test coverage gap — no test for `search_events`**. The `_FakeProvider` implements `search_events` but no test exercises `UnifiedCalendarService.search_events`. It uses the same `_read_from_providers` path so it's implicitly covered, but explicit coverage would catch regressions.

- **Test coverage gap — no test for `delete_event`**. No test verifies that `delete_event` correctly resolves ownership, calls the right provider, and cleans up the ownership DB.

- **Test coverage gap — no router tests**. `ProviderRouter` has no dedicated test file. Its behavior is tested indirectly through `UnifiedCalendarService` tests, but edge cases in `decide_write` (work calendar heuristic, target unavailable fallback) are untested.

- **`calendar_unified.py:29-33`** — Ownership DB connections are opened and closed per operation. For high-frequency batch reads this is fine due to SQLite's connection overhead being ~0.1ms, but if this ever moves to a remote DB, connection pooling would be needed.

### ✅ Nothing to flag

- **Dual-read policy enforcement** is correct and well-implemented.
- **`find_my_open_slots` integration** is sound — `require_all_success=False` correctly returns partial results without error contamination.
- **Write fallback chain** works correctly — tested that M365 failure falls back to Apple with `fallback_used=True`.
- **Ownership tracking** correctly handles the full lifecycle (upsert on read/create/update, delete on delete_event).

## Verdict

This chunk is well-implemented and correct for its core use cases. The dual-read policy and `require_all_success` parameter work as designed, and the `find_my_open_slots` integration is sound — error payloads from failing providers do not leak into valid event lists. The most actionable issue is the dedup fallback key's fragility with inconsistent time string formats across providers, which could cause duplicate events when `ical_uid` is absent. The router's behavior of including both providers even with an explicit preference is a design choice that could surprise callers but is mitigated by the `require_all_success` and `source_filter` parameters. Test coverage is adequate for the happy path but has gaps around dedup edge cases, search, delete, and router-level policy decisions.
