"""End-to-end test of the persistent Teams browser flow.

Usage: python3.11 scripts/teams_persistent_test.py [target] [message]

Steps:
1. Opens browser (or connects to existing)
2. Navigates to Teams
3. Searches for target
4. Shows detected channel and waits for confirmation (30s)
5. Sends message
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.manager import TeamsBrowserManager
from browser.teams_poster import PlaywrightTeamsPoster


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "General"
    message = sys.argv[2] if len(sys.argv) > 2 else "Test from persistent browser"

    print(f"Target: {target}")
    print(f"Message: {message}\n")

    mgr = TeamsBrowserManager()

    # Step 1: Ensure browser is running
    if not mgr.is_alive():
        print("Launching browser...")
        result = mgr.launch()
        print(f"Launch: {json.dumps(result, indent=2)}")
        if result["status"] == "error":
            sys.exit(1)
        print("Waiting 15s for Teams to load...")
        await asyncio.sleep(15)
    else:
        print("Browser already running.")

    # Step 2: Prepare message
    poster = PlaywrightTeamsPoster(manager=mgr)
    print(f"\nSearching for '{target}'...")
    result = await poster.prepare_message(target, message)
    print(f"Prepare result: {json.dumps(result, indent=2)}")

    if result["status"] != "confirm_required":
        print(f"\nCannot proceed: {result.get('error', 'unknown error')}")
        return

    print(f"\n*** Detected: {result['detected_channel']} ***")
    print(f"*** Message:  {result['message']} ***")
    print("\nSending in 30s... (Ctrl+C to cancel)")

    try:
        await asyncio.sleep(30)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nCancelling...")
        cancel = await poster.cancel_prepared_message()
        print(f"Cancel: {json.dumps(cancel, indent=2)}")
        return

    # Step 3: Send
    print("\nSending...")
    send = await poster.send_prepared_message()
    print(f"Send: {json.dumps(send, indent=2)}")

    print("\nBrowser is still running. Use close_teams_browser to stop it.")


if __name__ == "__main__":
    asyncio.run(main())
