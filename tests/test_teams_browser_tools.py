"""Tests for the Teams browser automation MCP tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mcp_server  # noqa: F401 — triggers tool registrations
from mcp_tools import teams_browser_tools

teams_browser_tools.register(mcp_server.mcp, mcp_server._state)
from mcp_tools.teams_browser_tools import (
    cancel_teams_post,
    close_teams_browser,
    confirm_teams_post,
    open_teams_browser,
    post_teams_message,
)


@pytest.mark.asyncio
class TestOpenTeamsBrowser:
    async def test_open_launches_browser(self):
        mock_mgr = MagicMock()
        mock_mgr.launch.return_value = {"status": "launched", "pid": 123, "cdp_port": 9222}

        with patch.object(teams_browser_tools, "_get_manager", return_value=mock_mgr):
            with patch.object(teams_browser_tools, "_wait_for_teams", new_callable=AsyncMock, return_value=True):
                raw = await open_teams_browser()

        result = json.loads(raw)
        assert result["status"] == "running"
        mock_mgr.launch.assert_called_once()

    async def test_open_already_running(self):
        mock_mgr = MagicMock()
        mock_mgr.launch.return_value = {"status": "already_running", "pid": 123}

        with patch.object(teams_browser_tools, "_get_manager", return_value=mock_mgr):
            with patch.object(teams_browser_tools, "_wait_for_teams", new_callable=AsyncMock, return_value=True):
                raw = await open_teams_browser()

        result = json.loads(raw)
        assert result["status"] == "running"

    async def test_open_launch_error(self):
        mock_mgr = MagicMock()
        mock_mgr.launch.return_value = {"status": "error", "error": "Chromium not found"}

        with patch.object(teams_browser_tools, "_get_manager", return_value=mock_mgr):
            raw = await open_teams_browser()

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "Chromium" in result["error"]


@pytest.mark.asyncio
class TestCloseTeamsBrowser:
    async def test_close_stops_browser(self):
        mock_mgr = MagicMock()
        mock_mgr.close.return_value = {"status": "closed"}

        with patch.object(teams_browser_tools, "_get_manager", return_value=mock_mgr):
            raw = await close_teams_browser()

        result = json.loads(raw)
        assert result["status"] == "closed"
        mock_mgr.close.assert_called_once()


@pytest.mark.asyncio
class TestPostTeamsMessage:
    async def test_post_returns_confirm(self):
        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "confirm_required",
            "detected_channel": "Engineering",
            "message": "Hello",
            "target": "Engineering",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await post_teams_message(target="Engineering", message="Hello")

        result = json.loads(raw)
        assert result["status"] == "confirm_required"
        assert result["detected_channel"] == "Engineering"
        mock_poster.prepare_message.assert_awaited_once_with("Engineering", "Hello")

    async def test_post_auto_send(self):
        """auto_send=True sends immediately without confirmation."""
        mock_poster = AsyncMock()
        mock_poster.send_message = AsyncMock(return_value={
            "status": "sent",
            "detected_channel": "Jonas",
            "message": "Hello!",
        })

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await post_teams_message(
                target="Jonas", message="Hello!", auto_send=True
            )

        result = json.loads(raw)
        assert result["status"] == "sent"
        mock_poster.send_message.assert_awaited_once_with("Jonas", "Hello!")

    async def test_post_browser_not_running(self):
        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "error",
            "error": "Browser is not running. Call open_teams_browser first.",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await post_teams_message(target="Engineering", message="Hello")

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "not running" in result["error"].lower()


@pytest.mark.asyncio
class TestConfirmTeamsPost:
    async def test_confirm_sends(self):
        mock_poster = AsyncMock()
        mock_poster.send_prepared_message.return_value = {
            "status": "sent",
            "detected_channel": "Engineering",
            "message": "Hello",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await confirm_teams_post()

        result = json.loads(raw)
        assert result["status"] == "sent"
        mock_poster.send_prepared_message.assert_awaited_once()

    async def test_confirm_without_prepare(self):
        mock_poster = AsyncMock()
        mock_poster.send_prepared_message.return_value = {
            "status": "error",
            "error": "No pending message. Call prepare_message first.",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await confirm_teams_post()

        result = json.loads(raw)
        assert result["status"] == "error"


@pytest.mark.asyncio
class TestCancelTeamsPost:
    async def test_cancel_works(self):
        mock_poster = AsyncMock()
        mock_poster.cancel_prepared_message.return_value = {"status": "cancelled"}

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await cancel_teams_post()

        result = json.loads(raw)
        assert result["status"] == "cancelled"
        mock_poster.cancel_prepared_message.assert_awaited_once()

    async def test_cancel_without_prepare(self):
        mock_poster = AsyncMock()
        mock_poster.cancel_prepared_message.return_value = {
            "status": "error",
            "error": "No pending message to cancel.",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await cancel_teams_post()

        result = json.loads(raw)
        assert result["status"] == "error"
