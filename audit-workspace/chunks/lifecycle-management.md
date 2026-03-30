# Chunk Audit: Lifecycle Management

**User-facing feature**: Decision tracking, delegation management, alert rules
**Risk Level**: Medium
**Files Audited**:
- `tools/__init__.py` (empty — 0 lines, just marks `tools/` as a package)
- `tools/lifecycle.py` (420 lines — core business logic)
- `tools/executor.py` (54 lines — shared memory/document execution helpers; not lifecycle-specific)
- `mcp_tools/lifecycle_tools.py` (326 lines — MCP registration layer)
**Status**: Complete

## Purpose (as understood from reading the code)

This chunk implements the decision log, delegation tracker, and alert rule system: create/update/delete CRUD for decisions and delegations with status workflows, a rule-based alert engine that evaluates conditions against live data, and an MCP registration layer that wraps the core logic in async tool handlers. `tools/executor.py` is included in the assignment but is not lifecycle-specific — it contains shared helpers for memory queries and document search that are used elsewhere.

## Runtime Probe Results

- **Tests found**: Yes — `tests/test_tools_lifecycle.py` (53 tests)
- **Tests run**: 53 passed, 0 failed (1.32s)
- **Import/load check**: OK — `import mcp_server` then `from mcp_tools.lifecycle_tools import create_decision` passes cleanly
- **Type check**: Not applicable (mypy not installed in active environment)
- **Edge case probes**:
  - `_parse_rule_condition(None)` → `{}` (safe, no crash)
  - `_parse_rule_condition("")` → `{}` (safe)
  - `_parse_rule_condition("[1,2,3]")` → `{}` (correct — rejects non-dict JSON)
  - `_validate_enum("", DecisionStatus, "status")` → `ValueError` (raises on empty string, as expected)
  - `ms.update_decision(id, status="invalid_status")` → **silently writes invalid value to DB** (confirmed bug — see Correct section)
  - Date string comparison `today_str <= d.due_date <= soon` — correct for ISO dates; malformed dates sort lexicographically and produce nonsense results silently
- **Key observation**: The update path bypasses enum validation that create enforces, allowing corrupt status values to be written to and then returned from SQLite.

## Dimension Assessments

### Implemented

All functions described in CLAUDE.md are present with real logic: `create_decision`, `search_decisions`, `update_decision`, `list_pending_decisions`, `delete_decision`, `create_delegation`, `list_delegations`, `update_delegation`, `check_overdue_delegations`, `delete_delegation`, `create_alert_rule`, `list_alert_rules`, `check_alerts`, `dismiss_alert`. The `_evaluate_rule` function handles four alert types: `overdue_delegation`, `pending_decision`/`stale_decision`, `upcoming_deadline`, `stale_backup`. No stubs or TODOs found.

`tools/executor.py` is implemented and used — it provides `execute_query_memory`, `execute_store_memory`, `execute_search_documents` for other tool modules. Its inclusion in this chunk's assignment appears to be a scoping artifact.

### Correct

**Confirmed bug — status not validated on update**: `create_decision` and `create_delegation` call `_validate_enum` before storing. `update_decision` (lifecycle.py:76–97) and `update_delegation` (lifecycle.py:171–196) do not call `_validate_enum` before passing `status` to the store. `MemoryStore.update_decision` (`memory/lifecycle_store.py:71`) does not validate enum values — it accepts any string. Runtime probe confirmed: `ms.update_decision(id, status="invalid_status")` silently stores `"invalid_status"` and returns it. Subsequent `search_decisions(status="pending_execution")` will miss these records and `list_decisions_by_status` will also silently omit them, making decisions effectively disappear from normal views.

**Double-counting in `check_alerts`**: `check_alerts` (lifecycle.py:360–406) runs three hardcoded alert checks (overdue delegations, stale decisions, upcoming deadlines) and then also evaluates all enabled `alert_rules`. The `_evaluate_rule` function handles `overdue_delegation`, `stale_decision`/`pending_decision`, and `upcoming_deadline` rule types. If a user creates a rule of type `overdue_delegation`, the total count will include those items twice — once from the hardcoded check and once from the rule evaluation. The `total_alerts` field (line 401) is the sum of both, so it overstates the actual alert count. The test `test_check_alerts_rule_based_overdue` passes because it only checks `rule_alerts`, not `total_alerts`.

**`dismiss_alert` disables the rule permanently, not the alert instance**: The docstring and tool description say "Disable an alert rule so it no longer triggers." This is the intended behavior, but the MCP tool is named `dismiss_alert` which implies dismissing a single alert occurrence. Once dismissed, the underlying overdue delegation or stale decision will silently continue without alerting. There is no snooze/acknowledge pattern. This is a design choice that may surprise users who expect to clear a notification temporarily.

**`stale_backup` alert type has no tests**: The `stale_backup` branch in `_evaluate_rule` (lifecycle.py:325–347) has no test coverage. It calls `memory_store.get_fact("work", "backup_last_success")` — if the fact doesn't exist, it fires an alert. If the date parsing fails (non-standard value format), it fires an alert. Both of these behaviors are correct but untested.

**`due_date` not validated on write**: `create_delegation` and `update_delegation` accept any string for `due_date`. Malformed dates (e.g., `"tomorrow"`, `"03/31/2026"`) are stored, and comparison against ISO date strings in `check_alerts` (line 387: `today_str <= d.due_date <= soon`) produces silent lexicographic nonsense. The `_evaluate_rule` overdue path (line 287: `date.fromisoformat(d.due_date)`) handles this with a `try/except ValueError: continue` — so it skips malformed dates silently rather than surfacing the bad data.

### Efficient

No efficiency concerns at production scale. All queries are straightforward SQLite lookups via indexed columns. The `check_alerts` function performs multiple DB calls in sequence (lines 362–398) but they are all O(n) on small datasets typical of delegation/decision tracking. No N+1 patterns observed.

### Robust

**Unvalidated status on update** (see Correct above) — this is also a robustness issue as it silently corrupts the workflow state machine.

**`update_decision` and `update_delegation` return types are inconsistent with the no-op path**: `memory_store.update_decision` (`lifecycle_store.py:71`) returns `Optional[Decision]` but the lifecycle layer at line 91 does `updated = memory_store.update_decision(...)` without a null check before accessing `updated.id` on line 92. If the DB returns `None` (theoretically possible after an update with zero matching rows), this crashes with `AttributeError`. The existing null-check at line 77 (`if not existing: return ...`) guards against this for well-behaved input but is not a guarantee if concurrent deletes occur between the get and the update.

**`_format_delegations`, `_format_decisions`, `_format_alerts` swallow all exceptions** (lifecycle_tools.py:16–74): Each helper wraps its formatter import and render call in a bare `except Exception: results["formatted"] = ""`. This silently degrades without logging. Not critical since `formatted` is supplemental, but failure modes are invisible.

**`tools/executor.py` — `execute_query_memory` does no null-guard on location fields**: Line 20 does `(l.name or "").lower()` but the query could be an empty string, which matches every location. This is not a bug (empty query returns all matching locations) but is worth knowing.

### Architecture

**Clean layering**: `tools/lifecycle.py` is pure business logic (no I/O, no MCP), `mcp_tools/lifecycle_tools.py` is pure MCP transport. This separation is good and makes the logic directly testable without the MCP harness — the 53 tests confirm this works.

**`tools/executor.py` is a naming mismatch**: The file is called `executor.py` and contains memory/document query helpers that have nothing to do with lifecycle. It is imported by other modules (`mcp_tools/memory_tools.py`) but is not used by the lifecycle tools at all. Its inclusion in this chunk assignment is probably a mistake, or the file should be renamed to better reflect its scope.

**Formatter helpers inline in registration file**: `_format_delegations`, `_format_decisions`, and `_format_alerts` (lifecycle_tools.py:16–74) are defined at module level before `register()`. These are display-layer concerns mixed into a registration file. Low impact but adds clutter.

**`sys.modules` mutation for test exposure** (lifecycle_tools.py:311–326): The pattern of `module = sys.modules[__name__]; module.create_decision = create_decision` is consistent with the rest of the project and documented in CLAUDE.md. Not ideal but not a regression risk.

**`_evaluate_rule` is a 83-line function** (lifecycle.py:275–357): Above the 50-line complexity signal. It is essentially a switch on `alert_type` with four branches. Adding new alert types means growing this function further. A dispatch dict or registry pattern would be more extensible, but this is low priority given the current alert type count.

## Findings

### 🔴 Critical

- **`tools/lifecycle.py:76-97` and `tools/lifecycle.py:171-196`** — `update_decision` and `update_delegation` do not validate the `status` (or `priority`) enum values before writing to the database. `create_decision` calls `_validate_enum` at line 25; `update_decision` does not. Runtime probe confirmed: calling `ms.update_decision(id, status="invalid_status")` silently stores the invalid value. A decision updated to `status="done"` (instead of `"executed"`) will never appear in `list_pending_decisions` or `search_decisions(status="executed")` — it becomes unreachable through normal query paths. Fix: add `_validate_enum(status, DecisionStatus, "status")` before the update call in both functions, same pattern as create.

### 🟡 Warning

- **`tools/lifecycle.py:360-406`** — `check_alerts` double-counts items when alert rules of type `overdue_delegation`, `pending_decision`, or `upcoming_deadline` are active. The hardcoded section (lines 362–393) and the rule-based section (lines 395–399) independently query the same data. `total_alerts` (line 401) sums both. The test suite validates rule-based alerts in isolation but does not test the combined `total_alerts` value when both hardcoded and rule-based checks fire on the same items. Fix: either skip the hardcoded checks when a matching rule exists, or document that rules supplement rather than replace the hardcoded checks and clarify the counting semantics.

- **`tools/lifecycle.py:90-92` and `tools/lifecycle.py:190-192`** — `updated = memory_store.update_decision(...)` and `memory_store.update_delegation(...)` return `Optional[...]` (per `lifecycle_store.py:71,156`), but the lifecycle layer accesses `updated.id`, `updated.title`, etc. without a null check. A race condition (concurrent delete between get and update) could cause `AttributeError: 'NoneType' has no attribute 'id'`, which would propagate as an unhandled exception to the MCP caller.

- **`tools/lifecycle.py:325-347` (`stale_backup` alert type)** — No test coverage for this branch. The logic is non-trivial (fact lookup + date parsing + threshold comparison) and includes a fallback for unparseable dates. Should have at least one test for: fact missing, date parseable, date too old, date recent, date malformed.

### 🟢 Note

- `tools/executor.py` is unrelated to lifecycle management and its inclusion in this chunk may be a scoping artifact. The file provides `execute_query_memory`, `execute_store_memory`, `execute_search_documents` used by memory tools — not lifecycle tools. Consider auditing it with the memory/document chunk instead.
- `dismiss_alert` permanently disables the alert rule rather than snoozing it. Users expecting to acknowledge an alert and have it re-fire next check cycle will be surprised. The tool docstring is accurate but the name `dismiss_alert` implies an instance action, not a rule-level permanent change.
- `due_date` accepts any string format. Callers passing non-ISO dates (e.g., `"tomorrow"`, `"March 31"`) will store silently. The overdue check in `_evaluate_rule` handles this gracefully with `try/except` but silently ignores the bad record rather than surfacing the data quality issue.
- The `_format_*` helpers in `lifecycle_tools.py` swallow all exceptions silently. Adding a `logger.debug` or `logger.warning` in the `except` block would aid debugging without changing behavior.

## Verdict

This chunk is functionally complete and well-tested for happy paths — 53 tests pass. The critical flaw is that `update_decision` and `update_delegation` skip the enum validation that `create_*` enforces, allowing corrupt status values to be silently written to SQLite, causing records to fall out of normal query views permanently. The secondary concern is double-counting in `check_alerts` when rules overlap with hardcoded checks. Both issues are straightforward to fix. The `stale_backup` alert type has zero test coverage and should be addressed before expanding its use.
