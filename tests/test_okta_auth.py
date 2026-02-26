"""Tests for browser.okta_auth — Okta authentication flow for Teams."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser.constants import (
    AUTH_TIMEOUT_MS,
    OKTA_DASHBOARD_PATTERNS,
    OKTA_TEAMS_TILE_SELECTORS,
    OKTA_URL,
    TEAMS_PATTERNS,
)


def _make_locator(count=1, texts=None):
    """Mock locator with count and optional text content."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    loc.click = AsyncMock()
    if texts:
        items = []
        for t in texts:
            item = AsyncMock()
            item.inner_text = AsyncMock(return_value=t)
            item.click = AsyncMock()
            items.append(item)

        def nth_effect(i):
            return items[i] if i < len(items) else AsyncMock()

        loc.nth = MagicMock(side_effect=nth_effect)
        loc.first = items[0]
    else:
        first = AsyncMock()
        first.click = AsyncMock()
        loc.first = first
        loc.nth = MagicMock(return_value=first)
    return loc


@pytest.fixture(autouse=True)
def _fast_sleep():
    """Replace asyncio.sleep with instant coroutine."""
    async def _instant(_seconds):
        pass
    with patch("browser.okta_auth.asyncio.sleep", side_effect=_instant):
        yield


@pytest.mark.asyncio
class TestIsOktaDashboard:
    async def test_user_home_url(self):
        from browser.okta_auth import _is_okta_dashboard
        assert _is_okta_dashboard("https://mychg.okta.com/app/UserHome") is True

    async def test_enduser_catalog_url(self):
        from browser.okta_auth import _is_okta_dashboard
        assert _is_okta_dashboard("https://mychg.okta.com/enduser/catalog") is True

    async def test_login_url_is_not_dashboard(self):
        from browser.okta_auth import _is_okta_dashboard
        assert _is_okta_dashboard("https://mychg.okta.com/login/login.htm") is False

    async def test_teams_url_is_not_dashboard(self):
        from browser.okta_auth import _is_okta_dashboard
        assert _is_okta_dashboard("https://teams.cloud.microsoft/") is False


@pytest.mark.asyncio
class TestIsOnTeams:
    async def test_teams_cloud_url(self):
        from browser.okta_auth import _is_on_teams
        assert _is_on_teams("https://teams.cloud.microsoft/v2/#/conversations") is True

    async def test_teams_microsoft_url(self):
        from browser.okta_auth import _is_on_teams
        assert _is_on_teams("https://teams.microsoft.com/v2/#/channel/123") is True

    async def test_okta_url_is_not_teams(self):
        from browser.okta_auth import _is_on_teams
        assert _is_on_teams("https://mychg.okta.com/app/UserHome") is False


@pytest.mark.asyncio
class TestWaitForOktaAuth:
    async def test_already_on_dashboard(self):
        from browser.okta_auth import _wait_for_okta_auth
        page = AsyncMock()
        page.url = "https://mychg.okta.com/app/UserHome"
        result = await _wait_for_okta_auth(page, timeout_ms=5_000)
        assert result is True

    async def test_auth_completes_after_login(self):
        from browser.okta_auth import _wait_for_okta_auth
        page = AsyncMock()
        urls = iter([
            "https://mychg.okta.com/login/login.htm",
            "https://mychg.okta.com/login/login.htm",
            "https://mychg.okta.com/app/UserHome",
        ])
        type(page).url = property(lambda self: next(urls))
        result = await _wait_for_okta_auth(page, timeout_ms=10_000)
        assert result is True

    async def test_auth_times_out(self):
        from browser.okta_auth import _wait_for_okta_auth
        page = AsyncMock()
        type(page).url = property(lambda self: "https://mychg.okta.com/login/login.htm")
        result = await _wait_for_okta_auth(page, timeout_ms=100)
        assert result is False


@pytest.mark.asyncio
class TestClickTeamsTile:
    async def test_clicks_first_matching_selector(self):
        from browser.okta_auth import _click_teams_tile
        page = AsyncMock()
        found_loc = _make_locator(count=1)
        empty_loc = _make_locator(count=0)

        def locator_effect(selector):
            if selector == OKTA_TEAMS_TILE_SELECTORS[0]:
                return found_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_effect)
        await _click_teams_tile(page)
        found_loc.first.click.assert_awaited_once()

    async def test_falls_back_to_later_selector(self):
        from browser.okta_auth import _click_teams_tile
        page = AsyncMock()
        found_loc = _make_locator(count=1)
        empty_loc = _make_locator(count=0)

        def locator_effect(selector):
            if selector == OKTA_TEAMS_TILE_SELECTORS[2]:
                return found_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_effect)
        await _click_teams_tile(page)
        found_loc.first.click.assert_awaited_once()

    async def test_raises_when_tile_not_found(self):
        from browser.okta_auth import _click_teams_tile
        page = AsyncMock()
        empty_loc = _make_locator(count=0)
        page.locator = MagicMock(return_value=empty_loc)

        with pytest.raises(RuntimeError, match="Teams tile"):
            await _click_teams_tile(page)


@pytest.mark.asyncio
class TestWaitForTeamsTab:
    async def test_detects_new_tab(self):
        from browser.okta_auth import _wait_for_teams_tab
        okta_page = AsyncMock()
        okta_page.url = "https://mychg.okta.com/app/UserHome"

        teams_page = AsyncMock()
        teams_page.url = "https://teams.cloud.microsoft/v2/#/conversations"
        teams_page.wait_for_load_state = AsyncMock()

        context = MagicMock()
        context.pages = [okta_page, teams_page]

        result = await _wait_for_teams_tab(context, original_page_count=1, timeout_ms=5_000)
        assert result is teams_page

    async def test_detects_same_tab_navigation(self):
        from browser.okta_auth import _wait_for_teams_tab
        page = AsyncMock()
        page.url = "https://teams.cloud.microsoft/v2/#/conversations"
        page.wait_for_load_state = AsyncMock()

        context = MagicMock()
        context.pages = [page]

        result = await _wait_for_teams_tab(context, original_page_count=1, timeout_ms=5_000)
        assert result is page

    async def test_times_out(self):
        from browser.okta_auth import _wait_for_teams_tab
        page = AsyncMock()
        page.url = "https://mychg.okta.com/app/UserHome"

        context = MagicMock()
        context.pages = [page]

        with pytest.raises(RuntimeError, match="Teams.*load"):
            await _wait_for_teams_tab(context, original_page_count=1, timeout_ms=100)


@pytest.mark.asyncio
class TestEnsureOktaAndOpenTeams:
    async def test_happy_path_new_tab(self):
        """Dashboard active -> tile click -> new tab with Teams -> returns Teams page."""
        from browser.okta_auth import ensure_okta_and_open_teams

        okta_page = AsyncMock()
        okta_page.url = "https://mychg.okta.com/app/UserHome"
        okta_page.goto = AsyncMock()
        okta_page.close = AsyncMock()

        teams_page = AsyncMock()
        teams_page.url = "https://teams.cloud.microsoft/v2/#/conversations"
        teams_page.wait_for_load_state = AsyncMock()

        found_loc = _make_locator(count=1)
        empty_loc = _make_locator(count=0)

        def locator_effect(selector):
            if selector == OKTA_TEAMS_TILE_SELECTORS[0]:
                return found_loc
            return empty_loc

        okta_page.locator = MagicMock(side_effect=locator_effect)

        context = MagicMock()
        context.pages = [okta_page, teams_page]

        result = await ensure_okta_and_open_teams(okta_page, context)
        assert result is teams_page
        okta_page.goto.assert_awaited_once()
        okta_page.close.assert_awaited_once()

    async def test_auth_required_then_proceeds(self):
        """Login page -> user auths -> dashboard -> tile click -> Teams."""
        from browser.okta_auth import ensure_okta_and_open_teams

        okta_page = AsyncMock()
        teams_page = AsyncMock()
        teams_page.url = "https://teams.cloud.microsoft/v2/#/conversations"
        teams_page.wait_for_load_state = AsyncMock()

        url_sequence = iter([
            "https://mychg.okta.com/login/login.htm",
            "https://mychg.okta.com/login/login.htm",
            "https://mychg.okta.com/app/UserHome",
            "https://mychg.okta.com/app/UserHome",
        ])
        type(okta_page).url = property(lambda self: next(url_sequence))
        okta_page.goto = AsyncMock()
        okta_page.close = AsyncMock()

        found_loc = _make_locator(count=1)
        empty_loc = _make_locator(count=0)

        def locator_effect(selector):
            if selector == OKTA_TEAMS_TILE_SELECTORS[0]:
                return found_loc
            return empty_loc

        okta_page.locator = MagicMock(side_effect=locator_effect)

        context = MagicMock()
        context.pages = [okta_page, teams_page]

        result = await ensure_okta_and_open_teams(okta_page, context)
        assert result is teams_page

    async def test_auth_timeout_raises(self):
        """Login page -> auth never completes -> raises RuntimeError."""
        from browser.okta_auth import ensure_okta_and_open_teams

        okta_page = AsyncMock()
        type(okta_page).url = property(
            lambda self: "https://mychg.okta.com/login/login.htm"
        )
        okta_page.goto = AsyncMock()

        context = MagicMock()
        context.pages = [okta_page]

        with patch("browser.okta_auth.AUTH_TIMEOUT_MS", 100):
            with pytest.raises(RuntimeError, match="authentication timed out"):
                await ensure_okta_and_open_teams(okta_page, context)

    async def test_tile_not_found_raises(self):
        """Dashboard reached but tile not found -> raises RuntimeError."""
        from browser.okta_auth import ensure_okta_and_open_teams

        okta_page = AsyncMock()
        okta_page.url = "https://mychg.okta.com/app/UserHome"
        okta_page.goto = AsyncMock()

        empty_loc = _make_locator(count=0)
        okta_page.locator = MagicMock(return_value=empty_loc)

        context = MagicMock()
        context.pages = [okta_page]

        with pytest.raises(RuntimeError, match="Teams tile"):
            await ensure_okta_and_open_teams(okta_page, context)
