"""Test posting to a Teams channel using cached session.

Usage: python3.11 scripts/teams_test_post.py <channel_url> [message]
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.teams_poster import PlaywrightTeamsPoster


async def main():
    if len(sys.argv) < 2:
        print("Usage: python3.11 scripts/teams_test_post.py <channel_url> [message]")
        print("Example: python3.11 scripts/teams_test_post.py 'https://teams.microsoft.com/...' 'Hello from Jarvis'")
        sys.exit(1)

    channel_url = sys.argv[1]
    message = sys.argv[2] if len(sys.argv) > 2 else "Test message from Jarvis"

    print(f"Channel: {channel_url}")
    print(f"Message: {message}")
    print()

    poster = PlaywrightTeamsPoster()
    result = await poster.post_message(channel_url, message)
    print(f"Result: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
