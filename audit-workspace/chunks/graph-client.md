# Chunk Audit: Graph Client Core

**Files audited:**
- `/Users/jasricha/Documents/GitHub/chief_of_staff/connectors/graph_client.py`
- `/Users/jasricha/Documents/GitHub/chief_of_staff/tests/test_graph_client.py`

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-12

---

## Dimension Scores

| Dimension | Score | Notes |
|-----------|-------|-------|
| Correctness | 3/5 | Client credentials scope bug; 401 retry can re-fire stale token |
| Reliability | 3/5 | No 5xx retry; auth code server has race/port-conflict risks |
| Security | 3/5 | Token cache file permissions uncontrolled; XSS in callback; no CSRF state validation |
| Testability | 3/5 | Good core coverage but major gaps in auth code flow, SSL, token cache, edge cases |
| Maintainability | 4/5 | Clean structure, good separation; minor dead-code concern |

---

## Findings

### CRITICAL

#### F1. Client credentials grant uses wrong scopes
- **File:** `graph_client.py`, line 247
- **Status:** Confirmed
- **Details:** `acquire_token_for_client(scopes=self._scopes)` passes delegated scopes like `["Chat.Read", "Mail.Send"]`. The client credentials grant in Azure AD/Entra requires a single scope in the form `https://graph.microsoft.com/.default`. MSAL will reject or silently fail with delegated permission names. This means headless daemon authentication will always fail.
- **Fix:** When `_is_confidential` is True, override scopes to `["https://graph.microsoft.com/.default"]` for the `acquire_token_for_client` call.

### HIGH

#### F2. 401 retry re-calls `ensure_authenticated()` which may return the same stale token
- **File:** `graph_client.py`, lines 421-425
- **Status:** Confirmed
- **Details:** On a 401, `_request()` calls `ensure_authenticated()` again, which calls `acquire_token_silent()` on the same first account. If the cache hasn't expired the token yet (MSAL caches by expiry, not by server rejection), the same token is returned, leading to an immediate second 401 which falls through to a `GraphAPIError`. The code does guard against infinite loops (retry only on `attempt == 0`), so this is not an infinite loop, but it means the retry is ineffective. Proper fix: call `self._app.remove_account(accounts[0])` or force a fresh token acquisition on 401 retry.

#### F3. Auth code flow callback server has no CSRF/state validation
- **File:** `graph_client.py`, lines 306-328
- **Status:** Confirmed
- **Details:** The `_CallbackHandler.do_GET` accepts any request with a `code` parameter. It captures `state` but never validates it against the `state` in the `flow` dict. An attacker on the local network could race the legitimate callback and inject a malicious auth code. MSAL's `acquire_token_by_auth_code_flow` does validate state internally, which partially mitigates this, but the server still accepts and stores the first code it receives regardless.

#### F4. Reflected XSS in auth code callback error response
- **File:** `graph_client.py`, lines 326-327
- **Status:** Confirmed
- **Details:** Error description from the query string is rendered directly into HTML without escaping: `f"<p>{desc}</p>"`. A crafted redirect URL with `error_description=<script>alert(1)</script>` would execute JavaScript in the user's browser. Low practical impact (localhost, one-shot server) but still a vulnerability.
- **Fix:** Use `html.escape(desc)` before embedding in the response.

#### F5. Token cache file permissions are not restricted
- **File:** `graph_client.py`, lines 209-215
- **Status:** Confirmed
- **Details:** `cache_dir.mkdir(parents=True, exist_ok=True)` creates `~/.jarvis/` with default umask permissions (typically 0o755). The fallback `token_cache.bin` file is created by `FilePersistence` with whatever the default permissions are. On a shared system, other users could read the token cache. The Keychain path is preferred on macOS, but the file fallback is still reachable.
- **Fix:** Set `mode=0o700` on `mkdir` and ensure the file is created with `0o600` permissions.

### MEDIUM

#### F6. No retry on 5xx responses
- **File:** `graph_client.py`, lines 446-449
- **Status:** Confirmed
- **Details:** A single 5xx response immediately raises `GraphTransientError`. The 429 path has retry logic (up to 3 attempts), but 5xx errors (502, 503, 504) are common transient failures from Graph API and should also be retried with backoff. The exception class is named "Transient" suggesting retry was intended.

#### F7. Auth code flow hardcoded port 8400 with no fallback
- **File:** `graph_client.py`, line 343
- **Status:** Confirmed
- **Details:** `HTTPServer(("127.0.0.1", 8400), ...)` will raise `OSError: [Errno 48] Address already in use` if port 8400 is occupied. No fallback port or dynamic port selection. The Azure app registration's redirect URI must match, so dynamic ports require registration of multiple redirect URIs or a range.

#### F8. Auth code flow server thread cleanup
- **File:** `graph_client.py`, lines 350-360
- **Status:** Confirmed
- **Details:** If the user never completes auth, `thread.join(timeout=300)` returns after 5 minutes but the `HTTPServer` is never explicitly shut down. The thread is daemonic so it won't block process exit, but the socket remains bound until GC. Calling `server.server_close()` in a finally block would be cleaner.

#### F9. `_check_token_age` uses `iat` claim which may not be present
- **File:** `graph_client.py`, lines 377-391
- **Status:** Suspected
- **Details:** The `iat` claim is not guaranteed in all MSAL token responses. For client credentials grants, there is no `id_token_claims` at all. The code handles this gracefully (returns silently), but the 60-day warning threshold never fires for client credentials tokens, which also expire.

#### F10. `Retry-After` header parsed as int without error handling
- **File:** `graph_client.py`, line 429
- **Status:** Confirmed
- **Details:** `int(response.headers.get("Retry-After", "5"))` will raise `ValueError` if the Graph API returns a date string (RFC 7231 allows `Retry-After: <http-date>`). Should wrap in try/except with a fallback.

### LOW

#### F11. `create_chat` does not include the authenticated user in the members list
- **File:** `graph_client.py`, lines 503-535
- **Status:** Suspected
- **Details:** Comment says "The authenticated user is automatically included" but the Graph API documentation states the caller must be included in the members array for chat creation. If the caller is not included, the API will return a 400 error. This may work in some tenants with specific policies but is not guaranteed.

#### F12. `find_chat_by_members` has O(n*m) complexity and limited to 50 chats
- **File:** `graph_client.py`, lines 483-501
- **Status:** Confirmed
- **Details:** Iterates through up to 50 chats, checking member email sets. If the user has more than 50 chats, the target chat may not be found. No pagination support. The email extraction logic also won't find members if the email is nested differently than expected in `additionalData`.

#### F13. No `async with` / context manager support
- **File:** `graph_client.py`
- **Status:** Confirmed
- **Details:** The class has a `close()` method but no `__aenter__`/`__aexit__`, so callers can't use `async with GraphClient(...) as client:`. This makes it easy to leak the httpx connection pool.

---

## Test Coverage Gaps

| Gap | Priority | Description |
|-----|----------|-------------|
| Auth code flow | High | `_auth_code_flow()` is only tested via mock patch at the method level (F3 test_ensure_authenticated_auth_code_flow). The HTTP server, threading, browser open, and code exchange logic are untested. |
| SSL context chain | High | `_get_ssl_context()` is completely untested. All paths (Jarvis bundle, env vars, certifi, fallback) lack coverage. |
| Token cache building | Medium | `_build_token_cache()` is untested (Keychain path, file fallback, in-memory fallback). |
| 429 retry exhaustion | Medium | No test for what happens after 3 consecutive 429s (should raise `GraphTransientError`). |
| 401 then non-401 error | Medium | No test for 401 followed by another error code on retry. |
| `__init__` with real msal | Medium | Constructor is bypassed via `__new__` in tests. No test validates the `ConfidentialClientApplication` vs `PublicClientApplication` branching. |
| `find_chat_by_members` | Low | No test coverage at all. |
| `list_chats` / `get_chat_messages` | Low | No test coverage. |
| `create_chat` | Low | No test coverage. |
| Device code flow error path | Low | No test for `initiate_device_flow` returning an error (no `user_code`). |
| Token age warning | Low | `_check_token_age` is exercised implicitly but no test asserts the warning is logged. |

---

## Summary

The core request/retry loop is well-structured and the exception hierarchy is clean. The main correctness issue is **F1** (client credentials using wrong scopes), which will cause all headless/daemon authentication to fail. The auth code flow (F3, F4, F7, F8) has multiple issues typical of embedded OAuth servers but has limited blast radius since it only runs during interactive re-auth. The 401 retry (F2) is safe from infinite loops but likely ineffective.

Test coverage is solid for the happy path and basic error codes but completely misses the auth code flow internals, SSL context resolution, token cache construction, and several Teams convenience methods.

**Top 3 actions:**
1. Fix client credentials scopes (F1) -- this blocks daemon mode entirely
2. Add `Retry-After` parsing safety and 5xx retry (F10, F6) -- reliability in production
3. HTML-escape the auth callback error response (F4) -- quick security fix
