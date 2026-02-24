"""Explore Teams DOM: open with cached session, inspect compose box selectors and URL patterns.

Opens Teams, waits for you to navigate to a channel, then inspects the page
to find compose box elements and report on what selectors work.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.teams_poster import SESSION_PATH, COMPOSE_SELECTORS


async def main():
    from playwright.async_api import async_playwright

    session_file = SESSION_PATH
    if not session_file.exists():
        print(f"No session at {session_file}. Run teams_auth_setup.py first.")
        sys.exit(1)

    session = json.loads(session_file.read_text())
    print(f"Loaded session ({len(session.get('cookies', []))} cookies)\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=session)
        page = await context.new_page()

        print("Opening Teams...")
        await page.goto("https://teams.cloud.microsoft")
        await page.wait_for_load_state("domcontentloaded")
        print(f"URL: {page.url}\n")

        # Wait for Teams to load
        print("Waiting 10s for Teams to initialize...")
        await asyncio.sleep(10)

        # Monitor URL and periodically check for compose box
        print("\nNavigate to a channel. Checking every 5s for compose box...")
        print("=" * 60)

        last_url = ""
        for cycle in range(36):  # 3 minutes
            await asyncio.sleep(5)

            # Print URL if changed
            current_url = page.url
            if current_url != last_url:
                print(f"\n[URL changed] {current_url}")
                last_url = current_url

            # Check each compose selector
            print(f"\n--- Selector check (cycle {cycle + 1}) ---")
            for sel in COMPOSE_SELECTORS:
                try:
                    loc = page.locator(sel)
                    count = await loc.count()
                    if count > 0:
                        print(f"  FOUND ({count}): {sel}")
                    else:
                        print(f"  miss  (0): {sel}")
                except Exception as e:
                    print(f"  ERROR: {sel} -> {e}")

            # Also try some broader selectors
            broad_selectors = [
                'div[contenteditable="true"]',
                '[data-tid*="compose"]',
                '[data-tid*="reply"]',
                '[data-tid*="editor"]',
                '[data-tid*="message"]',
                '[role="textbox"]',
                'div[aria-label*="compose"]',
                'div[aria-label*="Type"]',
                'div[aria-label*="type"]',
                'div[aria-label*="message"]',
                'div[aria-label*="Message"]',
            ]
            found_any = False
            for sel in broad_selectors:
                try:
                    loc = page.locator(sel)
                    count = await loc.count()
                    if count > 0:
                        print(f"  BROAD ({count}): {sel}")
                        found_any = True
                except Exception:
                    pass

            if not found_any:
                print("  (no broad selectors matched either)")

        # Save session
        state = await context.storage_state()
        SESSION_PATH.write_text(json.dumps(state, indent=2))
        await browser.close()
        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
