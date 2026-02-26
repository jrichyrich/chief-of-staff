# Design: Playwright-Based Teams Channel Poster

**Date**: 2026-02-23
**Status**: Proposed

## Problem

Jarvis agents need the ability to post messages to Microsoft Teams channels on demand. The current M365 integration (via `ClaudeM365Bridge`) supports calendar operations and Teams message *reading* but not *posting*. Rather than navigating OAuth app registration and admin consent for the Graph API, this design uses Playwright browser automation with manual user authentication.

## Design Decisions

1. **Playwright over Graph API / webhooks** — User preference. Avoids Azure AD app registration, admin consent, and OAuth token management. Trades API stability for simplicity of setup.
2. **Manual auth, not automated Okta** — User authenticates in the browser when sessions expire. No TOTP secret extraction, no MFA automation. Human-in-the-loop for auth.
3. **Always headed (visible browser)** — User can observe what the agent is doing in Teams. No headless mode.
4. **Dynamic channel URLs** — Agent provides the full Teams channel URL at call time. No pre-configured channel mapping.
5. **Humanizer integration** — Outbound messages pass through the humanizer hook before posting.

## Architecture

```
Agent / MCP Tool Call
    post_teams_message(channel_url, message)
        |
        v
    PlaywrightTeamsPoster
        |
        +-- load storageState (cached session)
        +-- launch browser (always headed)
        +-- navigate to channel_url
        |
        +-- [if redirected to Okta/login page]
        |       wait for user to complete auth
        |       save new storageState
        |
        +-- locate compose box
        +-- type message + send
        +-- return result
```

## Components

### 1. `browser/teams_poster.py` — Core Automation

```python
class PlaywrightTeamsPoster:
    """Posts messages to Teams channels via Playwright browser automation."""

    SESSION_PATH = "data/playwright/teams_session.json"
    AUTH_TIMEOUT_MS = 120_000  # 2 min for user to complete auth
    POST_TIMEOUT_MS = 30_000  # 30s for message to send

    async def post_message(self, channel_url: str, message: str) -> dict:
        """Navigate to channel, type message, send. Returns status dict."""

    async def _ensure_authenticated(self, page) -> None:
        """Detect login redirect, wait for user auth, save session."""

    async def _send_message(self, page, message: str) -> None:
        """Locate compose box, type text, press Enter to send."""

    async def _is_login_page(self, page) -> bool:
        """Check if current page is Okta/Entra login."""

    async def _save_session(self, context) -> None:
        """Persist storageState to SESSION_PATH."""

    async def _load_session(self) -> Optional[dict]:
        """Load cached storageState if it exists and is not expired."""
```

**Key behaviors:**

- **Session caching**: After successful auth, `storageState` (cookies + localStorage) is saved to `data/playwright/teams_session.json`. Subsequent calls restore this state to skip login.
- **Auth detection**: After navigating to the channel URL, check if the page redirected to `login.microsoftonline.com`, `*.okta.com`, or similar. If so, print a message to stdout ("Please authenticate in the browser window...") and wait up to `AUTH_TIMEOUT_MS` for the URL to return to `teams.microsoft.com`.
- **Compose box targeting**: The Teams web compose box can be located via `[data-tid="ckeditor-replyConversation"]` or similar accessibility-friendly selectors. This is the most fragile part — selectors will need maintenance when Teams updates its UI.
- **Message sending**: Type the message text into the compose box, then press Enter (or click the send button). Wait for confirmation that the message appeared in the channel.
- **Error handling**: Return structured result dict with status, error message if failed, and whether re-auth is needed.

### 2. `mcp_tools/teams_browser_tools.py` — MCP Tool Registration

```python
def register(mcp, state):
    @mcp.tool()
    async def post_teams_message(channel_url: str, message: str) -> str:
        """Post a message to a Microsoft Teams channel via browser automation.

        Args:
            channel_url: Full Teams channel URL (e.g. https://teams.microsoft.com/l/channel/...)
            message: The message text to post

        Returns:
            JSON result with status and details
        """
```

- Registered like all other MCP tools via `register(mcp, state)`
- Imported and called from `mcp_server.py`
- Humanizer hook applies automatically (outbound `message` arg transformed by `before_tool_call`)

### 3. Session Management

| Item | Detail |
|------|--------|
| Storage location | `data/playwright/teams_session.json` |
| Contents | Playwright `storageState` JSON (cookies, localStorage, origins) |
| Expected lifetime | 4-8 hours (depends on Okta/Entra session policy) |
| Expiry detection | Auth redirect after navigation = session expired |
| Refresh mechanism | User manually re-authenticates in headed browser |
| Security | File excluded from git (add to `.gitignore`). Contains session tokens. |

### 4. Browser Lifecycle

The Playwright browser instance should be **short-lived per operation**, not a persistent daemon:

1. Tool call received → launch browser with cached `storageState`
2. Navigate, authenticate if needed, post message
3. Close browser

This avoids memory leaks, stale browser state, and zombie processes. The trade-off is ~2-3 seconds of browser startup per message, which is acceptable for agent-driven (not high-throughput) posting.

**Alternative considered**: Keep a persistent browser context in `ServerState` and reuse across calls. Rejected because browser processes can leak, crash, or accumulate stale state. The startup cost is acceptable.

## Auth Flow Detail

```
1. Launch Chromium (headed) with storageState
2. Navigate to channel_url
3. Check: did page land on Teams or redirect to login?

   [If Teams] → session valid → proceed to post
   [If Login] →
       a. Print to stdout: "Teams session expired. Please authenticate in the browser window."
       b. Send macOS notification via osascript (optional, nice UX)
       c. Poll page URL every 1s for up to AUTH_TIMEOUT_MS
       d. When URL matches teams.microsoft.com/* → auth complete
       e. Save new storageState
       f. Proceed to post

4. Post message
5. Close browser
```

## Compose Box Targeting Strategy

The Teams web app compose box is the most fragile element. Strategy for resilience:

1. **Primary selector**: `[data-tid="ckeditor-replyConversation"]` — Teams uses `data-tid` attributes for testing
2. **Fallback selector**: `div[role="textbox"][aria-label*="message"]` — accessibility attributes
3. **Last resort**: `contenteditable="true"` divs within the message compose area

If all selectors fail, return an error indicating the UI may have changed and selectors need updating.

**Selector maintenance**: When Teams updates break selectors, update the constants in `teams_poster.py`. This is expected maintenance — document the selectors and include a comment with the date they were last verified.

## Dependencies

| Package | Purpose | Install |
|---------|---------|---------|
| `playwright` | Browser automation | `pip install playwright && playwright install chromium` |

Note: Playwright requires a one-time `playwright install chromium` to download the browser binary (~150MB). This should be documented in setup instructions.

## File Layout

```
browser/
    __init__.py
    teams_poster.py          # PlaywrightTeamsPoster class
mcp_tools/
    teams_browser_tools.py   # MCP tool: post_teams_message
data/
    playwright/
        teams_session.json   # Cached storageState (gitignored)
```

## Integration Points

- **Humanizer hook**: The existing `before_tool_call` hook in `hooks/registry.py` will transform the `message` argument before posting, consistent with email and iMessage humanization.
- **Audit hook**: The existing `after_tool_call` audit hook logs all tool calls to `data/audit.jsonl`, including Teams posts.
- **Agent capabilities**: Add `teams_write` capability to `capabilities/registry.py` so agent YAML configs can declare access to `post_teams_message`.

## Testing Strategy

- **Unit tests**: Mock Playwright's `Page`, `BrowserContext`, and `Browser` objects. Test auth detection logic, session save/load, and error handling without launching a real browser.
- **No integration tests against real Teams**: Browser automation tests are inherently flaky and require auth. Manual verification only.
- **Selector validation**: Include a standalone script (`scripts/verify_teams_selectors.py`) that opens Teams in a browser and checks if the compose box selectors still work. Run manually when debugging selector breakage.

## Known Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Teams UI changes break selectors | High | Use `data-tid` attributes (more stable than class names). Document selectors with verification dates. |
| Microsoft ToS violation | Medium | Acknowledged. This is browser automation, not API abuse. Low volume, authenticated user. |
| Session expiry interrupts agent flow | Medium | Agent receives clear error; user re-authenticates. Not a crash. |
| Playwright browser binary size (~150MB) | Low | One-time download. Documented in setup. |
| macOS permissions (screen recording, accessibility) | Low | Headed Chromium may prompt for permissions on first run. |

## Out of Scope

- Reading Teams messages via Playwright (existing M365 MCP connector handles this)
- Automated Okta/MFA login (user authenticates manually)
- Headless mode
- Pre-configured channel mapping (dynamic URLs only)
- Rich formatting / Adaptive Cards (plain text only for v1)
- File/image attachments
