"""Discover Teams search bar selectors.

Opens Teams with the persistent browser, then periodically checks
candidate selectors for the search bar / command bar. Prints which
selectors match so we can use them in TeamsNavigator.

Usage: python3.11 scripts/teams_search_explore.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.manager import TeamsBrowserManager


SEARCH_SELECTORS = [
    # Known data-tid patterns
    '[data-tid="search-input"]',
    '[data-tid="app-search-input"]',
    '[data-tid="search-box"]',
    '[data-tid="unified-search-input"]',
    # aria-label patterns
    'input[aria-label*="Search"]',
    'input[aria-label*="search"]',
    '[aria-label*="Search"]',
    # role patterns
    'input[role="search"]',
    'input[role="combobox"][aria-label*="Search"]',
    # Command bar / shortcut
    '[data-tid="command-bar"]',
    '[data-tid*="search"]',
    # Broader patterns
    'input[type="text"][placeholder*="Search"]',
    'input[placeholder*="search"]',
    'input[placeholder*="Search"]',
]

SEARCH_RESULT_SELECTORS = [
    '[data-tid="search-result"]',
    '[data-tid*="suggestion"]',
    'li[role="option"]',
    'div[role="option"]',
    'li[role="listitem"]',
    '[data-tid*="result"]',
    '[data-tid*="people"]',
    '[data-tid*="channel"]',
]


async def main():
    mgr = TeamsBrowserManager()

    if not mgr.is_alive():
        print("Browser not running. Launching...")
        result = mgr.launch()
        print(f"Launch: {result}")
        if result["status"] == "error":
            sys.exit(1)
        print("Waiting 15s for browser to start...")
        await asyncio.sleep(15)

    pw, browser = await mgr.connect()
    ctx = browser.contexts[0]

    if not ctx.pages:
        page = await ctx.new_page()
    else:
        page = ctx.pages[0]

    if "teams" not in page.url.lower():
        print("Navigating to Teams...")
        await page.goto("https://teams.cloud.microsoft/",
                        wait_until="domcontentloaded", timeout=30_000)

    print(f"URL: {page.url}")
    print("Waiting 10s for Teams to load...")
    await asyncio.sleep(10)

    print("\nChecking search selectors every 5s for 2 minutes...")
    print("=" * 60)

    for cycle in range(24):
        await asyncio.sleep(5)
        print(f"\n--- Cycle {cycle + 1} ---")

        # Check search bar selectors
        print("\nSearch bar selectors:")
        for sel in SEARCH_SELECTORS:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                if count > 0:
                    print(f"  FOUND ({count}): {sel}")
            except Exception as e:
                print(f"  ERROR: {sel} -> {e}")

        # Check search result selectors (useful if search is already open)
        print("\nSearch result selectors:")
        for sel in SEARCH_RESULT_SELECTORS:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                if count > 0:
                    print(f"  FOUND ({count}): {sel}")
            except Exception:
                pass

    await pw.stop()
    print("\nDone. Browser still running.")


if __name__ == "__main__":
    asyncio.run(main())
