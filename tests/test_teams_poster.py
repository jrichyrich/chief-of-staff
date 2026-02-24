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
    pw = MagicMock()
    pw.chromium = AsyncMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    return pw


def _make_compose_locator(count=1):
    """Return a mock locator that reports *count* matching elements."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    loc.click = AsyncMock()
    loc.fill = AsyncMock()
    return loc


# -------------------------------------------------------------------
# post_message tests
# -------------------------------------------------------------------

@pytest.mark.asyncio
class TestPostMessage:
    async def test_post_message_returns_result(self, poster):
        """Happy path: compose box found, message sent, status='sent'."""
        channel = "https://teams.microsoft.com/l/channel/123"
        compose_loc = _make_compose_locator(count=1)

        page = _make_mock_page(url=channel)
        # After goto the page URL is the channel (not a login page).
        page.locator = MagicMock(return_value=compose_loc)

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with patch("browser.teams_poster.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)

            result = await poster.post_message(channel, "hello team")

        assert result["status"] == "sent"
        assert result["channel_url"] == channel
        compose_loc.click.assert_awaited_once()
        compose_loc.fill.assert_awaited_once_with("hello team")
        page.keyboard.press.assert_awaited_once_with("Enter")
        br.close.assert_awaited_once()

    async def test_post_message_auth_timeout(self, poster):
        """Login page that never resolves gives 'auth_required'."""
        login_url = "https://login.microsoftonline.com/common/oauth2"
        page = _make_mock_page(url=login_url)

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        # Override AUTH_TIMEOUT_MS so the test doesn't actually wait 2 min.
        poster_fast = PlaywrightTeamsPoster(session_path=poster.session_path)

        with (
            patch("browser.teams_poster.async_playwright") as mock_apw,
            patch("browser.teams_poster.AUTH_TIMEOUT_MS", 0),
        ):
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            result = await poster_fast.post_message(
                "https://teams.microsoft.com/l/channel/xyz", "hi"
            )

        assert result["status"] == "auth_required"
        assert "timed out" in result["error"].lower() or "timeout" in result["error"].lower()
        br.close.assert_awaited_once()

    async def test_post_message_no_compose_box(self, poster):
        """All selectors return 0 matches -> error with 'compose' in msg."""
        channel = "https://teams.microsoft.com/l/channel/456"
        empty_loc = _make_compose_locator(count=0)

        page = _make_mock_page(url=channel)
        page.locator = MagicMock(return_value=empty_loc)

        ctx = _make_mock_context(page)
        br = _make_mock_browser(ctx)
        mock_pw = _make_mock_playwright(br)

        with patch("browser.teams_poster.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            result = await poster.post_message(channel, "test msg")

        assert result["status"] == "error"
        assert "compose" in result["error"].lower()
        br.close.assert_awaited_once()
