# Chunk Audit: Webhooks & Events

**User-facing feature**: Webhook event processing, event rule management
**Risk Level**: Medium
**Files Audited**:
- `webhook/__init__.py` (empty)
- `webhook/dispatcher.py` (278 lines)
- `webhook/ingest.py` (224 lines)
- `webhook/receiver.py` (35 lines)
- `mcp_tools/webhook_tools.py` (114 lines)
- `mcp_tools/event_rule_tools.py` (215 lines)
**Status**: Complete

## Purpose (as understood from reading the code)

This chunk handles file-drop inbox ingestion of webhook events (JSON files dropped into a directory), stores them in SQLite, and dispatches them to matching expert agents based on event rules. The MCP tools expose CRUD for event rules and manual dispatch triggers, while the dispatcher handles the async fan-out with parallel agent execution and optional result delivery.

No divergence from the stated intent map description.

## Runtime Probe Results

- **Tests found**: Yes — `tests/test_webhook_tools.py`, `tests/test_webhook_ingest.py`, `tests/test_event_rule_tools.py`
- **Tests run**: 53 passed, 0 failed (1.79s)
- **Import/load check**: FAILED — `webhook.dispatcher` fails to import directly due to `agents.triage` depending on `anthropic` module (not installed in the default Python env). Imports succeed via pytest because it uses the project's venv.
- **Type check**: mypy not available in PATH
- **Edge case probes**: Skipped — all public functions write to DB or invoke agents (side effects)
- **Key observation**: No-matching-rules behavior is inconsistent between the daemon path (`dispatch_pending_events`) and the MCP tool path (`dispatch_webhook_event`): the daemon leaves events `pending` indefinitely, while the MCP tool marks them `processed`. This is a state divergence that would cause events to pile up in the daemon path.

## Dimension Assessments

### Implemented

All declared features exist with real logic:
- `EventDispatcher.dispatch()` with parallel/sequential modes and semaphore-based concurrency cap
- `ingest_events()` with debounce, file locking, processed/failed dirs
- `dispatch_pending_events()` for daemon-driven batch dispatch
- Full CRUD for event rules: `create_event_rule`, `update_event_rule`, `delete_event_rule`, `list_event_rules`
- Manual dispatch: `dispatch_webhook_event` (MCP tool)
- Backward-compat alias: `process_webhook_event_with_agents = dispatch_webhook_event`

No stubs, TODOs, or unfulfilled markers found.

### Correct

**Main happy path is correct.** One confirmed logic bug and one behavioral inconsistency:

1. **`agent_had_error` check always evaluates `False` at runtime** (`dispatcher.py:190`):
   ```python
   agent_had_error = hasattr(result_text, "is_error") and result_text.is_error
   ```
   `agent.execute()` returns `AgentResult`, which is a `str` subclass with `.is_error` as a `@property`. `hasattr(result_text, "is_error")` will return `True`, but `.is_error` returns `True` only for non-success statuses (`loop_detected`, `max_rounds_reached`). The logic structure is actually correct here — this is fine. However, `overall_status` on line 217 calls `getattr(result_text, "status", "error")`, which returns an `AgentResultStatus` enum value (`"loop_detected"` or `"max_rounds_reached"`), not `"error"`. The upstream caller in `dispatch_pending_events` checks `r["status"] == "success"` — so enum string values other than `"success"` will correctly trigger `failed`. No confirmed bug here.

2. **No-matching-rules status divergence** (`ingest.py:61-63` vs `event_rule_tools.py:191-192`):
   - `dispatch_pending_events`: when 0 rules match, marks `counts["skipped"]` and leaves event `status=pending`
   - `dispatch_webhook_event` (MCP tool): when 0 rules match, marks event `status=processed`
   The daemon will therefore re-dispatch events with no matching rules on every tick, accumulating forever. This is a behavioral bug.

3. **`update_event_rule` cannot clear `delivery_channel`** (`event_rule_tools.py:119`):
   ```python
   if delivery_channel:
       kwargs["delivery_channel"] = delivery_channel
   ```
   Once a `delivery_channel` is set on a rule, there is no way to remove it via `update_event_rule`. Passing `delivery_channel=""` is silently ignored. The only way to clear it is to delete and recreate the rule.

### Efficient

`match_event_rules` in `webhook_store.py:164-173` calls `list_event_rules(enabled_only=True)` which executes a full `SELECT * FROM event_rules` query, then filters in Python. This is called once per event during dispatch. For batch dispatch of N pending events via `dispatch_pending_events`, this is N separate full-table scans with no DB-side filtering by `event_source`. There are no indices on `event_rules(event_source)` or `webhook_events(status)`. At low event volumes this is acceptable, but under any meaningful load (hundreds of events) this becomes a hot path. Not critical for current usage, but worth noting.

### Robust

1. **`ingest_events` lock file not cleaned up on crash** (`ingest.py:101-107`): The lock file `.ingest.lock` is created with `open(lock_file, "w")` before the `try/except BlockingIOError` block. If the process is killed between `open()` and `finally: lf.close()`, the lock file remains on disk. On the next run, `flock()` will succeed (the file descriptor is gone), so this is not a deadlock. However, the lock file accumulates. Low-severity.

2. **`ingest_events` store failure leaves file in inbox without counting as failed** (`ingest.py:163-165`):
   ```python
   except Exception as exc:
       logger.error("Failed to store event from %s: %s", filepath.name, exc)
       counts["failed"] += 1
   ```
   The file is NOT moved to `failed/` on store errors (only `failed += 1`). The file stays in the inbox and will be retried on the next ingest run. This is arguably the correct behavior (retry on transient DB errors), but it is not documented and differs from the parse/validation failure path which moves files to `failed/`. If the DB error is permanent, the file will loop forever.

3. **120-second agent timeout in `_dispatch_single` is per-rule, not per-event** (`dispatcher.py:183`). A single event matching 50 rules with `max_concurrent=5` could run for `(50/5) * 120 = 1200 seconds` (20 minutes). This is within expected async behavior but could cause daemon tick overlap.

4. **`delivery_fn` is called synchronously inside an async context** (`dispatcher.py:204-210`): The delivery function (`deliver_result`) is called as a regular synchronous call from an async method without `asyncio.to_thread`. If the delivery function blocks (e.g., sending email via SMTP), it will block the event loop.

5. **Delivery failures do not prevent the event from being marked `processed`** in `dispatch_pending_events` (`ingest.py:54-56`): `all_success` checks `r["status"] == "success"`, but `dispatch_single` returns `overall_status = "delivery_failed"` on delivery errors — so the event will be marked `WebhookStatus.failed`, not `processed`. This is actually correct and consistent.

### Architecture

1. **`delivery.service` import path vs docstring mismatch**: `dispatcher.py:41` documents that delivery defaults to `scheduler.delivery.deliver_result`, but the actual import at line 56 is `from delivery.service import deliver_result`. The function lives in a `delivery/` package, not `scheduler/delivery.py`. The comment is stale (likely from a refactor) — not a runtime bug, but a misleading docstring.

2. **`webhook/receiver.py` duplicates `webhook/ingest.py` `__main__` block** (`receiver.py:21-31`): The `__main__` block in `ingest.py:204-224` and the `main()` in `receiver.py` are nearly identical — both create a `MemoryStore`, call `ingest_events`, and print results. Two entry points for the same operation with different logging setup (receiver uses `stream=sys.stderr`, ingest uses both file and stderr).

3. **`process_webhook_event` in `webhook_tools.py` vs `dispatch_webhook_event` in `event_rule_tools.py` name collision**: Both are MCP tools. `process_webhook_event` (webhook_tools.py:89) merely marks an event as processed — no agent dispatch. `dispatch_webhook_event` (event_rule_tools.py:163) triggers agent dispatch. The names do not communicate this distinction well. The backward-compat alias `process_webhook_event_with_agents` exists but adds to the confusion.

4. **Hardcoded 50-rule fan-out cap in dispatcher** (`dispatcher.py:82`): `max_rules = 50` is hardcoded with no config knob. This should be in `config.py` alongside `MAX_CONCURRENT_AGENT_DISPATCHES`.

5. **`agents.triage.classify_and_resolve` is imported at module load time** (`dispatcher.py:19`): This causes the entire `anthropic` SDK to be required at import, even in tests. This is why the direct import check failed — the module is not importable without the Anthropic SDK. Fine in production, but makes the module harder to test in isolation.

## Findings

### 🔴 Critical

- **`webhook/ingest.py:61-63` and `mcp_tools/event_rule_tools.py:191-192`** — No-matching-rules status divergence: daemon path leaves events `pending` forever (they will be re-dispatched every tick indefinitely), while the MCP tool marks them `processed`. In a system where new event rules are added after events arrive, this means the daemon will fire agents for old events that were already handled. At minimum, the daemon should mark unmatched events as `processed` after N attempts or implement a `no_match` terminal state.

### 🟡 Warning

- **`mcp_tools/event_rule_tools.py:119`** — `update_event_rule` silently ignores `delivery_channel=""`. Once a delivery channel is set on a rule, it cannot be removed. Users will be confused when passing an empty string to clear the field has no effect.

- **`webhook/dispatcher.py:204`** — `deliver_result` called synchronously in an async context without `asyncio.to_thread`. If delivery blocks (e.g., SMTP), it blocks the asyncio event loop during agent dispatch. Could cause cascading timeouts under load.

- **`webhook/ingest.py:163-165`** — Store failures leave the source file in the inbox without moving it to `failed/`. On a permanent DB error, the file loops forever. Should either move to `failed/` after N attempts or document the retry-only intent explicitly.

- **`webhook/dispatcher.py:82`** — `max_rules = 50` hardcoded, not in `config.py`. Inconsistent with `MAX_CONCURRENT_AGENT_DISPATCHES` which is config-driven.

### 🟢 Note

- `webhook/__init__.py` is empty (no exports). Module discovery relies on direct submodule imports. Acceptable but no public API surface is declared.
- `webhook/receiver.py` duplicates the `__main__` block in `webhook/ingest.py`. One of them should be removed or they should share a common `main()`.
- `dispatcher.py:41` docstring says delivery defaults to `scheduler.delivery.deliver_result`, but the actual import is `delivery.service.deliver_result`. Stale comment from a refactor.
- The 50-rule fan-out cap log message correctly uses `len(matched_rules)` — well done.
- `_format_input` uses `Template.safe_substitute` (not `substitute`), so unknown template variables silently pass through rather than raising `KeyError`. Good defensive choice.
- The debounce logic in `ingest_events` (skip files modified < 2s ago) is a sound guard against partial writes.

## Verdict

The chunk is functionally complete and all 53 tests pass. The most important issue is the **no-matching-rules status divergence** between daemon dispatch (`dispatch_pending_events`) and the MCP tool (`dispatch_webhook_event`): the daemon path will accumulate and re-dispatch unmatched pending events indefinitely, which is both a correctness bug and a potential performance/cost issue as the event backlog grows. Secondary concerns are the inability to clear `delivery_channel` via update, and the synchronous delivery call inside the async dispatch loop. Everything else is low-severity.
