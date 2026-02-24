"""Tests for browser.navigator — TeamsNavigator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser.navigator import TeamsNavigator, SEARCH_SELECTORS, SEARCH_RESULT_SELECTOR


def _make_locator(count=1, texts=None):
    """Mock locator with count and optional text content.

    If *texts* is provided, each element via nth(i) returns the
    corresponding text from inner_text(). This supports both
    ``locator.first.inner_text()`` and ``locator.nth(i).inner_text()``.
    """
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    loc.click = AsyncMock()

    if texts:
        # Build per-item mocks for nth() access
        items = []
        for t in texts:
            item = AsyncMock()
            item.inner_text = AsyncMock(return_value=t)
            item.click = AsyncMock()
            items.append(item)

        def nth_effect(i):
            if i < len(items):
                return items[i]
            return AsyncMock()

        loc.nth = MagicMock(side_effect=nth_effect)
        loc.first = items[0]
    else:
        first = AsyncMock()
        first.click = AsyncMock()
        loc.first = first
        loc.nth = MagicMock(return_value=first)
    return loc


# Patch asyncio.sleep in the navigator module so tests don't wait.
@pytest.fixture(autouse=True)
def _fast_sleep():
    """Replace asyncio.sleep with an instant coroutine for all navigator tests."""
    async def _instant_sleep(_seconds):
        pass

    with patch("browser.navigator.asyncio.sleep", side_effect=_instant_sleep):
        yield


@pytest.mark.asyncio
class TestSearchAndNavigate:
    async def test_search_finds_target(self):
        """Happy path: search bar found, target typed, matching result clicked."""
        page = AsyncMock()
        search_loc = _make_locator(count=1)
        # Result locator with text that matches the target
        result_loc = _make_locator(count=2, texts=[
            "Engineering | General Channel",
            "Engineering Ops | Other Channel",
        ])
        compose_loc = _make_locator(count=1)
        channel_loc = _make_locator(count=1, texts=["Engineering"])
        empty_loc = _make_locator(count=0)

        from browser.constants import COMPOSE_SELECTORS, CHANNEL_NAME_SELECTORS

        def locator_effect(selector):
            if selector in SEARCH_SELECTORS:
                return search_loc
            if selector == SEARCH_RESULT_SELECTOR:
                return result_loc
            if selector in COMPOSE_SELECTORS:
                return compose_loc
            if selector in CHANNEL_NAME_SELECTORS:
                return channel_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_effect)
        page.keyboard = AsyncMock()
        page.title = AsyncMock(return_value="Engineering | Microsoft Teams")

        nav = TeamsNavigator()
        result = await nav.search_and_navigate(page, "Engineering")

        assert result["status"] == "navigated"
        assert result["detected_channel"] == "Engineering"
        search_loc.click.assert_awaited()

    async def test_search_recovers_after_reload(self):
        """Reloads page and retries when search bar not initially found."""
        page = AsyncMock()
        search_loc = _make_locator(count=1)
        result_loc = _make_locator(count=1, texts=["Engineering"])
        compose_loc = _make_locator(count=1)
        channel_loc = _make_locator(count=1, texts=["Engineering"])
        empty_loc = _make_locator(count=0)

        from browser.constants import COMPOSE_SELECTORS, CHANNEL_NAME_SELECTORS

        call_count = {"reload_called": False}

        original_empty = _make_locator(count=0)

        def locator_effect(selector):
            if selector in SEARCH_SELECTORS and not call_count["reload_called"]:
                return empty_loc
            if selector in SEARCH_SELECTORS:
                return search_loc
            if selector == SEARCH_RESULT_SELECTOR:
                return result_loc
            if selector in COMPOSE_SELECTORS:
                return compose_loc
            if selector in CHANNEL_NAME_SELECTORS:
                return channel_loc
            return original_empty

        async def fake_reload(**kwargs):
            call_count["reload_called"] = True

        page.locator = MagicMock(side_effect=locator_effect)
        page.reload = AsyncMock(side_effect=fake_reload)
        page.keyboard = AsyncMock()
        page.title = AsyncMock(return_value="Engineering | Microsoft Teams")

        nav = TeamsNavigator()
        result = await nav.search_and_navigate(page, "Engineering")

        assert result["status"] == "navigated"
        page.reload.assert_awaited_once()

    async def test_search_no_search_bar(self):
        """Error when search bar not found."""
        page = AsyncMock()
        empty_loc = _make_locator(count=0)
        page.locator = MagicMock(return_value=empty_loc)

        nav = TeamsNavigator()
        result = await nav.search_and_navigate(page, "Engineering")

        assert result["status"] == "error"
        assert "search bar" in result["error"].lower()

    async def test_search_no_results(self):
        """Error when no search results appear."""
        page = AsyncMock()
        search_loc = _make_locator(count=1)
        empty_loc = _make_locator(count=0)

        def locator_effect(selector):
            if selector in SEARCH_SELECTORS:
                return search_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_effect)
        page.keyboard = AsyncMock()

        nav = TeamsNavigator()
        result = await nav.search_and_navigate(page, "NonExistentChannel")

        assert result["status"] == "error"
        assert "NonExistentChannel" in result["error"]
        page.keyboard.press.assert_awaited_with("Escape")

    async def test_search_no_compose_box(self):
        """Error when compose box not found after navigation."""
        page = AsyncMock()
        search_loc = _make_locator(count=1)
        result_loc = _make_locator(count=1, texts=["Engineering"])
        empty_loc = _make_locator(count=0)

        from browser.constants import COMPOSE_SELECTORS

        def locator_effect(selector):
            if selector in SEARCH_SELECTORS:
                return search_loc
            if selector == SEARCH_RESULT_SELECTOR:
                return result_loc
            if selector in COMPOSE_SELECTORS:
                return empty_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_effect)
        page.keyboard = AsyncMock()

        nav = TeamsNavigator()
        result = await nav.search_and_navigate(page, "Engineering")

        assert result["status"] == "error"
        assert "compose box" in result["error"].lower()


@pytest.mark.asyncio
class TestFindElement:
    async def test_find_element_returns_first_match(self):
        """Returns the first locator that matches."""
        page = AsyncMock()
        empty_loc = _make_locator(count=0)
        found_loc = _make_locator(count=1)

        def locator_effect(selector):
            if selector == 'input[placeholder*="Search"]':
                return found_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_effect)

        result = await TeamsNavigator._find_element(page, SEARCH_SELECTORS, timeout_ms=2_000)
        assert result is found_loc

    async def test_find_element_returns_none_on_timeout(self):
        """Returns None when no selector matches within timeout."""
        page = AsyncMock()
        empty_loc = _make_locator(count=0)
        page.locator = MagicMock(return_value=empty_loc)

        result = await TeamsNavigator._find_element(page, SEARCH_SELECTORS, timeout_ms=500)
        assert result is None


@pytest.mark.asyncio
class TestFindMatchingResult:
    async def test_finds_matching_text(self):
        """Returns the element whose text contains the target."""
        loc = _make_locator(count=3, texts=[
            "Messages",
            "Heather Allen | DIR II PRIVACY",
            "Heather Allen in all results",
        ])
        match = await TeamsNavigator._find_matching_result(loc, "Heather Allen")
        assert match is not None
        text = await match.inner_text()
        assert "Heather Allen" in text

    async def test_returns_none_when_no_match(self):
        """Returns None when no element text matches."""
        loc = _make_locator(count=2, texts=["General Channel", "Random Channel"])
        match = await TeamsNavigator._find_matching_result(loc, "NonExistent")
        assert match is None

    async def test_case_insensitive_match(self):
        """Match is case-insensitive."""
        loc = _make_locator(count=1, texts=["engineering General"])
        match = await TeamsNavigator._find_matching_result(loc, "Engineering")
        assert match is not None


@pytest.mark.asyncio
class TestDetectChannelName:
    async def test_detect_from_selector(self):
        """Detects channel name from DOM selector."""
        page = AsyncMock()
        channel_loc = _make_locator(count=1, texts=["General"])
        empty_loc = _make_locator(count=0)

        from browser.constants import CHANNEL_NAME_SELECTORS

        def locator_effect(selector):
            if selector in CHANNEL_NAME_SELECTORS:
                return channel_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_effect)
        page.title = AsyncMock(return_value="General | Microsoft Teams")

        result = await TeamsNavigator._detect_channel_name(page)
        assert result == "General"

    async def test_detect_from_page_title(self):
        """Falls back to page title when no selector matches."""
        page = AsyncMock()
        empty_loc = _make_locator(count=0)
        page.locator = MagicMock(return_value=empty_loc)
        page.title = AsyncMock(return_value="Engineering | Microsoft Teams")

        result = await TeamsNavigator._detect_channel_name(page)
        assert result == "Engineering"

    async def test_detect_returns_unknown(self):
        """Returns (unknown) when nothing matches."""
        page = AsyncMock()
        empty_loc = _make_locator(count=0)
        page.locator = MagicMock(return_value=empty_loc)
        page.title = AsyncMock(return_value="Microsoft Teams")

        result = await TeamsNavigator._detect_channel_name(page)
        assert result == "(unknown)"
