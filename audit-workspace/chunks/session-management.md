# Chunk Audit: Session Management

**User-facing feature**: Session status, context restore, brain persistence
**Risk Level**: Medium
**Files Audited**:
- `session/__init__.py`
- `session/brain.py`
- `session/context_config.py`
- `session/context_loader.py`
- `session/manager.py`
- `mcp_tools/session_tools.py`
- `mcp_tools/brain_tools.py`

**Status**: Complete

## Purpose (as understood from reading the code)

This chunk manages the Claude Code session lifecycle: it tracks in-session interactions and classifies them by keyword matching (decisions/action items/facts), flushes classified content to the SQLite memory store, loads contextual data from all sources at startup for instant `get_session_status` responses, and maintains a persistent markdown "brain" file that carries workstreams, decisions, and people context across session boundaries.

No divergence from stated purpose, though the interaction classification is keyword-based (fragile) rather than semantic.

## Runtime Probe Results

- **Tests found**: Yes — 6 test files: `test_session_brain.py`, `test_session_manager.py`, `test_session_context_integration.py`, `test_checkpoint_session.py`, `test_session_health.py`, `test_session_context_resource.py`
- **Tests run**: 140 passed, 0 failed (when run as individual suites). When combined in one `pytest` invocation with other test files, 10 tests in `test_checkpoint_session.py` fail due to `mcp_server._state` shared-singleton contamination between test modules — a test isolation issue, not a code bug.
- **Import/load check**: All 7 files compiled cleanly via `py_compile`. Module-level imports OK.
- **Type check**: mypy not installed; pyright not run. No type errors apparent from static reading.
- **Edge case probes**:
  - Workstream with multi-word status (e.g. `"in progress"`) is saved to disk correctly but **fails to round-trip through parse** — `_RE_WORKSTREAM` requires `(\S+)` (no spaces) for the status field, so the entry is silently dropped on load. Confirmed data loss.
  - Workstream names and decision summaries containing colons, and action item text containing pipes, all round-trip correctly.
  - `SessionContext.is_stale` with empty `loaded_at` correctly returns `True`.
  - `_ttl_minutes` is a private dataclass field; it is correctly excluded from `to_dict()` output.
- **Key observation**: Silent data loss when a workstream's status contains a space — written to file, silently discarded on next `load()`. No validation prevents this at write time.

## Dimension Assessments

### Implemented

All described functionality exists with real logic. No stubs or `pass`-body functions. The module exposes the full advertised API:

- `SessionBrain`: load, save, render, all mutation methods, `_parse` — all implemented
- `SessionManager`: track_interaction, estimate_tokens, extract_structured_data, flush, get_session_summary, restore_from_checkpoint — all implemented
- `load_session_context`: implemented with concurrent ThreadPoolExecutor, per-source timeout, error isolation
- MCP tools: `get_session_status`, `flush_session_memory`, `restore_session`, `refresh_session_context`, `get_session_brain`, `update_session_brain` — all implemented

One missing coverage point: `refresh_session_context` rate-limiting logic (the 30-second cooldown) has **no test**.

### Correct

The main happy paths are correct. Several logic issues identified:

1. **Silent workstream data loss on round-trip** (confirmed): `_RE_WORKSTREAM` at `brain.py:221` uses `(\S+)` for the status group, which requires a single word. `add_workstream` at `brain.py:127` has no validation. Any workstream written with a multi-word status (e.g. "in progress", "on hold", "needs review") is written correctly to disk but produces `NO MATCH` on parse and is silently dropped.

2. **`flush` priority_threshold semantics are internally inconsistent**: The docstring at `manager.py:113` only contracts that `"decisions"` flushes only decisions and `"all"` flushes everything. The actual condition at line 138 is `if priority_threshold in ("all", "action_items", "key_facts")` — meaning `"key_facts"` also triggers action_item flushing. This is undocumented and likely unintended: a caller requesting only `"key_facts"` silently also flushes action_items.

3. **Context window percentage hardcoded to 150,000**: `session_tools.py:67` computes `round(tokens / 150000, 3)`. The default model is `claude-sonnet-4-6` which has a 200,000-token context window. This percentage will read as artificially lower than reality. The value is not sourced from `config.py`.

4. **`extract_structured_data` uses first-match priority**: `manager.py:91-98` classifies each interaction by checking decision → action → fact in priority order. An interaction matching multiple patterns (e.g. "I decided we should also remember this") is classified only as a decision and is never also captured as a key_fact. Whether this is intentional or limiting depends on usage, but it is undocumented.

### Efficient

The `load_session_context` concurrent fetch design is sound — 6 sources load in parallel via `ThreadPoolExecutor` with per-source timeouts. No N+1 patterns. The `_fetch_brain_summary` in `context_loader.py:153` calls `state.session_brain.to_dict()` which returns lists (no DB hit). `get_session_brain` in `brain_tools.py:32` calls `brain.load()` on every invocation (disk read each time), but the file is small and the load is atomic — acceptable for the usage pattern.

### Robust

1. **`get_session_brain` calls `brain.load()` on every invocation** (`brain_tools.py:32`). This is correct for cross-process scenarios (another process may have updated the file), but the call signature provides no error handling around `load()`. If `locked_read` throws (e.g. OS-level lock timeout), the exception propagates unhandled out of `get_session_brain`. The save path has the same exposure: `update_session_brain` calls `brain.save()` with no try/except, so an I/O error returns an unhandled exception rather than a JSON error response.

2. **`brain_tools._state_ref` is a module-level global** (`brain_tools.py:9`). The `register()` function at line 18 overwrites it with each call. In test isolation scenarios where `register()` is called multiple times with different state instances, the last one wins. This is a known pattern in the codebase (other tool modules do the same) but it means all `get_session_brain` / `update_session_brain` calls route through whichever state was registered last.

3. **`_fetch_due_reminders` swallows exceptions from `list_reminders`** (`context_loader.py:136`): the bare `except Exception: return []` at line 138 is intentional (error isolation per the design), but other fetchers do not have this inner try/except — they rely on the outer `ThreadPoolExecutor` catch in `load_session_context`. The asymmetry is fine functionally but inconsistent in style.

4. **`restore_from_checkpoint` performs 3 separate `search_facts` calls** (`manager.py:232-234`) — one for decisions, one for actions, one for facts — all keyed on session_id prefix. These are sequential SQLite reads. No explicit timeout protection. This is acceptable at current scale.

5. **Rate-limiting in `refresh_session_context` has no test** (`session_tools.py:139-148`). The logic reads the `loaded_at` field and returns `rate_limited` if the elapsed time is under 30 seconds. This is tested nowhere, so regressions here would go undetected.

### Architecture

The chunk is cleanly layered: `session/` contains pure domain logic, `mcp_tools/` wraps it in JSON-returning async handlers. The `SessionBrain` class correctly encapsulates the markdown format details. The `SessionContext` dataclass is a clean DTO.

The one structural concern is the `_ttl_minutes` field on `SessionContext` (`context_loader.py:36`). It is a private underscore-prefixed field on a public dataclass, which is unusual — dataclasses are not designed for private fields. Constructing `SessionContext(_ttl_minutes=15)` works, but the intent (making TTL configurable per-instance) is awkward. A cleaner approach would be to pass TTL to `is_stale()` as a parameter or bake it into the loader.

The `_SECTIONS` list in `SessionBrain` at `brain.py:25` controls both render order and parse recognition. This is a single source of truth — correct. However, the render format at `brain.py:68` (`{ws['name']}: {ws['status']} - {ws['context']}`) is implicitly the contract that `_RE_WORKSTREAM` must parse. If anyone changes the render format without updating the regex (or vice versa), data silently drops. There is no test that explicitly verifies render → parse round-trips for every section type.

## Findings

### 🔴 Critical

- **`session/brain.py:221`** — `_RE_WORKSTREAM = re.compile(r"^-\s+(.+?):\s+(\S+)\s+-\s+(.+)$")` — The `(\S+)` token requires a single non-whitespace word for the workstream status. `add_workstream()` applies no validation. Any workstream saved with a status like `"in progress"`, `"on hold"`, or `"needs review"` is written to the markdown file but silently dropped on the next `load()`. The in-memory session state is gone. Confirmed via runtime probe: `add_workstream('Project', 'in progress', 'context')` → save → load → `[]`.

### 🟡 Warning

- **`session/manager.py:138`** — `flush()` priority_threshold `"key_facts"` also flushes action_items. The condition `if priority_threshold in ("all", "action_items", "key_facts")` means calling `flush(priority_threshold="key_facts")` silently includes action_items. The docstring does not mention this, and the `flush_session_memory` MCP tool advertises `"key_facts"` as a distinct option to the caller. This is a semantic contract violation.

- **`mcp_tools/session_tools.py:67`** — Context window usage percentage hardcoded to 150,000 tokens (`round(tokens / 150000, 3)`). The deployed model (`claude-sonnet-4-6`) has a 200,000-token context window. The displayed percentage will read ~25% lower than actual, causing the "should I flush?" decision heuristic to be miscalibrated. Should reference a constant from `config.py`.

- **`mcp_tools/brain_tools.py:74-78`** — `update_session_brain` calls `brain.save()` with no try/except. An I/O failure (disk full, permission error, lock timeout from `atomic_write`) raises an unhandled exception and returns a 500-style error rather than a JSON error response. Same for `brain.load()` in `get_session_brain` (line 32). All other MCP tool error paths in `session_tools.py` wrap in try/except and return `{"error": ...}`.

- **`session/brain.py`** — No test verifies the render → parse round-trip for all section types under adversarial inputs (multi-word status, colons in names, pipes in action text). The existing `test_session_brain.py` covers the public API but not the underlying regex behavior. The confirmed workstream bug (above) would have been caught by such tests.

- **`mcp_tools/session_tools.py:139-148`** — Rate-limiting logic in `refresh_session_context` (30-second cooldown) has zero test coverage. The code path exists and appears correct, but any future refactor could silently break it.

### 🟢 Note

- `session/context_loader.py:36`: `_ttl_minutes` as an underscore-prefixed field on a public dataclass is structurally awkward. The field is functional but violates typical dataclass conventions. A static field or a parameter to `is_stale()` would be cleaner.

- `mcp_tools/brain_tools.py:9`: module-level `_state_ref` global is consistent with the rest of the codebase but means the last `register()` call wins. Acceptable given the single-server deployment model.

- `session/manager.py:31`: The string `"TODO"` appears in `_ACTION_PATTERNS` as a classification keyword. This is intentional (classify "TODO: do X" as an action item), but it also means any source code snippet or literal TODO comment in a tracked interaction will be classified as an action item.

- The concurrent fetch architecture in `context_loader.py` is well-designed: per-source timeouts, isolated error handling, and clean result attribution via the `_SOURCE_FETCHERS` dispatch table.

## Verdict

The chunk is substantially implemented and correct for the common case. The critical issue is a confirmed silent data loss bug: any workstream with a multi-word status (a natural choice — "in progress", "on hold") is written to disk but silently dropped on parse due to a restrictive regex. This affects `SessionBrain` persistence, which is the primary cross-session durability mechanism. Secondary concerns are the miscalibrated context window percentage (cosmetic but affects flush decisions), an inconsistent `flush()` priority semantic, and missing error handling around brain I/O in `brain_tools.py`. The test suite is otherwise thorough at 140 passing tests, with the notable gap of no test for rate-limiting behavior in `refresh_session_context`.
