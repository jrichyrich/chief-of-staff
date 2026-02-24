# tests/test_teams_browser_tools.py
"""Tests for the Teams browser automation MCP tools."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import mcp_server  # noqa: F401 — triggers tool registrations

# The module must be registered before importing the tool function.
# Since mcp_server does NOT yet register teams_browser_tools (Task 5),
# we call register() manually so the module-level function is available.
from mcp_tools import teams_browser_tools
from mcp_tools.state import ServerState

# Manually register to expose post_teams_message at module level.
teams_browser_tools.register(mcp_server.mcp, mcp_server._state)
from mcp_tools.teams_browser_tools import post_teams_message


@pytest.mark.asyncio
class TestPostTeamsMessage:
    async def test_post_teams_message_success(self):
        """Mock _get_poster so post_message returns a 'sent' result."""
        mock_poster = AsyncMock()
        mock_poster.post_message.return_value = {
            "status": "sent",
            "channel_url": "https://teams.microsoft.com/l/channel/test",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await post_teams_message(
                channel_url="https://teams.microsoft.com/l/channel/test",
                message="Hello from test",
            )

        result = json.loads(raw)
        assert result["status"] == "sent"
        assert "teams.microsoft.com" in result["channel_url"]
        mock_poster.post_message.assert_awaited_once_with(
            "https://teams.microsoft.com/l/channel/test",
            "Hello from test",
        )

    async def test_post_teams_message_auth_required(self):
        """Mock _get_poster so post_message returns an 'auth_required' result."""
        mock_poster = AsyncMock()
        mock_poster.post_message.return_value = {
            "status": "auth_required",
            "error": "Authentication timed out. Please re-run and complete login within the browser window.",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await post_teams_message(
                channel_url="https://teams.microsoft.com/l/channel/test",
                message="Hello",
            )

        result = json.loads(raw)
        assert result["status"] == "auth_required"
        assert "error" in result

    async def test_post_teams_message_error(self):
        """Mock _get_poster so post_message returns an error about compose box."""
        mock_poster = AsyncMock()
        mock_poster.post_message.return_value = {
            "status": "error",
            "error": "Could not find compose box. The Teams UI may have changed or the page did not load completely.",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await post_teams_message(
                channel_url="https://teams.microsoft.com/l/channel/test",
                message="Hello",
            )

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "compose" in result["error"].lower()

    async def test_post_teams_message_validates_url(self):
        """Non-Teams URL should be rejected without calling the poster."""
        raw = await post_teams_message(
            channel_url="https://example.com/not-teams",
            message="Hello",
        )

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "teams.microsoft.com" in result["error"]
