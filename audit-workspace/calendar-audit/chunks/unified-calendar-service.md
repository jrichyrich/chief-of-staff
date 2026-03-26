# Chunk Audit: unified-calendar-service

**User-facing feature**: Transparent multi-provider calendar access, event ownership tracking, cross-provider dedup
**Risk Level**: High
**Files Audited**: `connectors/calendar_unified.py` (567 lines)
**Status**: Complete

## Purpose (as understood from reading the code)

`UnifiedCalendarService` is a facade that routes calendar CRUD operations across Apple and Microsoft 365 providers, with a SQLite-backed event ownership database for tracking which provider owns each event. It deduplicates events that appear on both providers (via iCal UID or title+start+end fallback), preferring the M365 version for richer metadata. Consistent with the intent map description -- no divergence.

## Runtime Probe Results

- **Tests found**: Yes -- `tests/test_calendar_unified.py`
- **Tests run**: 21 passed, 0 failed
- **Import/load check**: OK
- **Type check**: Not run (mypy/pyright not installed in active environment)
- **Edge case probes**: Ran on `_event_dedupe_key`, `_is_error_payload`, `_provider_from_prefixed_uid`, `_filter_source`, `_tag_event`
- **Key observation**: `str(None)` produces `"None"` in dedupe keys and tag fields, causing collision between actual None values and literal "None" strings. Events with all-None fields produce key `('fallback', 'none', 'None', 'None')` which would collide with events having literal string `"None"` as title. Low practical risk but technically incorrect.

## Dimension Assessments

### Implemented

All functions listed in the intent map exist with real logic:
- `UnifiedCalendarService` class: lines 14-567
- `_read_from_providers`: lines 180-261 -- core shared read loop
- `_resolve_write_provider`: lines 407-451 -- multi-strategy provider resolution for writes
- `_dedupe_events`: lines 285-297 -- cross-provider deduplication
- `_upsert_ownership` / `_batch_upsert_ownership` / `_lookup_ownership` / `_delete_ownership`: lines 56-125 -- SQLite ownership CRUD
- `list_calendars`, `get_events`, `get_events_with_routing`, `search_events`: read operations (lines 310-405)
- `create_event`, `update_event`, `delete_event`: write operations (lines 453-567)

No stubs, no TODOs, no raise NotImplementedError. Every function has substantive logic.

### Correct

The core logic is sound. The read loop, dedup, ownership tracking, and write-with-fallback all trace correctly through happy paths.

Specific observations:

1. **`get_events_with_routing` calls `decide_read` twice** (line 361 and again inside `_read_from_providers` at line 201). The routing decision is computed once explicitly to build `routing_info`, then again internally when `_read_from_providers` is called. These two calls should produce the same result (deterministic), but it is wasted work and a latent correctness risk if `decide_read` ever becomes stateful.

2. **`str(None)` used in dedupe keys** (`_event_dedupe_key` lines 271-273): `str(event.get("title", ""))` when `title` is explicitly `None` produces `"None"` not `""`. This means an event with `title=None` and an event with `title="None"` produce identical keys. Low practical risk since calendar events with literal title "None" are vanishingly rare.

3. **`_tag_event` lines 130-131**: `str(tagged.get("native_id", "") or tagged.get("uid", ""))` -- the `or` operates on the result of `get("native_id", "")`. If `native_id` is falsy (empty string), it falls through to `uid`. But if `native_id` is explicitly `0` or `False`, it also falls through, which may not be intended. For string IDs this is fine in practice.

4. **Ownership tracking happens after dedup and filtering** (line 255-256 in `_read_from_providers`): This is correct -- only surviving (non-duplicate) events get ownership records, avoiding stale entries.

5. **`_is_error_payload` treats `{"error": ""}` as non-error** (line 145): Empty string is falsy, so `bool(payload.get("error"))` returns `False`. This is arguably correct since an empty error string is ambiguous, but could mask edge cases from providers that set `error=""`.

### Efficient

1. **Double `decide_read` in `get_events_with_routing`** (lines 361 + 201 via `_read_from_providers`): Minor -- two lightweight in-memory calls. Not a real perf concern.

2. **`_batch_upsert_ownership` iterates one-by-one** (line 90-91): Uses a single connection but individual `INSERT OR REPLACE` per event rather than `executemany`. For typical calendar result sets (10-50 events), this is negligible. At scale (hundreds of events), a single `executemany` would be faster.

3. **Dedup uses a dict scan** (lines 286-296): O(n) with dict lookups -- appropriate for calendar event volumes.

No genuine efficiency concerns for production scale.

### Robust

1. **Broad exception catch in read loop** (line 230): `except Exception` catches everything from provider calls, logs with `logger.exception`, and continues to the next provider. This is intentional for fault tolerance -- a provider crash shouldn't take down the entire read. The exception is logged, not silently swallowed.

2. **No timeout on provider calls** (line 229): `fetch_fn(provider)` has no timeout wrapper. If a provider (especially the M365 bridge which does subprocess calls) hangs, the entire read operation blocks indefinitely. The M365 bridge has its own timeout, but the unified service has no defense against a provider that ignores its own timeout.

3. **SQLite connection management**: `_open_ownership_db` (line 29) opens a new connection per call. The `busy_timeout=30000` (30 seconds) is set. The `with` context manager in most methods ensures connections are closed. However, `_upsert_ownership` (line 56) manually manages connection lifecycle in the `own_conn` path -- this is correct but more fragile than always using `with`.

4. **No validation of `provider_preference` or `target_provider`**: Invalid values like `"foobar"` silently normalize to empty string via `normalize_provider_name`, which then falls through to the default/auto path. This is safe behavior but makes typos invisible.

5. **`_lookup_ownership` double-query pattern** (lines 106-124): First looks up by `unified_uid`, then falls back to `native_id`. The fallback query could match the wrong event if two different events share a `native_id` across providers (unlikely but not impossible). The `ORDER BY updated_at_utc DESC LIMIT 1` mitigates this somewhat.

### Architecture

1. **Clean facade pattern**: The class is a well-structured facade over the provider router and ownership DB. Read and write paths are cleanly separated.

2. **`_read_from_providers` is a good abstraction** (lines 180-261): All four read operations delegate to this shared method via lambda `fetch_fn`, eliminating duplication. The boolean flags (`tag_events`, `dedupe_events`, `track_ownership`) control behavior per caller.

3. **Ownership DB is tightly coupled to this class**: The SQLite schema, connection management, and queries are all inside `UnifiedCalendarService`. For a single-use ownership tracker this is fine, but if ownership queries are needed elsewhere, this would need extraction.

4. **No interface/protocol for the service itself**: Callers depend directly on the concrete `UnifiedCalendarService` class. For the current two-provider architecture, this is adequate.

5. **`get_events_with_routing` duplicates logic**: It calls `decide_read` explicitly and then `_read_from_providers` calls it again. The routing metadata assembly (lines 372-386) could be integrated into `_read_from_providers` as an optional return, avoiding the duplication.

6. **Testability is good**: The constructor accepts a `ProviderRouter` and a DB path, making it easy to inject fakes. The test file confirms this with `_FakeProvider` and `tmp_path`.

## Findings

### Critical

None.

### Warning

- **[calendar_unified.py:361]** -- `get_events_with_routing` calls `self.router.decide_read()` at line 361, then `_read_from_providers` calls it again at line 201. If `decide_read` ever becomes non-deterministic (e.g., health-check based routing), the routing metadata returned could diverge from the actual providers used. Recommend passing the decision object into `_read_from_providers` or having it return routing metadata.

- **[calendar_unified.py:229]** -- No timeout protection on `fetch_fn(provider)` calls inside the read loop. A hung provider blocks the entire operation. The broad `except Exception` on line 230 only catches raised exceptions, not hangs. Consider wrapping with `concurrent.futures` timeout or similar.

- **[calendar_unified.py:269-277]** -- `_event_dedupe_key` uses `str()` on potentially-None values (`str(event.get("title", ""))` when title is explicitly `None`). Produces `"none"` / `"None"` strings that could theoretically collide with real values. Use `(event.get("title") or "")` instead of `str(event.get("title", ""))` for safety.

### Note

- **[calendar_unified.py:56-83]** -- `_upsert_ownership` has two code paths: one using a passed-in connection, one opening/closing its own. The `_batch_upsert_ownership` method correctly uses the shared-connection path. Consider always requiring a connection parameter to simplify.

- **[calendar_unified.py:90-91]** -- `_batch_upsert_ownership` iterates with individual `_upsert_ownership` calls rather than using `executemany`. Adequate for calendar volumes but suboptimal for large batches.

- **[calendar_unified.py:145]** -- `_is_error_payload` treats `{"error": ""}` as non-error due to falsy empty string. This matches the apparent convention but could mask edge cases.

- Test coverage is solid at 21 tests covering dedup, routing, fallback, dual-read policy, and ownership. No tests cover `delete_event` or `search_events` through the service (only via `_FakeProvider` indirectly).

### Nothing to flag

Efficiency and architecture dimensions are clean. The facade pattern is well-executed, the code is readable, and the separation of concerns between routing policy (router.py) and orchestration (calendar_unified.py) is sound.

## Verdict

This chunk is complete, well-tested, and architecturally sound. The dual-provider facade with ownership tracking and deduplication works correctly for all tested paths. The two warnings worth addressing are: (1) the double `decide_read` call in `get_events_with_routing` which creates a latent divergence risk, and (2) the lack of timeout protection on provider calls in the read loop. The `str(None)` collision in dedupe keys is a minor correctness nit. Overall, this is production-quality code with good test coverage.
