"""Teams browser automation tools for MCP server."""

import json
import sys

# Module-level poster instance (lazy, replaceable for tests)
_poster = None


def _get_poster():
    """Get or create the poster singleton."""
    global _poster
    if _poster is None:
        from browser.teams_poster import PlaywrightTeamsPoster
        _poster = PlaywrightTeamsPoster()
    return _poster


def register(mcp, state):
    """Register Teams browser tools with the MCP server."""

    @mcp.tool()
    async def post_teams_message(channel_url: str, message: str) -> str:
        """Post a message to a Microsoft Teams channel via browser automation.

        Opens a Chromium browser window. If the Teams session has expired,
        the browser will show a login page -- authenticate manually and the
        session will be cached for future calls.

        Args:
            channel_url: Full Teams channel URL (e.g. https://teams.microsoft.com/l/channel/...)
            message: The message text to post
        """
        # Validate URL
        if "teams.microsoft.com" not in channel_url:
            return json.dumps({
                "status": "error",
                "error": "Invalid URL. Must be a teams.microsoft.com URL.",
            })

        poster = _get_poster()
        result = await poster.post_message(channel_url, message)
        return json.dumps(result)

    # Expose at module level for test imports
    current_module = sys.modules[__name__]
    current_module.post_teams_message = post_teams_message
