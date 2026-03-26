# Chunk Audit: GraphClient — Auth & HTTP Transport

## 1. Correctness
- confirmed: `ensure_authenticated` silently succeeds even when `acquire_token_silent` returns a result missing `access_token` — it would try `get("access_token")` which would KeyError or return None but the early return `return result["access_token"]` would raise a KeyError. Actually re-reading: `if result and "access_token" in result:` guards it correctly. ✓
- confirmed: 401 retry logic removes all cached accounts before re-acquiring. Token header is updated correctly for the retry. ✓
- confirmed: 429 Retry-After header is read and respected. Falls back to 5s on parse failure. ✓
- confirmed: 5xx triggers exponential backoff (1s, 2s) then `GraphTransientError`. Correct. ✓
- suspected: `_auth_code_flow` HTTP server uses `handle_request()` which handles exactly one request; if the user never completes auth, it hangs until the 300s thread join times out — but `server.server_close()` is not called until after the thread join, so the port stays bound for the full timeout even on failure. Low severity.

## 2. Completeness
- confirmed: `_is_confidential` is always `False` in `__init__` (line 142-143). The `if self._is_confidential:` branch at line 283 is unreachable dead code in all production paths. `_auth_code_flow` method is dead code unless `_is_confidential` is manually set (tests do this).
- suspected: `_check_token_age` only fires when `id_token_claims` contains `iat`. MSAL may not always include `id_token_claims` in silent refresh results — the warning may never fire even when tokens are near expiry.

## 3. Data Flow
- confirmed: Token cache is shared between `_public_app` and `_confidential_app` (same `cache` object passed to both). This is intentional. ✓
- confirmed: httpx client is created once in `__init__` and reused. `close()` method exists. ✓

## 4. Error Handling
- confirmed: `GraphTransientError`, `GraphAPIError`, `GraphAuthError` hierarchy is clean and well-documented. ✓
- confirmed: `_extract_error_body` handles both JSON and non-JSON error responses. Falls back to first 500 chars. ✓
- confirmed: All SSL context failures are silently caught and fall back gracefully. ✓

## 5. Security
- confirmed: Token cache file is chmod 0o600 (owner-only) when file-based. ✓
- confirmed: Cache dir is mkdir'd with mode 0o700. ✓
- confirmed: Auth code flow callback server binds to `127.0.0.1` (not 0.0.0.0). ✓
- confirmed: Error descriptions in HTML callback are html.escape'd before writing to browser. ✓
- confirmed: No hardcoded credentials anywhere. ✓
