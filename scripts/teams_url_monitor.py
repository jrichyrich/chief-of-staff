"""Open Teams with cached session and print the URL as it changes.

Navigate to different channels — this script will print the URL
every time it changes so we can discover the URL pattern.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.teams_poster import SESSION_PATH


async def main():
    from playwright.async_api import async_playwright

    session_file = SESSION_PATH
    if not session_file.exists():
        print(f"No session found at {session_file}. Run teams_auth_setup.py first.")
        sys.exit(1)

    session = json.loads(session_file.read_text())
    print(f"Loaded session with {len(session.get('cookies', []))} cookies\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=session)
        page = await context.new_page()

        await page.goto("https://teams.microsoft.com")
        await page.wait_for_load_state("domcontentloaded")

        print("Teams is open. Click on different channels.")
        print("URL changes will be printed below.\n")

        last_url = ""
        # Monitor for 3 minutes
        for i in range(180):
            await asyncio.sleep(1)
            current = page.url
            if current != last_url:
                print(f"[{i:3d}s] URL: {current}")
                last_url = current

        # Save final session state
        state = await context.storage_state()
        session_file.write_text(json.dumps(state, indent=2))
        print(f"\nSession re-saved. Browser closing.")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
