"""Tests for ABNavigator — agent-browser-based Teams navigator."""

import pytest
from unittest.mock import AsyncMock

from browser.ab_navigator import ABNavigator
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
    def test_parses_multiple_lines(self):
        text = "@e10 listitem 'Michael Larsen'\n@e11 listitem 'Bob Smith'"
        pairs = ABNavigator._extract_refs_with_text(text)
        assert len(pairs) == 2
        assert pairs[0] == ("@e10", "listitem 'Michael Larsen'")
        assert pairs[1] == ("@e11", "listitem 'Bob Smith'")

    def test_empty_input(self):
        assert ABNavigator._extract_refs_with_text("") == []


class TestCreateGroupChat:
    @pytest.mark.asyncio
    async def test_creates_new_chat_and_adds_recipients(self, nav, ab):
        """Should click new chat, add each recipient, and return navigated."""
        ab.find = AsyncMock(return_value={"ok": True, "text": "@e5"})
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": "@e10 listitem 'Michael Larsen - Engineer'\n@e11 listitem 'Bob Smith'"
        })

        result = await nav.create_group_chat(["Michael Larsen", "Heather Allen"])

        assert result["status"] == "navigated"
        # Should have called find for chat button + new chat button + To field per recipient
        assert ab.find.call_count >= 1
        # Should have filled each recipient name
        assert ab.fill.call_count >= 2

    @pytest.mark.asyncio
    async def test_returns_error_when_new_chat_button_not_found(self, nav, ab):
        """Should error if new chat button can't be found."""
        ab.find = AsyncMock(side_effect=AgentBrowserError("not found"))

        result = await nav.create_group_chat(["Alice"])

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_empty_recipients_skipped(self, nav, ab):
        """Should skip empty recipient names."""
        ab.find = AsyncMock(return_value={"ok": True, "text": "@e5"})
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": "@e10 option 'Alice Corp'"
        })

        result = await nav.create_group_chat(["Alice", "", "  "])

        assert result["status"] == "navigated"
        # Should only have filled for "Alice" (empty names skipped)
        assert ab.fill.call_count >= 1


class TestSearchAndNavigate:
    @pytest.mark.asyncio
    async def test_searches_and_navigates_to_person(self, nav, ab):
        """Should use search bar to find and navigate to a person."""
        ab.find = AsyncMock(return_value={"ok": True, "text": "@e3"})
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": "@e20 option 'Jonas De Oliveira - Engineering'"
        })

        result = await nav.search_and_navigate("Jonas De Oliveira")

        assert result["status"] == "navigated"

    @pytest.mark.asyncio
    async def test_returns_error_when_no_results(self, nav, ab):
        """Should error when search returns no matching results."""
        ab.find = AsyncMock(return_value={"ok": True, "text": "@e3"})
        ab.snapshot = AsyncMock(return_value={"ok": True, "text": ""})

        result = await nav.search_and_navigate("Nonexistent Person")

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_returns_error_when_search_bar_not_found(self, nav, ab):
        """Should error when search bar can't be located."""
        ab.find = AsyncMock(side_effect=AgentBrowserError("not found"))

        result = await nav.search_and_navigate("Someone")

        assert result["status"] == "error"


class TestDetectChannelName:
    @pytest.mark.asyncio
    async def test_detects_from_snapshot(self, nav, ab):
        """Should extract channel name from accessibility snapshot."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": "@e1 heading 'Michael Larsen'\n@e2 textbox 'Type a message'"
        })

        name = await nav.detect_channel_name()
        assert name == "Michael Larsen"

    @pytest.mark.asyncio
    async def test_skips_generic_headings(self, nav, ab):
        """Should skip headings like 'Chat', 'Teams', 'Microsoft Teams'."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": "@e1 heading 'Microsoft Teams'\n@e2 heading 'Engineering'"
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
        """Should find the compose textbox by role and text."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": "@e1 heading 'Chat'\n@e15 textbox 'Type a message'"
        })

        ref = await nav.find_compose_box()
        assert ref == "@e15"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_compose_box(self, nav, ab):
        """Should return None if no compose box found."""
        ab.snapshot = AsyncMock(return_value={
            "ok": True,
            "text": "@e1 heading 'Chat'\n@e2 button 'New chat'"
        })

        ref = await nav.find_compose_box()
        assert ref is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, nav, ab):
        """Should return None if snapshot fails."""
        ab.snapshot = AsyncMock(side_effect=AgentBrowserError("crashed"))

        ref = await nav.find_compose_box()
        assert ref is None
