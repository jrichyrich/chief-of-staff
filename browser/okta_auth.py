"""Okta authentication flow for Teams browser automation.

Navigates to the Okta dashboard, waits for user authentication if needed,
clicks the Teams app tile, and returns the Teams page object.
"""

import asyncio
import logging

from browser.constants import (
    AUTH_TIMEOUT_MS,
    MS_SSO_CONTINUE_SELECTORS,
    MS_SSO_RETRY_SELECTORS,
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


async def _click_teams_tile(page, timeout_ms: int = 15_000) -> None:
    """Find and click the Microsoft Teams tile on the Okta dashboard.

    Retries every 2 seconds up to *timeout_ms* for tiles to render.
    Tries each selector in :data:`OKTA_TEAMS_TILE_SELECTORS` in order.
    Raises ``RuntimeError`` if no tile is found after timeout.
    """
    elapsed = 0
    poll_ms = 2_000
    while True:
        for selector in OKTA_TEAMS_TILE_SELECTORS:
            locator = page.locator(selector)
            if await locator.count() > 0:
                logger.info("Clicking Teams tile (selector: %s)", selector)
                await locator.first.click()
                return
        elapsed += poll_ms
        if elapsed >= timeout_ms:
            break
        logger.debug("Teams tile not found yet, retrying in %dms...", poll_ms)
        await asyncio.sleep(poll_ms / 1_000)
    raise RuntimeError(
        "Could not find Microsoft Teams tile on Okta dashboard. "
        "Check OKTA_TEAMS_TILE_SELECTORS in browser/constants.py."
    )


async def _handle_sso_prompts(page) -> bool:
    """Auto-click through Microsoft SSO intermediate pages.

    Handles "Do you trust mychg.com?" consent prompts and OAuth error
    retry buttons. Returns True if a button was clicked.
    """
    for selector in MS_SSO_CONTINUE_SELECTORS:
        locator = page.locator(selector)
        if await locator.count() > 0:
            logger.info("Clicking SSO continue button: %s", selector)
            await locator.first.click()
            return True

    # Check for Teams error page with retry buttons
    for selector in MS_SSO_RETRY_SELECTORS:
        locator = page.locator(selector)
        if await locator.count() > 0:
            logger.info("Clicking Teams retry button: %s", selector)
            await locator.first.click()
            return True

    return False


async def _wait_for_teams_tab(
    context, original_page_count: int, timeout_ms: int = 60_000
) -> "Page":
    """Wait for a Teams page to appear after clicking the tile.

    Handles intermediate Microsoft SSO pages (trust prompts, OAuth errors)
    by auto-clicking through them. If the tile redirect lands on Teams with
    an OAuth error (e.g. missing nonce), falls back to direct navigation
    since the SSO cookies are already established.

    Returns the page with a Teams URL.
    Raises ``RuntimeError`` on timeout.
    """
    elapsed = 0
    poll_ms = 2_000
    direct_nav_attempted = False
    while elapsed < timeout_ms:
        # Check all pages for Teams URL without errors
        for page in context.pages:
            if _is_on_teams(page.url) and "#error=" not in page.url:
                await page.wait_for_load_state("domcontentloaded")
                return page

        # Handle Teams pages with OAuth errors — fall back to direct nav
        for page in context.pages:
            if _is_on_teams(page.url) and "#error=" in page.url:
                if not direct_nav_attempted:
                    logger.warning(
                        "Teams SSO redirect failed (%s), "
                        "falling back to direct navigation.",
                        page.url.split("#error=")[1][:80],
                    )
                    direct_nav_attempted = True
                    await page.goto(
                        "https://teams.microsoft.com",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    # Give it time to authenticate via existing cookies
                    await asyncio.sleep(3)
                    continue

        # Auto-click through SSO prompts on login pages
        for page in context.pages:
            if "login.microsoftonline.com" in page.url:
                await _handle_sso_prompts(page)

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
    # Brief pause to let Okta's client-side JS redirect if session is expired
    # (URL may briefly show /app/UserHome before JS redirects to login)
    await asyncio.sleep(2)

    # 2. Wait for auth if needed
    if not _is_okta_dashboard(page.url):
        auth_ok = await _wait_for_okta_auth(page)
        if not auth_ok:
            raise RuntimeError(
                "Okta authentication timed out. Please try again."
            )

    # 3. Wait for dashboard tiles to render before clicking
    logger.info("Waiting for Okta dashboard tiles to load...")
    await page.wait_for_load_state("networkidle", timeout=15_000)
    await asyncio.sleep(2)  # Extra buffer for SPA tile rendering

    # 4. Click the Teams tile
    await _click_teams_tile(page)

    # 5. Wait for Teams to load (new tab or same-tab navigation)
    teams_page = await _wait_for_teams_tab(context, original_page_count)

    # 6. Close the Okta tab (if Teams opened in a new tab)
    if teams_page is not page:
        await page.close()

    return teams_page
