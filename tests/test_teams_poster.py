# tests/test_teams_poster.py
"""Tests for browser.teams_poster — PlaywrightTeamsPoster."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser.teams_poster import PlaywrightTeamsPoster


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------

@pytest.fixture
def poster(tmp_path):
    """Return a PlaywrightTeamsPoster with an isolated session path."""
    return PlaywrightTeamsPoster(session_path=tmp_path / "session.json")


# -------------------------------------------------------------------
# Session persistence
# -------------------------------------------------------------------

class TestSessionPersistence:
    def test_load_session_no_file(self, poster):
        """_load_session returns None when the file does not exist."""
        assert poster._load_session() is None

    def test_save_and_load_session(self, poster):
        """Round-trip: _save_session_sync then _load_session."""
        state = {"cookies": [{"name": "auth", "value": "tok"}]}
        poster._save_session_sync(state)
        loaded = poster._load_session()
        assert loaded == state

    def test_session_path_creates_parent_dir(self, tmp_path):
        """_save_session_sync creates intermediate directories."""
        deep = tmp_path / "a" / "b" / "c" / "session.json"
        poster = PlaywrightTeamsPoster(session_path=deep)
        poster._save_session_sync({"ok": True})
        assert deep.exists()
        assert json.loads(deep.read_text()) == {"ok": True}

    def test_load_session_corrupt_json(self, poster):
        """_load_session returns None on invalid JSON."""
        poster.session_path.parent.mkdir(parents=True, exist_ok=True)
        poster.session_path.write_text("not valid json{{{")
        assert poster._load_session() is None


# -------------------------------------------------------------------
# Login-page detection
# -------------------------------------------------------------------

class TestIsLoginPage:
    def test_is_login_page_okta(self, poster):
        assert poster._is_login_page("https://acme.okta.com/sso/login") is True

    def test_is_login_page_microsoft(self, poster):
        assert poster._is_login_page(
            "https://login.microsoftonline.com/common/oauth2"
        ) is True

    def test_is_login_page_microsoft_alt(self, poster):
        assert poster._is_login_page(
            "https://login.microsoft.com/common/oauth2"
        ) is True

    def test_is_login_page_teams(self, poster):
        """A Teams channel URL should NOT be detected as a login page."""
        assert poster._is_login_page(
            "https://teams.microsoft.com/l/channel/abc"
        ) is False

    def test_is_login_page_empty(self, poster):
        """about:blank should NOT be detected as a login page."""
        assert poster._is_login_page("about:blank") is False


# -------------------------------------------------------------------
# Helpers for mocking Playwright objects
# -------------------------------------------------------------------

def _make_mock_page(url="https://teams.microsoft.com/l/channel/123"):
    """Return a MagicMock page whose .url returns *url*."""
    page = AsyncMock()
    page.url = url
    page.goto = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.title = AsyncMock(return_value="General | Microsoft Teams")
    return page


def _make_mock_context(page, storage_state=None):
    """Return a MagicMock browser context that yields *page*."""
    ctx = AsyncMock()
    ctx.new_page = AsyncMock(return_value=page)
    ctx.storage_state = AsyncMock(return_value=storage_state or {})
    return ctx


def _make_mock_browser(context):
    """Return a MagicMock browser that yields *context*."""
    br = AsyncMock()
    br.new_context = AsyncMock(return_value=context)
    br.close = AsyncMock()
    return br


def _make_mock_playwright(browser):
    """Return a MagicMock Playwright instance."""
    pw = AsyncMock()
    pw.chromium = AsyncMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    pw.stop = AsyncMock()
    return pw


def _make_compose_locator(count=1):
    """Return a mock locator that reports *count* matching elements."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    loc.click = AsyncMock()
    loc.fill = AsyncMock()
    return loc


def _make_channel_locator(text="General", count=1):
    """Return a mock locator that reports a channel header element."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    first = AsyncMock()
    first.inner_text = AsyncMock(return_value=text)
    loc.first = first
    return loc


def _setup_page_locators(page, compose_count=1, channel_text="General"):
    """Wire up page.locator to return appropriate mocks for compose and channel selectors."""
    compose_loc = _make_compose_locator(count=compose_count)
    channel_loc = _make_channel_locator(text=channel_text, count=1 if channel_text else 0)
    empty_loc = _make_compose_locator(count=0)

    from browser.teams_poster import COMPOSE_SELECTORS, CHANNEL_NAME_SELECTORS

    def locator_side_effect(selector):
        if selector in COMPOSE_SELECTORS:
            return compose_loc
        if selector in CHANNEL_NAME_SELECTORS:
            return channel_loc
        return empty_loc

    page.locator = MagicMock(side_effect=locator_side_effect)
    return compose_loc, channel_loc


# -------------------------------------------------------------------
# prepare_message tests
# -------------------------------------------------------------------

@pytest.mark.asyncio
class TestPrepareMessage:
    async def test_prepare_returns_confirm_required(self, poster):
        """Happy path: compose box found, returns confirm_required with channel name."""
        channel = "https://teams.microsoft.com/l/channel/123"
        page = _make_mock_page(url=channel)
        compose_loc, _ = _setup_page_locators(page, channel_text="General")

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with patch("browser.teams_poster.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            result = await poster.prepare_message(channel, "hello team")

        assert result["status"] == "confirm_required"
        assert result["detected_channel"] == "General"
        assert result["message"] == "hello team"
        assert result["channel_url"] == channel
        # Browser should still be open
        assert poster.has_pending_message
        br.close.assert_not_awaited()

        # Clean up
        await poster._cleanup()

    async def test_prepare_auth_timeout(self, poster):
        """Login page that never resolves gives 'auth_required'."""
        login_url = "https://login.microsoftonline.com/common/oauth2"
        page = _make_mock_page(url=login_url)

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with (
            patch("browser.teams_poster.async_playwright") as mock_apw,
            patch("browser.teams_poster.AUTH_TIMEOUT_MS", 0),
        ):
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            result = await poster.prepare_message(
                "https://teams.microsoft.com/l/channel/xyz", "hi"
            )

        assert result["status"] == "auth_required"
        assert "timed out" in result["error"].lower() or "timeout" in result["error"].lower()
        assert not poster.has_pending_message
        br.close.assert_awaited_once()

    async def test_prepare_no_compose_box(self, poster):
        """All selectors return 0 matches -> error with 'compose' in msg."""
        channel = "https://teams.microsoft.com/l/channel/456"
        page = _make_mock_page(url=channel)
        _setup_page_locators(page, compose_count=0)

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with patch("browser.teams_poster.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            result = await poster.prepare_message(channel, "test msg")

        assert result["status"] == "error"
        assert "compose" in result["error"].lower()
        assert not poster.has_pending_message
        br.close.assert_awaited_once()

    async def test_prepare_cleans_up_previous(self, poster):
        """Calling prepare_message again cleans up the previous browser."""
        channel = "https://teams.microsoft.com/l/channel/123"
        page = _make_mock_page(url=channel)
        _setup_page_locators(page, channel_text="General")

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with patch("browser.teams_poster.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)

            # First prepare
            result1 = await poster.prepare_message(channel, "first")
            assert result1["status"] == "confirm_required"

            # Second prepare (should clean up first)
            page2 = _make_mock_page(url=channel)
            _setup_page_locators(page2, channel_text="Random")
            ctx2 = _make_mock_context(page2)
            br2 = _make_mock_browser(ctx2)
            mock_pw2 = _make_mock_playwright(br2)
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw2)

            result2 = await poster.prepare_message(channel, "second")
            assert result2["status"] == "confirm_required"
            assert result2["message"] == "second"

            # First browser should have been closed
            br.close.assert_awaited_once()

        await poster._cleanup()

    async def test_prepare_detects_channel_from_title(self, poster):
        """When no header selector matches, falls back to page title."""
        channel = "https://teams.cloud.microsoft/"
        page = _make_mock_page(url=channel)
        page.title = AsyncMock(return_value="Engineering | Microsoft Teams")

        compose_loc = _make_compose_locator(count=1)
        empty_loc = _make_compose_locator(count=0)

        # All channel selectors fail, compose succeeds
        from browser.teams_poster import COMPOSE_SELECTORS

        def locator_side_effect(selector):
            if selector in COMPOSE_SELECTORS:
                return compose_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_side_effect)

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with patch("browser.teams_poster.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            result = await poster.prepare_message(channel, "test")

        assert result["status"] == "confirm_required"
        assert result["detected_channel"] == "Engineering"

        await poster._cleanup()


# -------------------------------------------------------------------
# send_prepared_message tests
# -------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendPreparedMessage:
    async def test_send_without_prepare_fails(self, poster):
        """Calling send_prepared_message without prepare returns an error."""
        result = await poster.send_prepared_message()
        assert result["status"] == "error"
        assert "No pending message" in result["error"]

    async def test_send_after_prepare(self, poster):
        """Happy path: prepare then send types and submits."""
        channel = "https://teams.microsoft.com/l/channel/123"
        page = _make_mock_page(url=channel)
        compose_loc, _ = _setup_page_locators(page, channel_text="General")

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with patch("browser.teams_poster.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            await poster.prepare_message(channel, "hello team")

        result = await poster.send_prepared_message()

        assert result["status"] == "sent"
        assert result["detected_channel"] == "General"
        assert result["message"] == "hello team"
        compose_loc.click.assert_awaited_once()
        compose_loc.fill.assert_awaited_once_with("hello team")
        page.keyboard.press.assert_awaited_once_with("Enter")
        br.close.assert_awaited_once()
        mock_pw.stop.assert_awaited_once()
        assert not poster.has_pending_message


# -------------------------------------------------------------------
# cancel_prepared_message tests
# -------------------------------------------------------------------

@pytest.mark.asyncio
class TestCancelPreparedMessage:
    async def test_cancel_without_prepare(self, poster):
        """Cancelling with nothing pending returns an error."""
        result = await poster.cancel_prepared_message()
        assert result["status"] == "error"
        assert "No pending message" in result["error"]

    async def test_cancel_after_prepare(self, poster):
        """Cancel after prepare closes browser and returns 'cancelled'."""
        channel = "https://teams.microsoft.com/l/channel/123"
        page = _make_mock_page(url=channel)
        _setup_page_locators(page, channel_text="General")

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with patch("browser.teams_poster.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            await poster.prepare_message(channel, "message to cancel")

        result = await poster.cancel_prepared_message()
        assert result["status"] == "cancelled"
        assert not poster.has_pending_message
        br.close.assert_awaited_once()


# -------------------------------------------------------------------
# Legacy post_message tests
# -------------------------------------------------------------------

@pytest.mark.asyncio
class TestPostMessage:
    async def test_post_message_returns_sent(self, poster):
        """Legacy one-shot: compose box found, message sent, status='sent'."""
        channel = "https://teams.microsoft.com/l/channel/123"
        page = _make_mock_page(url=channel)
        compose_loc, _ = _setup_page_locators(page, channel_text="General")

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with patch("browser.teams_poster.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            result = await poster.post_message(channel, "hello team")

        assert result["status"] == "sent"
        compose_loc.click.assert_awaited_once()
        compose_loc.fill.assert_awaited_once_with("hello team")
        page.keyboard.press.assert_awaited_once_with("Enter")
        br.close.assert_awaited_once()
        mock_pw.stop.assert_awaited_once()

    async def test_post_message_auth_timeout(self, poster):
        """Login page that never resolves gives 'auth_required'."""
        login_url = "https://login.microsoftonline.com/common/oauth2"
        page = _make_mock_page(url=login_url)

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with (
            patch("browser.teams_poster.async_playwright") as mock_apw,
            patch("browser.teams_poster.AUTH_TIMEOUT_MS", 0),
        ):
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            result = await poster.post_message(
                "https://teams.microsoft.com/l/channel/xyz", "hi"
            )

        assert result["status"] == "auth_required"
        br.close.assert_awaited_once()

    async def test_post_message_no_compose_box(self, poster):
        """All selectors return 0 matches -> error with 'compose' in msg."""
        channel = "https://teams.microsoft.com/l/channel/456"
        page = _make_mock_page(url=channel)
        _setup_page_locators(page, compose_count=0)

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with patch("browser.teams_poster.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            result = await poster.post_message(channel, "test msg")

        assert result["status"] == "error"
        assert "compose" in result["error"].lower()
        br.close.assert_awaited_once()
