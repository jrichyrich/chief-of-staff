# Microsoft Graph API Integration & Secrets Layer

**Date**: 2026-03-12
**Status**: Approved (rev 2 — post spec review)
**Scope**: Teams send/read + Outlook email send via Graph API, with fallback to existing methods. New secrets layer for macOS Keychain.

## Context

Jarvis currently accesses Microsoft 365 through two indirect paths:
- **Teams sending**: Playwright browser automation with Okta SSO session
- **Teams/Email reading**: Claude CLI subprocess bridge (`ClaudeM365Bridge`)
- **Email sending**: Apple Mail AppleScript only — no Outlook send capability

Jonas De Oliveira provisioned an Entra Enterprise App registration ("Jarvis - Entra Enterprise App") with **delegated permissions** stored in 1Password. This enables direct Microsoft Graph API access acting as the user.

All secrets in the project are currently plain environment variables with no keychain integration.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scope | Teams send/read + Email send (B) | Biggest ROI: kills fragile browser automation, unlocks Outlook sending for daemon tasks |
| Fallback | Hybrid (C) | Config sets preferred backend; auto-falls back on transient errors |
| Secrets | Keychain-first with env var fallback | No breakage for existing setups; establishes pattern for all future secrets |
| Auth flow | Device code (public client) | Delegated permissions require user consent; no client_secret needed |
| Token storage | msal-extensions KeychainPersistence | Native macOS Keychain encryption; automatic token refresh |
| 1Password | One-time bootstrap script | Decouples runtime from 1Password availability |
| HTTP client | httpx (async) | Already in dependency tree; async fits MCP server pattern |
| Package name | `vault/` (not `secrets/`) | Avoids shadowing Python stdlib `secrets` module (same class of bug as `calendar/` — see CLAUDE.md) |

## Architecture

### 1. Secrets Layer (`vault/keychain.py`)

New module providing unified secret retrieval. Package named `vault/` to avoid shadowing Python's stdlib `secrets` module.

```
get_secret(key: str) -> str | None
    1. Try macOS Keychain: `security find-generic-password -s jarvis -a {key} -w`
       - Catches subprocess errors gracefully (returns None on any failure)
    2. Fall back to os.environ.get(key)
    3. Return None if neither found

set_secret(key: str, value: str) -> bool
    Store in macOS Keychain: `security add-generic-password -s jarvis -a {key} -w {value} -U`

delete_secret(key: str) -> bool
    Remove from Keychain: `security delete-generic-password -s jarvis -a {key}`
```

Service name: `jarvis` (all entries under one service).
Account names: `m365_client_id`, `m365_tenant_id`, `anthropic_api_key`, `webhook_secret`.

Platform guard: on non-macOS, skip Keychain entirely, only use env vars.

**Caching**: `get_secret()` caches results in a module-level dict after first call per key. This avoids subprocess overhead on repeated calls (e.g., `config.py` import-time reads). Cache can be cleared with `clear_secret_cache()`.

### 2. Bootstrap Script (`scripts/bootstrap_secrets.py`)

Interactive CLI that:
1. Checks for `op` CLI availability
2. Reads from 1Password: `op read "op://<vault>/Jarvis - Entra Enterprise App/<field>"`
3. Stores each field in macOS Keychain via `set_secret()`
4. Runs MSAL device code flow to obtain initial tokens (stored in Keychain via msal-extensions)
5. Verifies Graph API connectivity with a test call

Fields to bootstrap:
- `m365_client_id` (from 1Password)
- `m365_tenant_id` (from 1Password)

No client_secret — device code flow is a public client flow.

Additional flags:
- `--clear-tokens` — Removes MSAL token cache from Keychain (for rollback/security incidents)
- `--verify` — Reads back from Keychain and prints masked values

### 3. Graph API Client (`connectors/graph_client.py`)

Async client wrapping MSAL auth + httpx calls.

```python
class GraphTransientError(Exception):
    """Raised on 429/5xx — triggers fallback to old backend."""
    pass

class GraphAPIError(Exception):
    """Raised on non-transient Graph errors — no fallback."""
    pass

class GraphAuthError(GraphAPIError):
    """Raised when token refresh fails and device code flow is needed."""
    pass

class GraphClient:
    def __init__(self, client_id: str, tenant_id: str):
        # msal.PublicClientApplication with KeychainPersistence cache
        # Scopes: Chat.Read, ChatMessage.Send, Mail.Send, User.Read
        # Creates httpx.AsyncClient (reused for connection pooling)

    async def ensure_authenticated(self) -> str:
        # Try acquire_token_silent() first
        # If silent fails: raise GraphAuthError (daemon) or prompt device_code_flow (interactive)
        # Returns access_token

    async def close(self):
        # Close httpx.AsyncClient — called during server shutdown

    # Teams
    async def list_chats(self, limit: int = 50) -> list[dict]
    async def get_chat_messages(self, chat_id: str, limit: int = 50) -> list[dict]
    async def send_chat_message(self, chat_id: str, content: str) -> dict
    async def find_chat_by_members(self, member_emails: list[str]) -> str | None
    async def create_chat(self, member_emails: list[str], message: str | None = None) -> dict

    # Email
    async def send_mail(self, to: list[str], subject: str, body: str, cc: list[str] | None = None) -> dict
    async def reply_mail(self, message_id: str, body: str) -> dict
```

**Error handling:**
- 401 → attempt token refresh, retry once; if still fails raise `GraphAuthError`
- 429 → respect Retry-After header, retry; if exhausted raise `GraphTransientError`
- 5xx → raise `GraphTransientError` (triggers fallback)
- Other errors → raise `GraphAPIError` (no fallback)

**httpx lifecycle**: `GraphClient` owns an `httpx.AsyncClient` instance created in `__init__`. MCP server lifespan teardown calls `await state.graph_client.close()`.

### 4. Hybrid Backend Routing

#### Teams (`mcp_tools/teams_browser_tools.py`)

**Config migration**: `TEAMS_POSTER_BACKEND` is deprecated. Replaced by `TEAMS_SEND_BACKEND` which accepts all old values plus `"graph"`. If only `TEAMS_POSTER_BACKEND` is set, its value is used as the default for `TEAMS_SEND_BACKEND` (backward compat). If both are set, `TEAMS_SEND_BACKEND` wins.

New config in `config.py`:
```python
TEAMS_SEND_BACKEND = os.environ.get(
    "TEAMS_SEND_BACKEND",
    os.environ.get("TEAMS_POSTER_BACKEND", "graph" if M365_GRAPH_ENABLED else "agent-browser")
)  # graph | agent-browser | playwright
TEAMS_READ_BACKEND = os.environ.get("TEAMS_READ_BACKEND", "graph" if M365_GRAPH_ENABLED else "m365-bridge")  # graph | m365-bridge
```

`post_teams_message()` changes:
```
if backend == "graph":
    try: graph_client.send_chat_message(...)
    except (GraphTransientError, GraphAuthError):
        log warning
        fall back to browser poster (agent-browser or playwright)
else:
    existing browser poster logic (unchanged)
```

**Teams reading**: New MCP tool `read_teams_messages(query, after_datetime, limit)` in `teams_browser_tools.py`. When `TEAMS_READ_BACKEND=graph`, calls `GraphClient.get_chat_messages()` / `list_chats()`. When `m365-bridge`, delegates to `ClaudeM365Bridge` as today. This is a Jarvis-native tool, separate from the Claude M365 connector's `chat_message_search` which remains available in Claude Code sessions.

#### Email (`mcp_tools/mail_tools.py`)

New config:
```python
EMAIL_SEND_BACKEND = os.environ.get("EMAIL_SEND_BACKEND", "graph" if M365_GRAPH_ENABLED else "apple")  # graph | apple
```

`send_email()` changes:
```
# confirm_send gate is preserved BEFORE backend routing
if not confirm_send:
    return "Set confirm_send=True to send"

if backend == "graph":
    try: graph_client.send_mail(...)
    except (GraphTransientError, GraphAuthError):
        log warning
        fall back to Apple Mail
else:
    existing AppleScript logic (unchanged)
```

`reply_to_email()` follows the same pattern, preserving the `confirm_send` gate.

### 5. Config Changes (`config.py`)

New settings (using cached `get_secret()` — subprocess cost paid once per key, not per import):
```python
from vault.keychain import get_secret

# Graph API
M365_CLIENT_ID = get_secret("m365_client_id") or ""
M365_TENANT_ID = get_secret("m365_tenant_id") or ""
M365_GRAPH_ENABLED = bool(M365_CLIENT_ID)
M365_GRAPH_SCOPES = ["Chat.Read", "ChatMessage.Send", "Mail.Send", "User.Read"]
# Note: Mail.Read omitted — email reading stays on M365 MCP connector / Apple Mail.
# Add Mail.Read here if/when email reading migrates to Graph.

# Backend routing (TEAMS_POSTER_BACKEND deprecated in favor of TEAMS_SEND_BACKEND)
TEAMS_SEND_BACKEND = os.environ.get(
    "TEAMS_SEND_BACKEND",
    os.environ.get("TEAMS_POSTER_BACKEND", "graph" if M365_GRAPH_ENABLED else "agent-browser")
)
TEAMS_READ_BACKEND = os.environ.get("TEAMS_READ_BACKEND", "graph" if M365_GRAPH_ENABLED else "m365-bridge")
EMAIL_SEND_BACKEND = os.environ.get("EMAIL_SEND_BACKEND", "graph" if M365_GRAPH_ENABLED else "apple")
```

### 6. ServerState Changes (`mcp_tools/state.py`)

Add field:
```python
graph_client: Optional["GraphClient"] = None
```

Update `clear()` method to handle `graph_client`.

MCP server lifespan (`mcp_server.py`):
- If `M365_GRAPH_ENABLED`: create `GraphClient(M365_CLIENT_ID, M365_TENANT_ID)` and assign to `state.graph_client`
- On shutdown: `if state.graph_client: await state.graph_client.close()`

### 7. Dependencies

Add to `pyproject.toml` or `setup.py`:
```
msal >= 1.28.0
msal-extensions >= 1.1.0
```

`httpx` is already a dependency. No new heavy packages.

### 8. Daemon Token Expiry Handling

Entra refresh tokens are valid for ~90 days (rolling — each use extends the window). For daemon/headless contexts:

- `GraphClient.ensure_authenticated()` detects interactive vs headless mode
- In headless mode: if `acquire_token_silent()` fails, raises `GraphAuthError` (does NOT attempt device code flow)
- `GraphAuthError` triggers fallback to old backend (browser/CLI bridge) — daemon continues working
- **Monitoring**: `GraphClient` logs a WARNING when silent token refresh succeeds but token age > 60 days (approaching expiry)
- **Alerting**: Bootstrap script's `--verify` flag can be run as a scheduled health check; logs ERROR if tokens are missing/expired
- **Re-auth**: User runs `python scripts/bootstrap_secrets.py` to re-do device code flow when tokens expire

## What Is NOT Changing

- Calendar system (Apple Calendar + Claude M365 Bridge)
- Email reading (Apple Mail AppleScript + M365 MCP connector in Claude Code)
- Claude M365 Bridge (`connectors/claude_m365_bridge.py`) — stays as fallback for Teams read
- Browser automation code — stays as fallback for Teams send, not deleted
- Agent capabilities registry — no new capabilities needed (existing `teams_write` covers it)

## Implementation Workstreams

### WS1: Secrets Layer
- `vault/__init__.py`, `vault/keychain.py`
- `scripts/bootstrap_secrets.py`
- Tests: `tests/test_keychain.py`
- No dependencies on other workstreams

### WS2: Graph Auth Client
- `connectors/graph_client.py` (includes `GraphTransientError`, `GraphAuthError`, `GraphAPIError`)
- MSAL wrapper with KeychainPersistence
- Device code flow + silent refresh + headless detection
- httpx.AsyncClient lifecycle management
- Tests: `tests/test_graph_client.py` (mocked MSAL)
- **Depends on**: WS1 (for `get_secret()`)

### WS3: Teams Graph Integration
- Modify `mcp_tools/teams_browser_tools.py` — add Graph backend routing for send
- Add `read_teams_messages()` MCP tool with Graph/bridge routing
- Hybrid fallback logic with logging
- Deprecate `TEAMS_POSTER_BACKEND` in favor of `TEAMS_SEND_BACKEND`
- Tests: `tests/test_teams_graph.py`
- **Depends on**: WS2 (for `GraphClient`)

### WS4: Email Graph Integration
- Modify `mcp_tools/mail_tools.py` — add Graph send/reply path
- Preserve `confirm_send` gate before backend routing
- Hybrid fallback logic with logging
- Tests: `tests/test_mail_graph.py`
- **Depends on**: WS2 (for `GraphClient`)

### WS5: Config & Wiring
- Update `config.py` with new settings (using cached `get_secret()`)
- Update `mcp_tools/state.py` — add `graph_client` field to `ServerState`
- Update `mcp_server.py` lifespan — init/teardown `GraphClient`
- Update `pyproject.toml` / `setup.py` with new deps
- **Depends on**: WS1, WS2

## Testing Strategy

- All Graph API calls mocked (never hit real Microsoft endpoints in tests)
- MSAL token acquisition mocked
- Keychain calls mocked (subprocess mock for `security` CLI)
- Fallback paths tested explicitly: Graph failure → verify old method called
- `confirm_send` gate tested for both Graph and Apple Mail paths
- Daemon token expiry tested: silent refresh fails → GraphAuthError → fallback
- Integration test: bootstrap script with mocked `op` CLI

## Rollback

If Graph API integration causes issues:
1. Set `TEAMS_SEND_BACKEND=agent-browser`, `TEAMS_READ_BACKEND=m365-bridge`, `EMAIL_SEND_BACKEND=apple`
2. Everything reverts to pre-change behavior
3. No code changes needed — pure config rollback

To clear tokens (security incident):
1. Run `python scripts/bootstrap_secrets.py --clear-tokens`
2. This removes the MSAL token cache entry from macOS Keychain
3. Re-auth requires running the bootstrap script again with device code flow
