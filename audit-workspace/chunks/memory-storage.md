# Chunk Audit: Memory & Storage

**User-facing feature**: Fact storage/recall, location tracking, session checkpoints
**Risk Level**: High
**Files Audited**:
- `memory/__init__.py`
- `memory/store.py`
- `memory/models.py`
- `memory/fact_store.py`
- `memory/agent_memory_store.py`
- `memory/api_usage_store.py`
- `memory/identity_store.py`
- `memory/lifecycle_store.py`
- `memory/scheduler_store.py`
- `memory/skill_store.py`
- `memory/webhook_store.py`
- `mcp_tools/memory_tools.py`

**Status**: Complete

---

## Purpose (as understood from reading the code)

This chunk is a SQLite-backed persistent store for all Jarvis state, decomposed into eight
domain-scoped store classes (FactStore, LifecycleStore, WebhookStore, SchedulerStore, SkillStore,
AgentMemoryStore, IdentityStore, ApiUsageStore) unified by a `MemoryStore` facade that shares a
single connection and RLock. FactStore adds FTS5 full-text search and optional ChromaDB vector
search. `mcp_tools/memory_tools.py` exposes the subset needed for interactive sessions (facts,
locations, checkpoints).

No divergence from the stated intent.

---

## Runtime Probe Results

- **Tests found**: Yes — `tests/test_memory_store.py`, `tests/test_memory_models.py`, `tests/test_agent_memory.py`
- **Tests run**: 117 passed, 0 failed (2.67 s)
- **Import/load check**: OK — all 10 memory modules import cleanly
- **Type check**: Not applicable (mypy not installed)
- **Edge case probes**:
  - ChromaDB failure during `store_fact` correctly rolls back the SQLite row. OK.
  - ChromaDB failure during `delete_fact` correctly keeps the SQLite row (via rollback). OK.
  - `rank_facts` with `updated_at=None` scores the fact at full confidence (age_days=0). Behaviour is documented via `else: age_days = 0.0`. Acceptable but non-obvious.
  - FTS5 sanitizer strips `OR AND NOT` to empty tokens — returns `[]` rather than falling back to LIKE search. Silent empty result for keyword-only queries.
  - BM25 rank values on small fact tables are near-zero floats (e.g. `-0.000001`); the negation-based score is functionally identical to zero. Scores are not normalized against vector search scores (0–1 range).
- **Key observation**: All 117 tests pass. The chromadb rollback paths are correctly implemented and verified at runtime. The score normalization issue in hybrid search is a design concern, not a crash.

---

## Dimension Assessments

### Implemented

All public methods declared in the architecture doc exist with real logic. No stubs, no NotImplementedError, no empty bodies. The `pass` instances found are all correct idioms:

- `memory/store.py:454,462,471,479` — `except sqlite3.OperationalError: pass` in migration helpers (expected: column already exists).
- `memory/fact_store.py:370` — `except (IndexError, KeyError): pass` in `_row_to_fact` for missing `pinned` column in older rows.
- `memory/agent_memory_store.py:88` — same pattern for `namespace` column.
- `memory/scheduler_store.py:126` — `except (ValueError, TypeError): pass` in `_row_to_scheduled_task` for invalid `delivery_config` JSON.

All legitimate. No missing functionality.

`repair_vector_index` is fully implemented and wired to `MemoryStore._mmr_rerank` via a staticmethod alias for backward compatibility. Both are callable.

### Correct

**Happy path**: Correct throughout. Insert-on-conflict upserts are correct for facts (category+key), locations (name), alert_rules (name), scheduled_tasks (name), agent_memory (agent_name+memory_type+key), identities (provider+provider_id). Decisions and delegations intentionally allow duplicates (no unique constraint), which matches the design.

**Temporal decay formula**: `score = confidence × exp(-ln(2) × age / half_life)` — mathematically correct for half-life semantics. Pinned facts bypass decay at full confidence. Verified by tests.

**FTS5 trigger-based sync**: The triggers in `_create_tables` correctly handle INSERT/DELETE/UPDATE to keep `facts_fts` in sync with the content table.

**Potential correctness issue — `store_fact` namespace omission**: `AgentMemoryStore.store_agent_memory` (`agent_memory_store.py:24`) does not include the `namespace` field in its INSERT statement, even though `AgentMemory` has a `namespace` field. If a caller constructs an `AgentMemory` with `namespace='x'` and calls `store_agent_memory`, the namespace is silently discarded. Only `store_shared_memory` correctly handles namespace. This is a data-loss bug for callers who expect namespace to be preserved via `store_agent_memory`.

**FTS fallback when query contains only stopwords**: `search_facts_fts` sanitizes FTS5 operators and wraps tokens in double-quotes. If the query is composed entirely of FTS5 operator keywords (`OR`, `AND`, `NOT`) or special characters, `tokens` becomes empty, the function returns `[]` — does not fall back to `search_facts(query)`. This means a query of `"OR"` or `"NOT"` returns zero results silently.

### Efficient

**No N+1 queries**: `search_facts_vector` correctly batch-fetches all matched facts in a single SQL OR clause rather than one query per vector result.

**repair_vector_index**: Loads all facts from SQLite into memory and upserts one-by-one to ChromaDB with no batching. At personal assistant data volumes (hundreds to low thousands of facts) this is fine. Would be slow at tens of thousands.

**match_event_rules**: Fetches all enabled rules and filters in Python. Acceptable for small rule sets.

**context table unbounded growth**: There is no `DELETE FROM context` anywhere in the codebase (confirmed by grep). The `context` table accumulates entries forever. For a personal assistant in daily use, this grows without bound. Same for `tool_usage_log` and `agent_api_log` — no pruning or TTL logic exists. Not a crash risk now but a long-term maintenance concern.

**Hybrid search score normalization**: `search_facts_hybrid` (`fact_store.py:222`) merges three result sets using heterogeneous score scales: FTS5 BM25 scores (negated rank, near-zero on small datasets), vector cosine similarity (0–1), and a flat 0.5 for LIKE-only hits. On small databases, BM25 produces near-zero values that are indistinguishable from LIKE scores. On larger datasets BM25 could dominate. The scores are combined without normalization, making ranking unreliable as data grows.

### Robust

**Migration error handling** (`store.py:448–479`): All four `_migrate_*` helpers catch `sqlite3.OperationalError` with a bare `pass`. This is the correct idiom for "column already exists" — SQLite raises `OperationalError: duplicate column name` in this case. However, this also silently masks other `OperationalError` conditions (locked database, I/O error during migration). A production system should at minimum log the error before passing.

**Delivery config silent data loss** (`scheduler_store.py:119–126`): `_row_to_scheduled_task` catches JSON parse errors on `delivery_config` and silently returns `None`. A scheduler task with a corrupted delivery config will run but deliver nowhere, with no log message. Should at minimum emit a warning.

**create_event_rule dead import** (`webhook_store.py:99`): `import json as _json` is inside `create_event_rule` but `_json` is never used in that function (delivery_config is accepted as a raw string, not serialized). Dead code, harmless.

**Read-outside-lock pattern**: `store_fact` acquires the lock for the INSERT, then calls `self.get_fact(...)` outside the lock to return the stored object (`fact_store.py:55`). Same pattern in `store_agent_memory`, `store_shared_memory`, `store_context`, etc. Because all stores share a single connection with WAL mode and Python's GIL, this is safe in practice — `lastrowid` is per-connection and not invalidated by concurrent readers. It is an architectural smell worth noting but not a real bug here.

**No input length limits**: `store_fact` accepts arbitrary-length `value` strings. No validation that `confidence` is in [0.0, 1.0] range (the tool layer passes it directly to the store, and the store does no clamping). A confidence of 5.0 would be stored silently.

**`list_delegations`, `list_decisions_by_status`, `list_alert_rules`, `list_scheduled_tasks`, `list_locations`** all lack `ORDER BY` clauses. Return order is non-deterministic (SQLite rowid order in practice, but not guaranteed). This can cause jitter in UI or summary outputs.

### Architecture

**Facade pattern** (`store.py`): Clean. `MemoryStore` delegates all public methods to domain stores via attribute assignment in `__init__`. This preserves backward compatibility while allowing domain decomposition. The `_mmr_rerank` staticmethod alias at line 157 is a reasonable backward-compat shim.

**Table creation centralized in `MemoryStore._create_tables`**: This is correct — domain stores receive an already-initialized connection. The single-file schema definition is easy to audit.

**Module-level tool exposure** (`memory_tools.py:303–314`): The `sys.modules[__name__]` injection at the bottom of `register()` is an unusual but documented pattern to expose inner functions for test imports. It works but is non-idiomatic and confusing to new contributors.

**`create_event_rule` in WebhookStore takes `delivery_config` as a raw string**, while `SchedulerStore.store_scheduled_task` accepts `delivery_config` as a dict and serializes it. Inconsistent interface for the same field type across two stores.

**No abstraction for common CRUD patterns**: Every domain store repeats the same pattern (INSERT ... ON CONFLICT ... DO UPDATE, then SELECT by id/name, then _row_to_*). This is ~200 lines of boilerplate that could be a generic `_upsert_and_return` helper. Not a bug, but increases maintenance surface.

---

## Findings

### 🔴 Critical

- **`memory/agent_memory_store.py:24`** — `store_agent_memory` INSERT omits the `namespace` column. If called with an `AgentMemory(namespace="x")`, the namespace is silently discarded. The `AgentMemory` dataclass has the field; `store_shared_memory` uses it correctly. Any code path that calls `store_agent_memory` to save an agent memory with a namespace will lose the value without error or warning. To fix: add `namespace` to the INSERT column list and parameter tuple.

### 🟡 Warning

- **`memory/fact_store.py:113–128`** — `search_facts_fts`: if query is composed entirely of FTS5 special tokens (e.g., `"OR"`, `"AND NOT"`, `"*"`), `tokens` becomes empty after sanitization and the method returns `[]` rather than falling back to `search_facts(query)`. The fallback at line 128 is only reached if the FTS query *raises* an exception, not if it produces zero tokens. Low probability in practice but creates a silent empty-result trap for queries that are valid natural language but happen to be FTS keywords.

- **`memory/store.py:448–479`** — All `_migrate_*` helpers catch `sqlite3.OperationalError` with bare `pass`. This correctly handles "column already exists" but also silently swallows genuine errors (locked DB, disk full, corrupted schema) during startup migration. Should log the exception at WARNING level before passing so that misconfigured environments are diagnosable.

- **`memory/scheduler_store.py:123–126`** — `_row_to_scheduled_task` silently returns `delivery_config=None` when JSON parse fails. A scheduled task with a corrupted or non-JSON `delivery_config` will run with no delivery configuration, dropping the result silently. Should emit a `logger.warning(...)` with the task name and raw value.

- **`memory/fact_store.py:222` / `memory/store.py`** — Hybrid search (`search_facts_hybrid`) merges FTS5 BM25 scores, vector cosine scores (0–1), and a flat 0.5 without normalization. On small datasets BM25 produces near-zero values that are interchangeable with LIKE scores, rendering ranking meaningless. The behavior degrades silently as the dataset grows, with no indication to callers.

- **`memory/lifecycle_store.py:65,136,148,226`, `memory/scheduler_store.py:73`, `memory/fact_store.py:409`** — `list_decisions_by_status`, `list_delegations`, `list_overdue_delegations`, `list_alert_rules`, `list_scheduled_tasks`, `list_locations` have no `ORDER BY` clause. Return order is non-deterministic. For deterministic outputs in summaries and briefings, each should have a stable ORDER BY (e.g., `created_at DESC` or alphabetically by primary key field).

- **`memory/fact_store.py` / `memory/agent_memory_store.py`** — No row count limits or TTL on `context`, `tool_usage_log`, `agent_api_log` tables. No pruning logic exists anywhere in the codebase. All three accumulate indefinitely. `tool_usage_log` and `agent_api_log` log every tool call and every API invocation respectively — in active daily use these tables will grow significantly over time with no mechanism to reclaim space.

### 🟢 Note

- **`memory/webhook_store.py:99`** — `import json as _json` inside `create_event_rule` is dead code. `_json` is never used in the function body (delivery_config is stored as a raw string). Safe to remove.

- **`memory/agent_memory_store.py` / `memory/fact_store.py`** — The read-outside-lock pattern (INSERT inside `with self._lock:`, then SELECT by lastrowid outside the lock) is consistent across all stores. Safe on a shared single connection but worth documenting as a deliberate design choice so future contributors don't "fix" it by moving the SELECT inside the lock (which would cause deadlock with RLock on re-entrant paths).

- **`mcp_tools/memory_tools.py:303–314`** — `sys.modules[__name__]` injection at the bottom of `register()` is a non-idiomatic testing escape hatch. Consider a module-level dict or a proper test fixture as a cleaner alternative.

- **`memory/fact_store.py:184–220`** — `_mmr_rerank` uses Jaccard word overlap as a proxy for semantic similarity (token set intersection/union). This is a reasonable cheap approximation but will fail to suppress semantically similar facts that use different wording. No known bug, just a limitation worth noting in docs.

- **`mcp_tools/memory_tools.py:24`** — `confidence` parameter has no validation that it falls in [0.0, 1.0]. The store will accept and persist `confidence=5.0` or `confidence=-1.0` silently. Consider a bounds check in the tool handler.

---

## Verdict

This chunk is implemented correctly and all 117 tests pass. The most important issue is a data-loss bug in `store_agent_memory` that silently drops the `namespace` field — any caller who passes a namespaced `AgentMemory` object will have the namespace discarded. The second priority is the unbounded growth of `context`, `tool_usage_log`, and `agent_api_log` tables with no pruning mechanism, which will cause gradual database bloat in production. The hybrid search score normalization issue is a ranking quality problem that degrades silently as fact volume grows. All other findings are warnings or notes; no other data-integrity bugs were found.
