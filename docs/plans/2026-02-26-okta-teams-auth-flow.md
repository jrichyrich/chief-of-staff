# Okta Auth Flow for Teams Browser Posting — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update the Teams browser flow to authenticate through Okta (`mychg.okta.com`) before opening Teams, by clicking the Teams app tile on the Okta dashboard.

**Architecture:** New `browser/okta_auth.py` module with `ensure_okta_and_open_teams()` handles Okta navigation → auth wait → tile click → new tab → Teams load. Constants added to `browser/constants.py`. The existing `_wait_for_teams()` in `mcp_tools/teams_browser_tools.py` is updated to call the new Okta flow. All downstream code (`teams_poster.py`, `navigator.py`) is unchanged.

**Tech Stack:** Python 3.11+, Playwright (async API), pytest, pytest-asyncio

**Design Doc:** `docs/plans/2026-02-26-okta-teams-auth-flow-design.md`

---

### Task 1: Add Okta constants to `browser/constants.py`

**Files:**
- Modify: `browser/constants.py`

**Step 1: Add Okta constants**

Add these after the existing `TEAMS_PATTERNS` tuple at line 21 of `browser/constants.py`:

```python
# Okta configuration.
OKTA_URL = "https://mychg.okta.com"

# URL patterns that indicate we're on the Okta dashboard (authenticated).
OKTA_DASHBOARD_PATTERNS = (
    "/app/UserHome",
    "/app/user-home",
    "/enduser/catalog",
)

# CSS selectors for the Teams app tile on the Okta dashboard, tried in order.
OKTA_TEAMS_TILE_SELECTORS = (
    'a:has-text("Microsoft Teams")',
    'a[aria-label*="Microsoft Teams"]',
    '.app-button:has-text("Microsoft Teams")',
    'a[data-se="app-card"]:has-text("Teams")',
)
```

**Step 2: Verify import works**

Run: `python -c "from browser.constants import OKTA_URL, OKTA_DASHBOARD_PATTERNS, OKTA_TEAMS_TILE_SELECTORS; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add browser/constants.py
git commit -m "feat: add Okta constants for Teams auth flow"
```

---

### Task 2: Write failing tests for `browser/okta_auth.py`

**Files:**
- Create: `tests/test_okta_auth.py`

**Step 1: Write the test file**

```python
"""Tests for browser.okta_auth — Okta authentication flow for Teams."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser.constants import (
    AUTH_TIMEOUT_MS,
    OKTA_DASHBOARD_PATTERNS,
    OKTA_TEAMS_TILE_SELECTORS,
    OKTA_URL,
    TEAMS_PATTERNS,
)


def _make_locator(count=1, texts=None):
    """Mock locator with count and optional text content."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    loc.click = AsyncMock()
    if texts:
        items = []
        for t in texts:
            item = AsyncMock()
            item.inner_text = AsyncMock(return_value=t)
            item.click = AsyncMock()
            items.append(item)

        def nth_effect(i):
            return items[i] if i < len(items) else AsyncMock()

        loc.nth = MagicMock(side_effect=nth_effect)
        loc.first = items[0]
    else:
        first = AsyncMock()
        first.click = AsyncMock()
        loc.first = first
        loc.nth = MagicMock(return_value=first)
    return loc


@pytest.fixture(autouse=True)
def _fast_sleep():
    """Replace asyncio.sleep with instant coroutine."""
    async def _instant(_seconds):
        pass
    with patch("browser.okta_auth.asyncio.sleep", side_effect=_instant):
        yield


@pytest.mark.asyncio
class TestIsOktaDashboard:
    async def test_user_home_url(self):
        from browser.okta_auth import _is_okta_dashboard
        assert _is_okta_dashboard("https://mychg.okta.com/app/UserHome") is True

    async def test_enduser_catalog_url(self):
        from browser.okta_auth import _is_okta_dashboard
        assert _is_okta_dashboard("https://mychg.okta.com/enduser/catalog") is True

    async def test_login_url_is_not_dashboard(self):
        from browser.okta_auth import _is_okta_dashboard
        assert _is_okta_dashboard("https://mychg.okta.com/login/login.htm") is False

    async def test_teams_url_is_not_dashboard(self):
        from browser.okta_auth import _is_okta_dashboard
        assert _is_okta_dashboard("https://teams.cloud.microsoft/") is False


@pytest.mark.asyncio
class TestIsOnTeams:
    async def test_teams_cloud_url(self):
        from browser.okta_auth import _is_on_teams
        assert _is_on_teams("https://teams.cloud.microsoft/v2/#/conversations") is True

    async def test_teams_microsoft_url(self):
        from browser.okta_auth import _is_on_teams
        assert _is_on_teams("https://teams.microsoft.com/v2/#/channel/123") is True

    async def test_okta_url_is_not_teams(self):
        from browser.okta_auth import _is_on_teams
        assert _is_on_teams("https://mychg.okta.com/app/UserHome") is False


@pytest.mark.asyncio
class TestWaitForOktaAuth:
    async def test_already_on_dashboard(self):
        from browser.okta_auth import _wait_for_okta_auth
        page = AsyncMock()
        page.url = "https://mychg.okta.com/app/UserHome"
        result = await _wait_for_okta_auth(page, timeout_ms=5_000)
        assert result is True

    async def test_auth_completes_after_login(self):
        from browser.okta_auth import _wait_for_okta_auth
        page = AsyncMock()
        # Start on login page, then transition to dashboard
        urls = iter([
            "https://mychg.okta.com/login/login.htm",
            "https://mychg.okta.com/login/login.htm",
            "https://mychg.okta.com/app/UserHome",
        ])
        type(page).url = property(lambda self: next(urls))
        result = await _wait_for_okta_auth(page, timeout_ms=10_000)
        assert result is True

    async def test_auth_times_out(self):
        from browser.okta_auth import _wait_for_okta_auth
        page = AsyncMock()
        # Stays on login page forever
        type(page).url = property(lambda self: "https://mychg.okta.com/login/login.htm")
        result = await _wait_for_okta_auth(page, timeout_ms=100)
        assert result is False


@pytest.mark.asyncio
class TestClickTeamsTile:
    async def test_clicks_first_matching_selector(self):
        from browser.okta_auth import _click_teams_tile
        page = AsyncMock()
        found_loc = _make_locator(count=1)
        empty_loc = _make_locator(count=0)

        def locator_effect(selector):
            if selector == OKTA_TEAMS_TILE_SELECTORS[0]:
                return found_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_effect)
        await _click_teams_tile(page)
        found_loc.first.click.assert_awaited_once()

    async def test_falls_back_to_later_selector(self):
        from browser.okta_auth import _click_teams_tile
        page = AsyncMock()
        found_loc = _make_locator(count=1)
        empty_loc = _make_locator(count=0)

        def locator_effect(selector):
            if selector == OKTA_TEAMS_TILE_SELECTORS[2]:
                return found_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_effect)
        await _click_teams_tile(page)
        found_loc.first.click.assert_awaited_once()

    async def test_raises_when_tile_not_found(self):
        from browser.okta_auth import _click_teams_tile
        page = AsyncMock()
        empty_loc = _make_locator(count=0)
        page.locator = MagicMock(return_value=empty_loc)

        with pytest.raises(RuntimeError, match="Teams tile"):
            await _click_teams_tile(page)


@pytest.mark.asyncio
class TestWaitForTeamsTab:
    async def test_detects_new_tab(self):
        from browser.okta_auth import _wait_for_teams_tab
        # Simulate context with original Okta page and a new Teams page
        okta_page = AsyncMock()
        okta_page.url = "https://mychg.okta.com/app/UserHome"

        teams_page = AsyncMock()
        teams_page.url = "https://teams.cloud.microsoft/v2/#/conversations"
        teams_page.wait_for_load_state = AsyncMock()

        context = MagicMock()
        context.pages = [okta_page, teams_page]

        result = await _wait_for_teams_tab(context, original_page_count=1, timeout_ms=5_000)
        assert result is teams_page

    async def test_detects_same_tab_navigation(self):
        from browser.okta_auth import _wait_for_teams_tab
        # No new tab, but existing page navigated to Teams
        page = AsyncMock()
        page.url = "https://teams.cloud.microsoft/v2/#/conversations"
        page.wait_for_load_state = AsyncMock()

        context = MagicMock()
        context.pages = [page]

        result = await _wait_for_teams_tab(context, original_page_count=1, timeout_ms=5_000)
        assert result is page

    async def test_times_out(self):
        from browser.okta_auth import _wait_for_teams_tab
        page = AsyncMock()
        page.url = "https://mychg.okta.com/app/UserHome"

        context = MagicMock()
        context.pages = [page]

        with pytest.raises(RuntimeError, match="Teams.*load"):
            await _wait_for_teams_tab(context, original_page_count=1, timeout_ms=100)


@pytest.mark.asyncio
class TestEnsureOktaAndOpenTeams:
    async def test_happy_path_new_tab(self):
        """Dashboard active → tile click → new tab with Teams → returns Teams page."""
        from browser.okta_auth import ensure_okta_and_open_teams

        okta_page = AsyncMock()
        # After goto, we're on the dashboard
        okta_page.url = "https://mychg.okta.com/app/UserHome"
        okta_page.goto = AsyncMock()
        okta_page.close = AsyncMock()

        teams_page = AsyncMock()
        teams_page.url = "https://teams.cloud.microsoft/v2/#/conversations"
        teams_page.wait_for_load_state = AsyncMock()

        found_loc = _make_locator(count=1)
        empty_loc = _make_locator(count=0)

        def locator_effect(selector):
            if selector == OKTA_TEAMS_TILE_SELECTORS[0]:
                return found_loc
            return empty_loc

        okta_page.locator = MagicMock(side_effect=locator_effect)

        context = MagicMock()
        # Before tile click: 1 page. After: 2 pages.
        context.pages = [okta_page, teams_page]

        result = await ensure_okta_and_open_teams(okta_page, context)
        assert result is teams_page
        okta_page.goto.assert_awaited_once()
        okta_page.close.assert_awaited_once()

    async def test_auth_required_then_proceeds(self):
        """Login page → user auths → dashboard → tile click → Teams."""
        from browser.okta_auth import ensure_okta_and_open_teams

        okta_page = AsyncMock()
        teams_page = AsyncMock()
        teams_page.url = "https://teams.cloud.microsoft/v2/#/conversations"
        teams_page.wait_for_load_state = AsyncMock()

        # Start on login, then move to dashboard
        url_sequence = iter([
            "https://mychg.okta.com/login/login.htm",  # after goto
            "https://mychg.okta.com/login/login.htm",  # first poll
            "https://mychg.okta.com/app/UserHome",     # auth completed
            "https://mychg.okta.com/app/UserHome",     # dashboard check
        ])
        type(okta_page).url = property(lambda self: next(url_sequence))
        okta_page.goto = AsyncMock()
        okta_page.close = AsyncMock()

        found_loc = _make_locator(count=1)
        empty_loc = _make_locator(count=0)

        def locator_effect(selector):
            if selector == OKTA_TEAMS_TILE_SELECTORS[0]:
                return found_loc
            return empty_loc

        okta_page.locator = MagicMock(side_effect=locator_effect)

        context = MagicMock()
        context.pages = [okta_page, teams_page]

        result = await ensure_okta_and_open_teams(okta_page, context)
        assert result is teams_page

    async def test_auth_timeout_raises(self):
        """Login page → auth never completes → raises RuntimeError."""
        from browser.okta_auth import ensure_okta_and_open_teams

        okta_page = AsyncMock()
        type(okta_page).url = property(
            lambda self: "https://mychg.okta.com/login/login.htm"
        )
        okta_page.goto = AsyncMock()

        context = MagicMock()
        context.pages = [okta_page]

        with patch("browser.okta_auth.AUTH_TIMEOUT_MS", 100):
            with pytest.raises(RuntimeError, match="authentication timed out"):
                await ensure_okta_and_open_teams(okta_page, context)

    async def test_tile_not_found_raises(self):
        """Dashboard reached but tile not found → raises RuntimeError."""
        from browser.okta_auth import ensure_okta_and_open_teams

        okta_page = AsyncMock()
        okta_page.url = "https://mychg.okta.com/app/UserHome"
        okta_page.goto = AsyncMock()

        empty_loc = _make_locator(count=0)
        okta_page.locator = MagicMock(return_value=empty_loc)

        context = MagicMock()
        context.pages = [okta_page]

        with pytest.raises(RuntimeError, match="Teams tile"):
            await ensure_okta_and_open_teams(okta_page, context)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_okta_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'browser.okta_auth'`

**Step 3: Commit**

```bash
git add tests/test_okta_auth.py
git commit -m "test: add failing tests for Okta auth flow"
```

---

### Task 3: Implement `browser/okta_auth.py`

**Files:**
- Create: `browser/okta_auth.py`

**Step 1: Write the implementation**

```python
"""Okta authentication flow for Teams browser automation.

Navigates to the Okta dashboard, waits for user authentication if needed,
clicks the Teams app tile, and returns the Teams page object.
"""

import asyncio
import logging

from browser.constants import (
    AUTH_TIMEOUT_MS,
    OKTA_DASHBOARD_PATTERNS,
    OKTA_TEAMS_TILE_SELECTORS,
    OKTA_URL,
    TEAMS_PATTERNS,
)

logger = logging.getLogger(__name__)


def _is_okta_dashboard(url: str) -> bool:
    """Return True if *url* is on the Okta dashboard (authenticated)."""
    return any(pattern in url for pattern in OKTA_DASHBOARD_PATTERNS)


def _is_on_teams(url: str) -> bool:
    """Return True if *url* is a Teams page."""
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in TEAMS_PATTERNS)


async def _wait_for_okta_auth(page, timeout_ms: int = AUTH_TIMEOUT_MS) -> bool:
    """Wait for user to complete Okta authentication.

    Polls ``page.url`` every 2 seconds until it matches an Okta dashboard
    pattern. Returns True if auth completed, False if timed out.
    """
    if _is_okta_dashboard(page.url):
        return True

    logger.info("Okta session expired. Please authenticate in the browser window.")
    elapsed = 0
    poll_ms = 2_000
    while elapsed < timeout_ms:
        await asyncio.sleep(poll_ms / 1_000)
        elapsed += poll_ms
        if _is_okta_dashboard(page.url):
            logger.info("Okta authentication completed.")
            return True
    return False


async def _click_teams_tile(page) -> None:
    """Find and click the Microsoft Teams tile on the Okta dashboard.

    Tries each selector in :data:`OKTA_TEAMS_TILE_SELECTORS` in order.
    Raises ``RuntimeError`` if no tile is found.
    """
    for selector in OKTA_TEAMS_TILE_SELECTORS:
        locator = page.locator(selector)
        if await locator.count() > 0:
            logger.info("Clicking Teams tile (selector: %s)", selector)
            await locator.first.click()
            return
    raise RuntimeError(
        "Could not find Microsoft Teams tile on Okta dashboard. "
        "Check OKTA_TEAMS_TILE_SELECTORS in browser/constants.py."
    )


async def _wait_for_teams_tab(
    context, original_page_count: int, timeout_ms: int = 30_000
) -> "Page":
    """Wait for a Teams page to appear after clicking the tile.

    Checks for a new tab first, then falls back to same-tab navigation.
    Returns the page with a Teams URL. Raises ``RuntimeError`` on timeout.
    """
    elapsed = 0
    poll_ms = 1_000
    while elapsed < timeout_ms:
        # Check for new tab
        if len(context.pages) > original_page_count:
            for page in context.pages[original_page_count:]:
                if _is_on_teams(page.url):
                    await page.wait_for_load_state("domcontentloaded")
                    return page

        # Check if an existing page navigated to Teams
        for page in context.pages:
            if _is_on_teams(page.url):
                await page.wait_for_load_state("domcontentloaded")
                return page

        await asyncio.sleep(poll_ms / 1_000)
        elapsed += poll_ms

    raise RuntimeError(
        "Teams did not load after clicking tile. "
        "Check if the tile opened a new window instead of a tab."
    )


async def ensure_okta_and_open_teams(page, context) -> "Page":
    """Navigate through Okta to open Teams. Returns the Teams page.

    Flow:
    1. Navigate to Okta
    2. Wait for user auth if session expired
    3. Click the Teams tile
    4. Wait for Teams to load in a new tab
    5. Close the Okta tab
    6. Return the Teams page

    Args:
        page: The current Playwright page (will be navigated to Okta).
        context: The browser context (used to detect new tabs).

    Returns:
        The Playwright Page object showing Teams.

    Raises:
        RuntimeError: If auth times out, tile not found, or Teams fails to load.
    """
    original_page_count = len(context.pages)

    # 1. Navigate to Okta
    await page.goto(OKTA_URL, wait_until="domcontentloaded", timeout=30_000)

    # 2. Wait for auth if needed
    if not _is_okta_dashboard(page.url):
        auth_ok = await _wait_for_okta_auth(page)
        if not auth_ok:
            raise RuntimeError(
                "Okta authentication timed out. Please try again."
            )

    # 3. Click the Teams tile
    await _click_teams_tile(page)

    # 4. Wait for Teams to load (new tab or same-tab navigation)
    teams_page = await _wait_for_teams_tab(context, original_page_count)

    # 5. Close the Okta tab (if Teams opened in a new tab)
    if teams_page is not page:
        await page.close()

    return teams_page
```

**Step 2: Run tests to verify they pass**

Run: `pytest tests/test_okta_auth.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add browser/okta_auth.py
git commit -m "feat: implement Okta auth flow for Teams browser automation"
```

---

### Task 4: Update `_wait_for_teams` in `mcp_tools/teams_browser_tools.py`

**Files:**
- Modify: `mcp_tools/teams_browser_tools.py:37-52`

**Step 1: Write failing test for the updated flow**

Add to `tests/test_teams_browser_tools.py` after the existing `TestCancelTeamsPost` class:

```python
@pytest.mark.asyncio
class TestWaitForTeams:
    async def test_skips_okta_when_already_on_teams(self):
        """If a page is already on Teams, skip the Okta flow."""
        mock_mgr = MagicMock()
        mock_pw = AsyncMock()
        mock_page = AsyncMock()
        mock_page.url = "https://teams.cloud.microsoft/v2/#/conversations"

        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        mock_browser = MagicMock()
        mock_browser.contexts = [mock_ctx]
        mock_mgr.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        result = await teams_browser_tools._wait_for_teams(mock_mgr)
        assert result is True
        mock_pw.stop.assert_awaited_once()

    async def test_calls_okta_flow_when_not_on_teams(self):
        """If no page is on Teams, call ensure_okta_and_open_teams."""
        mock_mgr = MagicMock()
        mock_pw = AsyncMock()
        mock_page = AsyncMock()
        mock_page.url = "about:blank"

        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        mock_browser = MagicMock()
        mock_browser.contexts = [mock_ctx]
        mock_mgr.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        teams_page = AsyncMock()
        teams_page.url = "https://teams.cloud.microsoft/"

        with patch(
            "mcp_tools.teams_browser_tools.ensure_okta_and_open_teams",
            new_callable=AsyncMock,
            return_value=teams_page,
        ) as mock_okta:
            result = await teams_browser_tools._wait_for_teams(mock_mgr)

        assert result is True
        mock_okta.assert_awaited_once_with(mock_page, mock_ctx)
        mock_pw.stop.assert_awaited_once()

    async def test_returns_false_on_okta_failure(self):
        """Returns False if the Okta flow raises."""
        mock_mgr = MagicMock()
        mock_pw = AsyncMock()
        mock_page = AsyncMock()
        mock_page.url = "about:blank"

        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        mock_browser = MagicMock()
        mock_browser.contexts = [mock_ctx]
        mock_mgr.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        with patch(
            "mcp_tools.teams_browser_tools.ensure_okta_and_open_teams",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Okta authentication timed out"),
        ):
            result = await teams_browser_tools._wait_for_teams(mock_mgr)

        assert result is False
```

**Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_teams_browser_tools.py::TestWaitForTeams -v`
Expected: FAIL (test expects `ensure_okta_and_open_teams` import and new behavior)

**Step 3: Update `_wait_for_teams` in `mcp_tools/teams_browser_tools.py`**

Replace the `_wait_for_teams` function (lines 37-52) with:

```python
async def _wait_for_teams(manager, timeout_s: int = 30) -> bool:
    """After launch, navigate through Okta to Teams and wait for it to load."""
    try:
        pw, browser = await manager.connect()
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # If already on Teams, nothing to do
        if any(p in page.url.lower() for p in ("teams.microsoft.com", "teams.cloud.microsoft")):
            await pw.stop()
            return True

        # Go through Okta auth → tile click → Teams
        from browser.okta_auth import ensure_okta_and_open_teams
        await ensure_okta_and_open_teams(page, ctx)

        await pw.stop()
        return True
    except Exception as exc:
        logger.warning("Failed to navigate to Teams via Okta: %s", exc)
        return False
```

Also add this import near the top of the file (after `import sys`):

```python
from browser.okta_auth import ensure_okta_and_open_teams
```

**Step 4: Run all teams browser tools tests**

Run: `pytest tests/test_teams_browser_tools.py -v`
Expected: All tests PASS (existing + new)

**Step 5: Commit**

```bash
git add mcp_tools/teams_browser_tools.py tests/test_teams_browser_tools.py
git commit -m "feat: update _wait_for_teams to use Okta auth flow"
```

---

### Task 5: Run full test suite and verify no regressions

**Step 1: Run all tests**

Run: `pytest --tb=short -q`
Expected: All existing tests pass + all new tests pass. No regressions.

**Step 2: Run just the new and modified test files**

Run: `pytest tests/test_okta_auth.py tests/test_teams_browser_tools.py -v`
Expected: All PASS

**Step 3: Commit (only if any fixups were needed)**

---

### Task 6: Manual smoke test

This task is manual — not automatable.

**Step 1: Close any running Teams browser**

Call `close_teams_browser` or manually kill Chromium.

**Step 2: Call `open_teams_browser`**

Expected flow:
- Chromium launches (headed)
- Navigates to `mychg.okta.com`
- If session active: lands on Okta dashboard, clicks Teams tile
- If session expired: shows Okta login, complete FastPass/biometrics manually
- After auth: clicks Teams tile
- New tab opens with Teams
- Okta tab closes
- Returns `{"status": "running", ...}`

**Step 3: Verify Teams is loaded**

Call `post_teams_message` with a test target to confirm Teams is navigable.

**Step 4: Note any selector issues**

If the Okta Teams tile selectors don't match, inspect the DOM and update `OKTA_TEAMS_TILE_SELECTORS` in `browser/constants.py`.
