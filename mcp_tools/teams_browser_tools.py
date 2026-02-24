"""Teams browser automation tools for MCP server.

Exposes a two-phase posting flow:
1. ``post_teams_message`` — opens browser, detects active channel, returns
   confirmation info without sending.
2. ``confirm_teams_post`` — sends the prepared message after user approval.
3. ``cancel_teams_post`` — closes the browser without sending.
"""

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
        """Prepare a message for posting to a Microsoft Teams channel.

        Opens a Chromium browser window, navigates to the channel URL,
        and detects the active channel/conversation. Does NOT send
        the message — returns confirmation info so the user can verify
        the correct channel before sending.

        If the Teams session has expired, the browser will show a login
        page — authenticate manually and the session will be cached.

        After this returns ``"confirm_required"``, call
        ``confirm_teams_post`` to send or ``cancel_teams_post`` to abort.

        Args:
            channel_url: Full Teams channel URL
            message: The message text to post
        """
        # Validate URL — Teams uses both old and new domains
        valid_domains = ("teams.microsoft.com", "teams.cloud.microsoft")
        if not any(d in channel_url for d in valid_domains):
            return json.dumps({
                "status": "error",
                "error": "Invalid URL. Must be a teams.microsoft.com or teams.cloud.microsoft URL.",
            })

        poster = _get_poster()
        result = await poster.prepare_message(channel_url, message)
        return json.dumps(result)

    @mcp.tool()
    async def confirm_teams_post() -> str:
        """Send the previously prepared Teams message.

        Must be called after ``post_teams_message`` returned
        ``"confirm_required"``. The message will be typed into the
        compose box and sent. The browser window closes after sending.
        """
        poster = _get_poster()
        result = await poster.send_prepared_message()
        return json.dumps(result)

    @mcp.tool()
    async def cancel_teams_post() -> str:
        """Cancel the previously prepared Teams message.

        Closes the browser window without sending. Use this if the
        detected channel was wrong or the user wants to abort.
        """
        poster = _get_poster()
        result = await poster.cancel_prepared_message()
        return json.dumps(result)

    # Expose at module level for test imports
    current_module = sys.modules[__name__]
    current_module.post_teams_message = post_teams_message
    current_module.confirm_teams_post = confirm_teams_post
    current_module.cancel_teams_post = cancel_teams_post
