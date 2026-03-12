# Consolidated Audit Report: Microsoft Graph API Integration

**Date**: 2026-03-12
**Auditor**: Synthesis Agent (Claude Opus 4.6)
**Scope**: vault/, connectors/graph_client.py, mcp_tools/teams_browser_tools.py, mcp_tools/mail_tools.py, config.py, mcp_server.py

---

## Summary

6 source reports (5 chunk audits + 1 security audit) produced 43 raw findings. After deduplication, **35 unique findings** remain: 1 critical, 8 high, 14 medium, 12 low.

### Cross-Cutting Patterns

1. **Silent data loss on Graph paths**: BCC dropped on send, reply_all/cc/bcc dropped on reply. The Graph backend was added without updating the `GraphClient` method signatures to match the full parameter surface.
2. **Exception handling gaps in fallback logic**: Teams and email fallback handlers catch specific Graph exceptions but miss `httpx` network errors, `GraphAPIError` (non-transient 4xx), and programming bugs. Unexpected exceptions either skip fallback entirely or silently fall through.
3. **Subprocess timeout missing everywhere**: All `subprocess.run()` calls in vault/keychain.py and scripts/bootstrap_secrets.py lack `timeout`. Found independently by vault, config, and security agents.
4. **Deprecated config split**: `TEAMS_POSTER_BACKEND` vs `TEAMS_SEND_BACKEND` creates a confusing dual-config path. Found by teams and config agents.
5. **Secrets held at module scope**: `config.M365_CLIENT_SECRET` and `config.ANTHROPIC_API_KEY` persist as plain strings for the process lifetime. Found by config and security agents.

---

## CRITICAL

### AUD-001: Client credentials grant uses wrong scopes
- **Source**: graph-client F1
- **File**: `connectors/graph_client.py`, line 247
- **Status**: Confirmed
- **Description**: `acquire_token_for_client(scopes=self._scopes)` passes delegated scopes like `["Chat.Read", "Mail.Send"]`. Azure AD client credentials require `["https://graph.microsoft.com/.default"]`. Headless/daemon authentication will always fail.
- **Fix**: Override scopes to `["https://graph.microsoft.com/.default"]` when `_is_confidential` is True.

---

## HIGH

### AUD-002: BCC silently dropped on Graph email send
- **Source**: email-routing F1
- **File**: `mcp_tools/mail_tools.py`, lines 232-238
- **Status**: Confirmed
- **Description**: `bcc_list` is computed but never passed to `graph_client.send_mail()`. `GraphClient.send_mail()` has no `bcc` parameter. Every BCC recipient is silently discarded with no warning.
- **Fix**: Add `bcc` parameter to `GraphClient.send_mail()` and pass `bcc_list` through.

### AUD-003: reply_all, CC, and BCC dropped on Graph reply
- **Source**: email-routing F2
- **File**: `mcp_tools/mail_tools.py`, lines 182-185
- **Status**: Confirmed
- **Description**: Graph reply path only passes `message_id` and `body`. `reply_all`, `cc_list`, and `bcc_list` are all ignored. `GraphClient.reply_mail()` only accepts `message_id` and `body`.
- **Fix**: Update `GraphClient.reply_mail()` to accept all parameters and use `/replyAll` endpoint when appropriate.

### AUD-004: 401 retry returns the same stale token
- **Source**: graph-client F2
- **File**: `connectors/graph_client.py`, lines 421-425
- **Status**: Confirmed
- **Description**: On 401, `ensure_authenticated()` calls `acquire_token_silent()` which may return the same cached token MSAL hasn't expired yet. The retry is ineffective -- it gets a second 401 and raises `GraphAPIError`.
- **Fix**: Remove the account (`self._app.remove_account(accounts[0])`) before retrying, or force a fresh token acquisition on 401.

### AUD-005: Auth code flow has no CSRF state validation in callback handler
- **Source**: graph-client F3, security-report FINDING-05
- **File**: `connectors/graph_client.py`, lines 306-328
- **Status**: Confirmed
- **Description**: `_CallbackHandler.do_GET` accepts any request with a `code` parameter. State is captured but never validated against the flow dict. MSAL validates state internally during `acquire_token_by_auth_code_flow`, partially mitigating this. Combined with fixed port 8400, a local attacker could race the callback.
- **Fix**: Validate `state` parameter in the callback handler before accepting the code. Use an ephemeral port instead of fixed 8400.

### AUD-006: Reflected XSS in auth code callback error response
- **Source**: graph-client F4
- **File**: `connectors/graph_client.py`, lines 326-327
- **Status**: Confirmed
- **Description**: Error description from the query string is rendered into HTML without escaping. `error_description=<script>alert(1)</script>` would execute JavaScript. Low practical impact (localhost, one-shot) but still a vulnerability.
- **Fix**: Use `html.escape(desc)` before embedding in response.

### AUD-007: No subprocess timeout on Keychain operations
- **Source**: vault-secrets F1, config-wiring F4/F9, security-report FINDING-04 (partial)
- **File**: `vault/keychain.py`, lines 46-56, 86-97, 126-135
- **Status**: Confirmed
- **Description**: All `subprocess.run()` calls lack `timeout`. A hung `security` process blocks indefinitely. Since `get_secret()` runs at `config.py` import time, this can freeze MCP server startup with no recovery.
- **Fix**: Add `timeout=10` to all `subprocess.run()` calls. Catch `subprocess.TimeoutExpired`.

### AUD-008: Display-name chat resolution matches first substring hit
- **Source**: teams-routing F-03
- **File**: `mcp_tools/teams_browser_tools.py`, lines 156-174
- **Status**: Confirmed
- **Description**: Substring match with first-hit-wins. Target "Al" matches "Alice Smith", "Allan Jones", etc. No disambiguation, no confidence threshold. Messages can be silently delivered to the wrong recipient.
- **Fix**: Prefer exact match. If multiple chats match, return an error listing ambiguous matches. Consider requiring email for programmatic sends.

### AUD-009: GraphAPIError (non-transient 4xx) not caught in email fallback
- **Source**: email-routing F3
- **File**: `mcp_tools/mail_tools.py`, lines 187, 240
- **Status**: Confirmed
- **Description**: Fallback catches `GraphTransientError` and `GraphAuthError` but not `GraphAPIError`. A 400/403/404 from Graph propagates unhandled and does not trigger Apple Mail fallback.
- **Fix**: Either catch `GraphAPIError` base class, or document that non-transient errors are terminal by design.

---

## MEDIUM

### AUD-010: Token cache file permissions unrestricted
- **Source**: graph-client F5, security-report FINDING-02
- **File**: `connectors/graph_client.py`, lines 209-215
- **Status**: Confirmed
- **Description**: `~/.jarvis/` created with default umask. `token_cache.bin` could be world-readable on shared systems.
- **Fix**: `mkdir(mode=0o700)` and `chmod(0o600)` on the cache file.

### AUD-011: No retry on 5xx responses from Graph API
- **Source**: graph-client F6
- **File**: `connectors/graph_client.py`, lines 446-449
- **Status**: Confirmed
- **Description**: 5xx raises `GraphTransientError` immediately with no retry. 429 has retry logic (up to 3 attempts), but 502/503/504 -- common transient failures -- do not.
- **Fix**: Apply the same retry-with-backoff logic used for 429 to 5xx responses.

### AUD-012: Auth code flow hardcoded port 8400 with no fallback
- **Source**: graph-client F7, security-report FINDING-05
- **File**: `connectors/graph_client.py`, line 343
- **Status**: Confirmed
- **Description**: `HTTPServer(("127.0.0.1", 8400), ...)` fails if port is occupied. No dynamic fallback.
- **Fix**: Use port 0 for OS-assigned ephemeral port, or try a range of ports.

### AUD-013: Auth code flow server thread cleanup gap
- **Source**: graph-client F8
- **File**: `connectors/graph_client.py`, lines 350-360
- **Status**: Confirmed
- **Description**: If user never completes auth, `thread.join(timeout=300)` returns but the HTTPServer socket is never closed. Socket remains bound until GC.
- **Fix**: Call `server.server_close()` in a finally block.

### AUD-014: Retry-After header parsed without error handling
- **Source**: graph-client F10
- **File**: `connectors/graph_client.py`, line 429
- **Status**: Confirmed
- **Description**: `int(response.headers.get("Retry-After", "5"))` raises `ValueError` if Graph returns an HTTP-date string (allowed by RFC 7231).
- **Fix**: Wrap in try/except with fallback to default.

### AUD-015: Identical exception branches mask bugs in Teams send
- **Source**: teams-routing F-01
- **File**: `mcp_tools/teams_browser_tools.py`, lines 318-330
- **Status**: Confirmed
- **Description**: Both `if isinstance(exc, _graph_exceptions)` and `else` branches execute identical code. Any exception -- including `TypeError`, `AttributeError` -- silently falls back to browser, hiding real bugs.
- **Fix**: Re-raise unexpected exceptions in the `else` branch, or log at ERROR with `exc_info=True`.

### AUD-016: Identical exception branches mask bugs in Teams read
- **Source**: teams-routing F-02
- **File**: `mcp_tools/teams_browser_tools.py`, lines 471-483
- **Status**: Confirmed
- **Description**: Same pattern as AUD-015 for the read path. Unexpected exceptions silently fall through to m365-bridge.
- **Fix**: Same as AUD-015.

### AUD-017: `find_chat_by_members` matches chats with extra members
- **Source**: teams-routing F-07
- **File**: `connectors/graph_client.py`, lines 498-499
- **Status**: Confirmed
- **Description**: `target.issubset(chat_emails)` means a message intended for Alice 1:1 can land in a group chat containing Alice. Combined with AUD-008, compounds misdirection risk.
- **Fix**: Prefer `oneOnOne` type for single recipients. Sort by member count ascending.

### AUD-018: Teams read path makes O(N) sequential API calls
- **Source**: teams-routing F-04
- **File**: `mcp_tools/teams_browser_tools.py`, lines 424-464
- **Status**: Confirmed
- **Description**: Lists up to 50 chats then queries each sequentially. 50 requests at ~200ms = ~10 seconds.
- **Fix**: Use `asyncio.gather` for parallel fetching, or use server-side message search endpoint.

### AUD-019: httpx exceptions bypass email fallback entirely
- **Source**: email-routing F4
- **File**: `mcp_tools/mail_tools.py`, lines 187, 240
- **Status**: Confirmed
- **Description**: Network-level failures (`httpx.ConnectError`, `httpx.TimeoutException`) are not Graph exception subclasses and skip fallback to Apple Mail.
- **Fix**: Broaden except clause to include `httpx.HTTPError, OSError, ConnectionError`.

### AUD-020: GraphClient interactive=True default in MCP server
- **Source**: config-wiring F5
- **File**: `mcp_server.py`, lines 204-208
- **Status**: Confirmed
- **Description**: GraphClient defaults to `interactive=True`. If token expires during MCP stdio transport, device-code flow blocks all tool calls and stderr output is lost.
- **Fix**: Pass `interactive=False` for MCP server context. Handle `GraphAuthError` with user-facing re-auth message.

### AUD-021: graph_client.close() not wrapped in try/except in shutdown
- **Source**: config-wiring F6
- **File**: `mcp_server.py`, lines 226-228
- **Status**: Confirmed
- **Description**: If `close()` raises, it prevents `memory_store.close()` from executing, risking SQLite WAL data loss.
- **Fix**: Wrap in `try/except Exception` with warning log.

### AUD-022: No input validation on Graph API path parameters
- **Source**: security-report FINDING-03
- **File**: `connectors/graph_client.py`, lines 472, 479, 575
- **Status**: Confirmed
- **Description**: `chat_id` and `message_id` interpolated directly into URL paths. Path traversal or OData injection possible if IDs come from user input.
- **Fix**: Validate against allowlist pattern or use `urllib.parse.quote()`.

### AUD-023: Device code displayed to stdout -- phishing surface
- **Source**: security-report FINDING-06
- **File**: `connectors/graph_client.py`, lines 277-286
- **Status**: Confirmed
- **Description**: Device code printed to stderr and logged at INFO. Anyone with log/terminal access can complete the flow. 15-minute expiry window.
- **Fix**: Log at WARNING with "do not share" message. Verify authenticated identity matches expected user.

---

## LOW

### AUD-024: Client secret held as module-level constant
- **Source**: config-wiring F3/F7, security-report FINDING-01
- **File**: `config.py`, line 165
- **Status**: Confirmed
- **Description**: `M365_CLIENT_SECRET` stored as plain string at module scope. Unused by any consumer (GraphClient fetches independently). Keeps secret in memory unnecessarily.
- **Fix**: Remove from config.py entirely. GraphClient's own `get_secret()` call is sufficient.

### AUD-025: Secret value visible in process argument list
- **Source**: vault-secrets F2
- **File**: `vault/keychain.py`, line 91
- **Status**: Confirmed
- **Description**: `set_secret` passes value via `-w` CLI arg, visible via `ps aux`. Known limitation of macOS `security` CLI.
- **Fix**: Document as known limitation. For the current use case (non-password values), risk is acceptable.

### AUD-026: Cache stores None values, blocking env var updates
- **Source**: vault-secrets F3
- **File**: `vault/keychain.py`, lines 34-39
- **Status**: Confirmed
- **Description**: `get_secret()` caches `None` results. If a user later sets the env var, the cached `None` persists until `clear_secret_cache()` is called.
- **Fix**: Don't cache `None` results.

### AUD-027: In-memory secret cache never cleared
- **Source**: security-report FINDING-07
- **File**: `vault/keychain.py`, lines 18-19
- **Status**: Confirmed
- **Description**: `clear_secret_cache()` exists but is never called. Secrets persist in process memory for entire session.
- **Fix**: Call `clear_secret_cache()` in shutdown handler.

### AUD-028: Teams Graph send bypasses confirm_send gate
- **Source**: security-report FINDING-08
- **File**: `mcp_tools/teams_browser_tools.py`, lines 309-317
- **Status**: Confirmed
- **Description**: Graph path sends immediately without `confirm_send` check. `auto_send` parameter is ignored. Inconsistent with email tools' defensive pattern.
- **Fix**: Add `confirm_send` gate matching email tools pattern.

### AUD-029: No key validation on keychain operations
- **Source**: vault-secrets F5, security-report FINDING-04
- **File**: `vault/keychain.py`, lines 27, 74, 115
- **Status**: Confirmed
- **Description**: No validation that `key` is a reasonable string. Empty, newline-containing, or extremely long strings passed to `security` CLI.
- **Fix**: Add `re.match(r'^[a-zA-Z0-9_-]+$', key)` guard.

### AUD-030: ISO datetime comparison is string-based
- **Source**: teams-routing F-08
- **File**: `mcp_tools/teams_browser_tools.py`, line 445
- **Status**: Confirmed
- **Description**: Lexicographic comparison fails when timestamps have different precision (e.g., `.0000000Z` vs `Z`).
- **Fix**: Parse with `datetime.fromisoformat()` before comparing.

### AUD-031: Deprecated TEAMS_POSTER_BACKEND still actively used
- **Source**: teams-routing F-05, config-wiring F1/F2
- **File**: `mcp_tools/teams_browser_tools.py`, lines 44-46; `config.py`, line 178
- **Status**: Confirmed
- **Description**: Three browser-related functions use deprecated `_get_backend()` reading `TEAMS_POSTER_BACKEND`, creating a split from `TEAMS_SEND_BACKEND`.
- **Fix**: Migrate all call sites to `TEAMS_SEND_BACKEND`. Emit deprecation warning on old var.

### AUD-032: ANTHROPIC_API_KEY not routed through Keychain
- **Source**: security-report FINDING-11
- **File**: `config.py`, line 18
- **Status**: Confirmed
- **Description**: Unlike M365 secrets, `ANTHROPIC_API_KEY` reads from env var only and persists as module-level constant.
- **Fix**: Route through `get_secret()` for consistency.

### AUD-033: Error messages may leak API response metadata
- **Source**: security-report FINDING-10
- **File**: `connectors/graph_client.py`, lines 447-456
- **Status**: Confirmed
- **Description**: First 500 chars of response body included in exceptions. Can contain tenant IDs and request IDs.
- **Fix**: Parse error JSON and extract only `error.code` and `error.message`.

### AUD-034: Keychain service name collision risk
- **Source**: security-report FINDING-09
- **File**: `vault/keychain.py`, line 14
- **Status**: Confirmed
- **Description**: Generic service name "jarvis" could collide with other applications.
- **Fix**: Use reverse-DNS style: `com.jarvis.chief-of-staff`.

### AUD-035: Test fixtures rely on manual state cleanup
- **Source**: teams-routing F-09
- **File**: `tests/test_teams_graph.py`
- **Status**: Confirmed
- **Description**: Tests manually reset `_state.graph_client = None` at end. If a test fails before cleanup, subsequent tests see stale state.
- **Fix**: Use pytest `yield` fixtures for automatic cleanup.

---

## Test Coverage Gaps (Consolidated)

| Area | Gap | Priority |
|------|-----|----------|
| Auth code flow | HTTP server, threading, browser open, code exchange untested | High |
| SSL context | `_get_ssl_context()` completely untested (all 4 paths) | High |
| Email BCC on Graph | No test for BCC parameter (masks AUD-002) | High |
| Email reply_all on Graph | No test for reply_all/cc/bcc (masks AUD-003) | High |
| Display-name ambiguity | No test for multiple chat matches (masks AUD-008) | Medium |
| Dual-backend failure | No test for Graph fail + browser/bridge also fail | Medium |
| Token cache building | Keychain path, file fallback, in-memory fallback untested | Medium |
| 429 retry exhaustion | No test for 3 consecutive 429s | Medium |
| GraphAPIError (4xx) | No test for non-transient 4xx in email tools | Medium |
| httpx exceptions | No test for network-level failures in email tools | Medium |
| GraphClient lifecycle | No test for init/shutdown in mcp_server.py | Low |
| Teams chat methods | find_chat_by_members, list_chats, create_chat untested | Low |
