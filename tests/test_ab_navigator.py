"""Tests for ABNavigator — agent-browser-based Teams navigator."""

import pytest
from unittest.mock import AsyncMock, call

from browser.ab_navigator import ABNavigator, SHORTCUT_NEW_MESSAGE, SHORTCUT_SEARCH
from browser.agent_browser import AgentBrowserError


@pytest.fixture
def ab():
    """Return a mocked AgentBrowser."""
    mock = AsyncMock()
    mock.snapshot = AsyncMock(return_value={"ok": True, "text": ""})
    mock.find = AsyncMock(return_value={"ok": True, "text": "@e1"})
    mock.click = AsyncMock(return_value={"ok": True})
    mock.fill = AsyncMock(return_value={"ok": True})
    mock.type_text = AsyncMock(return_value={"ok": True})
    mock.press = AsyncMock(return_value={"ok": True})
    mock.wait = AsyncMock(return_value={"ok": True})
    mock.open = AsyncMock(return_value={"ok": True})
    return mock


@pytest.fixture
def nav(ab):
    return ABNavigator(ab)


class TestExtractRef:
    def test_extracts_ref_from_text(self):
        result = {"text": "@e5 button 'Submit'"}
        assert ABNavigator._extract_ref(result) == "@e5"

    def test_returns_none_when_no_ref(self):
        result = {"text": "no refs here"}
        assert ABNavigator._extract_ref(result) is None

    def test_returns_none_on_empty(self):
        result = {"text": ""}
        assert ABNavigator._extract_ref(result) is None


class TestExtractRefsWithText:
    def test_parses_legacy_format(self):
        text = "@e10 listitem 'Michael Larsen'\n@e11 listitem 'Bob Smith'"
        pairs = ABNavigator._extract_refs_with_text(text)
        assert len(pairs) == 2
        assert pairs[0] == ("@e10", "listitem 'Michael Larsen'")
        assert pairs[1] == ("@e11", "listitem 'Bob Smith'")

    def test_parses_real_agent_browser_format(self):
        text = (
            '    - heading "Chat" [ref=e17] [level=1]\n'
            '    - textbox "Type a message" [ref=e194]'
        )
        pairs = ABNavigator._extract_refs_with_text(text)
        assert len(pairs) == 2
        assert pairs[0][0] == "@e17"
        assert "heading" in pairs[0][1]
        assert pairs[1][0] == "@e194"
        assert "textbox" in pairs[1][1]

    def test_empty_input(self):
        assert ABNavigator._extract_refs_with_text("") == []


class TestCreateGroupChat:
    @pytest.mark.asyncio
    async def test_creates_new_chat_and_adds_recipients(self, nav, ab):
        """Should press New Message shortcut and add each recipient."""
        # First snapshot: find To textbox
        # Second snapshot: find suggestions
        ab.snapshot = AsyncMock(side_effect=[
            {"ok": True, "text": '    - textbox "To:" [ref=e167]'},
            {"ok": True, "text": '    - option "Michael Larsen, VP" [ref=e10]'},
            {"ok": True, "text": '    - textbox "To:" [ref=e167]'},
            {"ok": True, "text": '    - option "Heather Allen, Dir" [ref=e11]'},
            {"ok": True, "text": '    - heading "Chat" [ref=e1] [level=1]'},
        ])

        result = await nav.create_group_chat(["Michael Larsen", "Heather Allen"])

        assert result["status"] == "navigated"
        ab.press.assert_any_call(SHORTCUT_NEW_MESSAGE)
        assert ab.fill.call_count == 2

    @pytest.mark.asyncio
    async def test_reports_failed_recipients(self, nav, ab):
        """Should report recipients that couldn't be found."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": '    - textbox "To:" [ref=e167]',
        })

        result = await nav.create_group_chat(["Nobody Exists"])

        assert result["status"] == "navigated"
        assert "warnings" in result
        assert "Nobody Exists" in result["warnings"]

    @pytest.mark.asyncio
    async def test_falls_back_to_recipient_names_when_unknown(self, nav, ab):
        """Should use recipient list as detected_channel when snapshot can't detect."""
        ab.snapshot = AsyncMock(side_effect=[
            {"ok": True, "text": '    - textbox "To:" [ref=e167]'},
            {"ok": True, "text": '    - option "Alice Smith, Corp" [ref=e10]'},
            {"ok": True, "text": '    - textbox "To:" [ref=e167]'},
            {"ok": True, "text": '    - option "Bob Jones, Corp" [ref=e11]'},
            # detect_channel_name snapshot — no heading or treeitem
            {"ok": True, "text": '    - heading "Chat" [ref=e1] [level=1]'},
        ])

        result = await nav.create_group_chat(["Alice Smith", "Bob Jones"])

        assert result["status"] == "navigated"
        assert result["detected_channel"] == "Alice Smith, Bob Jones"

    @pytest.mark.asyncio
    async def test_empty_recipients_skipped(self, nav, ab):
        """Should skip empty recipient names."""
        ab.snapshot = AsyncMock(side_effect=[
            {"ok": True, "text": '    - textbox "To:" [ref=e167]'},
            {"ok": True, "text": '    - option "Alice, Corp" [ref=e10]'},
            {"ok": True, "text": '    - heading "Chat" [ref=e1] [level=1]'},
        ])

        result = await nav.create_group_chat(["Alice", "", "  "])

        assert result["status"] == "navigated"
        # Should only fill for "Alice"
        assert ab.fill.call_count == 1


class TestSearchAndNavigate:
    @pytest.mark.asyncio
    async def test_searches_and_navigates_to_person(self, nav, ab):
        """Should activate search, type, and click matching result."""
        ab.snapshot = AsyncMock(side_effect=[
            # First snapshot: find search combobox
            {"ok": True, "text": '    - combobox "Search (⌥ ⌘ E)" [ref=e2]'},
            # Second snapshot: search results
            {"ok": True, "text": '    - option "Jonas De Oliveira, Engineering" [ref=e20]'},
            # Third snapshot: detect channel
            {"ok": True, "text": '    - heading "Jonas De Oliveira" [ref=e165] [level=2]'},
        ])

        result = await nav.search_and_navigate("Jonas De Oliveira")

        assert result["status"] == "navigated"
        ab.press.assert_any_call(SHORTCUT_SEARCH)
        ab.fill.assert_called_once()
        ab.click.assert_called_once_with("@e20")

    @pytest.mark.asyncio
    async def test_returns_error_when_no_results(self, nav, ab):
        """Should error when search returns no matching results."""
        ab.snapshot = AsyncMock(side_effect=[
            {"ok": True, "text": '    - combobox "Search" [ref=e2]'},
            {"ok": True, "text": ""},
        ])

        result = await nav.search_and_navigate("Nonexistent Person")

        assert result["status"] == "error"
        ab.press.assert_any_call("Escape")

    @pytest.mark.asyncio
    async def test_returns_error_when_search_bar_not_found(self, nav, ab):
        """Should error when search bar can't be located."""
        ab.snapshot = AsyncMock(return_value={"ok": True, "text": ""})

        result = await nav.search_and_navigate("Someone")

        assert result["status"] == "error"
        assert "search bar" in result["error"].lower()


class TestDetectChannelName:
    @pytest.mark.asyncio
    async def test_detects_from_snapshot(self, nav, ab):
        """Should extract channel name from real agent-browser snapshot format."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Chat" [ref=e17] [level=1]\n'
                '    - heading "Michael Larsen" [ref=e165] [level=2]\n'
                '    - textbox "Type a message" [ref=e194]'
            ),
        })

        name = await nav.detect_channel_name()
        assert name == "Michael Larsen"

    @pytest.mark.asyncio
    async def test_skips_generic_headings(self, nav, ab):
        """Should skip headings like 'Chat', 'Teams', 'Microsoft Teams'."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Microsoft Teams" [ref=e1] [level=1]\n'
                '    - heading "Engineering" [ref=e2] [level=2]'
            ),
        })

        name = await nav.detect_channel_name()
        assert name == "Engineering"

    @pytest.mark.asyncio
    async def test_detects_from_treeitem_in_1to1_chat(self, nav, ab):
        """Should extract name from treeitem when no heading exists (1:1 chats)."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Chat" [ref=e17] [level=1]\n'
                '    - treeitem "Chat Jason Richards (You)" [ref=e33] [level=2]\n'
                '    - textbox "Type a message" [ref=e194]'
            ),
        })

        name = await nav.detect_channel_name()
        assert name == "Jason Richards"

    @pytest.mark.asyncio
    async def test_detects_from_treeitem_without_suffix(self, nav, ab):
        """Should handle treeitem without parenthetical suffix."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Chat" [ref=e17] [level=1]\n'
                '    - treeitem "Chat Michael Larsen" [ref=e40] [level=2]\n'
                '    - textbox "Type a message" [ref=e194]'
            ),
        })

        name = await nav.detect_channel_name()
        assert name == "Michael Larsen"

    @pytest.mark.asyncio
    async def test_detects_multi_participant_treeitem(self, nav, ab):
        """Should extract multi-participant name from treeitem."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Chat" [ref=e17] [level=1]\n'
                '    - treeitem "Chat Alice, Bob, Charlie" [ref=e40] [level=2]\n'
                '    - textbox "Type a message" [ref=e194]'
            ),
        })

        name = await nav.detect_channel_name()
        assert name == "Alice, Bob, Charlie"

    @pytest.mark.asyncio
    async def test_prefers_selected_treeitem(self, nav, ab):
        """Should prefer treeitem with [selected] over first match."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Chat" [ref=e17] [level=1]\n'
                '    - treeitem "Chat Wrong Person" [ref=e30] [level=2]\n'
                '    - treeitem "Chat Right Person" [ref=e33] [level=2] [selected=true]\n'
                '    - textbox "Type a message" [ref=e194]'
            ),
        })

        name = await nav.detect_channel_name()
        assert name == "Right Person"

    @pytest.mark.asyncio
    async def test_skips_date_headings(self, nav, ab):
        """Should skip headings that look like date separators."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Chat" [ref=e17] [level=1]\n'
                '    - heading "Wednesday, April 17, 2024" [ref=e50] [level=2]\n'
                '    - heading "Today" [ref=e51] [level=2]\n'
                '    - treeitem "Chat Jason Richards" [ref=e33] [level=2]'
            ),
        })

        name = await nav.detect_channel_name()
        assert name == "Jason Richards"

    @pytest.mark.asyncio
    async def test_prefers_heading_over_treeitem(self, nav, ab):
        """Should prefer level-2 heading when both heading and treeitem exist."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Chat" [ref=e17] [level=1]\n'
                '    - heading "Engineering" [ref=e165] [level=2]\n'
                '    - treeitem "Chat Jason Richards" [ref=e33] [level=2]\n'
                '    - textbox "Type a message" [ref=e194]'
            ),
        })

        name = await nav.detect_channel_name()
        assert name == "Engineering"

    @pytest.mark.asyncio
    async def test_returns_unknown_on_error(self, nav, ab):
        """Should return (unknown) if snapshot fails."""
        ab.snapshot = AsyncMock(side_effect=AgentBrowserError("no page"))

        name = await nav.detect_channel_name()
        assert name == "(unknown)"


class TestFindComposeBox:
    @pytest.mark.asyncio
    async def test_finds_message_textbox(self, nav, ab):
        """Should find the compose textbox."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Chat" [ref=e1] [level=1]\n'
                '    - textbox "Type a message" [ref=e15]'
            ),
        })

        ref = await nav.find_compose_box()
        assert ref == "@e15"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_compose_box(self, nav, ab):
        """Should return None if no compose box found."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Chat" [ref=e1] [level=1]\n'
                '    - button "New chat" [ref=e2]'
            ),
        })

        ref = await nav.find_compose_box()
        assert ref is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, nav, ab):
        """Should return None if snapshot fails."""
        ab.snapshot = AsyncMock(side_effect=AgentBrowserError("crashed"))

        ref = await nav.find_compose_box()
        assert ref is None


class TestFindRefInSnapshot:
    @pytest.mark.asyncio
    async def test_finds_matching_element(self, nav, ab):
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": (
                '    - heading "Chat" [ref=e1] [level=1]\n'
                '    - textbox "To:" [ref=e167]'
            ),
        })

        ref = await nav._find_ref_in_snapshot("textbox", "to:")
        assert ref == "@e167"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, nav, ab):
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": '    - heading "Chat" [ref=e1] [level=1]',
        })

        ref = await nav._find_ref_in_snapshot("textbox", "to:")
        assert ref is None
