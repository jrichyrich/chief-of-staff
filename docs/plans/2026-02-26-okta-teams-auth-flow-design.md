# Design: Okta Authentication Flow for Teams Browser Posting

**Date**: 2026-02-26
**Status**: Approved

## Problem

The Teams browser automation currently navigates directly to `teams.cloud.microsoft/`, which fails because the user's org requires Okta SSO authentication first. The browser gets redirected to an Okta login page with no automated path forward. The flow needs to go through Okta — authenticate if needed, then click the Teams app tile on the Okta dashboard to open Teams properly.

## Design Decisions

1. **Okta-first navigation** — Navigate to `mychg.okta.com` before Teams. This mirrors what a human does and ensures the SSO session is established before Teams loads.
2. **Tile click, not direct URL** — Click the Teams tile on the Okta dashboard rather than navigating directly to `teams.cloud.microsoft/` after Okta auth. This is the "official" path and avoids depending on SSO cookie propagation behavior.
3. **Human-in-the-loop auth** — When the Okta session is expired (~8 hour lifetime), the user manually completes FastPass/biometrics in the headed browser window. No automated MFA.
4. **Close Okta tab after Teams opens** — Keep the browser tidy with only the Teams tab.
5. **Okta logic in its own module** — `browser/okta_auth.py` isolates Okta-specific selectors and flow from Teams navigation/posting code.

## Architecture

```
open_teams_browser
    |
    v
TeamsBrowserManager.launch()          # Start Chromium (or reuse running)
    |
    v
_wait_for_teams(manager)              # Updated entry point
    |
    +-- connect to browser via CDP
    +-- check: any existing page already on Teams?
    |       [yes] → done (idempotent)
    |       [no]  → continue
    |
    +-- ensure_okta_and_open_teams(page, context)
            |
            +-- navigate to mychg.okta.com
            +-- detect: login page or dashboard?
            |
            |   [login page]
            |       → log "Please authenticate in the browser window..."
            |       → poll URL every 1-2s up to AUTH_TIMEOUT_MS (120s)
            |       → user completes FastPass/biometrics
            |
            |   [dashboard]
            |       → session active, proceed
            |
            +-- find Teams tile on dashboard
            +-- set up listener for new tab
            +-- click Teams tile
            +-- wait for new tab (or same-tab navigation)
            +-- switch to Teams tab
            +-- wait for Teams to load (URL matches TEAMS_PATTERNS)
            +-- close Okta tab
            +-- return Teams page
```

## Components

### 1. `browser/constants.py` — New Okta Constants

```python
# Okta configuration
OKTA_URL = "https://mychg.okta.com"

# Selectors for the Teams app tile on the Okta dashboard, tried in order.
OKTA_TEAMS_TILE_SELECTORS = (
    'a:has-text("Microsoft Teams")',
    'a[aria-label*="Microsoft Teams"]',
    '.app-button:has-text("Microsoft Teams")',
    'a[data-se="app-card"]:has-text("Teams")',
)

# URL patterns indicating the Okta dashboard (authenticated).
OKTA_DASHBOARD_PATTERNS = (
    "/app/UserHome",
    "/app/user-home",
    "/enduser/catalog",
)
```

### 2. `browser/okta_auth.py` — New Module

Single main function: `ensure_okta_and_open_teams(page, context) -> Page`

```python
async def ensure_okta_and_open_teams(page, context) -> Page:
    """Navigate through Okta to open Teams. Returns the Teams page object.

    Flow:
    1. Navigate to OKTA_URL
    2. If on login page, wait for user to authenticate (up to AUTH_TIMEOUT_MS)
    3. Find and click the Teams tile on the Okta dashboard
    4. Wait for new tab with Teams, switch to it
    5. Close the Okta tab
    6. Return the Teams page

    Raises RuntimeError if auth times out, tile not found, or Teams fails to load.
    """
```

Key internal helpers:

- `_is_okta_dashboard(url) -> bool` — checks URL against `OKTA_DASHBOARD_PATTERNS`
- `_wait_for_okta_auth(page) -> bool` — polls URL until dashboard reached or timeout
- `_click_teams_tile(page) -> None` — tries each `OKTA_TEAMS_TILE_SELECTORS` in order
- `_wait_for_teams_tab(context, original_pages) -> Page` — waits for new tab with Teams URL

### 3. `mcp_tools/teams_browser_tools.py` — Modified `_wait_for_teams`

```python
async def _wait_for_teams(manager, timeout_s: int = 30) -> bool:
    """After launch, navigate through Okta to Teams."""
    try:
        pw, browser = await manager.connect()
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Skip Okta if already on Teams
        if any(p in page.url.lower() for p in TEAMS_PATTERNS):
            await pw.stop()
            return True

        # Go through Okta
        teams_page = await ensure_okta_and_open_teams(page, ctx)
        # teams_page is now the active Teams tab

        await pw.stop()
        return True
    except Exception as exc:
        logger.warning("Failed to navigate to Teams via Okta: %s", exc)
        return False
```

### 4. Unchanged Modules

- `browser/teams_poster.py` — receives a `page` object, no changes needed
- `browser/navigator.py` — operates on the Teams page, no changes needed
- `browser/manager.py` — browser lifecycle unchanged

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Okta session active | Skip auth, proceed to tile click |
| Okta session expired | Wait for user FastPass/biometrics (up to 120s) |
| Auth timeout | Return error: "Okta authentication timed out" |
| Teams tile not found | Return error: "Could not find Microsoft Teams tile on Okta dashboard" |
| Tile click doesn't open new tab | Fallback: check if current page navigated to Teams URL |
| Intermediate SSO hop after tile click | Wait for any page URL to match TEAMS_PATTERNS (up to AUTH_TIMEOUT_MS) |
| Already on Teams (idempotent call) | Skip Okta flow entirely |

## File Changes Summary

| File | Change |
|------|--------|
| `browser/okta_auth.py` | **New** — `ensure_okta_and_open_teams()` and helpers |
| `browser/constants.py` | **Modified** — add `OKTA_URL`, `OKTA_TEAMS_TILE_SELECTORS`, `OKTA_DASHBOARD_PATTERNS` |
| `mcp_tools/teams_browser_tools.py` | **Modified** — `_wait_for_teams` uses Okta flow |
| `tests/test_okta_auth.py` | **New** — unit tests for Okta auth module |
| `browser/teams_poster.py` | Unchanged |
| `browser/navigator.py` | Unchanged |
| `browser/manager.py` | Unchanged |

## Testing Strategy

- **Unit tests** (`tests/test_okta_auth.py`): Mock Playwright Page/Context objects. Test login detection, dashboard detection, tile click selector fallback, new tab handling, auth timeout, and idempotent skip.
- **No live integration tests**: Okta auth requires real credentials and MFA. Manual verification only.
- **Selector exploration script**: Add `scripts/okta_tile_explore.py` to launch browser, navigate to Okta dashboard, and dump available app tile selectors for debugging.

## Known Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Okta dashboard layout changes | Medium | Multiple tile selectors with fallbacks. Exploration script for debugging. |
| Intermediate SSO redirect adds delay | Low | Extended timeout after tile click. Poll for Teams URL. |
| FastPass prompt doesn't appear in Chromium | Low | Okta Verify runs as separate app, should work. Test during manual smoke test. |
| New tab behavior varies by Okta config | Low | Fallback to same-tab navigation detection. |
