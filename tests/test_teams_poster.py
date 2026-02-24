# tests/test_teams_poster.py
"""Tests for browser.teams_poster -- PlaywrightTeamsPoster."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser.teams_poster import PlaywrightTeamsPoster


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------

@pytest.fixture
def poster():
    """Return a PlaywrightTeamsPoster with default manager/navigator."""
    return PlaywrightTeamsPoster()


# -------------------------------------------------------------------
# Helpers for mocking Playwright objects
# -------------------------------------------------------------------

def _make_mock_page():
    """Return a MagicMock page suitable for Teams interaction."""
    page = AsyncMock()
    page.url = "https://teams.cloud.microsoft/"
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.title = AsyncMock(return_value="General | Microsoft Teams")
    return page


def _make_compose_locator(count=1):
    """Return a mock locator that reports *count* matching elements."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    loc.click = AsyncMock()
    loc.fill = AsyncMock()
    return loc


# -------------------------------------------------------------------
# prepare_message tests
# -------------------------------------------------------------------

@pytest.mark.asyncio
class TestPrepareMessage:
    async def test_prepare_connects_and_navigates(self, poster):
        """prepare_message connects via manager, navigates via navigator."""
        mock_page = _make_mock_page()
        compose_loc = _make_compose_locator()

        mock_browser = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        mock_browser.contexts = [mock_ctx]
        mock_pw = AsyncMock()

        mock_mgr = MagicMock()
        mock_mgr.is_alive.return_value = True
        mock_mgr.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        mock_nav = AsyncMock()
        mock_nav.search_and_navigate = AsyncMock(return_value={
            "status": "navigated",
            "detected_channel": "Engineering",
        })

        poster._manager = mock_mgr
        poster._navigator = mock_nav

        from browser.constants import COMPOSE_SELECTORS
        empty_loc = _make_compose_locator(count=0)

        def locator_side_effect(sel):
            if sel in COMPOSE_SELECTORS:
                return compose_loc
            return empty_loc

        mock_page.locator = MagicMock(side_effect=locator_side_effect)

        result = await poster.prepare_message("Engineering", "Hello team")

        assert result["status"] == "confirm_required"
        assert result["detected_channel"] == "Engineering"
        assert result["message"] == "Hello team"
        assert result["target"] == "Engineering"
        mock_mgr.connect.assert_awaited_once()
        mock_nav.search_and_navigate.assert_awaited_once_with(mock_page, "Engineering")

    async def test_prepare_browser_not_running(self, poster):
        """Returns error when browser is not running."""
        mock_mgr = MagicMock()
        mock_mgr.is_alive.return_value = False
        poster._manager = mock_mgr

        result = await poster.prepare_message("Engineering", "Hello")

        assert result["status"] == "error"
        assert "not running" in result["error"].lower()

    async def test_prepare_navigation_fails(self, poster):
        """Returns error when navigator can't find target."""
        mock_page = _make_mock_page()
        mock_browser = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        mock_browser.contexts = [mock_ctx]
        mock_pw = AsyncMock()

        mock_mgr = MagicMock()
        mock_mgr.is_alive.return_value = True
        mock_mgr.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        mock_nav = AsyncMock()
        mock_nav.search_and_navigate = AsyncMock(return_value={
            "status": "error",
            "error": "No search results found for 'NonExistent'.",
        })

        poster._manager = mock_mgr
        poster._navigator = mock_nav

        result = await poster.prepare_message("NonExistent", "Hello")

        assert result["status"] == "error"
        assert "NonExistent" in result["error"]

    async def test_prepare_no_compose_box(self, poster):
        """Returns error when compose box not found after navigation."""
        mock_page = _make_mock_page()
        mock_browser = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        mock_browser.contexts = [mock_ctx]
        mock_pw = AsyncMock()

        mock_mgr = MagicMock()
        mock_mgr.is_alive.return_value = True
        mock_mgr.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        mock_nav = AsyncMock()
        mock_nav.search_and_navigate = AsyncMock(return_value={
            "status": "navigated",
            "detected_channel": "Engineering",
        })

        poster._manager = mock_mgr
        poster._navigator = mock_nav

        # All locators return 0 matches
        empty_loc = _make_compose_locator(count=0)
        mock_page.locator = MagicMock(return_value=empty_loc)

        with patch("browser.teams_poster.asyncio.sleep", new_callable=AsyncMock):
            result = await poster.prepare_message("Engineering", "Hello")

        assert result["status"] == "error"
        assert "compose box" in result["error"].lower()
        assert not poster.has_pending_message

    async def test_prepare_cleans_up_previous(self, poster):
        """Calling prepare again disconnects previous connection."""
        mock_page = _make_mock_page()
        compose_loc = _make_compose_locator()

        mock_browser = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        mock_browser.contexts = [mock_ctx]
        mock_pw = AsyncMock()

        mock_mgr = MagicMock()
        mock_mgr.is_alive.return_value = True
        mock_mgr.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        mock_nav = AsyncMock()
        mock_nav.search_and_navigate = AsyncMock(return_value={
            "status": "navigated",
            "detected_channel": "Engineering",
        })

        poster._manager = mock_mgr
        poster._navigator = mock_nav

        from browser.constants import COMPOSE_SELECTORS
        empty_loc = _make_compose_locator(count=0)

        def locator_side_effect(sel):
            if sel in COMPOSE_SELECTORS:
                return compose_loc
            return empty_loc

        mock_page.locator = MagicMock(side_effect=locator_side_effect)

        # First prepare
        await poster.prepare_message("Engineering", "first")
        # Second prepare -- should disconnect first
        await poster.prepare_message("Engineering", "second")
        # pw.stop should have been called for the first connection
        mock_pw.stop.assert_awaited()

    async def test_prepare_creates_new_page_if_none(self, poster):
        """Creates a new page when the browser context has no pages."""
        mock_page = _make_mock_page()
        compose_loc = _make_compose_locator()

        mock_ctx = MagicMock()
        mock_ctx.pages = []  # No existing pages
        mock_ctx.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.contexts = [mock_ctx]
        mock_pw = AsyncMock()

        mock_mgr = MagicMock()
        mock_mgr.is_alive.return_value = True
        mock_mgr.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        mock_nav = AsyncMock()
        mock_nav.search_and_navigate = AsyncMock(return_value={
            "status": "navigated",
            "detected_channel": "General",
        })

        poster._manager = mock_mgr
        poster._navigator = mock_nav

        from browser.constants import COMPOSE_SELECTORS
        empty_loc = _make_compose_locator(count=0)

        def locator_side_effect(sel):
            if sel in COMPOSE_SELECTORS:
                return compose_loc
            return empty_loc

        mock_page.locator = MagicMock(side_effect=locator_side_effect)

        result = await poster.prepare_message("General", "test")

        assert result["status"] == "confirm_required"
        mock_ctx.new_page.assert_awaited_once()


# -------------------------------------------------------------------
# send_prepared_message tests
# -------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendPreparedMessage:
    async def test_send_types_and_submits(self, poster):
        """send_prepared_message types into compose box and presses Enter."""
        page = _make_mock_page()
        compose = _make_compose_locator()

        poster._pw = AsyncMock()
        poster._page = page
        poster._compose = compose
        poster._pending_message = "Hello team"

        from browser.constants import CHANNEL_NAME_SELECTORS
        channel_loc = AsyncMock()
        channel_loc.count = AsyncMock(return_value=1)
        first = AsyncMock()
        first.inner_text = AsyncMock(return_value="Engineering")
        channel_loc.first = first
        empty_loc = _make_compose_locator(count=0)

        def locator_side_effect(sel):
            if sel in CHANNEL_NAME_SELECTORS:
                return channel_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_side_effect)

        result = await poster.send_prepared_message()

        assert result["status"] == "sent"
        assert result["detected_channel"] == "Engineering"
        assert result["message"] == "Hello team"
        compose.click.assert_awaited_once()
        compose.fill.assert_awaited_once_with("Hello team")
        page.keyboard.press.assert_awaited_once_with("Enter")
        # Should disconnect after sending
        assert not poster.has_pending_message

    async def test_send_without_prepare(self, poster):
        """Calling send without prepare returns an error."""
        result = await poster.send_prepared_message()
        assert result["status"] == "error"
        assert "No pending message" in result["error"]

    async def test_send_disconnects_on_error(self, poster):
        """Disconnects even when sending fails."""
        page = _make_mock_page()
        compose = _make_compose_locator()
        compose.click = AsyncMock(side_effect=RuntimeError("click failed"))

        poster._pw = AsyncMock()
        poster._page = page
        poster._compose = compose
        poster._pending_message = "Hello"

        # Need locator for _detect_channel_name
        empty_loc = _make_compose_locator(count=0)
        page.locator = MagicMock(return_value=empty_loc)
        page.title = AsyncMock(return_value="Engineering | Microsoft Teams")

        result = await poster.send_prepared_message()

        assert result["status"] == "error"
        assert not poster.has_pending_message
        poster._pw is None  # Should be cleared


# -------------------------------------------------------------------
# cancel_prepared_message tests
# -------------------------------------------------------------------

@pytest.mark.asyncio
class TestCancelPreparedMessage:
    async def test_cancel_after_prepare(self, poster):
        """Cancel after prepare disconnects and returns 'cancelled'."""
        poster._pw = AsyncMock()
        poster._page = AsyncMock()
        poster._compose = AsyncMock()
        poster._pending_message = "test"

        result = await poster.cancel_prepared_message()
        assert result["status"] == "cancelled"
        assert not poster.has_pending_message

    async def test_cancel_without_prepare(self, poster):
        """Cancelling with nothing pending returns an error."""
        result = await poster.cancel_prepared_message()
        assert result["status"] == "error"
        assert "No pending message" in result["error"]


# -------------------------------------------------------------------
# has_pending_message tests
# -------------------------------------------------------------------

class TestHasPendingMessage:
    def test_no_pending_initially(self, poster):
        """No pending message after construction."""
        assert not poster.has_pending_message

    def test_pending_requires_both(self, poster):
        """Need both _pending_message and _page to be set."""
        poster._pending_message = "test"
        poster._page = None
        assert not poster.has_pending_message

        poster._pending_message = None
        poster._page = AsyncMock()
        assert not poster.has_pending_message

    def test_pending_when_both_set(self, poster):
        """Returns True when both _pending_message and _page are set."""
        poster._pending_message = "test"
        poster._page = AsyncMock()
        assert poster.has_pending_message
