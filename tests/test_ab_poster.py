"""Tests for ABTeamsPoster — agent-browser-based Teams poster."""

import pytest
from unittest.mock import AsyncMock

from browser.ab_poster import ABTeamsPoster


@pytest.fixture
def ab():
    mock = AsyncMock()
    mock.open = AsyncMock(return_value={"ok": True})
    mock.snapshot = AsyncMock(return_value={"ok": True, "text": ""})
    mock.find = AsyncMock(return_value={"ok": True, "text": "@e1"})
    mock.click = AsyncMock(return_value={"ok": True})
    mock.fill = AsyncMock(return_value={"ok": True})
    mock.press = AsyncMock(return_value={"ok": True})
    mock.close = AsyncMock(return_value={"ok": True})
    return mock


class TestPrepareMessage:
    @pytest.mark.asyncio
    async def test_prepare_with_string_target(self, ab):
        poster = ABTeamsPoster(ab=ab)
        nav = AsyncMock()
        nav.search_and_navigate = AsyncMock(return_value={
            "status": "navigated", "detected_channel": "Jonas",
        })
        nav.find_compose_box = AsyncMock(return_value="@e10")
        poster._navigator = nav

        result = await poster.prepare_message("Jonas De Oliveira", "Hello!")

        assert result["status"] == "confirm_required"
        assert result["message"] == "Hello!"
        assert result["detected_channel"] == "Jonas"
        nav.search_and_navigate.assert_called_once_with("Jonas De Oliveira")

    @pytest.mark.asyncio
    async def test_prepare_with_list_target_creates_group(self, ab):
        poster = ABTeamsPoster(ab=ab)
        nav = AsyncMock()
        nav.create_group_chat = AsyncMock(return_value={
            "status": "navigated", "detected_channel": "Michael, Heather",
        })
        nav.find_compose_box = AsyncMock(return_value="@e10")
        poster._navigator = nav

        result = await poster.prepare_message(
            ["Michael Larsen", "Heather Allen"], "Hello!"
        )

        assert result["status"] == "confirm_required"
        assert result["detected_channel"] == "Michael, Heather"
        nav.create_group_chat.assert_called_once_with(
            ["Michael Larsen", "Heather Allen"]
        )

    @pytest.mark.asyncio
    async def test_prepare_returns_nav_error(self, ab):
        """Should pass through navigator errors."""
        poster = ABTeamsPoster(ab=ab)
        nav = AsyncMock()
        nav.search_and_navigate = AsyncMock(return_value={
            "status": "error", "error": "No results",
        })
        poster._navigator = nav

        result = await poster.prepare_message("Nobody", "Hello!")

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_prepare_error_when_no_compose_box(self, ab):
        """Should error if compose box not found after navigation."""
        poster = ABTeamsPoster(ab=ab)
        nav = AsyncMock()
        nav.search_and_navigate = AsyncMock(return_value={
            "status": "navigated", "detected_channel": "Jonas",
        })
        nav.find_compose_box = AsyncMock(return_value=None)
        poster._navigator = nav

        result = await poster.prepare_message("Jonas", "Hello!")

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_prepare_clears_previous_pending(self, ab):
        """Should clear any existing pending message before preparing new one."""
        poster = ABTeamsPoster(ab=ab)
        poster._compose_ref = "@e99"
        poster._pending_message = "old"

        nav = AsyncMock()
        nav.search_and_navigate = AsyncMock(return_value={
            "status": "navigated", "detected_channel": "Jonas",
        })
        nav.find_compose_box = AsyncMock(return_value="@e10")
        poster._navigator = nav

        result = await poster.prepare_message("Jonas", "new message")

        assert result["status"] == "confirm_required"
        assert result["message"] == "new message"


class TestSendPreparedMessage:
    @pytest.mark.asyncio
    async def test_send_types_and_submits(self, ab):
        poster = ABTeamsPoster(ab=ab)
        poster._compose_ref = "@e10"
        poster._pending_message = "Hello team"

        nav = AsyncMock()
        nav.detect_channel_name = AsyncMock(return_value="Engineering")
        poster._navigator = nav

        result = await poster.send_prepared_message()

        assert result["status"] == "sent"
        assert result["message"] == "Hello team"
        assert result["detected_channel"] == "Engineering"
        ab.fill.assert_called_once_with("@e10", "Hello team")

    @pytest.mark.asyncio
    async def test_send_without_prepare_returns_error(self, ab):
        poster = ABTeamsPoster(ab=ab)
        result = await poster.send_prepared_message()
        assert result["status"] == "error"
        assert "No pending message" in result["error"]

    @pytest.mark.asyncio
    async def test_send_clears_pending_on_success(self, ab):
        poster = ABTeamsPoster(ab=ab)
        poster._compose_ref = "@e10"
        poster._pending_message = "Hello"

        nav = AsyncMock()
        nav.detect_channel_name = AsyncMock(return_value="Chat")
        poster._navigator = nav

        await poster.send_prepared_message()

        assert not poster.has_pending_message


class TestCancelPreparedMessage:
    @pytest.mark.asyncio
    async def test_cancel_after_prepare(self, ab):
        poster = ABTeamsPoster(ab=ab)
        poster._compose_ref = "@e10"
        poster._pending_message = "test"

        result = await poster.cancel_prepared_message()
        assert result["status"] == "cancelled"
        assert not poster.has_pending_message

    @pytest.mark.asyncio
    async def test_cancel_without_pending_returns_error(self, ab):
        poster = ABTeamsPoster(ab=ab)
        result = await poster.cancel_prepared_message()
        assert result["status"] == "error"


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_one_shot_send(self, ab):
        """send_message should prepare + send in one call."""
        poster = ABTeamsPoster(ab=ab)
        nav = AsyncMock()
        nav.search_and_navigate = AsyncMock(return_value={
            "status": "navigated", "detected_channel": "Jonas",
        })
        nav.find_compose_box = AsyncMock(return_value="@e10")
        nav.detect_channel_name = AsyncMock(return_value="Jonas")
        poster._navigator = nav

        result = await poster.send_message("Jonas", "Quick message")

        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_one_shot_returns_nav_error(self, ab):
        """send_message should return error if navigation fails."""
        poster = ABTeamsPoster(ab=ab)
        nav = AsyncMock()
        nav.search_and_navigate = AsyncMock(return_value={
            "status": "error", "error": "Not found",
        })
        poster._navigator = nav

        result = await poster.send_message("Nobody", "Hello!")

        assert result["status"] == "error"


class TestHasPendingMessage:
    def test_false_when_empty(self, ab):
        poster = ABTeamsPoster(ab=ab)
        assert not poster.has_pending_message

    def test_true_when_both_set(self, ab):
        poster = ABTeamsPoster(ab=ab)
        poster._compose_ref = "@e10"
        poster._pending_message = "hello"
        assert poster.has_pending_message

    def test_false_when_only_ref(self, ab):
        poster = ABTeamsPoster(ab=ab)
        poster._compose_ref = "@e10"
        assert not poster.has_pending_message

    def test_false_when_only_message(self, ab):
        poster = ABTeamsPoster(ab=ab)
        poster._pending_message = "hello"
        assert not poster.has_pending_message
