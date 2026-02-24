"""Teams in-app navigation via the search bar."""

import asyncio
import logging

from browser.teams_poster import (
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

# Selector for search result items in the dropdown.
# Confirmed via scripts/teams_search_results_explore.py
SEARCH_RESULT_SELECTORS = (
    'div[role="option"]',
    '[data-tid*="entity"]',
    'li[role="option"]',
    '[data-tid="search-result"]',
    '[data-tid*="suggestion"]',
)


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

    async def search_and_navigate(self, page, target: str) -> dict:
        """Search for *target* in Teams and navigate to it.

        Returns a dict with:
        - ``"status": "navigated"`` and ``"detected_channel"`` on success
        - ``"status": "error"`` with ``"error"`` detail on failure
        """
        # Find the search bar
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

        # Find and click the first search result
        result_item = await self._find_element(
            page, SEARCH_RESULT_SELECTORS, timeout_ms=10_000
        )
        if result_item is None:
            await page.keyboard.press("Escape")
            return {
                "status": "error",
                "error": f"No search results found for '{target}'.",
            }

        await result_item.first.click()
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
