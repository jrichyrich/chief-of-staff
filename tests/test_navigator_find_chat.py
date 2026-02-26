"""Tests for TeamsNavigator.find_existing_chat() — sidebar filter approach."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from browser.navigator import TeamsNavigator


def _make_locator(count=0):
    """Create a mock locator with a given count."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    loc.first = AsyncMock()
    loc.first.click = AsyncMock()
    loc.first.fill = AsyncMock()
    loc.first.is_visible = AsyncMock(return_value=count > 0)
    loc.first.inner_text = AsyncMock(return_value="")
    return loc


def _make_treeitem_locator(items: list[dict]):
    """Create a mock locator for level-2 treeitems.

    Each item in *items* is a dict with 'text' (inner_text value).
    """
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=len(items))

    def nth_fn(idx):
        m = AsyncMock()
        if idx < len(items):
            m.inner_text = AsyncMock(return_value=items[idx]["text"])
        else:
            m.inner_text = AsyncMock(return_value="")
        m.click = AsyncMock()
        return m

    loc.nth = MagicMock(side_effect=nth_fn)
    loc.first = AsyncMock()
    if items:
        loc.first.inner_text = AsyncMock(return_value=items[0]["text"])
        loc.first.click = AsyncMock()
    return loc


class TestFindExistingChat:
    """Tests for TeamsNavigator.find_existing_chat()."""

    @pytest.mark.asyncio
    async def test_returns_error_when_chat_tab_not_found(self):
        """Should error if chat tab can't be found."""
        page = AsyncMock()
        page.locator = MagicMock(return_value=_make_locator(count=0))

        nav = TeamsNavigator()
        with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
            result = await nav.find_existing_chat(page, ["Alice"])

        assert result["status"] == "error"
        assert "Chat tab" in result["error"]

    @pytest.mark.asyncio
    async def test_returns_error_when_filter_not_found(self):
        """Should error if filter input can't be opened."""
        page = AsyncMock()

        def locator_side_effect(sel):
            # Chat tab found, but filter elements not found
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
            result = await nav.find_existing_chat(page, ["Alice"])

        assert result["status"] == "error"
        assert "filter" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_returns_not_found_when_no_matching_chat(self):
        """Should return not_found when filter shows no matching treeitems."""
        page = AsyncMock()
        filter_input = _make_locator(count=1)
        empty_treeitems = _make_treeitem_locator([])

        def locator_side_effect(sel):
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            if "filter" in sel.lower() and "Show" in sel:
                return _make_locator(count=1)
            if "Filter by person" in sel:
                return filter_input
            if 'aria-level="2"' in sel:
                return empty_treeitems
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
            result = await nav.find_existing_chat(page, ["Nonexistent"])

        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_finds_and_navigates_to_one_on_one_chat(self):
        """Should find a 1:1 chat by participant name and navigate to it."""
        page = AsyncMock()
        filter_input = _make_locator(count=1)
        treeitems = _make_treeitem_locator([
            {"text": "Alice\nHey, how are you?2:30 PM"},
            {"text": "Bob\nSee you tomorrow3:00 PM"},
        ])
        compose = _make_locator(count=1)

        def locator_side_effect(sel):
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            if "filter" in sel.lower() and "Show" in sel:
                return _make_locator(count=1)
            if "Filter by person" in sel:
                return filter_input
            if 'aria-level="2"' in sel:
                return treeitems
            # Compose selectors
            for kw in ("ckeditor", "textbox", "message", "Reply", "contenteditable"):
                if kw in sel:
                    return compose
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch.object(nav, "_detect_channel_name", new_callable=AsyncMock, return_value="Alice"):
            with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
                result = await nav.find_existing_chat(page, ["Alice"])

        assert result["status"] == "navigated"
        assert result["detected_channel"] == "Alice"

    @pytest.mark.asyncio
    async def test_finds_group_chat_by_participant_names(self):
        """Should find a group chat containing multiple participants."""
        page = AsyncMock()
        filter_input = _make_locator(count=1)
        treeitems = _make_treeitem_locator([
            {"text": "Jennifer, Jordan, +2\nJarvis here!5:00 PM"},
            {"text": "Jennifer Baume\nHi there1:00 PM"},
        ])
        compose = _make_locator(count=1)

        def locator_side_effect(sel):
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            if "filter" in sel.lower() and "Show" in sel:
                return _make_locator(count=1)
            if "Filter by person" in sel:
                return filter_input
            if 'aria-level="2"' in sel:
                return treeitems
            for kw in ("ckeditor", "textbox", "message", "Reply", "contenteditable"):
                if kw in sel:
                    return compose
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch.object(nav, "_detect_channel_name", new_callable=AsyncMock, return_value="Jennifer, +2"):
            with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
                result = await nav.find_existing_chat(
                    page, ["Jennifer Baume", "Jordan Johnson"]
                )

        assert result["status"] == "navigated"

    @pytest.mark.asyncio
    async def test_clears_filter_after_navigation(self):
        """Should clear the filter text box after successful navigation."""
        page = AsyncMock()
        filter_input = _make_locator(count=1)
        treeitems = _make_treeitem_locator([
            {"text": "Alice\nHello2:00 PM"},
        ])
        compose = _make_locator(count=1)

        def locator_side_effect(sel):
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            if "filter" in sel.lower() and "Show" in sel:
                return _make_locator(count=1)
            if "Filter by person" in sel:
                return filter_input
            if 'aria-level="2"' in sel:
                return treeitems
            for kw in ("ckeditor", "textbox", "message", "Reply", "contenteditable"):
                if kw in sel:
                    return compose
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch.object(nav, "_detect_channel_name", new_callable=AsyncMock, return_value="Alice"):
            with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
                result = await nav.find_existing_chat(page, ["Alice"])

        assert result["status"] == "navigated"
        # Verify filter was cleared (fill called with empty string)
        fill_calls = filter_input.first.fill.call_args_list
        assert any(call.args == ("",) for call in fill_calls), \
            "Filter should be cleared after navigation"

    @pytest.mark.asyncio
    async def test_returns_error_when_compose_box_not_found(self):
        """Should error if compose box doesn't appear after clicking chat."""
        page = AsyncMock()
        filter_input = _make_locator(count=1)
        treeitems = _make_treeitem_locator([
            {"text": "Alice\nHello2:00 PM"},
        ])

        def locator_side_effect(sel):
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            if "filter" in sel.lower() and "Show" in sel:
                return _make_locator(count=1)
            if "Filter by person" in sel:
                return filter_input
            if 'aria-level="2"' in sel:
                return treeitems
            # No compose box found
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
            result = await nav.find_existing_chat(page, ["Alice"])

        assert result["status"] == "error"
        assert "compose" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_prefers_group_chat_over_individual_match(self):
        """When searching for multiple participants, should prefer the group chat
        entry that contains multiple names over a 1:1 chat with one participant."""
        page = AsyncMock()
        filter_input = _make_locator(count=1)

        # Track which index was clicked
        clicked_indices = []
        items_data = [
            {"text": "Jennifer Baume\nHi there1:00 PM"},
            {"text": "Jennifer, Jordan, +2\nGroup convo5:00 PM"},
        ]

        treeitems = AsyncMock()
        treeitems.count = AsyncMock(return_value=len(items_data))

        def nth_fn(idx):
            m = AsyncMock()
            m.inner_text = AsyncMock(return_value=items_data[idx]["text"])

            async def track_click(**kwargs):
                clicked_indices.append(idx)

            m.click = AsyncMock(side_effect=track_click)
            return m

        treeitems.nth = MagicMock(side_effect=nth_fn)
        compose = _make_locator(count=1)

        def locator_side_effect(sel):
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            if "filter" in sel.lower() and "Show" in sel:
                return _make_locator(count=1)
            if "Filter by person" in sel:
                return filter_input
            if 'aria-level="2"' in sel:
                return treeitems
            for kw in ("ckeditor", "textbox", "message", "Reply", "contenteditable"):
                if kw in sel:
                    return compose
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch.object(nav, "_detect_channel_name", new_callable=AsyncMock, return_value="Jennifer, +2"):
            with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
                result = await nav.find_existing_chat(
                    page, ["Jennifer Baume", "Jordan Johnson"]
                )

        assert result["status"] == "navigated"
        # Should have clicked the group chat item (index 1), not the 1:1 (index 0)
        assert 1 in clicked_indices, f"Expected click on index 1, got clicks on {clicked_indices}"


class TestPosterFindOrCreateRouting:
    """Test that poster tries find_existing_chat before create_group_chat."""

    @pytest.mark.asyncio
    async def test_list_target_tries_find_first(self):
        """When target is a list, should try find_existing_chat first."""
        from browser.teams_poster import PlaywrightTeamsPoster

        manager = MagicMock()
        manager.is_alive.return_value = True
        manager.connect = AsyncMock(return_value=(AsyncMock(), MagicMock()))

        mock_page = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        manager.connect.return_value[1].contexts = [mock_ctx]

        navigator = MagicMock()
        navigator.find_existing_chat = AsyncMock(return_value={
            "status": "navigated",
            "detected_channel": "Alice, +1",
        })
        navigator.create_group_chat = AsyncMock()

        poster = PlaywrightTeamsPoster(manager=manager, navigator=navigator)

        with patch.object(poster, "_find_compose_box", new_callable=AsyncMock, return_value=AsyncMock()):
            result = await poster.prepare_message(["Alice", "Bob"], "Hello!")

        assert result["status"] == "confirm_required"
        navigator.find_existing_chat.assert_called_once_with(mock_page, ["Alice", "Bob"])
        navigator.create_group_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_create_when_not_found(self):
        """When find_existing_chat returns not_found, should fall back to create_group_chat."""
        from browser.teams_poster import PlaywrightTeamsPoster

        manager = MagicMock()
        manager.is_alive.return_value = True
        manager.connect = AsyncMock(return_value=(AsyncMock(), MagicMock()))

        mock_page = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        manager.connect.return_value[1].contexts = [mock_ctx]

        navigator = MagicMock()
        navigator.find_existing_chat = AsyncMock(return_value={
            "status": "not_found",
        })
        navigator.create_group_chat = AsyncMock(return_value={
            "status": "navigated",
            "detected_channel": "Alice, +1",
        })

        poster = PlaywrightTeamsPoster(manager=manager, navigator=navigator)

        with patch.object(poster, "_find_compose_box", new_callable=AsyncMock, return_value=AsyncMock()):
            result = await poster.prepare_message(["Alice", "Bob"], "Hello!")

        assert result["status"] == "confirm_required"
        navigator.find_existing_chat.assert_called_once()
        navigator.create_group_chat.assert_called_once_with(mock_page, ["Alice", "Bob"])

    @pytest.mark.asyncio
    async def test_string_target_still_uses_search(self):
        """Single string target should still use search_and_navigate (no find_existing_chat)."""
        from browser.teams_poster import PlaywrightTeamsPoster

        manager = MagicMock()
        manager.is_alive.return_value = True
        manager.connect = AsyncMock(return_value=(AsyncMock(), MagicMock()))

        mock_page = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page]
        manager.connect.return_value[1].contexts = [mock_ctx]

        navigator = MagicMock()
        navigator.search_and_navigate = AsyncMock(return_value={
            "status": "navigated",
            "detected_channel": "Alice",
        })

        poster = PlaywrightTeamsPoster(manager=manager, navigator=navigator)

        with patch.object(poster, "_find_compose_box", new_callable=AsyncMock, return_value=AsyncMock()):
            result = await poster.prepare_message("Alice", "Hello!")

        assert result["status"] == "confirm_required"
        navigator.search_and_navigate.assert_called_once_with(mock_page, "Alice")
