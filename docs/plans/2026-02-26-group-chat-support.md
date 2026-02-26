# Teams Group Chat Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable `post_teams_message` to create new group chats by accepting multiple comma-separated recipient names.

**Architecture:** Add a `create_group_chat()` method to `TeamsNavigator` that clicks "New message", adds recipients one-by-one via the people picker, then hands off to the existing compose/send flow. The MCP tool detects comma-separated targets and routes accordingly.

**Tech Stack:** Playwright, asyncio, existing browser automation stack

---

### Task 1: Add Group Chat Selectors to Constants

**Files:**
- Modify: `browser/constants.py`

**Step 1: Add new selectors**

Add these constants after the existing `CHANNEL_NAME_SELECTORS`:

```python
# Selector for the Chat tab in the left sidebar.
CHAT_TAB_SELECTORS = (
    'button[aria-label*="Chat ("]',
    'button[aria-label="Chat"]',
)

# Selectors for the "New message" button in the chat pane.
NEW_CHAT_SELECTORS = (
    'button[aria-label*="New message"]',
    '[data-tid="chat-pane-new-chat"]',
)

# Selectors for the "To:" recipient picker input field.
TO_FIELD_SELECTORS = (
    '[data-tid*="people-picker"] input',
    'input[placeholder*="Enter name"]',
    'input[placeholder*="name, chat, channel"]',
)

# Selector for recipient suggestion items in the people picker dropdown.
RECIPIENT_SUGGESTION_SELECTOR = '[data-tid*="people-picker"] [role="option"]'
```

**Step 2: Commit**

```bash
git add browser/constants.py
git commit -m "feat: add group chat CSS selectors to constants"
```

---

### Task 2: Add `create_group_chat` to TeamsNavigator

**Files:**
- Modify: `browser/navigator.py`
- Test: `tests/test_navigator_group_chat.py`

**Step 1: Write the failing tests**

```python
# tests/test_navigator_group_chat.py
"""Tests for TeamsNavigator.create_group_chat()."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from browser.navigator import TeamsNavigator


def _make_page():
    """Create a mock Playwright page."""
    page = AsyncMock()
    page.keyboard = AsyncMock()
    return page


def _make_locator(count=0, texts=None):
    """Create a mock locator with count and optional inner_text values."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    loc.first = AsyncMock()
    if texts:
        for i, text in enumerate(texts):
            loc.nth = MagicMock(side_effect=lambda idx: _make_nth(texts[idx] if idx < len(texts) else ""))
    loc.first.click = AsyncMock()
    loc.first.fill = AsyncMock()
    return loc


def _make_nth(text):
    m = AsyncMock()
    m.inner_text = AsyncMock(return_value=text)
    m.click = AsyncMock()
    return m


class TestCreateGroupChat:
    @pytest.mark.asyncio
    async def test_returns_error_when_chat_tab_not_found(self):
        page = _make_page()
        page.locator = MagicMock(return_value=_make_locator(count=0))

        nav = TeamsNavigator()
        result = await nav.create_group_chat(page, ["Alice", "Bob"])
        assert result["status"] == "error"
        assert "Chat tab" in result["error"]

    @pytest.mark.asyncio
    async def test_returns_error_when_new_chat_button_not_found(self):
        page = _make_page()
        call_count = 0

        def locator_side_effect(sel):
            nonlocal call_count
            # First calls find chat tab, rest don't find new chat
            if "Chat" in sel and "aria-label" in sel:
                return _make_locator(count=1)
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        result = await nav.create_group_chat(page, ["Alice", "Bob"])
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_returns_error_when_to_field_not_found(self):
        page = _make_page()

        def locator_side_effect(sel):
            if "Chat" in sel:
                return _make_locator(count=1)
            if "New message" in sel or "new-chat" in sel:
                return _make_locator(count=1)
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        result = await nav.create_group_chat(page, ["Alice"])
        assert result["status"] == "error"
        assert "To" in result["error"] or "recipient" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_returns_navigated_on_success(self):
        page = _make_page()
        to_field = _make_locator(count=1)
        suggestion = _make_locator(count=1, texts=["Alice\n(ALICE) Engineer"])
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
            if "placeholder" in sel and "name" in sel.lower():
                return to_field
            # compose selectors
            for cs in ("ckeditor", "textbox", "message", "Reply", "contenteditable"):
                if cs in sel:
                    return compose
            return _make_locator(count=0)

        page.locator = MagicMock(side_effect=locator_side_effect)

        nav = TeamsNavigator()
        with patch.object(nav, "_detect_channel_name", return_value="Alice"):
            with patch("browser.navigator.asyncio.sleep", new_callable=AsyncMock):
                result = await nav.create_group_chat(page, ["Alice"])

        assert result["status"] == "navigated"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_navigator_group_chat.py -v`
Expected: FAIL (create_group_chat doesn't exist yet)

**Step 3: Implement `create_group_chat` in navigator.py**

Add imports for new constants and the method to `TeamsNavigator`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_navigator_group_chat.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add browser/navigator.py tests/test_navigator_group_chat.py
git commit -m "feat: add create_group_chat method to TeamsNavigator"
```

---

### Task 3: Update PlaywrightTeamsPoster to Route Group Targets

**Files:**
- Modify: `browser/teams_poster.py`
- Test: `tests/test_poster_group_chat.py`

**Step 1: Write the failing tests**

Test that `prepare_message` detects list targets and routes to `create_group_chat`.

**Step 2: Run tests to verify they fail**

**Step 3: Update `prepare_message` to accept `Union[str, list[str]]`**

If target is a list, call `self._navigator.create_group_chat(page, target)` instead of `search_and_navigate`.

**Step 4: Run tests to verify they pass**

**Step 5: Commit**

```bash
git add browser/teams_poster.py tests/test_poster_group_chat.py
git commit -m "feat: route list targets to group chat in poster"
```

---

### Task 4: Update MCP Tool to Parse Comma-Separated Targets

**Files:**
- Modify: `mcp_tools/teams_browser_tools.py`

**Step 1: Update `post_teams_message`**

Parse comma-separated target strings into a list when they contain commas. Pass list to poster.

**Step 2: Run existing tests**

Run: `pytest tests/test_teams_browser_tools.py -v`
Expected: PASS (existing behavior unchanged for single targets)

**Step 3: Commit**

```bash
git add mcp_tools/teams_browser_tools.py
git commit -m "feat: parse comma-separated targets for group chat"
```

---

### Task 5: Integration Test and Cleanup

**Step 1: Run full test suite**

Run: `pytest tests/test_navigator_group_chat.py tests/test_poster_group_chat.py tests/test_teams_browser_tools.py -v`

**Step 2: Clean up exploration scripts**

Delete `scripts/teams_group_chat_explore.py` and `scripts/teams_group_chat_explore2.py`.

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore: clean up group chat exploration scripts"
```
