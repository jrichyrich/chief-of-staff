# Playwright Teams Poster Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `post_teams_message` MCP tool that uses Playwright browser automation to post messages to Microsoft Teams channels, with manual user authentication and session caching.

**Architecture:** New `browser/` package with `PlaywrightTeamsPoster` class handles Playwright lifecycle, session persistence via `storageState`, and auth detection. An MCP tool module (`mcp_tools/teams_browser_tools.py`) exposes it as `post_teams_message(channel_url, message)`. A `teams_write` capability is added so agents can declare access.

**Tech Stack:** Python 3.11+, Playwright (async API), pytest, pytest-asyncio

**Design Doc:** `docs/plans/2026-02-23-playwright-teams-poster-design.md`

---

### Task 1: Add Playwright dependency and install browser

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add playwright to dependencies**

In `pyproject.toml`, add `playwright` to the `dependencies` list:

```toml
dependencies = [
    "anthropic>=0.42.0",
    "chromadb>=0.5.0",
    "openpyxl>=3.1.0",
    "pyyaml>=6.0",
    "mcp[cli]>=1.26,<2",
    "pyobjc-framework-EventKit>=10.0; sys_platform == 'darwin'",
    "pypdf>=5.0.0",
    "python-docx>=1.1.0",
    "playwright>=1.40.0",
]
```

Also add `browser*` to `[tool.setuptools.packages.find]`:

```toml
include = ["memory*", "agents*", "documents*", "chief*", "tools*", "utils*", "apple_calendar*", "apple_notifications*", "apple_reminders*", "apple_mail*", "apple_messages*", "connectors*", "okr*", "browser*"]
```

**Step 2: Install dependencies and browser binary**

Run:
```bash
pip install -e ".[dev]"
playwright install chromium
```

Expected: Both commands succeed. Chromium binary (~150MB) downloaded to Playwright cache.

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add playwright dependency for Teams browser automation"
```

---

### Task 2: Create `browser/` package with `PlaywrightTeamsPoster` — session management

**Files:**
- Create: `browser/__init__.py`
- Create: `browser/teams_poster.py`
- Create: `tests/test_teams_poster.py`

**Step 1: Write failing tests for session load/save**

Create `tests/test_teams_poster.py`:

```python
"""Tests for PlaywrightTeamsPoster session management."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from browser.teams_poster import PlaywrightTeamsPoster


@pytest.fixture
def poster(tmp_path):
    """Create a poster with session path in tmp_path."""
    p = PlaywrightTeamsPoster(session_path=tmp_path / "teams_session.json")
    return p


def test_load_session_no_file(poster):
    """Returns None when no session file exists."""
    result = poster._load_session()
    assert result is None


def test_save_and_load_session(poster):
    """Saves storageState and loads it back."""
    state = {"cookies": [{"name": "test", "value": "abc"}], "origins": []}
    poster._save_session_sync(state)

    loaded = poster._load_session()
    assert loaded is not None
    assert loaded["cookies"][0]["name"] == "test"


def test_session_path_creates_parent_dir(tmp_path):
    """Session save creates parent directories if needed."""
    deep_path = tmp_path / "nested" / "dir" / "session.json"
    p = PlaywrightTeamsPoster(session_path=deep_path)
    state = {"cookies": [], "origins": []}
    p._save_session_sync(state)
    assert deep_path.exists()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_teams_poster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'browser'`

**Step 3: Create `browser/__init__.py`**

```python
"""Browser automation package for Teams integration."""
```

**Step 4: Write minimal `browser/teams_poster.py` with session management**

```python
"""Playwright-based Teams channel poster with session caching."""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default session storage location
DEFAULT_SESSION_PATH = Path("data/playwright/teams_session.json")


class PlaywrightTeamsPoster:
    """Posts messages to Teams channels via Playwright browser automation.

    Uses storageState persistence to cache authenticated sessions.
    When sessions expire, opens a headed browser for manual re-authentication.
    """

    AUTH_TIMEOUT_MS = 120_000  # 2 min for user to complete auth
    POST_TIMEOUT_MS = 30_000  # 30s for message posting

    # Login page URL patterns that indicate auth is needed
    LOGIN_PATTERNS = (
        "login.microsoftonline.com",
        ".okta.com",
        "login.microsoft.com",
    )

    # Compose box selectors in order of preference (last verified: 2026-02-23)
    COMPOSE_SELECTORS = (
        '[data-tid="ckeditor-replyConversation"]',
        'div[role="textbox"][aria-label*="message"]',
        'div[role="textbox"][aria-label*="Reply"]',
        'div[contenteditable="true"][data-tid]',
    )

    def __init__(self, session_path: Optional[Path] = None):
        self.session_path = Path(session_path) if session_path else DEFAULT_SESSION_PATH

    def _load_session(self) -> Optional[dict]:
        """Load cached storageState from disk."""
        if not self.session_path.exists():
            return None
        try:
            data = json.loads(self.session_path.read_text())
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load session: %s", e)
            return None

    def _save_session_sync(self, state: dict) -> None:
        """Save storageState to disk (synchronous, for use after async save)."""
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(json.dumps(state, indent=2))
        logger.info("Session saved to %s", self.session_path)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_teams_poster.py -v`
Expected: 3 PASS

**Step 6: Commit**

```bash
git add browser/__init__.py browser/teams_poster.py tests/test_teams_poster.py
git commit -m "feat: add PlaywrightTeamsPoster with session management"
```

---

### Task 3: Add auth detection and browser posting logic

**Files:**
- Modify: `browser/teams_poster.py`
- Modify: `tests/test_teams_poster.py`

**Step 1: Write failing tests for auth detection and posting**

Append to `tests/test_teams_poster.py`:

```python
def test_is_login_page_okta(poster):
    """Detects Okta login page."""
    assert poster._is_login_page("https://chghealthcare.okta.com/login/login.htm") is True


def test_is_login_page_microsoft(poster):
    """Detects Microsoft login page."""
    assert poster._is_login_page("https://login.microsoftonline.com/common/oauth2") is True


def test_is_login_page_teams(poster):
    """Teams URL is not a login page."""
    assert poster._is_login_page("https://teams.microsoft.com/v2/#/channel/123") is False


def test_is_login_page_empty(poster):
    """Empty/blank URL is not a login page."""
    assert poster._is_login_page("about:blank") is False


@pytest.mark.asyncio
async def test_post_message_returns_result(poster):
    """post_message returns a structured result dict."""
    mock_page = AsyncMock()
    mock_page.url = "https://teams.microsoft.com/v2/#/channel/123"
    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.locator = MagicMock()

    # Mock the compose box found via first selector
    mock_locator = AsyncMock()
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.click = AsyncMock()
    mock_locator.fill = AsyncMock()
    mock_page.locator.return_value = mock_locator

    mock_page.keyboard = AsyncMock()
    mock_page.keyboard.press = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

    with patch("browser.teams_poster.async_playwright") as mock_pw:
        mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
        mock_pw.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await poster.post_message(
            "https://teams.microsoft.com/v2/#/channel/123",
            "Hello from Jarvis"
        )

    assert result["status"] == "sent"
    assert "error" not in result


@pytest.mark.asyncio
async def test_post_message_auth_timeout(poster):
    """post_message returns auth_required when login page detected and times out."""
    mock_page = AsyncMock()
    # Simulate staying on login page
    mock_page.url = "https://login.microsoftonline.com/common/oauth2"
    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

    # Use a very short timeout for testing
    poster.AUTH_TIMEOUT_MS = 100

    with patch("browser.teams_poster.async_playwright") as mock_pw:
        mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
        mock_pw.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await poster.post_message(
                "https://teams.microsoft.com/v2/#/channel/123",
                "Hello"
            )

    assert result["status"] == "auth_required"


@pytest.mark.asyncio
async def test_post_message_no_compose_box(poster):
    """post_message returns error when compose box not found."""
    mock_page = AsyncMock()
    mock_page.url = "https://teams.microsoft.com/v2/#/channel/123"
    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()

    # All selectors return 0 count
    mock_locator = AsyncMock()
    mock_locator.count = AsyncMock(return_value=0)
    mock_page.locator = MagicMock(return_value=mock_locator)

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

    with patch("browser.teams_poster.async_playwright") as mock_pw:
        mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
        mock_pw.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await poster.post_message(
            "https://teams.microsoft.com/v2/#/channel/123",
            "Hello"
        )

    assert result["status"] == "error"
    assert "compose" in result["error"].lower()
```

**Step 2: Run tests to verify new tests fail**

Run: `pytest tests/test_teams_poster.py -v`
Expected: New tests FAIL (methods not implemented)

**Step 3: Implement auth detection and posting in `browser/teams_poster.py`**

Add these imports to the top of the file:

```python
import asyncio
from playwright.async_api import async_playwright
```

Add these methods to `PlaywrightTeamsPoster`:

```python
    def _is_login_page(self, url: str) -> bool:
        """Check if the URL is an authentication/login page."""
        url_lower = url.lower()
        return any(pattern in url_lower for pattern in self.LOGIN_PATTERNS)

    async def _wait_for_auth(self, page) -> bool:
        """Wait for user to complete authentication in the browser.

        Returns True if auth completed, False if timed out.
        """
        logger.info("Teams session expired. Please authenticate in the browser window.")
        elapsed = 0
        poll_interval_ms = 1000
        while elapsed < self.AUTH_TIMEOUT_MS:
            await asyncio.sleep(poll_interval_ms / 1000)
            elapsed += poll_interval_ms
            current_url = page.url
            if not self._is_login_page(current_url) and "teams.microsoft.com" in current_url:
                logger.info("Authentication completed.")
                return True
        logger.warning("Authentication timed out after %d ms.", self.AUTH_TIMEOUT_MS)
        return False

    async def _find_compose_box(self, page):
        """Locate the Teams message compose box using fallback selectors.

        Returns the locator if found, None otherwise.
        """
        for selector in self.COMPOSE_SELECTORS:
            locator = page.locator(selector)
            count = await locator.count()
            if count > 0:
                logger.debug("Compose box found with selector: %s", selector)
                return locator
        return None

    async def post_message(self, channel_url: str, message: str) -> dict:
        """Post a message to a Teams channel via browser automation.

        Args:
            channel_url: Full Teams channel URL
            message: Text to post

        Returns:
            dict with 'status' key: 'sent', 'auth_required', or 'error'
        """
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            try:
                # Load cached session if available
                session = self._load_session()
                context_kwargs = {}
                if session:
                    context_kwargs["storage_state"] = session
                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                # Navigate to channel
                await page.goto(channel_url)
                await page.wait_for_load_state("domcontentloaded")

                # Check for auth redirect
                if self._is_login_page(page.url):
                    auth_ok = await self._wait_for_auth(page)
                    if not auth_ok:
                        return {"status": "auth_required", "error": "Authentication timed out. Please try again."}
                    # Save new session after successful auth
                    state = await context.storage_state()
                    self._save_session_sync(state)

                # Find and use compose box
                compose = await self._find_compose_box(page)
                if compose is None:
                    return {
                        "status": "error",
                        "error": "Could not find compose box. Teams UI selectors may need updating.",
                    }

                await compose.click()
                await compose.fill(message)
                await page.keyboard.press("Enter")

                # Save session state after successful post
                state = await context.storage_state()
                self._save_session_sync(state)

                return {"status": "sent", "channel_url": channel_url}

            except Exception as e:
                logger.error("Failed to post Teams message: %s", e)
                return {"status": "error", "error": str(e)}
            finally:
                await browser.close()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_teams_poster.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add browser/teams_poster.py tests/test_teams_poster.py
git commit -m "feat: add auth detection and browser posting to PlaywrightTeamsPoster"
```

---

### Task 4: Create MCP tool module `teams_browser_tools.py`

**Files:**
- Create: `mcp_tools/teams_browser_tools.py`
- Create: `tests/test_teams_browser_tools.py`

**Step 1: Write failing test for the MCP tool**

Create `tests/test_teams_browser_tools.py`:

```python
"""Tests for Teams browser MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import mcp_server  # Trigger registration
from mcp_tools.teams_browser_tools import post_teams_message


@pytest.mark.asyncio
async def test_post_teams_message_success():
    """Tool returns success JSON when message is sent."""
    mock_poster = AsyncMock()
    mock_poster.post_message = AsyncMock(return_value={
        "status": "sent",
        "channel_url": "https://teams.microsoft.com/v2/#/channel/123"
    })

    with patch("mcp_tools.teams_browser_tools._get_poster", return_value=mock_poster):
        result = await post_teams_message(
            channel_url="https://teams.microsoft.com/v2/#/channel/123",
            message="Hello from test"
        )

    parsed = json.loads(result)
    assert parsed["status"] == "sent"


@pytest.mark.asyncio
async def test_post_teams_message_auth_required():
    """Tool returns auth_required when session expired."""
    mock_poster = AsyncMock()
    mock_poster.post_message = AsyncMock(return_value={
        "status": "auth_required",
        "error": "Authentication timed out."
    })

    with patch("mcp_tools.teams_browser_tools._get_poster", return_value=mock_poster):
        result = await post_teams_message(
            channel_url="https://teams.microsoft.com/v2/#/channel/123",
            message="Hello"
        )

    parsed = json.loads(result)
    assert parsed["status"] == "auth_required"


@pytest.mark.asyncio
async def test_post_teams_message_error():
    """Tool returns error JSON on failure."""
    mock_poster = AsyncMock()
    mock_poster.post_message = AsyncMock(return_value={
        "status": "error",
        "error": "Compose box not found"
    })

    with patch("mcp_tools.teams_browser_tools._get_poster", return_value=mock_poster):
        result = await post_teams_message(
            channel_url="https://teams.microsoft.com/v2/#/channel/123",
            message="Hello"
        )

    parsed = json.loads(result)
    assert parsed["status"] == "error"
    assert "compose" in parsed["error"].lower()


@pytest.mark.asyncio
async def test_post_teams_message_validates_url():
    """Tool rejects non-Teams URLs."""
    result = await post_teams_message(
        channel_url="https://example.com/not-teams",
        message="Hello"
    )

    parsed = json.loads(result)
    assert parsed["status"] == "error"
    assert "teams.microsoft.com" in parsed["error"].lower()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_teams_browser_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_tools.teams_browser_tools'`

**Step 3: Write the MCP tool module**

Create `mcp_tools/teams_browser_tools.py`:

```python
"""Teams browser automation tools for MCP server."""

import json
import sys

from browser.teams_poster import PlaywrightTeamsPoster

# Module-level poster instance (lazy, replaceable for tests)
_poster = None


def _get_poster() -> PlaywrightTeamsPoster:
    """Get or create the poster singleton."""
    global _poster
    if _poster is None:
        _poster = PlaywrightTeamsPoster()
    return _poster


def register(mcp, state):
    """Register Teams browser tools with the MCP server."""

    @mcp.tool()
    async def post_teams_message(channel_url: str, message: str) -> str:
        """Post a message to a Microsoft Teams channel via browser automation.

        Opens a Chromium browser window. If the Teams session has expired,
        the browser will show a login page — authenticate manually and the
        session will be cached for future calls.

        Args:
            channel_url: Full Teams channel URL (e.g. https://teams.microsoft.com/l/channel/...)
            message: The message text to post
        """
        # Validate URL
        if "teams.microsoft.com" not in channel_url:
            return json.dumps({
                "status": "error",
                "error": "Invalid URL. Must be a teams.microsoft.com URL.",
            })

        poster = _get_poster()
        result = await poster.post_message(channel_url, message)
        return json.dumps(result)

    # Expose at module level for test imports
    current_module = sys.modules[__name__]
    current_module.post_teams_message = post_teams_message
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_teams_browser_tools.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add mcp_tools/teams_browser_tools.py tests/test_teams_browser_tools.py
git commit -m "feat: add post_teams_message MCP tool"
```

---

### Task 5: Register tool module in `mcp_server.py`

**Files:**
- Modify: `mcp_server.py`

**Step 1: Add import and registration call**

In `mcp_server.py`, add `teams_browser_tools` to the import block:

```python
from mcp_tools import (
    memory_tools,
    document_tools,
    agent_tools,
    lifecycle_tools,
    calendar_tools,
    reminder_tools,
    mail_tools,
    imessage_tools,
    okr_tools,
    webhook_tools,
    skill_tools,
    scheduler_tools,
    proactive_tools,
    channel_tools,
    identity_tools,
    event_rule_tools,
    session_tools,
    resources,
    enrichment,
    teams_browser_tools,
)
```

And add the registration call after the existing ones:

```python
teams_browser_tools.register(mcp, _state)
```

**Step 2: Verify MCP server starts**

Run: `python -c "import mcp_server; print('OK')"`
Expected: `OK` (no import errors)

**Step 3: Commit**

```bash
git add mcp_server.py
git commit -m "feat: register teams_browser_tools in MCP server"
```

---

### Task 6: Add `teams_write` capability to capabilities registry

**Files:**
- Modify: `capabilities/registry.py`
- Create: `tests/test_teams_capability.py`

**Step 1: Write failing test for the new capability**

Create `tests/test_teams_capability.py`:

```python
"""Tests for teams_write capability."""

from capabilities.registry import (
    CAPABILITY_DEFINITIONS,
    TOOL_SCHEMAS,
    get_tools_for_capabilities,
    validate_capabilities,
)


def test_teams_write_capability_defined():
    """teams_write capability exists in definitions."""
    assert "teams_write" in CAPABILITY_DEFINITIONS
    defn = CAPABILITY_DEFINITIONS["teams_write"]
    assert "post_teams_message" in defn.tool_names


def test_teams_write_tool_schema_exists():
    """post_teams_message has a tool schema."""
    assert "post_teams_message" in TOOL_SCHEMAS
    schema = TOOL_SCHEMAS["post_teams_message"]
    assert schema["name"] == "post_teams_message"
    assert "channel_url" in schema["input_schema"]["properties"]
    assert "message" in schema["input_schema"]["properties"]


def test_teams_write_capability_returns_tools():
    """get_tools_for_capabilities returns post_teams_message for teams_write."""
    tools = get_tools_for_capabilities(["teams_write"])
    tool_names = [t["name"] for t in tools]
    assert "post_teams_message" in tool_names


def test_teams_write_validates():
    """teams_write passes capability validation."""
    validated = validate_capabilities(["teams_write"])
    assert "teams_write" in validated
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_teams_capability.py -v`
Expected: FAIL (`teams_write` not defined yet)

**Step 3: Add tool schema and capability definition**

In `capabilities/registry.py`, add to `TOOL_SCHEMAS` dict (after the existing `send_email` entry is a logical place):

```python
    "post_teams_message": {
        "name": "post_teams_message",
        "description": "Post a message to a Microsoft Teams channel via browser automation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel_url": {
                    "type": "string",
                    "description": "Full Teams channel URL (e.g. https://teams.microsoft.com/l/channel/...)",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to post",
                },
            },
            "required": ["channel_url", "message"],
        },
    },
```

And add to `CAPABILITY_DEFINITIONS` dict (after `mail_write`):

```python
    "teams_write": CapabilityDefinition(
        name="teams_write",
        description="Post messages to Microsoft Teams channels via browser automation",
        tool_names=("post_teams_message",),
    ),
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_teams_capability.py -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add capabilities/registry.py tests/test_teams_capability.py
git commit -m "feat: add teams_write capability with post_teams_message tool schema"
```

---

### Task 7: Add humanizer hook support for Teams tool

**Files:**
- Modify: `humanizer/hook.py`
- Modify: `tests/test_humanizer_hook.py`

**Step 1: Write failing test**

Add to `tests/test_humanizer_hook.py`:

```python
def test_humanize_hook_teams_message():
    """Humanizer hook processes post_teams_message tool."""
    context = {
        "tool_name": "post_teams_message",
        "tool_args": {
            "channel_url": "https://teams.microsoft.com/v2/#/channel/123",
            "message": "I wanted to take a moment to share this — it's incredibly important."
        },
    }
    result = humanize_hook(context)
    assert result is not None
    # "incredibly" should be removed (AI vocabulary rule)
    assert "incredibly" not in result["tool_args"]["message"]
    # channel_url should be unchanged
    assert result["tool_args"]["channel_url"] == context["tool_args"]["channel_url"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_humanizer_hook.py::test_humanize_hook_teams_message -v`
Expected: FAIL (post_teams_message not in OUTBOUND_TOOLS)

**Step 3: Update humanizer hook**

In `humanizer/hook.py`, add `"post_teams_message"` to `OUTBOUND_TOOLS`:

```python
OUTBOUND_TOOLS = frozenset({
    "send_email",
    "reply_to_email",
    "send_imessage_reply",
    "post_teams_message",
})
```

And add `"message"` to `TEXT_FIELDS`:

```python
TEXT_FIELDS = ("body", "subject", "message")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_humanizer_hook.py -v`
Expected: All tests PASS (new + existing)

**Step 5: Commit**

```bash
git add humanizer/hook.py tests/test_humanizer_hook.py
git commit -m "feat: add post_teams_message to humanizer hook"
```

---

### Task 8: Add `data/playwright/` to `.gitignore`

**Files:**
- Modify: `.gitignore`

**Step 1: Add playwright session dir to gitignore**

The existing `.gitignore` already has `data/*` with `!data/.gitkeep`, so `data/playwright/` is already ignored. Verify this is the case.

If `data/*` is present with `!data/.gitkeep`, no change needed. If not, add:

```
# Playwright session state (contains auth tokens)
data/playwright/
```

**Step 2: Verify**

Run: `git status` — confirm `data/playwright/` does not appear in untracked.

**Step 3: Commit (only if changes were needed)**

```bash
git add .gitignore
git commit -m "chore: ensure playwright session dir is gitignored"
```

---

### Task 9: Run full test suite

**Step 1: Run all tests**

Run: `pytest --tb=short`
Expected: All existing tests pass + new tests pass. No regressions.

**Step 2: Run new tests specifically**

Run:
```bash
pytest tests/test_teams_poster.py tests/test_teams_browser_tools.py tests/test_teams_capability.py tests/test_humanizer_hook.py -v
```
Expected: All PASS

---

### Task 10: Manual smoke test (requires browser)

This task is manual — not automatable in CI.

**Step 1: Start the MCP server**

Run: `jarvis-mcp`
Expected: Server starts without errors.

**Step 2: Test with a real Teams channel**

From Claude Code or a test script, call:
```python
post_teams_message(
    channel_url="<a real Teams channel URL>",
    message="Test message from Jarvis"
)
```

Expected:
- Browser window opens
- If no cached session: redirected to Okta login. Complete login manually.
- After auth: navigates to channel, posts message
- Session saved to `data/playwright/teams_session.json`
- Second call reuses session (no login required)
