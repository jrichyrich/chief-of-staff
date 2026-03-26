# Chunk Audit: provider-router

**User-facing feature**: Infrastructure — determines which backend handles each calendar operation
**Risk Level**: High
**Files Audited**: `connectors/router.py` (140 lines), `connectors/provider_base.py` (64 lines)
**Status**: Complete

## Purpose (as understood from reading the code)

`provider_base.py` defines `CalendarProvider`, an abstract base class with 6 abstract methods (is_connected, list_calendars, get_events, create_event, update_event, delete_event, search_events) forming the contract for Apple and M365 backends.

`router.py` implements `ProviderRouter` with two policy methods: `decide_read()` (returns all connected providers for full-picture reads, with preference/fallback ordering) and `decide_write()` (selects a single target provider based on explicit target, provider preference, work-calendar heuristics, or "personal first" default). Both return a `RouteDecision` dataclass. A `normalize_provider_name()` helper maps aliases (outlook, m365, local, etc.) to canonical names.

No divergence from the intent map description.

## Runtime Probe Results

- **Tests found**: Yes — `tests/test_connectors_router.py` (4 tests)
- **Tests run**: 4 passed, 0 failed
- **Import/load check**: OK
- **Type check**: mypy not installed in venv; skipped
- **Edge case probes**: All pure functions probed. `normalize_provider_name(None)` returns `""` safely. `_looks_work_calendar(None)` returns `False` safely. Unknown preference strings fall through to auto/default behavior correctly. Empty provider dict returns `no_provider_connected` for all paths. Recursive `decide_write` terminates after exactly 1 level.
- **Key observation**: No runtime issues detected. All edge cases handled gracefully.

## Dimension Assessments

### Implemented

All functions listed in the intent map exist with real logic:
- `normalize_provider_name()` (line 20) — complete, handles None/whitespace/aliases
- `RouteDecision` dataclass (line 24) — complete
- `ProviderRouter.__init__` (line 35) — stores providers dict
- `ProviderRouter.get_provider` (line 38) — normalizes and looks up
- `ProviderRouter.is_connected` (line 42) — safe null-chain with `bool(provider and ...)`
- `ProviderRouter.connected_providers` (line 46) — list comprehension
- `ProviderRouter.decide_read` (line 49) — full decision tree for both/explicit/auto
- `ProviderRouter.decide_write` (line 90) — full decision tree for target/pref/heuristic/default
- `ProviderRouter._looks_work_calendar` (line 134) — keyword matching
- `CalendarProvider` ABC (provider_base.py) — 7 abstract methods, all declared

Nothing is stubbed, missing, or dead code.

### Correct

The logic matches the stated intent. Traced all branches:

1. **decide_read**: "both" returns both connected providers; explicit provider preference adds the other as fallback; unknown preferences fall through to auto (returns all connected). Correct.

2. **decide_write**: explicit target takes priority, then provider preference (recurses once with target set), then work-calendar heuristic (routes to M365), then personal-first default (routes to Apple). Correct.

3. **Recursion safety** (line 114): `decide_write(target_provider=pref, ...)` — on the recursive call, `target` is non-empty so it enters the `if target:` block and returns immediately. Max depth = 1. Verified at runtime.

4. **"both" for writes** falls through to default personal-first behavior. This is correct — you should not create an event in two providers simultaneously.

5. **normalize_provider_name** uses `(value or "").strip().lower()` so None is safe.

No bugs found.

### Efficient

Clean. The provider dict is typically 2 entries. `is_connected()` is called up to 4 times in `decide_read`/`decide_write` (2 calls per method for `has_apple`/`has_m365`), but these are trivially cheap boolean lookups. The `_looks_work_calendar` keyword scan is over a 7-element tuple. No efficiency concerns.

### Robust

**Input validation**: All string inputs handle `None` gracefully via `(x or "")` guards. Unknown provider names return empty string from `normalize_provider_name`, which causes decisions to fall through to auto/default behavior rather than crashing.

**Failure modes**: `decide_read` and `decide_write` always return a valid `RouteDecision` — even with zero connected providers, they return an empty providers list with reason `"no_provider_connected"`. Callers can check `decision.providers` before proceeding.

**No exceptions raised**: These are pure decision functions with no I/O, no exceptions, no side effects. Robust by design.

One observation: `is_connected()` delegates to the provider's implementation. If a provider's `is_connected()` throws, it would propagate uncaught. However, this is appropriate — a provider that can't report its own connectivity is genuinely broken and should surface that error.

### Architecture

Well-structured:

- **Clean ABC contract**: `CalendarProvider` defines the exact interface both backends must implement. 7 abstract methods, no concrete logic, no coupling to implementation details.
- **Separation of concerns**: Router makes decisions; it does not execute calendar operations. The `RouteDecision` dataclass is a clean value object that flows to the unified service.
- **Testability**: Excellent. Tests use a simple `_StubProvider` with no real dependencies. Pure functions are trivially testable.
- **Naming**: Clear and consistent. `decide_read`/`decide_write` clearly separate the two policy paths. `normalize_provider_name` is self-documenting. Reason strings on `RouteDecision` are descriptive and debuggable.
- **No duplication**: The repeated `has_apple`/`has_m365` pattern in each decision tree is unavoidable given the branching logic.

## Findings

### 🟡 Warning

- **router.py:113-114** — `decide_write` recursive call passes `provider_preference=pref` alongside `target_provider=pref`. On recursion, line 97 re-normalizes `provider_preference` but it is ignored because `target` is already set. The `provider_preference` parameter is dead on the recursive call. Not a bug (it terminates correctly), but the recursion is unnecessary complexity — a direct fall-through to the target branch would be clearer and eliminate the recursion entirely.

- **router.py:139** — `_looks_work_calendar` uses substring matching ("team" matches "My Team" and "Steaming Hot Yoga"). This is a heuristic, so false positives are expected, but "team" is particularly prone to matching personal calendars. The upstream `decide_write` only uses this for auto-routing (no explicit preference set), so the blast radius is limited — it would route an event to M365 instead of Apple, and the event still gets created.

- **Test coverage is thin** — 4 tests cover the happy paths (auto read, fallback read, work write, personal write) but miss: `decide_read("both")`, `decide_write` with explicit `target_provider`, `decide_write` when target is disconnected (fallback path), `decide_write` with `provider_preference="both"`, empty providers dict, `None` inputs, `normalize_provider_name` aliases. The code handles all these correctly (verified by runtime probes), but they are not regression-protected.

### 🟢 Note

- `provider_base.py` uses `Optional` from `typing` (lines 5, 36-38, 47-49, 54) alongside the `from __future__ import annotations` import. With `annotations` active, `X | None` syntax works and is the modern style. Low priority but could be cleaned up for consistency with `router.py` which uses `X | None` (line 38).

- The `_PROVIDER_ALIASES` dict (router.py:8-17) is a clean, extensible pattern. Adding new providers only requires a new alias entry and a provider implementation.

### ✅ Nothing to flag

- **Critical**: No critical issues found. All code paths produce correct results, handle edge cases, and fail gracefully.

## Verdict

This chunk is well-implemented, correct, and cleanly architected. The routing logic is straightforward, all edge cases are handled, and the code is easy to test. The main improvement opportunity is expanding test coverage from 4 tests to ~12-15 to regression-protect the edge cases that were verified via runtime probes. The recursive `decide_write` call at line 114 could be simplified to a direct branch but is not a correctness issue.
