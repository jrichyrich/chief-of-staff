# Chunk Audit: Proactive & Skills

**User-facing feature**: Proactive suggestions (overdue delegations, stale decisions, skill hints, session health), skill auto-creation from usage patterns
**Risk Level**: Low
**Files Audited**:
- `proactive/__init__.py`
- `proactive/engine.py`
- `proactive/models.py`
- `proactive/action_executor.py`
- `skills/__init__.py`
- `skills/pattern_detector.py`
- `mcp_tools/proactive_tools.py`
- `mcp_tools/skill_tools.py`

**Status**: Complete

## Purpose (as understood from reading the code)

`ProactiveSuggestionEngine` polls the memory store and optional session-health/brain objects to surface actionable items (overdue delegations, stale decisions, pending webhooks, skill suggestions, session token limits, stale documents). The skills subsystem (`PatternDetector`) groups raw tool-usage records by Jaccard similarity, derives confidence scores relative to the most-used cluster, and proposes new agent configs when thresholds are met. Both subsystems are exposed via MCP tools and are designed to be passive/advisory by default, with autonomous action gated behind config flags.

## Runtime Probe Results

- **Tests found**: Yes — 7 focused test files covering engine, tools, action executor, pattern detector, push, and config
- **Tests run**: 3 failed, 91 passed (out of 94 total)
- **Import/load check**: OK — all modules compile and import cleanly
- **Type check**: Clean — `mypy --ignore-missing-imports` returned no errors
- **Edge case probes**: `_jaccard_similarity("", "")` returns `0.0` correctly (early return); `_cluster_patterns` correctly groups similar patterns and isolates dissimilar ones
- **Key observation**: All 3 failures share a single root cause — `_check_stale_documents` reads the developer's live OneDrive directory (`/Users/jasricha/Library/CloudStorage/...`) at test time, returning real stale files that tests do not expect

## Dimension Assessments

### Implemented

All described features are fully implemented with real logic — no stubs, no TODOs, no `pass` bodies. The action executor correctly maps suggestion categories to handlers via `_ACTION_HANDLERS` and resolves handlers through `globals()`. Config flags (`PROACTIVE_ACTION_ENABLED`, `SKILL_AUTO_EXECUTE_ENABLED`) gate autonomous behaviour correctly.

One stored field is never consumed: `SkillSuggestion.suggested_capabilities` (set in `skill_tools.py:60` to the raw tool name) is written to the DB but never read back when `auto_create_skill` calls `AgentFactory.create_agent(suggestion.description)`. The factory LLM-generates capabilities from the description, ignoring the pre-computed value. This is dead data.

### Correct

**Confidence scoring in `PatternDetector.detect_patterns`** (`skills/pattern_detector.py:74`): confidence is computed as `count / max_count`, where `max_count` is the highest total in any cluster. This means only the single most-used cluster can reach confidence 1.0. Every other cluster is scored relative to it. A cluster used 8 times out of a maximum of 10 gets confidence 0.8 — it passes the 0.7 threshold. But if the dominant cluster has 50 uses and a secondary has 6 (just above the `min_occurrences=5` floor), it gets confidence 0.12, which fails the threshold even though it clearly qualifies. Pattern detection is effectively **threshold-blind for subordinate clusters** in uneven usage distributions. The semantics of `confidence_threshold` are therefore inconsistent with its stated purpose: "patterns exceeding the configured confidence threshold" cannot be satisfied by any cluster except the most-frequent one in practice.

**Clustering representative is never updated** (`pattern_detector.py:33`): when patterns merge into a cluster, the `representative` key remains the first item ever added. Later merges compare new arrivals against that original representative, not against the growing cluster. This causes order-dependent grouping: two similar patterns may or may not merge depending on which appeared first in the DB query.

**Priority filter semantics in `push_suggestions`** (`engine.py:311`): `PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}`, and the filter is `PRIORITY_ORDER.get(s.priority, 3) <= threshold_val`. For `push_threshold="high"` this passes only items with value 0 — correctly sending only high-priority items. The docstring says "minimum priority to push", which matches: setting `push_threshold="medium"` passes values 0 and 1 (high + medium). Logic is correct, though the inverted numeric encoding could confuse future editors.

### Efficient

`_check_stale_documents` calls `os.walk` recursively over the entire Jarvis output directory on every `generate_suggestions()` call. On a populated OneDrive folder this is a synchronous filesystem walk done in-process inside the MCP server. For the current folder size (dozens of files) this is acceptable. No N+1 issues; memory store queries are simple single-SELECT calls.

`get_tool_statistics` with a `tool_name` argument fetches up to 500 log rows into memory to count patterns (`skill_tools.py:186-195`). At 500 rows this is fine, but the limit is not surfaced in the tool docstring and the manual pattern-counting loop could be replaced by a GROUP BY SQL query.

### Robust

**`_check_stale_documents` has no configurable output dir and reads the hardcoded path** (`engine.py:22`): `JARVIS_OUTPUT_DIR = "/Users/jasricha/Library/CloudStorage/OneDrive-CHGHealthcare/Jarvis"`. This is a machine-specific absolute path. If this MCP server runs on any other machine (or the OneDrive sync path changes), the check silently passes `os.path.isdir()` as False and returns nothing — acceptable. But it also means:
1. Tests cannot mock this without patching the module-level constant, which none of them do — causing the 3 test failures observed.
2. The path is not derived from `config.py`, breaking the project's own convention (all paths live in `config.py`).

**`dismiss_suggestion` partial-failure path** (`proactive_tools.py:82-89`): if `memory_store.store_fact` raises, the function returns a "dismissed" status with a warning message but the dismissal is not persisted. On the next call to `get_proactive_suggestions`, the supposedly dismissed suggestion will reappear. The caller gets back `"status": "dismissed"` with no visible indication the persistence failed (the error is buried in the message string). This is a silent soft-failure that misleads the user.

**`execute_suggestion_action` resolves handlers via `globals()`** (`action_executor.py:58`): `handler = globals().get(handler_name)`. This works only because the handler functions are defined at module level in the same file. If a handler were moved to a submodule or refactored, it would silently return `None` and produce a "Handler not found" non-executed result with no error surfaced. Low risk currently, but fragile coupling between the dispatch map and module structure.

**`_handle_checkpoint` accesses `session_health` via `**kwargs`** (`action_executor.py:80`): `if session_health := kwargs.get("session_health")`. The walrus assignment would fail silently (just not record the checkpoint) if `session_health` was not passed. This is defensive but means the checkpoint side-effect of updating `session_health` is silently skipped whenever called without that argument.

### Architecture

**Hardcoded dev path should be in `config.py`**: `JARVIS_OUTPUT_DIR` and `DOCUMENT_RETENTION_DAYS` are defined inline in `engine.py` (lines 22-27). All other environment-specific paths live in `config.py`. This violates the project's own convention and is the direct cause of the 3 test failures.

**`suggested_capabilities` is dead data**: stored by `analyze_skill_patterns` (`skill_tools.py:60`) but never read by `auto_create_skill`. The `AgentFactory.create_agent()` call at line 121 takes only `suggestion.description`. Either `suggested_capabilities` should be passed as a hint to `create_agent`, or the field should be removed to avoid confusion.

**`SkillSuggestionStatus.pending` enum vs `"pending"` string inconsistency**: `proactive/engine.py:55` passes the enum member, `skills/pattern_detector.py:102` passes a raw string `"pending"`. Both work because `StrEnum` compares equal to its string value, but the inconsistency adds cognitive load.

**`_cluster_patterns` O(n*m) complexity**: for each incoming row it iterates all existing clusters to find a match. For large usage tables this is O(n*m) where n=rows and m=clusters. Acceptable for the current scale (typical usage tables have hundreds of rows), but worth noting.

## Findings

### 🔴 Critical

- **`proactive/engine.py:22-27`** — `JARVIS_OUTPUT_DIR` is a hardcoded absolute path to a developer's OneDrive folder, not loaded from `config.py`. This causes 3 test failures on every test run (tests receive unexpected stale-document suggestions from the live filesystem). The path will silently produce no suggestions on any machine where the path doesn't exist, but there is no fallback or log warning. Tests cannot isolate this path without patching a private module constant.

### 🟡 Warning

- **`skills/pattern_detector.py:74`** — Confidence scoring is `count / max_count` across all clusters. Any cluster that isn't the dominant one by usage count will have a proportionally lower confidence score. With a skewed usage distribution (e.g., one tool used 50x and several others used 6x each), all secondary clusters fall below the default `0.7` threshold even when they clearly exceed `min_occurrences`. Useful skill suggestions will be silently dropped.

- **`skills/pattern_detector.py:33`** — Cluster `representative` is set once on creation and never updated as more patterns merge in. Similarity comparisons for all subsequent items are made against the original first item, not the evolving cluster. This produces order-dependent, non-deterministic clustering when the DB query order changes.

- **`mcp_tools/proactive_tools.py:82-89`** — `dismiss_suggestion` returns `"status": "dismissed"` even when persistence fails. The dismissal is not retried or re-raised; the user believes the item is dismissed but it will reappear on the next call to `get_proactive_suggestions`.

- **`mcp_tools/skill_tools.py:59-60`** — `suggested_capabilities` is set to a raw tool name string (e.g., `"query_memory"`) but is never read when `auto_create_skill` calls `AgentFactory.create_agent(suggestion.description)`. This field is dead data — it costs a DB write and returns in `list_skill_suggestions` output without ever influencing agent generation.

### 🟢 Note

- `proactive/action_executor.py:58` — Handler resolution via `globals().get(handler_name)` is functional but fragile. A registry pattern (e.g., a `_HANDLER_REGISTRY: dict[str, Callable]`) would make the dispatch explicit and testable.
- `mcp_tools/skill_tools.py:186-195` — The `get_tool_statistics` pattern-counting loop fetches 500 rows into memory and aggregates in Python. A `GROUP BY query_pattern` SQL query would be more efficient and reduce memory allocation.
- `SkillSuggestionStatus` enum usage is inconsistent across the chunk: the engine passes the enum member, the pattern detector passes a raw string. Both work due to `StrEnum` equality, but standardizing on one form would improve readability.
- `_jaccard_similarity` handles empty strings correctly (returns `0.0`). `_cluster_patterns` handles empty input correctly (returns `[]`). These edge cases are clean.

### ✅ Nothing to flag

- **Implemented**: All described functions exist with real logic. No stubs, TODOs, or empty bodies.
- **`action_executor.py` guard logic**: `PROACTIVE_ACTION_ENABLED` and `PROACTIVE_ACTION_CATEGORIES` checks are correct and defensive. Autonomous actions will not fire unless explicitly enabled via environment variables.
- **`push_suggestions` and `push_via_channel`**: Logic correctly maps the threshold semantics (lower numeric value = higher priority = stricter filter).
- **`Suggestion` model**: Clean dataclass with sensible defaults; `__post_init__` auto-populates `created_at` when not provided.
- **Type checking**: `mypy --ignore-missing-imports` returns zero errors across all chunk files.

## Verdict

This chunk is largely working and well-tested (91/94 tests pass), but has one confirmed root cause for all 3 failures: a hardcoded developer filesystem path in `engine.py` that the test suite cannot isolate. The pattern detection confidence formula has a design flaw that silently discards valid skill suggestions when usage patterns are unequal in frequency, and the `suggested_capabilities` field generated by `analyze_skill_patterns` is stored but never consumed by `auto_create_skill`. The most important fix is moving `JARVIS_OUTPUT_DIR` and `DOCUMENT_RETENTION_DAYS` to `config.py` with an injectable override — this would restore the 3 failing tests and make the stale-document check portable and testable.
