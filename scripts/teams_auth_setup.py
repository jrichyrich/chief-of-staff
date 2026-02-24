"""Auth setup: Okta login → click Teams tile → save Teams session.

Flow:
1. Open mychg.okta.com — you authenticate
2. You click the Microsoft Teams tile in Okta dashboard
3. SSO redirect establishes the Teams session
4. Script detects Teams loaded, saves session
5. Browser stays open so you can navigate to a channel and grab the URL
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.teams_poster import SESSION_PATH


async def main():
    from playwright.async_api import async_playwright

    print(f"Session will be saved to: {SESSION_PATH}")
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Step 1: Go to Okta
        print("\n--- Step 1: Opening mychg.okta.com ---")
        print("Log in with your Okta credentials.\n")
        await page.goto("https://mychg.okta.com")

        # Wait for Okta auth
        print("Waiting for Okta authentication...")
        for _ in range(120):
            await asyncio.sleep(1)
            url = page.url
            if "okta.com/app/" in url or "okta.com/home" in url or "/enduser/portal" in url:
                print(f"Okta auth complete! URL: {url}")
                break
        else:
            print("Timeout waiting for Okta auth.")
            await browser.close()
            return

        # Step 2: User clicks the Teams tile
        print("\n--- Step 2: Click the Microsoft Teams tile in Okta ---")
        print("This triggers the SSO redirect to establish the Teams session.")
        print("Waiting for Teams to load...\n")

        # Monitor for Teams to appear — could be current page or a new tab
        last_url = ""
        teams_loaded = False
        for i in range(120):  # 2 min
            await asyncio.sleep(1)

            # Check all pages in the context (new tabs)
            for p in context.pages:
                url = p.url
                if url != last_url and url != "about:blank":
                    print(f"  [{i:3d}s] URL: {url}")
                    last_url = url

                if "teams.microsoft.com" in url and "login" not in url:
                    page = p  # Switch to the Teams page
                    teams_loaded = True
                    break

            if teams_loaded:
                print(f"\nTeams loaded! URL: {page.url}")
                break
        else:
            print("Timeout waiting for Teams. Saving session anyway...")

        # Step 3: Wait for Teams to fully initialize
        print("\nWaiting 5s for Teams to fully initialize...")
        await asyncio.sleep(5)

        # Step 4: Save session
        state = await context.storage_state()
        SESSION_PATH.write_text(json.dumps(state, indent=2))
        print(f"\nSession saved to {SESSION_PATH}")
        print(f"Cookies: {len(state.get('cookies', []))}")
        print(f"Origins: {len(state.get('origins', []))}")

        # Step 5: Monitor URLs as user navigates
        print("\n--- Step 3: Navigate to a channel ---")
        print("Click into a Teams channel. URL changes will print below.")
        print("Copy the URL when you're on the right channel.")
        print("Browser closes in 120s.\n")

        last_url = ""
        for i in range(120):
            await asyncio.sleep(1)
            for p in context.pages:
                current = p.url
                if current != last_url and "teams.microsoft.com" in current:
                    print(f"  [{i:3d}s] {current}")
                    last_url = current

        # Re-save session before closing
        state = await context.storage_state()
        SESSION_PATH.write_text(json.dumps(state, indent=2))
        await browser.close()
        print("\nDone! Session cached. Use teams_test_post.py to post.")


if __name__ == "__main__":
    asyncio.run(main())
