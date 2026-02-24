# tests/test_teams_browser_tools.py
"""Tests for the Teams browser automation MCP tools."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import mcp_server  # noqa: F401 — triggers tool registrations

# The module must be registered before importing the tool function.
from mcp_tools import teams_browser_tools
from mcp_tools.state import ServerState

# Manually register to expose tool functions at module level.
teams_browser_tools.register(mcp_server.mcp, mcp_server._state)
from mcp_tools.teams_browser_tools import (
    cancel_teams_post,
    confirm_teams_post,
    post_teams_message,
)


@pytest.mark.asyncio
class TestPostTeamsMessage:
    async def test_post_teams_message_returns_confirm(self):
        """post_teams_message calls prepare_message and returns confirm_required."""
        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "confirm_required",
            "detected_channel": "General",
            "message": "Hello from test",
            "channel_url": "https://teams.microsoft.com/l/channel/test",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await post_teams_message(
                channel_url="https://teams.microsoft.com/l/channel/test",
                message="Hello from test",
            )

        result = json.loads(raw)
        assert result["status"] == "confirm_required"
        assert result["detected_channel"] == "General"
        assert result["message"] == "Hello from test"
        mock_poster.prepare_message.assert_awaited_once_with(
            "https://teams.microsoft.com/l/channel/test",
            "Hello from test",
        )

    async def test_post_teams_message_auth_required(self):
        """Mock prepare_message returning 'auth_required'."""
        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "auth_required",
            "error": "Authentication timed out.",
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
        """Mock prepare_message returning an error about compose box."""
        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "error",
            "error": "Could not find compose box.",
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


@pytest.mark.asyncio
class TestConfirmTeamsPost:
    async def test_confirm_sends_message(self):
        """confirm_teams_post calls send_prepared_message."""
        mock_poster = AsyncMock()
        mock_poster.send_prepared_message.return_value = {
            "status": "sent",
            "detected_channel": "General",
            "message": "Hello",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await confirm_teams_post()

        result = json.loads(raw)
        assert result["status"] == "sent"
        mock_poster.send_prepared_message.assert_awaited_once()

    async def test_confirm_without_prepare(self):
        """confirm_teams_post without prepare returns error."""
        mock_poster = AsyncMock()
        mock_poster.send_prepared_message.return_value = {
            "status": "error",
            "error": "No pending message. Call prepare_message first.",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await confirm_teams_post()

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "No pending message" in result["error"]


@pytest.mark.asyncio
class TestCancelTeamsPost:
    async def test_cancel_returns_cancelled(self):
        """cancel_teams_post calls cancel_prepared_message."""
        mock_poster = AsyncMock()
        mock_poster.cancel_prepared_message.return_value = {"status": "cancelled"}

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await cancel_teams_post()

        result = json.loads(raw)
        assert result["status"] == "cancelled"
        mock_poster.cancel_prepared_message.assert_awaited_once()

    async def test_cancel_without_prepare(self):
        """cancel_teams_post without prepare returns error."""
        mock_poster = AsyncMock()
        mock_poster.cancel_prepared_message.return_value = {
            "status": "error",
            "error": "No pending message to cancel.",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await cancel_teams_post()

        result = json.loads(raw)
        assert result["status"] == "error"
