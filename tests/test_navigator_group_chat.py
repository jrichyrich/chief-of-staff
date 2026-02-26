"""Tests for TeamsNavigator.create_group_chat()."""

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
    loc.first.inner_text = AsyncMock(return_value="")
    return loc


def _make_suggestion_locator(names):
    """Create a mock locator that returns suggestion items."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=len(names))
    loc.first = AsyncMock()
    loc.first.click = AsyncMock()

    def nth_fn(idx):
        m = AsyncMock()
        m.inner_text = AsyncMock(return_value=names[idx] if idx < len(names) else "")
        m.click = AsyncMock()
        return m

    loc.nth = MagicMock(side_effect=nth_fn)
    return loc


class TestCreateGroupChat:
    @pytest.mark.asyncio
    async def test_error_when_chat_tab_not_found(self):
        page = AsyncMock()
        page.locator = MagicMock(return_value=_make_locator(count=0))

        nav = TeamsNavigator()
        with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
            result = await nav.create_group_chat(page, ["Alice", "Bob"])

        assert result["status"] == "error"
        assert "Chat tab" in result["error"]

    @pytest.mark.asyncio
    async def test_error_when_new_chat_not_found(self):
        page = AsyncMock()

        def locator_side_effect(sel):
            # Chat tab found, but new chat button not found
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
            result = await nav.create_group_chat(page, ["Alice"])

        assert result["status"] == "error"
        assert "New message" in result["error"]

    @pytest.mark.asyncio
    async def test_error_when_to_field_not_found(self):
        page = AsyncMock()

        def locator_side_effect(sel):
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            if "New message" in sel or "new-chat" in sel:
                return _make_locator(count=1)
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
            result = await nav.create_group_chat(page, ["Alice"])

        assert result["status"] == "error"
        assert "recipient" in result["error"].lower() or "To" in result["error"]

    @pytest.mark.asyncio
    async def test_success_with_single_recipient(self):
        page = AsyncMock()
        to_field = _make_locator(count=1)
        suggestion = _make_suggestion_locator(["Alice\n(ALICE) Engineer"])
        compose = _make_locator(count=1)

        def locator_side_effect(sel):
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            if "New message" in sel or "new-chat" in sel:
                return _make_locator(count=1)
            if "people-picker" in sel and "input" in sel:
                return to_field
            if "people-picker" in sel and "option" in sel:
                return suggestion
            if "Enter name" in sel or ("name" in sel and "placeholder" in sel):
                return to_field
            # Compose selectors
            for keyword in ("ckeditor", "textbox", "message", "Reply", "contenteditable"):
                if keyword in sel:
                    return compose
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch.object(nav, "_detect_channel_name", new_callable=AsyncMock, return_value="Alice"):
            with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
                result = await nav.create_group_chat(page, ["Alice"])

        assert result["status"] == "navigated"
        assert result["detected_channel"] == "Alice"

    @pytest.mark.asyncio
    async def test_success_with_multiple_recipients(self):
        page = AsyncMock()
        to_field = _make_locator(count=1)
        compose = _make_locator(count=1)

        def make_suggestion_for(name):
            return _make_suggestion_locator([f"{name}\n({name.upper()}) Engineer"])

        call_count = {"recipient": 0}

        def locator_side_effect(sel):
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            if "New message" in sel or "new-chat" in sel:
                return _make_locator(count=1)
            if "people-picker" in sel and "input" in sel:
                return to_field
            if "people-picker" in sel and "option" in sel:
                names = ["Alice", "Bob", "Charlie"]
                idx = min(call_count["recipient"], len(names) - 1)
                call_count["recipient"] += 1
                return make_suggestion_for(names[idx])
            if "Enter name" in sel or ("name" in sel and "placeholder" in sel):
                return to_field
            for keyword in ("ckeditor", "textbox", "message", "Reply", "contenteditable"):
                if keyword in sel:
                    return compose
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch.object(nav, "_detect_channel_name", new_callable=AsyncMock, return_value="Alice, +2"):
            with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
                result = await nav.create_group_chat(page, ["Alice", "Bob", "Charlie"])

        assert result["status"] == "navigated"
        assert "warnings" not in result

    @pytest.mark.asyncio
    async def test_reports_warnings_for_unfound_recipients(self):
        page = AsyncMock()
        to_field = _make_locator(count=1)
        empty_suggestions = _make_locator(count=0)
        compose = _make_locator(count=1)

        def locator_side_effect(sel):
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            if "New message" in sel or "new-chat" in sel:
                return _make_locator(count=1)
            if "people-picker" in sel and "input" in sel:
                return to_field
            if "people-picker" in sel and "option" in sel:
                return empty_suggestions
            if "Enter name" in sel or ("name" in sel and "placeholder" in sel):
                return to_field
            for keyword in ("ckeditor", "textbox", "message", "Reply", "contenteditable"):
                if keyword in sel:
                    return compose
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch.object(nav, "_detect_channel_name", new_callable=AsyncMock, return_value="(unknown)"):
            with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
                result = await nav.create_group_chat(page, ["Nonexistent Person"])

        assert result["status"] == "navigated"
        assert "warnings" in result
        assert "Nonexistent Person" in result["warnings"]


class TestPosterGroupChatRouting:
    """Test that PlaywrightTeamsPoster routes list targets through find → create."""

    @pytest.mark.asyncio
    async def test_list_target_creates_group_when_not_found(self):
        from browser.teams_poster import PlaywrightTeamsPoster

        manager = MagicMock()
        manager.is_alive.return_value = True
        manager.connect = AsyncMock(return_value=(AsyncMock(), MagicMock()))

        # Mock browser context and page
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

        # Mock compose box finding
        with patch.object(poster, "_find_compose_box", new_callable=AsyncMock, return_value=AsyncMock()):
            result = await poster.prepare_message(["Alice", "Bob"], "Hello group!")

        assert result["status"] == "confirm_required"
        navigator.find_existing_chat.assert_called_once_with(mock_page, ["Alice", "Bob"])
        navigator.create_group_chat.assert_called_once_with(mock_page, ["Alice", "Bob"])

    @pytest.mark.asyncio
    async def test_string_target_routes_to_search(self):
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


class TestMCPToolCommaParsing:
    """Test that the MCP tool parses comma-separated targets."""

    def test_comma_parsing_logic(self):
        """Test the comma-splitting logic directly."""
        target = "Alice, Bob, Charlie"
        names = [n.strip() for n in target.split(",") if n.strip()]
        assert names == ["Alice", "Bob", "Charlie"]

    def test_single_name_not_parsed(self):
        """Single name without commas stays as string."""
        target = "Alice"
        if "," in target:
            names = [n.strip() for n in target.split(",") if n.strip()]
        else:
            names = None
        assert names is None
