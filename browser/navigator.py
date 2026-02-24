"""Teams in-app navigation via the search bar."""

import asyncio
import logging

from browser.constants import (
    COMPOSE_SELECTORS,
    CHANNEL_NAME_SELECTORS,
    POST_TIMEOUT_MS,
)

logger = logging.getLogger(__name__)

# CSS selectors for the Teams search bar, tried in order.
# Confirmed via scripts/teams_search_explore.py
SEARCH_SELECTORS = (
    'input[placeholder*="Search"]',
    'input[aria-label*="Search"]',
    '[data-tid="search-input"]',
    '[data-tid="app-search-input"]',
)

# Selector for actual search result items (TOPHITS), not category filters.
# The dropdown has PRIMARYDOMAIN* items (filter shortcuts like "Messages",
# "Files") and TOPHITS* items (actual people/channel results).
# Confirmed via live DOM exploration 2026-02-23.
SEARCH_RESULT_SELECTOR = 'div[role="option"][data-tid*="TOPHITS"]'


class TeamsNavigator:
    """Navigate within the Teams SPA using the search bar."""

    @staticmethod
    async def _find_element(page, selectors, timeout_ms: int = 10_000):
        """Try each selector with retries. Returns first matching locator or None."""
        elapsed = 0
        interval_ms = 1_000
        while True:
            for selector in selectors:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    return locator
            elapsed += interval_ms
            if elapsed >= timeout_ms:
                return None
            await asyncio.sleep(interval_ms / 1_000)

    @staticmethod
    async def _detect_channel_name(page) -> str:
        """Detect active channel/conversation name from DOM."""
        for selector in CHANNEL_NAME_SELECTORS:
            try:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    text = await locator.first.inner_text()
                    text = text.strip()
                    if text:
                        return text
            except Exception:
                continue

        try:
            title = await page.title()
            if title and title not in ("Microsoft Teams", ""):
                for suffix in (" | Microsoft Teams", " - Microsoft Teams"):
                    if title.endswith(suffix):
                        title = title[: -len(suffix)]
                return title.strip() or "(unknown)"
        except Exception:
            pass

        return "(unknown)"

    @staticmethod
    async def _find_matching_result(locator, target: str):
        """Find the search result whose text contains *target*.

        Returns the matching element locator, or ``None`` if no match.
        """
        target_lower = target.lower()
        count = await locator.count()
        for i in range(count):
            try:
                text = await locator.nth(i).inner_text()
                if target_lower in text.lower():
                    return locator.nth(i)
            except Exception:
                continue
        return None

    async def search_and_navigate(self, page, target: str) -> dict:
        """Search for *target* in Teams and navigate to it.

        Returns a dict with:
        - ``"status": "navigated"`` and ``"detected_channel"`` on success
        - ``"status": "error"`` with ``"error"`` detail on failure
        """
        # Find the search bar
        search_bar = await self._find_element(page, SEARCH_SELECTORS, timeout_ms=10_000)
        if search_bar is None:
            # Auto-recover: reload page and retry once
            logger.info("Search bar not found, reloading page and retrying")
            try:
                await page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(3)
            except Exception as exc:
                logger.warning("Page reload failed during recovery: %s", exc)
            search_bar = await self._find_element(page, SEARCH_SELECTORS, timeout_ms=10_000)
            if search_bar is None:
                return {
                    "status": "error",
                    "error": "Could not find Teams search bar. Is Teams loaded?",
                }

        # Click search bar and type the target name
        await search_bar.click()
        await asyncio.sleep(0.5)
        await page.keyboard.press("Meta+a")  # Select all existing text
        await page.keyboard.type(target, delay=50)
        await asyncio.sleep(2)  # Wait for search results to populate

        # Find search results (TOPHITS only — skip category filters)
        result_items = await self._find_element(
            page, (SEARCH_RESULT_SELECTOR,), timeout_ms=10_000
        )
        if result_items is None:
            await page.keyboard.press("Escape")
            return {
                "status": "error",
                "error": f"No search results found for '{target}'.",
            }

        # Find the result whose text best matches the target
        match = await self._find_matching_result(result_items, target)
        if match is None:
            # Fall back to clicking the first TOPHITS result
            logger.info("No exact match for '%s', clicking first result", target)
            match = result_items.first

        await match.click()
        await asyncio.sleep(2)  # Wait for navigation

        # Wait for compose box to confirm we're in a conversation
        compose = await self._find_element(
            page, COMPOSE_SELECTORS, timeout_ms=POST_TIMEOUT_MS
        )
        if compose is None:
            return {
                "status": "error",
                "error": (
                    f"Navigated to '{target}' but compose box not found. "
                    "May have landed on a non-conversation page."
                ),
            }

        detected = await self._detect_channel_name(page)
        return {
            "status": "navigated",
            "detected_channel": detected,
        }
