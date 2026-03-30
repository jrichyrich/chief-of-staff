# Chunk Audit: Utilities & Infrastructure

**User-facing feature**: Infrastructure — supports all other chunks; affects every outbound message (humanizer), every secret lookup (vault), every delivery channel (scheduled tasks), and tool-call observability (hooks)
**Risk Level**: Medium
**Files Audited**:
- `utils/__init__.py` (empty)
- `utils/atomic.py`
- `utils/osascript.py`
- `utils/retry.py`
- `utils/subprocess.py`
- `utils/text.py`
- `vault/__init__.py`
- `vault/keychain.py`
- `hooks/__init__.py`
- `hooks/builtin.py`
- `hooks/registry.py`
- `humanizer/__init__.py`
- `humanizer/hook.py`
- `humanizer/rules.py`
- `delivery/__init__.py`
- `delivery/service.py`

**Status**: Complete

---

## Purpose (as understood from reading the code)

This chunk provides foundational infrastructure used throughout the system: atomic file I/O with flock-based locking, macOS Keychain secret retrieval with env var fallback, Anthropic API retry logic with exponential backoff, subprocess execution with process-group cleanup, AppleScript string escaping, rule-based text humanization for outbound communications, a plugin hook system for tool-call lifecycle events, and delivery adapters for routing scheduled task results to email, iMessage, macOS notifications, and Teams.

All modules are well-scoped to single responsibilities. No divergence from the stated purpose.

---

## Runtime Probe Results

- **Tests found**: Yes — `test_delivery.py`, `test_hook_registry.py`, `test_humanizer.py`, `test_humanizer_hook.py`, `test_keychain.py`, `test_retry.py`
- **Tests run**: 166 passed, 0 failed
- **Import/load check**: PARTIAL — direct import of `utils.retry` fails outside the virtualenv (`No module named 'anthropic'`); imports succeed correctly inside the project virtualenv
- **Type check**: Not run (mypy/pyright not in project dev deps)
- **Edge case probes**: Multiple probes run — see findings below
- **Key observation**: Three confirmed runtime bugs found via probing: (1) `escape_osascript(None)` raises `AttributeError`; (2) `split_addresses(None)` raises `AttributeError`; (3) `fire_hooks()` silently returns unawaited coroutine objects when async callbacks are registered, with no warning or error.

---

## Dimension Assessments

### Implemented

All declared functions and classes are fully implemented with real logic — no stubs, no `pass`-only bodies. The one `raise NotImplementedError` at `delivery/service.py:62` is correct: it's the abstract base class `DeliveryAdapter.deliver()` requiring subclass override. All four subclasses implement it.

The hook system is fully wired: `mcp_server.py` instantiates `HookRegistry`, loads YAML configs, passes it into `ServerState`, `usage_tracker.py` calls `fire_hooks()` for MCP tool calls, and `agents/base.py` calls it for agent tool calls. The MEMORY.md note about "fire_hooks not called by usage_tracker" is now outdated — it is wired.

### Correct

Main happy paths are correct. The atomic write pattern (tmpfile → fsync-less `os.replace`) is correct for atomicity. The retry decorator correctly implements exponential backoff (1s, 2s, 4s) with proper exception re-raise after exhaustion. The humanizer rule pipeline correctly chains all rules sequentially.

**Two confirmed bugs:**

1. `escape_osascript(None)` raises `AttributeError: 'NoneType' object has no attribute 'replace'`. The function signature says `text: str` but has no None guard. Callers in `apple_mail/mail.py` (e.g. `optional_subtitle`) pass potentially-None values.

2. `split_addresses(None)` raises `AttributeError: 'NoneType' object has no attribute 'split'`. Callers in `mcp_tools/mail_tools.py:182-183` guard with `if cc else None` but `agents/mixins.py:280-281` calls `_split_addresses(tool_input.get("cc", ""))` which is safe (defaults to `""`). Low-severity given current callers, but the function lacks a None guard.

3. **Humanizer double-replacement**: `humanize("utilize leverage")` returns `"use use"`. The rules run sequentially — "utilize" → "use", then "leverage" → "use" — producing nonsense. In practice this phrase is unlikely but demonstrates the pipeline doesn't check for cascading replacements.

### Efficient

All functions are appropriately efficient for their use patterns.

**One genuine inefficiency**: `vault/keychain.py` does not cache `None` results (line 49-51: `if value is not None: _cache[key] = value`). Every call for a missing secret re-invokes `subprocess.run("security find-generic-password ...")`, which costs ~5-10ms each. If `config.py` is re-evaluated at import time in multiple module contexts, this could add up. A TTL-based negative cache (even 60 seconds) would eliminate the subprocess overhead for known-missing keys. Not critical at current scale but worth noting.

**Module-level `_timing_store` dict** in `hooks/builtin.py` is an unbounded in-memory dict. Under normal operation it stays near-empty (before/after pairs cancel). But if a tool call raises before `after_tool_call` fires, the entry is leaked permanently. Probe confirmed: 100 abandoned before-hooks leave 100 permanent entries in `_timing_store`. At production volume this accumulates.

### Robust

**`utils/subprocess.py` — SIGTERM-only cleanup gap**: `run_with_cleanup` sends `SIGTERM` to the process group on timeout, then calls `proc.wait(timeout=5)`. If the child process ignores `SIGTERM` (which user-space processes can), `proc.wait()` raises another `TimeoutExpired`. This second exception propagates to the caller, but the process is NOT killed — it continues running as an orphan. The standard pattern is `SIGTERM → wait(5) → except TimeoutExpired → SIGKILL`. The current code only does the first two steps.

**`hooks/registry.py` — async callbacks silently uncalled**: `fire_hooks()` calls callbacks synchronously (`entry["callback"](dict(context))`). An async callback returns a coroutine object that is never awaited. The result is stored in the results list and no exception is raised. The coroutine runs zero of its actual logic. This is a silent failure mode — confirmed by runtime probe. The docstring says "May be sync or async" which creates a misleading contract.

**`vault/keychain.py` — None not cached creates subprocess amplification**: Covered under Efficiency above.

**`delivery/service.py` — `_build_template_vars` uses naive datetime**: Line 216 uses `datetime.now().isoformat()` (naive, local timezone). Scheduled delivery results that span timezone boundaries will have ambiguous timestamps. Minor in practice.

**`utils/atomic.py` — `locked_read` opens lock_path with `'w'` mode**: This truncates the lockfile on every read (line 35). Since fcntl advisory locking doesn't care about file content this is harmless, but it's semantically wrong — a shared reader should not truncate the shared lockfile. If any future code tries to store state in the lockfile, this will silently corrupt it.

### Architecture

The chunk is well-organized with clear single-responsibility modules. Each module is small (<220 lines), and functions are focused.

**`delivery/__init__.py` leaks a private function**: It imports `_build_template_vars` from `delivery/service.py` but excludes it from `__all__`. The name is still accessible as `delivery._build_template_vars`. This is a minor encapsulation leak — `_build_template_vars` is an internal helper and should not be re-exported from the package `__init__`.

**`hooks/registry.py:163` — `load_configs` uses `importlib.import_module` inside the function body**: The import is placed inside a helper function (`_import_handler`), which is fine, but the import statement itself (`import importlib`) is inside the function body (line 169). This works but is atypical — standard practice is to import at module level. No functional issue.

**`humanizer/rules.py` — vocabulary swaps have no cascade protection**: Rules are applied in sequence and can interact. The "leverage → use" and "utilize → use" substitutions can produce "use use" from "utilize leverage". At scale with more rules this grows worse. A single-pass approach (using a combined regex with a dispatch dict) would prevent cascades.

**`delivery/service.py` — `TeamsDeliveryAdapter._get_poster()`**: Instantiates a new `PlaywrightTeamsPoster` and `TeamsBrowserManager` on every delivery call. No session reuse. This is correct given the stateful browser model elsewhere but means every Teams delivery cold-starts a browser session.

---

## Findings

### 🔴 Critical

- **`utils/subprocess.py:22-23`** — SIGTERM-only process cleanup: after `os.killpg(..., SIGTERM)`, `proc.wait(timeout=5)` can raise `TimeoutExpired` if the process ignores SIGTERM. The second `TimeoutExpired` propagates to the caller but the zombie process is never SIGKILL'd. The caller (e.g. scheduler) thinks the task timed out but the child process continues running indefinitely. Fix: catch the second `TimeoutExpired` and escalate to `SIGKILL`.

### 🟡 Warning

- **`hooks/registry.py:87`** — `fire_hooks()` does not handle async callbacks: calling an async function returns a coroutine that is silently stored in results and never executed. The docstring at line 51 says callbacks "May be sync or async" — this is incorrect. Any async hook registered via `register_hook()` silently does nothing. Fix: add an `asyncio.iscoroutine()` check and either await the result or raise a `TypeError` at registration time.

- **`hooks/builtin.py:17`** — `_timing_store` leaks on unmatched before/after pairs: if a tool call raises before `after_tool_call` fires, the before-timing entry is never removed. In a long-running daemon this accumulates without bound. Fix: add a periodic cleanup (e.g. evict entries older than 60 seconds in `timing_after_hook`).

- **`utils/osascript.py:4`** — `escape_osascript(None)` raises `AttributeError`: the function calls `.replace()` on the input with no null guard. Callers in `apple_mail/mail.py` pass optional fields that could be `None`. An unescaped None passed to AppleScript would likely produce a script error or inject `"None"` as a literal string. Fix: add `if text is None: return ""` guard.

- **`vault/keychain.py:49`** — None not cached causes repeated subprocess calls: missing secrets hit `subprocess.run("security find-generic-password ...")` on every call (~5-10ms each). If called frequently for absent keys this adds measurable latency. Fix: implement a short-lived negative cache (e.g. TTL of 60s).

### 🟢 Note

- `utils/text.py:4` — `split_addresses(None)` raises `AttributeError`. Current callers guard against this, but a `None` guard would make the function defensive by design.

- `delivery/__init__.py:12` — `_build_template_vars` is imported and thereby exposed as `delivery._build_template_vars` despite being excluded from `__all__`. Remove the import from `__init__.py` since no external code should need it.

- `utils/atomic.py:35` — `locked_read` opens `lock_path` with `'w'` mode, truncating the shared lockfile. Functionally harmless for advisory locking but semantically wrong. Should use `'a'` or `'r+'` mode (or open with `open(lock_path, 'w')` in `atomic_write` only and `open(lock_path, 'r+')` or `'a'` in `locked_read`).

- `humanizer/rules.py` — Rule cascade: applying "utilize" and "leverage" substitutions sequentially produces "use use" from "utilize leverage". Not a production-breaking bug but could appear in formal communications. A single-pass combined regex would prevent this class of issue.

- `delivery/service.py:216` — `datetime.now()` uses naive local timezone. Use `datetime.now(timezone.utc)` for unambiguous timestamps in delivery records.

---

## Verdict

This chunk is largely well-implemented and passing 166 tests cleanly. The most important issue is the SIGTERM-only subprocess cleanup in `utils/subprocess.py` — it can leave zombie processes running after a timeout, which accumulates over time in the scheduler daemon. The async callback silent-failure in `hooks/registry.py` is a correctness trap: the docstring advertises async support but the implementation silently drops async hooks. Both should be fixed. The remaining issues (None guards, timing_store leak, None caching) are low-severity but worth addressing before the daemon runs at production scale.
