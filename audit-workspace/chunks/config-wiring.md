# Chunk Audit: Config & Server Wiring

**Date**: 2026-03-12
**Scope**: Configuration, backend selection, GraphClient lifecycle
**Risk Level**: MEDIUM

## Dimension Scores

| Dimension | Score (1-5) | Notes |
|-----------|-------------|-------|
| Correctness | 4 | Backend selection logic is sound; one inconsistency with deprecated var |
| Reliability | 3 | Import-time Keychain subprocess is cached but still a cold-start risk; close() unguarded |
| Security | 4 | Secrets not logged; client_secret stored in config module attribute is a minor concern |
| Testability | 4 | Good coverage of backend selection matrix; missing edge cases noted below |
| Maintainability | 3 | Deprecated TEAMS_POSTER_BACKEND still actively used in production code paths |

---

## Findings

### F1. `_get_backend()` still reads deprecated `TEAMS_POSTER_BACKEND` -- config split inconsistency

- **File**: `/Users/jasricha/Documents/GitHub/chief_of_staff/mcp_tools/teams_browser_tools.py`, lines 44-46
- **Severity**: Medium
- **Status**: Confirmed
- **Detail**: Three browser-related functions (`_get_poster()` line 86, `open_teams_browser` line 258, `close_teams_browser` line 380) call `_get_backend()`, which reads `config.TEAMS_POSTER_BACKEND`. Meanwhile, the *send* path (`_get_send_backend()` line 49) reads `config.TEAMS_SEND_BACKEND`. The problem: `TEAMS_POSTER_BACKEND` on config.py line 178 defaults to `"agent-browser"` unconditionally, while `TEAMS_SEND_BACKEND` on line 170-173 defaults to `"graph"` when Graph credentials are present. This means if a user sets no env vars but has Graph credentials: sending goes through Graph, but `open_teams_browser`/`close_teams_browser`/`_get_poster()` always use `"agent-browser"`. The poster created by `_get_poster()` may never be needed if `_get_send_backend()` returns `"graph"`, but the browser open/close tools will always report `agent-browser` backend regardless of send backend config. The deprecated var should be removed and all call sites migrated to `TEAMS_SEND_BACKEND`.

### F2. `config.TEAMS_POSTER_BACKEND` (line 178) is not dead code -- still consumed

- **File**: `/Users/jasricha/Documents/GitHub/chief_of_staff/config.py`, line 178
- **Severity**: Low
- **Status**: Confirmed
- **Detail**: Despite the deprecation comment, `TEAMS_POSTER_BACKEND` is imported directly by `teams_browser_tools.py:45`. It also serves as the env-var fallback for `TEAMS_SEND_BACKEND` on line 172. The variable should remain until all consumers are migrated, but should be marked more prominently (e.g., emit a deprecation warning at import time) to prevent new usage.

### F3. `M365_CLIENT_SECRET` exposed as module-level config attribute

- **File**: `/Users/jasricha/Documents/GitHub/chief_of_staff/config.py`, line 165
- **Severity**: Low
- **Status**: Confirmed
- **Detail**: `M365_CLIENT_SECRET = get_secret("m365_client_secret") or ""` stores the secret as a plain string in `config.M365_CLIENT_SECRET`, accessible to any module that imports config. However, no code outside of config.py actually reads this attribute -- `GraphClient.__init__` (graph_client.py line 116) independently calls `get_secret("m365_client_secret")`. The config attribute is therefore unused *and* unnecessarily keeps the secret in memory at module scope. Recommend removing it from config.py or converting it to a lazy accessor.

### F4. `get_secret()` subprocess at import time -- mitigated but not zero-cost

- **File**: `/Users/jasricha/Documents/GitHub/chief_of_staff/config.py`, lines 163-165
- **Severity**: Low
- **Status**: Confirmed (mitigated)
- **Detail**: Three `get_secret()` calls execute at config import time. The `vault/keychain.py` module-level `_cache` dict prevents repeated subprocess calls for the same key across multiple imports. First import still spawns up to 3 `security find-generic-password` subprocesses (one per key). On a healthy macOS system this takes <100ms total, but if Keychain is locked or the system is under I/O pressure, each call blocks the importing thread with no timeout. `subprocess.run()` on line 46 of `vault/keychain.py` has no `timeout` parameter. Consider adding `timeout=5` to the subprocess call to prevent indefinite hangs during MCP server startup.

### F5. GraphClient `interactive=True` default in MCP stdio server context

- **File**: `/Users/jasricha/Documents/GitHub/chief_of_staff/mcp_server.py`, lines 204-208
- **Severity**: Medium
- **Status**: Confirmed
- **Detail**: `GraphClient` is constructed without passing `interactive`, so it defaults to `True`. In interactive mode, if the cached token expires and silent refresh fails, the client triggers a device-code flow that prints to stderr and blocks waiting for user browser action (graph_client.py lines 277-290). During MCP stdio transport, stderr output may be lost or unexpected, and the blocking wait will freeze all tool calls. This is mitigated by MSAL's persistent token cache (tokens typically last 90 days), but when the token *does* expire, the server becomes unresponsive. Consider passing `interactive=False` for the MCP server context and handling `GraphAuthError` gracefully with a user-facing message to re-authenticate manually.

### F6. `graph_client.close()` not wrapped in try/except in shutdown

- **File**: `/Users/jasricha/Documents/GitHub/chief_of_staff/mcp_server.py`, lines 226-228
- **Severity**: Medium
- **Status**: Confirmed
- **Detail**: In the `finally` block:
  ```python
  if _state.graph_client:
      await _state.graph_client.close()
  ```
  If `close()` raises (e.g., httpx runtime error on an already-closed client, or event loop issues), it will propagate out of the `finally` block and prevent the remaining cleanup: `_state` field resets (lines 231-246) and `memory_store.close()` (line 247). The `memory_store.close()` call flushes SQLite WAL and is important for data integrity. Wrap in `try/except`:
  ```python
  if _state.graph_client:
      try:
          await _state.graph_client.close()
      except Exception:
          logger.warning("Failed to close Graph client", exc_info=True)
  ```

### F7. `M365_CLIENT_SECRET` fetched twice -- once in config.py, once in GraphClient

- **File**: `/Users/jasricha/Documents/GitHub/chief_of_staff/config.py` line 165 and `/Users/jasricha/Documents/GitHub/chief_of_staff/connectors/graph_client.py` line 116
- **Severity**: Low
- **Status**: Confirmed
- **Detail**: `config.py` calls `get_secret("m365_client_secret")` at import time (line 165) and stores the result. `GraphClient.__init__` independently calls `get_secret("m365_client_secret")` (line 116). Due to the vault cache, the second call returns the cached value, so there is no performance issue. However, `config.M365_CLIENT_SECRET` is unused by any consumer, making the config.py fetch purely wasteful. If the config attribute were removed (per F3), GraphClient's own fetch would be the single source of truth.

### F8. Test file does not cover GraphClient initialization or lifecycle

- **File**: `/Users/jasricha/Documents/GitHub/chief_of_staff/tests/test_config_graph.py`
- **Severity**: Low
- **Status**: Confirmed
- **Detail**: The test file covers config attribute values and backend selection well (5 test classes, 11 tests). However, there are no tests for:
  - GraphClient initialization path in `mcp_server.py` lines 200-213 (ImportError fallback, generic Exception fallback)
  - GraphClient shutdown in the finally block (close() success, close() raising)
  - The `M365_GRAPH_ENABLED` flag correctly gating GraphClient creation
  - `_reload_config()` helper (line 10-26) is defined but never called -- all tests inline their own reload logic. This is a minor DRY issue, not a correctness bug.

### F9. No subprocess timeout in vault/keychain.py

- **File**: `/Users/jasricha/Documents/GitHub/chief_of_staff/vault/keychain.py`, line 46
- **Severity**: Low
- **Status**: Confirmed
- **Detail**: `subprocess.run()` call to `security find-generic-password` has no `timeout` parameter. If the macOS Security framework hangs (e.g., Keychain locked requiring GUI unlock, FileVault unlocking), the MCP server startup blocks indefinitely. Adding `timeout=5` would allow graceful fallback to env vars.

---

## Summary

The config and server wiring is fundamentally sound. The main actionable findings are:

1. **F6 (Medium)**: Wrap `graph_client.close()` in try/except to protect downstream cleanup (memory_store.close). Easy fix, high impact on reliability.
2. **F5 (Medium)**: Consider `interactive=False` for MCP server GraphClient to prevent blocking device-code flow during stdio transport.
3. **F1 (Medium)**: Complete the `TEAMS_POSTER_BACKEND` -> `TEAMS_SEND_BACKEND` migration in `teams_browser_tools.py`. Three call sites still use the deprecated path.
4. **F3 + F7 (Low)**: Remove unused `M365_CLIENT_SECRET` from config.py -- it keeps a secret in module scope with no consumer.
5. **F4 + F9 (Low)**: Add `timeout=5` to `subprocess.run()` in `vault/keychain.py` to prevent startup hangs.
