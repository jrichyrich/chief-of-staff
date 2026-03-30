# Chunk Audit: MCP Server Core

**User-facing feature**: Infrastructure — all MCP tool calls flow through here
**Risk Level**: High
**Files Audited**:
- `mcp_server.py`
- `mcp_tools/__init__.py`
- `mcp_tools/state.py`
- `mcp_tools/decorators.py`
- `mcp_tools/usage_tracker.py`
- `mcp_tools/resources.py`
- `mcp_tools/api_usage_tools.py`
- `config.py`

**Status**: Complete

---

## Purpose (as understood from reading the code)

This chunk is the entry point and infrastructure backbone of the Jarvis MCP server. `mcp_server.py` initializes all stores via a FastMCP lifespan manager, registers 28 tool modules, and installs a usage-tracking middleware that wraps `ToolManager.call_tool`. `ServerState` is a typed dataclass holding all shared stores, passed by reference to every tool module. `config.py` is a pure settings file sourcing from environment variables and a keychain helper. `usage_tracker.py` is middleware that captures timing, fires hooks, and records invocations. No divergence from the intent map description.

---

## Runtime Probe Results

- **Tests found**: Yes — `test_mcp_server.py`, `test_usage_tracker.py`, `test_api_usage_tools.py`, `test_config_graph.py`, `test_config_proactive_action.py`, `test_config_synthesis.py`
- **Tests run**: 161 passed, 0 failed
- **Import/load check**: OK — `mcp_tools.state`, `mcp_tools.decorators`, `mcp_tools.usage_tracker`, `config` all import cleanly
- **Type check**: Not run (mypy not installed in project venv)
- **Edge case probes**: `_extract_query_pattern` handles None, empty dict, whitespace-only values, non-string values, and very long strings correctly. `SessionHealth.to_dict()` returns `None` for `last_checkpoint` when never set. `_retry_on_transient` correctly retries 3 times total (initial + 2 retries) and re-raises after exhaustion.
- **Key observation**: `DISPATCH_SYNTHESIS_MAX_TOKENS = int(os.environ.get(...))` at `config.py:102` has no try/except guard. A non-integer env var value causes a `ValueError` at import time, crashing the entire server before it starts.

---

## Dimension Assessments

### Implemented

All 28 tool modules are registered. The lifespan manager fully initializes all stores, seeds default scheduled tasks, loads session context, and optionally initializes the Graph API client. `SessionHealth`, `ServerState`, `_retry_on_transient`, `tool_errors`, `install_usage_tracker` are all implemented with real logic. No stubs or TODOs anywhere in the chunk files.

The `mcp_tools/__init__.py` is a single-line docstring with no exports — this is correct since modules register themselves by calling `register(mcp, state)`.

### Correct

**Logic is mostly correct** with three specific issues:

1. **resources.py `get_all_facts` hardcodes 4 categories** (`resources.py:13`), excluding `"backlog"`. The `VALID_FACT_CATEGORIES` frozenset (confirmed via probe) contains 5 categories: `personal`, `preference`, `work`, `relationship`, `backlog`. Any facts stored under `"backlog"` are silently excluded from `memory://facts` resource reads. The per-category resource `memory://facts/{category}` does work for `backlog` (it calls `get_facts_by_category(category)` directly), so the gap is only in the catch-all resource.

2. **CLAUDE.md documents `facts://all`** as the resource URI, but the actual implementation registers `memory://facts` (`resources.py:9`). The documented URI does not exist. Any integration or documentation relying on `facts://all` will fail silently (FastMCP returns an error for unknown resource URIs, which the host silently drops).

3. **api_usage_tools.py double error handling** (`api_usage_tools.py:31-51` and `75-88`): each tool function has both `@tool_errors("API usage error")` and an inner `try/except Exception`. The inner except catches the exception, logs it via `logger.exception`, and returns an error JSON. The outer `@tool_errors` decorator never fires because the exception is already consumed. The `@tool_errors` decorator is dead code for these two tools. This is a correctness issue in that duplicate error-handling paths were intended to cooperate but don't.

### Efficient

No efficiency concerns. Store initialization happens once at startup. `ServerState._field_names()` uses `@functools.cache` to avoid re-computing the dataclass fields set. `_retry_on_transient` uses `time.sleep()` (synchronous) for a synchronous retry helper — appropriate since all callers wrap synchronous store methods from async tool handlers.

`usage_tracker.py` computes `len(str(result).encode("utf-8"))` for every successful tool call to record response size (`usage_tracker.py:122`). The `str(result)` conversion on large tool results (e.g., a full calendar listing) happens on every call. This is a minor overhead but acceptable for instrumentation purposes.

### Robust

**Five robustness issues found:**

1. **`config.py:102` — unguarded `int()` at module level**: `DISPATCH_SYNTHESIS_MAX_TOKENS = int(os.environ.get("DISPATCH_SYNTHESIS_MAX_TOKENS", "1024"))` has no try/except. Other similar conversions in the same file are protected (e.g., lines 57-59, 63-65, 124-131). Additional unguarded `int()` calls: `line 52` (`DAEMON_TICK_INTERVAL_SECONDS`), `line 159` (`AGENT_BROWSER_TIMEOUT`), `line 197` (`IMESSAGE_DAEMON_POLL_INTERVAL_SECONDS`), `line 198` (`IMESSAGE_DAEMON_BOOTSTRAP_LOOKBACK_MINUTES`). A misconfigured env var crashes the entire MCP server at import time with a `ValueError` before any tool can execute.

2. **`resources.py:12-18` — null dereference on `memory_store`**: `get_all_facts()` and `get_facts_by_category()` call `memory_store.get_facts_by_category(...)` without a null check. If called before lifespan completes (or after shutdown), this raises `AttributeError: 'NoneType' object has no attribute 'get_facts_by_category'`. The `get_session_context` resource at line 48 wraps each call in `try/except` — the same pattern should apply to all resource handlers. Same issue at `resources.py:32-33` for `agent_registry`.

3. **`mcp_server.py:250` — session_start hooks fire outside try/finally**: The `hook_registry.fire_hooks("session_start", ...)` call happens after all initialization, before `yield`. This is inside the lifespan context manager, so the pattern is technically correct — but if a session_start hook raises an uncaught exception, it will crash the lifespan startup without running the `finally:` block (since the `try: yield` hasn't been entered yet). The `fire_hooks` method in `hooks/registry.py` is documented as error-isolated, so this is low-risk in practice, but worth noting.

4. **`mcp_server.py:265-281` — `agent_browser` and `session_health` not reset in lifespan finally**: The `finally:` block resets 16 of 18 `ServerState` fields to `None`. `agent_browser` and `session_health` are not reset. For `agent_browser`, this could leave a zombie browser process reference across MCP server restarts (if the MCP process doesn't fully exit between server restarts, which can happen in development). For `session_health`, the tool call counter accumulates across sessions — whether this is intentional is unclear from the code.

5. **`usage_tracker.py:89` — tracked_call_tool missing return for excluded tools path**: When `name` is in `_EXCLUDED_TOOLS` (line 165), the `else` branch returns `await original_call_tool(...)`. But the happy path through the main `if` block has an explicit `return result` inside the `try:` at line 125. If an excluded tool raises an exception, it correctly propagates. If a non-excluded tool raises, `success = False` is set and the exception re-raises. This is structurally correct, but the main `if` block never explicitly `return`s on the exception path — the `raise` inside `except Exception` handles that. Correct, just complex.

### Architecture

**Structure is clean overall.** The lifespan-based initialization is a sound pattern for FastMCP. Tool module registration via `register(mcp, state)` functions keeps modules decoupled and independently testable. `ServerState` as a typed dataclass with dict-style backward-compat accessors is an acceptable evolution strategy.

**One architectural concern**: `usage_tracker.py` hooks into `mcp._tool_manager`, a private attribute of the FastMCP library (`mcp.server.fastmcp.tools.tool_manager.ToolManager`). The comment at line 67-74 explains why this is necessary (the public `call_tool` is captured in a closure). This is correct reasoning, but it creates a coupling to FastMCP internals that could break on library upgrades. There's no version pin or assertion to catch breakage. Confirmed that `mcp._tool_manager.call_tool` exists in the installed version.

**Minor duplication**: `api_usage_tools.py` duplicates the `@tool_errors` + inner `try/except` pattern inconsistently with every other tool module in the codebase. Other modules use `@tool_errors` exclusively. This creates confusion about the intended error handling contract.

---

## Findings

### 🔴 Critical

- **`config.py:102`** — `DISPATCH_SYNTHESIS_MAX_TOKENS = int(os.environ.get("DISPATCH_SYNTHESIS_MAX_TOKENS", "1024"))` has no try/except guard. If this env var is set to a non-integer value, the entire MCP server fails to start with a `ValueError` at import time. Five env vars in config.py have this pattern while nearby vars are protected: lines 52, 102, 159, 197, 198. Other vars in the same file have consistent `try/except ValueError` guards — these appear to have been missed during additions.

### 🟡 Warning

- **`resources.py:13`** — `get_all_facts` hardcodes `["personal", "preference", "work", "relationship"]`, excluding the `"backlog"` category that exists in `FactCategory` and `VALID_FACT_CATEGORIES`. Facts stored as `backlog` are silently absent from the `memory://facts` resource. They ARE accessible via `memory://facts/backlog` directly.

- **`resources.py:12-18`, `resources.py:24-27`, `resources.py:32-33`** — `get_all_facts`, `get_facts_by_category`, and `get_agents_list` call `state.memory_store` and `state.agent_registry` without null checks. The companion `get_session_context` resource wraps all store access in `try/except`. An `AttributeError` on `NoneType` will surface as an unhandled exception from the resource handler if called before lifespan completes.

- **`CLAUDE.md:72` vs `resources.py:9`** — Documentation states resource URI `facts://all` but code registers `memory://facts`. The documented URI does not exist. Any consumer using the documented URI will get a silent failure.

- **`mcp_server.py:265-281`** — `agent_browser` is not reset to `None` in the lifespan `finally:` block. Could leave a stale browser reference on server restart in environments where the process is reused.

- **`api_usage_tools.py:31-51`, `75-88`** — Double error handling: `@tool_errors` decorator is dead code because inner `try/except` blocks consume all exceptions before they reach the decorator. Each error path also calls `logger.exception` once from the inner block and once would be called from the decorator — but since the decorator never fires, this is just dead code rather than double-logging. The inconsistency with all other tool modules creates a maintenance trap.

- **`usage_tracker.py:82`** — `mcp._tool_manager` is a private attribute of FastMCP. The code correctly explains why it's necessary, but there is no runtime assertion or version check to catch breakage on FastMCP upgrades.

### 🟢 Note

- `SessionHealth` is not reset in the lifespan `finally:` block (`mcp_server.py:265-281`). This may be intentional — cumulative tool call counts across the server lifetime. But if the intent is per-session tracking, this is a bug.

- `_retry_on_transient` is synchronous (uses `time.sleep`). All current callers wrap synchronous store operations from within async tool handlers, so this is correct. Future callers wrapping async coroutines would need an async version.

- `config.py` is loaded at import time (no lazy initialization). The `from memory.models import FactCategory` at `config.py:31` creates a circular import risk if `memory.models` ever imports from `config`. Currently safe but worth watching.

- The `install_usage_tracker` idempotency check at `usage_tracker.py:83` (`if getattr(tool_mgr.call_tool, "_usage_tracked", False)`) is correct and well-implemented.

### ✅ Nothing to flag

- All 8 files pass Python syntax checks cleanly.
- All 161 tests in the chunk's test files pass.
- `tool_errors` decorator in `decorators.py` correctly separates expected from unexpected exceptions, logs unexpected ones, and returns structured error JSON — clean and simple.
- `ServerState._field_names()` uses `@functools.cache` correctly (it's a `@staticmethod @cache` returning a frozenset — immutable result, safe to cache forever).
- No hardcoded secrets or credentials anywhere in the chunk.
- `_extract_query_pattern` handles all edge cases (None, empty, whitespace, non-string, oversized) gracefully.
- The `mcp._tool_manager.call_tool` wrapping approach is correctly explained and idempotent.
- Lifespan initialization order is sensible: stores first, then hooks, then session infrastructure, then optional Graph API client.

---

## Verdict

The MCP server core is functionally complete, well-tested (161/161 passing), and architecturally sound. The most urgent issue is five unguarded `int()` conversions in `config.py` that will crash the server at import time if a misconfigured env var is set — especially `DISPATCH_SYNTHESIS_MAX_TOKENS` which is a recently added feature flag without the try/except guard that all nearby vars have. A secondary concern is that `resources.py`'s two synchronous fact-fetching resources (`memory://facts` and `memory://facts/{category}`) will raise `AttributeError` on `NoneType` if called before/after lifespan, unlike `session://context` which defensively wraps all access — this should be made consistent. The `api_usage_tools.py` double error handler and the `facts://all` URI documentation mismatch are housekeeping items.
