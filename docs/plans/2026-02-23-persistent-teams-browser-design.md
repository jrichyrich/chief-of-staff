# Persistent Teams Browser Design

## Goal

Replace the open-close-per-message Teams browser with a persistent Chromium instance that stays running in the background. Jarvis connects to it on demand via CDP, navigates to channels/people by name using the Teams search bar, and posts messages after user confirmation.

## Architecture

Three layers:

1. **Browser Manager** (`browser/manager.py`) — Launches Playwright's bundled Chromium as a detached subprocess with `--remote-debugging-port=9222` and `--user-data-dir`. Handles CDP reconnection via `pw.chromium.connect_over_cdp()`, health checks via HTTP (`/json/version`), and process cleanup. Each MCP tool call connects, does work, then disconnects — the browser stays running.

2. **Teams Navigator** (`browser/navigator.py`) — Clicks the Teams search bar, types a target name (channel or person), waits for the results dropdown, clicks the matching result, waits for the compose box, and detects the active channel/conversation name.

3. **MCP Tools** (`mcp_tools/teams_browser_tools.py`) — Five tools exposing the full lifecycle: open, post (prepare), confirm, cancel, close.

## Tool Flow

```
open_teams_browser
  → launches Chromium (detached subprocess, survives MCP restart)
  → navigates to teams.cloud.microsoft
  → user authenticates if session expired
  → returns {"status": "running", "pid": 12345}

post_teams_message(target="Engineering", message="Hello")
  → connects to running browser via CDP
  → clicks Teams search bar, types "Engineering"
  → clicks matching result in dropdown
  → waits for compose box
  → detects active channel name
  → returns {"status": "confirm_required", "detected_channel": "Engineering", "message": "Hello"}

confirm_teams_post
  → types message into compose box, presses Enter
  → returns {"status": "sent", "detected_channel": "Engineering"}

cancel_teams_post
  → discards pending message, disconnects
  → returns {"status": "cancelled"}

close_teams_browser
  → sends SIGTERM to Chromium PID
  → removes state file
  → returns {"status": "closed"}
```

## MCP Tools

| Tool | Parameters | Purpose |
|------|-----------|---------|
| `open_teams_browser` | — | Launch Chromium, navigate to Teams, wait for auth. Idempotent — returns status if already running. |
| `post_teams_message` | `target: str, message: str` | Connect to running browser, search for target by name (channel or person), navigate, detect active channel, return `confirm_required`. |
| `confirm_teams_post` | — | Type and send the pending message. |
| `cancel_teams_post` | — | Cancel without sending. |
| `close_teams_browser` | — | Kill Chromium process and clean up. |

Key change: `target` is a **name** (e.g. "Engineering", "John Smith"), not a URL. The Teams search bar handles both channels and people.

## Teams Search Navigation

1. Click the search bar — selector TBD via DOM exploration (likely `[data-tid="search-input"]` or `input[aria-label*="Search"]`)
2. Type the target name
3. Wait for results dropdown to appear
4. Click the first matching result
5. Wait for compose box to confirm navigation succeeded
6. Detect channel/conversation name from DOM header

Edge cases:
- **No results** → return `{"status": "error", "error": "Target 'xyz' not found in Teams search"}`
- **Ambiguous results** → return list of matches for user to clarify
- **Compose box doesn't appear** → retry or return error

## Browser State Management

### State file: `data/playwright/browser.json`

```json
{
  "pid": 12345,
  "cdp_port": 9222,
  "launched_at": "2026-02-23T20:00:00Z"
}
```

### Health check

Before every tool call, HTTP GET `http://localhost:{port}/json/version`. If it responds, connect via CDP. If not, return error telling user to call `open_teams_browser`.

### Session persistence

Chromium launched with `--user-data-dir=data/playwright/profile/` keeps cookies/localStorage in its own profile directory. No separate `teams_session.json` needed.

### Lifecycle

- `open_teams_browser` → health check first. If already running, return current status. Otherwise launch, write state file.
- `close_teams_browser` → SIGTERM to PID, remove state file.
- MCP server restart → browser keeps running. Next tool call reconnects via CDP.
- Browser crashes → health check fails, tool returns "browser not running" error.
- Pending message state lives in Python process memory (the poster singleton). If MCP server restarts between prepare and confirm, pending message is lost — acceptable since it's a short window.

## Browser Launch Details

Chromium must be launched as a **detached subprocess** (`subprocess.Popen` with `start_new_session=True`) — not via `pw.chromium.launch()` which kills the browser when Python exits.

```python
proc = subprocess.Popen(
    [chromium_path,
     "--remote-debugging-port=9222",
     "--user-data-dir=data/playwright/profile",
     "--no-first-run",
     "--no-default-browser-check"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
)
```

Reconnection uses `pw.chromium.connect_over_cdp(f"http://localhost:{port}")`. Disconnecting does NOT kill the browser — it only closes the Playwright connection.

After connecting, existing pages are at `browser.contexts[0].pages`.

## What Changes From Current Code

### Keep
- `browser/` package
- Two-phase confirm flow (prepare → confirm/cancel)
- Compose box selectors (`COMPOSE_SELECTORS`) and retry detection
- Channel name detection (`CHANNEL_NAME_SELECTORS` + page title fallback)
- MCP tool registration pattern (`register(mcp, state)`)
- `teams_write` capability definition
- Humanizer hook integration for `post_teams_message`

### Replace
- `PlaywrightTeamsPoster` (open/close per call) → `TeamsBrowserManager` (persistent) + `TeamsNavigator` (search-based)
- `channel_url` parameter → `target` parameter (name-based)
- `session_path` / `_load_session` / `_save_session_sync` → Chromium's own `--user-data-dir` profile
- `_wait_for_auth` → same concept but in `open_teams_browser`

### New
- `browser/manager.py` — launch, connect, health check, close
- `browser/navigator.py` — Teams search bar interaction, result selection
- `open_teams_browser` and `close_teams_browser` MCP tools
- `open_teams_browser` / `close_teams_browser` tool schemas in capabilities registry
- DOM exploration script for discovering search bar selectors

### Delete
- Legacy `post_message` one-shot method
- `scripts/teams_auth_setup.py` (auth handled by `open_teams_browser`)
- `SESSION_PATH` and session JSON file management
- `scripts/teams_url_monitor.py` (URLs no longer relevant)

## Tech Stack

- **Playwright** (`playwright.async_api`) — browser automation + CDP connection
- **subprocess** — detached Chromium launch
- **httpx** (already a project dependency) — CDP health checks
- **FastMCP** — MCP tool registration (existing pattern)
