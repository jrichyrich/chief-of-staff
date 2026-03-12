# Security Audit Report: Microsoft Graph API Integration

**Auditor**: Security Agent (Claude)
**Date**: 2026-03-12
**Scope**: vault/keychain.py, connectors/graph_client.py, mcp_tools/teams_browser_tools.py, mcp_tools/mail_tools.py, config.py, scripts/bootstrap_secrets.py

---

## Executive Summary

The Graph API integration is reasonably well designed for a single-user desktop tool. Secrets are stored in macOS Keychain rather than plaintext, SSL verification is never disabled, and email/iMessage sends are gated behind `confirm_send`. However, there are several findings ranging from MEDIUM to LOW severity — most related to defense-in-depth gaps rather than active exploitability.

**Critical**: 0 | **High**: 1 | **Medium**: 6 | **Low**: 4

---

## Findings

### FINDING-01: Client secret held as module-level string constant (HIGH)

**File**: `config.py`, line 165
**Code**: `M365_CLIENT_SECRET = get_secret("m365_client_secret") or ""`

The client secret is resolved at import time and stored as a plain Python string at module scope for the lifetime of the process. Any code path that can read `config.M365_CLIENT_SECRET` — including debug endpoints, crash dumps, or `repr()` on the config module — gets the raw secret. The same applies to `ANTHROPIC_API_KEY` (line 18), though that one uses `os.environ.get` directly.

**Risk**: Memory inspection, crash dumps, or accidental logging of the config module exposes credentials.

**Recommendation**:
- Replace with a lazy accessor: `def get_m365_client_secret() -> str: return get_secret("m365_client_secret") or ""` so the secret is only held during the call, not as a permanent module attribute.
- At minimum, avoid storing in a named module-level constant. The current pattern means `dir(config)` reveals the attribute name and `config.M365_CLIENT_SECRET` is always available.

---

### FINDING-02: Token cache file lacks restricted permissions (MEDIUM)

**File**: `connectors/graph_client.py`, lines 209-215
**Code**: `cache_dir.mkdir(parents=True, exist_ok=True)` / `FilePersistence(str(cache_path))`

When the Keychain-backed cache fails, the fallback writes tokens to `~/.jarvis/token_cache.bin`. The directory is created with default permissions (`mkdir` without `mode=`), and `FilePersistence` does not restrict file permissions. On a shared system, this file could be world-readable.

Observed on this machine: `token_cache.lock` has permissions `-rw-r--r--` (world-readable). If `token_cache.bin` existed it would likely inherit the same umask.

**Risk**: Another local user could read MSAL tokens from the file-based fallback cache.

**Recommendation**:
```python
cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
# After FilePersistence creates the file:
cache_path.chmod(0o600)
```

---

### FINDING-03: No input validation on Graph API path parameters (MEDIUM)

**File**: `connectors/graph_client.py`, lines 472, 479, 575

`chat_id` and `message_id` are interpolated directly into URL paths:
```python
f"/me/chats/{chat_id}/messages?$top={limit}"
f"/me/messages/{message_id}/reply"
```

There is no validation that these IDs contain only expected characters. A malicious or malformed `chat_id` containing path-traversal characters (e.g., `../../`) or OData injection (`?$filter=...`) could alter the API call semantics.

**Risk**: In practice, these IDs come from prior Graph API responses (not user input), so exploitability is low. But in the MCP tool layer, `chat_id` can flow from user-provided arguments without sanitization.

**Recommendation**:
- Validate `chat_id` and `message_id` against an allowlist pattern (e.g., alphanumeric + hyphens + colons): `re.match(r'^[a-zA-Z0-9:_@.\-=]+$', chat_id)`.
- Use `urllib.parse.quote(chat_id, safe='')` when constructing URL paths.

---

### FINDING-04: Subprocess injection risk via keychain key names (MEDIUM)

**File**: `vault/keychain.py`, lines 46-56, 86-97

The `key` parameter is passed directly to `subprocess.run()` as a list element (`"-a", key`). Because `subprocess.run()` is called without `shell=True`, the standard shell injection vector is mitigated. However, the `security` CLI interprets certain key values specially — a key containing newlines or null bytes could cause unexpected behavior.

**Risk**: Low in practice since key names are hardcoded constants (`m365_client_id`, `m365_tenant_id`, `m365_client_secret`). But `set_secret` and `get_secret` are public functions with no input validation on `key`.

**Recommendation**:
```python
def _validate_key(key: str) -> None:
    if not re.match(r'^[a-zA-Z0-9_\-]+$', key):
        raise ValueError(f"Invalid keychain key: {key!r}")
```

---

### FINDING-05: Auth code flow binds to fixed port without TOCTOU protection (MEDIUM)

**File**: `connectors/graph_client.py`, lines 292-374

The auth code flow starts an HTTP server on `127.0.0.1:8400`. There is no check for whether port 8400 is already in use (a malicious process could pre-bind it to intercept the OAuth callback). The `state` parameter from the MSAL flow is captured but there is no explicit CSRF state validation in `_CallbackHandler` — this is delegated to `acquire_token_by_auth_code_flow` which validates it internally.

**Risk**: A local attacker could race to bind port 8400 before the legitimate server starts, intercepting the auth code. This is a classic OAuth redirect TOCTOU attack on localhost flows.

**Recommendation**:
- Bind to port 0 (OS-assigned ephemeral port) and dynamically construct the redirect URI.
- Alternatively, check for existing bindings before starting.

---

### FINDING-06: Device code displayed to stdout — phishing surface (MEDIUM)

**File**: `connectors/graph_client.py`, lines 277-286

The device code is printed to stderr and logged at INFO level:
```python
logger.info("Device code auth: visit %s and enter code %s", ...)
print(f"... enter code: {flow['user_code']}\n", file=sys.stderr)
```

In a multi-user or remote session scenario, anyone who can see the terminal or log output can complete the device code flow and obtain tokens for the target tenant.

**Risk**: Device code phishing is a known attack vector (T1528). An attacker with log access could silently complete the flow. The 15-minute expiry window of device codes provides ample time.

**Recommendation**:
- Log the device code at WARNING level with a clear message that it should not be shared.
- Consider adding a verification step that confirms the authenticated identity matches the expected user.
- In daemon/headless mode, device code flow is already disabled (raises `GraphAuthError`), which is correct.

---

### FINDING-07: In-memory secret cache not clearable on demand (MEDIUM)

**File**: `vault/keychain.py`, lines 18-19, 22-24

Secrets are cached in `_cache: dict[str, str | None]` at module level. While `clear_secret_cache()` exists, it is never called anywhere in the codebase. Secrets persist in process memory for the entire session lifetime.

**Risk**: In a long-running MCP server process, secrets remain in memory indefinitely. A memory dump or core dump would expose all cached secrets.

**Recommendation**:
- Call `clear_secret_cache()` in a session cleanup/shutdown handler.
- Consider using `mmap` with `mlock` for sensitive values, or at minimum zeroing out the cache dict values (not just clearing the dict).

---

### FINDING-08: Teams `post_teams_message` bypasses confirm gate for Graph backend (LOW)

**File**: `mcp_tools/teams_browser_tools.py`, lines 284-348

When `TEAMS_SEND_BACKEND=graph`, `post_teams_message` sends the message immediately via `_graph_send_message` — there is no `confirm_send` gate, and the `auto_send` parameter is ignored for the Graph path. This contrasts with the email tools which have a strict `confirm_send` gate.

The browser backend path does respect `auto_send` (line 344-347), but the Graph path at lines 309-317 sends immediately regardless.

**Risk**: An LLM agent calling `post_teams_message` can send Teams messages without explicit user confirmation when Graph is the backend. This is inconsistent with the defensive pattern used for email.

**Recommendation**:
- Add a `confirm_send` gate to `post_teams_message` matching the pattern in `send_email` and `reply_to_email`.
- Or at minimum, only send immediately when `auto_send=True`.

---

### FINDING-09: Keychain service name collision risk (LOW)

**File**: `vault/keychain.py`, line 14 — `KEYCHAIN_SERVICE = "jarvis"`

The generic service name "jarvis" could collide with other applications using the same service name in the macOS Keychain. macOS Keychain items are uniquely identified by (service, account) tuples, so a collision would require both matching. However, the account names (`m365_client_id`, `m365_tenant_id`) are also relatively generic.

**Risk**: Low — requires another app to use both the same service name and same account name.

**Recommendation**: Use a more specific service name, e.g., `com.jarvis.chief-of-staff` (reverse-DNS style).

---

### FINDING-10: Error messages may leak partial API response bodies (LOW)

**File**: `connectors/graph_client.py`, lines 447-456

Error responses include the first 500 characters of the response body:
```python
body = response.text[:500]
raise GraphAPIError(f"Graph API {response.status_code}: {body}")
```

Graph API error responses can include request IDs, tenant IDs, and other metadata. If these exceptions propagate to logs or user-facing output, they leak organizational identifiers.

**Risk**: Low — these are error details, not credentials. But they provide reconnaissance information.

**Recommendation**: Parse the error response JSON and extract only the `error.code` and `error.message` fields rather than dumping raw response text.

---

### FINDING-11: ANTHROPIC_API_KEY exposed via os.environ fallback (LOW)

**File**: `config.py`, line 18 — `ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")`

Unlike M365 credentials which use the Keychain-first `get_secret()` pattern, the Anthropic API key is read directly from environment variables and stored as a module-level constant. This means it is visible in `/proc/self/environ` (on Linux), in process inspection tools, and persists in `config.ANTHROPIC_API_KEY` for the process lifetime.

**Risk**: Inconsistency with the Keychain-first pattern used for M365 secrets. Environment variables are a weaker storage mechanism.

**Recommendation**: Route through `get_secret("ANTHROPIC_API_KEY")` for consistency with the M365 credential pattern, falling back to env var only when Keychain is unavailable.

---

## Positive Findings (Good Practices Observed)

1. **SSL never disabled**: `_get_ssl_context()` always returns either a proper SSL context or `True` (system default). There is no `verify=False` anywhere in the codebase.

2. **No shell=True in subprocess calls**: All `subprocess.run()` calls in `vault/keychain.py` and `scripts/bootstrap_secrets.py` use list-form arguments, preventing shell injection.

3. **confirm_send gate on email**: Both `send_email` and `reply_to_email` check `confirm_send` before any backend routing, preventing accidental sends.

4. **Secret masking in bootstrap output**: `scripts/bootstrap_secrets.py` uses `mask()` to display only first/last 4 characters of secrets.

5. **Secrets not logged**: Logger calls in `vault/keychain.py` log only the key name, never the secret value. Graph client logs token age but never the token itself.

6. **Headless mode disables interactive auth**: When `interactive=False`, device code and auth code flows are blocked, preventing unattended auth prompts.

7. **MSAL Keychain persistence preferred**: The token cache prefers macOS Keychain over file-based storage, with proper fallback chain.

8. **Rate limit handling**: Graph API 429 responses respect `Retry-After` headers with bounded retries.

---

## Risk Summary Matrix

| ID | Severity | Category | File | Exploitability |
|----|----------|----------|------|----------------|
| F-01 | HIGH | Secret leakage | config.py:165 | Local process access |
| F-02 | MEDIUM | Token security | graph_client.py:209 | Local file access |
| F-03 | MEDIUM | Input validation | graph_client.py:472 | Requires MCP tool abuse |
| F-04 | MEDIUM | Subprocess injection | keychain.py:46 | Requires custom key names |
| F-05 | MEDIUM | Auth flow | graph_client.py:343 | Local port race |
| F-06 | MEDIUM | Auth flow | graph_client.py:277 | Log/terminal access |
| F-07 | MEDIUM | Secret leakage | keychain.py:18 | Memory dump |
| F-08 | LOW | Confirm gate | teams_browser_tools.py:309 | LLM agent misuse |
| F-09 | LOW | Keychain | keychain.py:14 | Service name collision |
| F-10 | LOW | Error handling | graph_client.py:447 | Log access |
| F-11 | LOW | Secret leakage | config.py:18 | Process inspection |

---

## Recommended Priority Order

1. **F-01** (HIGH) — Make secrets lazy-loaded, not module-level constants
2. **F-08** (LOW but high-impact) — Add confirm_send gate to Teams Graph send path
3. **F-02** (MEDIUM) — Restrict token cache file permissions to 0600
4. **F-03** (MEDIUM) — Validate Graph API path parameters
5. **F-05** (MEDIUM) — Use ephemeral port for auth code redirect
6. **F-04** (MEDIUM) — Validate keychain key names
7. **F-07** (MEDIUM) — Wire up secret cache cleanup
8. **F-06** (MEDIUM) — Improve device code logging posture
9. **F-10** (LOW) — Parse error responses instead of dumping raw text
10. **F-11** (LOW) — Route ANTHROPIC_API_KEY through Keychain
11. **F-09** (LOW) — Use reverse-DNS keychain service name
