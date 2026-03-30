# Chunk Audit: Identity & Enrichment

**User-facing feature**: Identity management, person enrichment
**Risk Level**: Medium
**Files Audited**:
- `mcp_tools/identity_tools.py`
- `mcp_tools/enrichment.py`
**Status**: Complete

## Purpose (as understood from reading the code)

`identity_tools.py` exposes four MCP tools (`link_identity`, `unlink_identity`, `get_identity`, `search_identity`) that are thin wrappers delegating directly to `state.memory_store`. `enrichment.py` exposes a single `enrich_person` tool that fans out to 6 data sources in parallel (identity, facts, delegations, decisions, iMessages, email) using `asyncio.gather` over `asyncio.to_thread`, merges non-empty results, and returns consolidated JSON. No divergence from the stated purpose.

## Runtime Probe Results

- **Tests found**: Yes — `tests/test_identity_linking.py` (36 tests), `tests/test_enrichment.py` (17 tests)
- **Tests run**: 53 passed, 0 failed
- **Import/load check**: OK (both files compile clean: `python -m py_compile` passes)
- **Type check**: Not applicable (mypy not installed in project env)
- **Edge case probes**: Skipped — all functions write to DB or call external services
- **Key observation**: Full test coverage on the happy path, error isolation, and cap behavior. All 53 pass in 1.35s.

## Dimension Assessments

### Implemented

All four identity tools are fully implemented with real delegation to `state.memory_store`. `enrich_person` is fully implemented with all 6 parallel fetchers. Both modules correctly expose tool functions at module level via `sys.modules[__name__]` for test imports. No stubs or TODOs found.

### Correct

**Identity tools**: Logic is correct. The four tool functions faithfully pass their arguments to the corresponding store methods and serialize the result. Upsert-on-conflict behavior (UNIQUE(provider, provider_id)) lives in the store layer and is well-tested.

**Enrichment**: Logic is correct for the stated purpose. Each fetcher caps at 10 results. The `minutes` calculation (`days_back * 1440`) is correct. Empty sections are correctly omitted from the output. One subtlety: `fetch_emails` calls `mail_store.search_messages(name, limit=10)` — this calls `AppleMail.search_messages(query, mailbox="INBOX", ...)`, which only searches the INBOX mailbox. This is a functional limitation (not a bug) but means enrichment silently misses emails in non-INBOX folders. The docstring claims "emails" with no caveat.

### Efficient

**Enrichment**: The parallel fan-out via `asyncio.gather` + `asyncio.to_thread` is the right pattern for 6 independent blocking I/O calls. Result sets are capped at 10 per source before serialization. No inefficiencies found at production scale.

**Identity tools**: Direct delegation — no extra work.

### Robust

**Double error handling in identity_tools.py**: Each tool function has both `@tool_errors("Identity error")` at the decorator level AND an inner `try/except Exception as e: return json.dumps({"error": str(e)})`. The inner catch always fires first, so the decorator's error handler never activates for store exceptions. The practical consequence is that store exceptions are silently returned as bare `{"error": "..."}` without server-side logging (`logger.exception` in the decorator is bypassed). This degrades observability — errors from the store layer are invisible in server logs.

**Enrichment**: Error isolation per fetcher is correct and well-tested. Each fetcher is wrapped in `try/except Exception` and logs at DEBUG level on failure, returning `None` so the gather result is gracefully skipped. One concern: the DEBUG log level for fetcher failures means production errors (e.g., DB lock, unavailable service) generate no visible signal. A user calling `enrich_person` gets back a partial result with no indication of which sources failed.

**No input validation**: Neither file validates inputs before passing them to the store. Empty string `name` in `enrich_person` would produce a vacuously empty result with no error. Empty `canonical_name` in `link_identity` would insert a row with an empty canonical name — the store schema does not have a NOT NULL constraint check here (store layer may or may not enforce this).

### Architecture

**Redundant decorator in identity_tools.py**: The `@tool_errors` decorator was clearly designed so tool functions do NOT need inner try/except — the decorator is the error boundary. All other tool modules in the codebase follow this pattern (happy-path body only). `identity_tools.py` is the outlier: it has both, making the decorator dead weight for exception handling and silently disabling its logging behavior.

**Enrichment source gap — Teams and Calendar**: The docstring for `enrich_person` states "Get a consolidated profile... identities, facts, delegations, decisions, recent messages, and emails." The CLAUDE.md architecture table says "6 sources" but the CLAUDE.md module description line says "parallel person data fetching from 6 sources". The actual 6 sources are: identity, facts, delegations, decisions, iMessages, email. However, Teams and Calendar are named as dependencies for this chunk but are NOT fetched. This is not a bug per se (the tool does what it says), but the tool's utility for M365-heavy environments is limited — a Teams DM or calendar event with the person would not appear in the enrichment output.

**Fetcher closure design**: The 6 fetcher functions in `enrich_person` are defined as sync closures inside an async function and pushed to threads via `asyncio.to_thread`. This is architecturally clean and avoids threading issues with the asyncio event loop. The closures capture `state`, `name`, and `minutes` from the enclosing scope — no shared mutable state between fetchers.

## Findings

### Critical
- (none)

### Warning

- **`mcp_tools/identity_tools.py:32-42` (and lines 54-60, 71-74, 85-88)** — Inner `try/except` inside each tool function pre-empts the `@tool_errors` decorator's `logger.exception` call. Store-layer exceptions are returned as `{"error": str(e)}` with no server-side log entry. In production, a failing identity operation leaves no trace in server logs. Fix: remove the inner try/except blocks from all four tool functions and let `@tool_errors` handle exceptions as designed, or add explicit `logger.exception` calls inside the inner catch.

- **`mcp_tools/enrichment.py:93-103` — `fetch_emails` only searches Apple Mail INBOX** — `mail_store.search_messages(name, limit=10)` maps to `AppleMail.search_messages(query, mailbox="INBOX")`. Sent items, archive, and work mailboxes are not searched. The tool docstring claims "emails" without qualification. In an M365-heavy environment with Apple Mail not configured, `mail_store` is `None` and emails are silently skipped entirely — no M365 email source is wired into enrichment.

- **`mcp_tools/enrichment.py:36-103` — Fetcher failures logged at DEBUG only** — All 6 fetchers catch `Exception` and log at `logger.debug(...)`. A DB lock, schema error, or store misconfiguration produces no WARNING or ERROR log. Operators have no visibility into degraded enrichment results. Recommend WARNING level for unexpected exceptions (as distinct from "store is None" which is expected and should remain silent).

### Note

- `identity_tools.py` has no input validation for empty strings. `link_identity(canonical_name="", ...)` will insert a row with an empty canonical name. Whether this is blocked at the DB constraint level should be verified in `memory/store.py`.
- `enrich_person` with `days_back=0` passes `minutes=0` to `messages_store.search_messages`. The iMessage store handles this via `_normalize_minutes` which clamps to a minimum — behavior is safe but semantically odd (searching 0 days back returns nothing or a clamped window).
- The `context = {"name": name}` dict in `enrich_person` is returned even when all 6 fetchers fail or return empty — callers always get at least `{"name": "..."}` with no error signal. This is a design choice (silent degradation) but could mask total failures.
- Teams and Calendar are listed as dependencies for this chunk in the assignment but are not actually used by either file. If enrichment is ever extended to include Teams messages or calendar events with a person, the parallel fetcher pattern makes this straightforward to add.

### Nothing to flag

- Syntax: both files compile clean with no errors.
- Test coverage: 53 tests, all passing. Happy path, error isolation, capping, and days_back parameter are all covered.
- Parallel fan-out implementation in `enrich_person` is correct and efficient.
- Module-level tool exposure via `sys.modules[__name__]` is consistent with project conventions.

## Verdict

Both files are fully implemented and functionally correct for their stated purpose, with all 53 tests passing. The primary concern is observability: identity tool exceptions silently bypass server-side logging due to redundant inner try/except blocks that shadow the `@tool_errors` decorator, and enrichment fetcher failures are logged only at DEBUG. Neither issue causes data corruption or user-visible failures, but both degrade the ability to diagnose problems in production. The enrichment tool's email source only covers Apple Mail INBOX and has no M365 email path, which limits its utility in the target (M365-heavy) environment.
