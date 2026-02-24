# Persistent Teams Browser Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the open-close-per-message Teams browser with a persistent Chromium instance that Jarvis connects to on demand via CDP, navigates to targets by name using Teams search, and posts after user confirmation.

**Architecture:** Detached Chromium subprocess with `--remote-debugging-port=9222`. `TeamsBrowserManager` handles launch/connect/health. `TeamsNavigator` uses Teams search bar for name-based targeting. Two-phase confirm flow preserved. State file tracks PID + port.

**Tech Stack:** Playwright (async_api + connect_over_cdp), subprocess (detached launch), urllib.request (CDP health checks — stdlib, no new dependency)

---

### Task 1: TeamsBrowserManager — Launch and Health Check

Create the browser manager that launches Chromium as a detached process and checks if it's running.

**Files:**
- Create: `browser/manager.py`
- Create: `tests/test_teams_browser_manager.py`

**Step 1: Write the failing tests**

```python
# tests/test_teams_browser_manager.py
"""Tests for browser.manager — TeamsBrowserManager."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from browser.manager import TeamsBrowserManager


@pytest.fixture
def manager(tmp_path):
    """Manager with isolated state/profile dirs."""
    return TeamsBrowserManager(
        state_path=tmp_path / "browser.json",
        profile_dir=tmp_path / "profile",
    )


class TestStateFile:
    def test_load_state_no_file(self, manager):
        """Returns None when state file doesn't exist."""
        assert manager._load_state() is None

    def test_save_and_load_state(self, manager):
        """Round-trip: save then load."""
        state = {"pid": 12345, "cdp_port": 9222}
        manager._save_state(state)
        loaded = manager._load_state()
        assert loaded == state

    def test_load_state_corrupt_json(self, manager):
        """Returns None on invalid JSON."""
        manager.state_path.parent.mkdir(parents=True, exist_ok=True)
        manager.state_path.write_text("not json{{{")
        assert manager._load_state() is None


class TestHealthCheck:
    def test_is_alive_responds_200(self, manager):
        """Returns True when CDP endpoint responds."""
        with patch("browser.manager.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b'{"Browser":"Chrome"}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            assert manager.is_alive() is True

    def test_is_alive_connection_refused(self, manager):
        """Returns False when CDP endpoint is unreachable."""
        with patch("browser.manager.urlopen", side_effect=OSError("Connection refused")):
            assert manager.is_alive() is False


class TestFindChromium:
    def test_find_chromium_returns_path(self, manager):
        """Returns a path string when Chromium is installed."""
        path = manager._find_chromium_path()
        # Playwright must be installed for tests to run
        assert path is not None
        assert Path(path).exists()
```

**Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest tests/test_teams_browser_manager.py -v`
Expected: FAIL with "No module named 'browser.manager'"

**Step 3: Write minimal implementation**

```python
# browser/manager.py
"""Persistent Chromium browser manager using CDP.

Launches Chromium as a detached subprocess with --remote-debugging-port.
Reconnects via CDP for each tool call. The browser survives MCP server
restarts.
"""

import json
import logging
import os
import platform
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

try:
    from config import DATA_DIR
except ImportError:
    DATA_DIR = Path("data")

logger = logging.getLogger(__name__)

DEFAULT_CDP_PORT = 9222
DEFAULT_STATE_PATH = DATA_DIR / "playwright" / "browser.json"
DEFAULT_PROFILE_DIR = DATA_DIR / "playwright" / "profile"


class TeamsBrowserManager:
    """Manage a persistent Chromium browser process.

    Launch with :meth:`launch`, check status with :meth:`is_alive`,
    connect via :meth:`connect`, and stop with :meth:`close`.
    """

    def __init__(
        self,
        cdp_port: int = DEFAULT_CDP_PORT,
        state_path: Optional[Path] = None,
        profile_dir: Optional[Path] = None,
    ):
        self.cdp_port = cdp_port
        self.state_path = state_path or DEFAULT_STATE_PATH
        self.profile_dir = profile_dir or DEFAULT_PROFILE_DIR

    # ── State persistence ───────────────────────────────────

    def _load_state(self) -> Optional[dict]:
        """Load browser state (PID, port) from disk."""
        try:
            return json.loads(self.state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _save_state(self, state: dict) -> None:
        """Persist browser state to disk."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2))

    def _clear_state(self) -> None:
        """Remove the state file."""
        try:
            self.state_path.unlink()
        except FileNotFoundError:
            pass

    # ── Health check ────────────────────────────────────────

    def is_alive(self) -> bool:
        """Check if the CDP endpoint is responding."""
        try:
            url = f"http://localhost:{self.cdp_port}/json/version"
            with urlopen(url, timeout=2) as resp:
                return resp.status == 200
        except (URLError, OSError, TimeoutError):
            return False

    # ── Chromium path discovery ─────────────────────────────

    @staticmethod
    def _find_chromium_path() -> Optional[str]:
        """Find the Playwright-bundled Chromium executable."""
        if platform.system() == "Darwin":
            cache = Path.home() / "Library" / "Caches" / "ms-playwright"
        else:
            cache = Path.home() / ".cache" / "ms-playwright"

        for chromium_dir in sorted(cache.glob("chromium-*"), reverse=True):
            if platform.system() == "Darwin":
                candidate = (
                    chromium_dir / "chrome-mac" / "Chromium.app"
                    / "Contents" / "MacOS" / "Chromium"
                )
            else:
                candidate = chromium_dir / "chrome-linux" / "chrome"
            if candidate.exists():
                return str(candidate)
        return None

    # ── Launch ──────────────────────────────────────────────

    def launch(self) -> dict:
        """Launch Chromium as a detached subprocess.

        Returns a status dict with ``pid`` and ``cdp_port``.
        If already running, returns current status.
        """
        if self.is_alive():
            state = self._load_state() or {}
            return {"status": "already_running", **state}

        chromium = self._find_chromium_path()
        if chromium is None:
            return {
                "status": "error",
                "error": "Chromium not found. Run: playwright install chromium",
            }

        self.profile_dir.mkdir(parents=True, exist_ok=True)

        proc = subprocess.Popen(
            [
                chromium,
                f"--remote-debugging-port={self.cdp_port}",
                f"--user-data-dir={self.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait for CDP to become available
        for _ in range(30):
            if self.is_alive():
                state = {
                    "pid": proc.pid,
                    "cdp_port": self.cdp_port,
                }
                self._save_state(state)
                logger.info("Chromium launched (pid=%d, port=%d)", proc.pid, self.cdp_port)
                return {"status": "launched", **state}
            time.sleep(0.5)

        return {
            "status": "error",
            "error": f"Chromium started (pid={proc.pid}) but CDP not responding on port {self.cdp_port}",
        }

    # ── Close ───────────────────────────────────────────────

    def close(self) -> dict:
        """Stop the Chromium process."""
        state = self._load_state()
        if state and "pid" in state:
            try:
                os.kill(state["pid"], signal.SIGTERM)
                logger.info("Sent SIGTERM to pid %d", state["pid"])
            except ProcessLookupError:
                pass
        self._clear_state()

        # Also check if something is still listening on the port
        if self.is_alive():
            return {"status": "error", "error": "Browser still running after SIGTERM"}
        return {"status": "closed"}
```

**Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/test_teams_browser_manager.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add browser/manager.py tests/test_teams_browser_manager.py
git commit -m "feat: add TeamsBrowserManager for persistent Chromium via CDP"
```

---

### Task 2: TeamsBrowserManager — CDP Connect

Add the async `connect()` method that returns a Playwright browser object connected via CDP.

**Files:**
- Modify: `browser/manager.py`
- Modify: `tests/test_teams_browser_manager.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_teams_browser_manager.py

@pytest.mark.asyncio
class TestConnect:
    async def test_connect_returns_browser(self, manager):
        """connect() returns (pw, browser) tuple via CDP."""
        mock_browser = AsyncMock()
        mock_browser.contexts = [MagicMock()]
        mock_pw = AsyncMock()
        mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

        with patch("browser.manager.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            # Pretend CDP is alive
            with patch.object(manager, "is_alive", return_value=True):
                pw, browser = await manager.connect()

        assert browser is mock_browser
        mock_pw.chromium.connect_over_cdp.assert_awaited_once()

    async def test_connect_not_running_raises(self, manager):
        """connect() raises RuntimeError when browser is not running."""
        with patch.object(manager, "is_alive", return_value=False):
            with pytest.raises(RuntimeError, match="not running"):
                await manager.connect()
```

Add these imports to the test file:
```python
from unittest.mock import AsyncMock
```

**Step 2: Run test to verify it fails**

Run: `python3.11 -m pytest tests/test_teams_browser_manager.py::TestConnect -v`
Expected: FAIL with "AttributeError: 'TeamsBrowserManager' object has no attribute 'connect'"

**Step 3: Write minimal implementation**

Add to `browser/manager.py`:

```python
# Add import at top
try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

# Add method to TeamsBrowserManager class:

    async def connect(self):
        """Connect to running Chromium via CDP.

        Returns ``(playwright, browser)`` tuple. Caller must call
        ``await pw.stop()`` when done (this disconnects but does NOT
        kill the browser).

        Raises ``RuntimeError`` if the browser is not running.
        """
        if async_playwright is None:
            raise RuntimeError("playwright is not installed")
        if not self.is_alive():
            raise RuntimeError(
                "Browser is not running. Call open_teams_browser first."
            )
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(
            f"http://localhost:{self.cdp_port}",
            timeout=10_000,
        )
        return pw, browser
```

**Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/test_teams_browser_manager.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add browser/manager.py tests/test_teams_browser_manager.py
git commit -m "feat: add CDP connect method to TeamsBrowserManager"
```

---

### Task 3: DOM Exploration Script for Search Bar

Create a script that discovers the Teams search bar selectors. This is a manual step — run the script, observe output, and record which selectors work.

**Files:**
- Create: `scripts/teams_search_explore.py`

**Step 1: Write the exploration script**

```python
# scripts/teams_search_explore.py
"""Discover Teams search bar selectors.

Opens Teams with cached session, then periodically checks candidate
selectors for the search bar / command bar. Prints which selectors
match so we can use them in TeamsNavigator.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.manager import TeamsBrowserManager


SEARCH_SELECTORS = [
    # Known data-tid patterns
    '[data-tid="search-input"]',
    '[data-tid="app-search-input"]',
    '[data-tid="search-box"]',
    '[data-tid="unified-search-input"]',
    # aria-label patterns
    'input[aria-label*="Search"]',
    'input[aria-label*="search"]',
    '[aria-label*="Search"]',
    # role patterns
    'input[role="search"]',
    'input[role="combobox"][aria-label*="Search"]',
    # Command bar / shortcut
    '[data-tid="command-bar"]',
    '[data-tid*="search"]',
    # Broader patterns
    'input[type="text"][placeholder*="Search"]',
    'input[placeholder*="search"]',
    'input[placeholder*="Search"]',
]


async def main():
    mgr = TeamsBrowserManager()

    if not mgr.is_alive():
        print("Browser not running. Launching...")
        result = mgr.launch()
        print(f"Launch: {result}")
        if result["status"] == "error":
            sys.exit(1)

    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(
        f"http://localhost:{mgr.cdp_port}", timeout=10_000
    )

    ctx = browser.contexts[0]
    if not ctx.pages:
        page = await ctx.new_page()
        await page.goto("https://teams.cloud.microsoft/")
    else:
        page = ctx.pages[0]
        if "teams" not in page.url:
            await page.goto("https://teams.cloud.microsoft/")

    print(f"URL: {page.url}")
    print("Waiting 10s for Teams to load...")
    await asyncio.sleep(10)

    print("\nChecking search selectors every 5s for 2 minutes...")
    print("=" * 60)

    for cycle in range(24):
        await asyncio.sleep(5)
        print(f"\n--- Cycle {cycle + 1} ---")
        for sel in SEARCH_SELECTORS:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                if count > 0:
                    print(f"  FOUND ({count}): {sel}")
            except Exception as e:
                print(f"  ERROR: {sel} -> {e}")

    await pw.stop()
    print("\nDone. Browser still running.")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Run the exploration script**

Run: `python3.11 scripts/teams_search_explore.py`

Observe which selectors match. Record the working selectors — these will be used in Task 4 as `SEARCH_SELECTORS` in `browser/navigator.py`.

**Step 3: Commit**

```bash
git add scripts/teams_search_explore.py
git commit -m "feat: add Teams search bar DOM exploration script"
```

---

### Task 4: TeamsNavigator — Search and Navigate

Create the navigator that uses the Teams search bar to find channels/people by name.

**Files:**
- Create: `browser/navigator.py`
- Create: `tests/test_teams_navigator.py`

**Step 1: Write the failing tests**

```python
# tests/test_teams_navigator.py
"""Tests for browser.navigator — TeamsNavigator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from browser.navigator import TeamsNavigator


def _make_locator(count=1, texts=None):
    """Mock locator with count and optional text content."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    loc.click = AsyncMock()
    loc.fill = AsyncMock()
    loc.press_sequentially = AsyncMock()
    if texts:
        first = AsyncMock()
        first.inner_text = AsyncMock(return_value=texts[0])
        loc.first = first
    return loc


@pytest.mark.asyncio
class TestSearchAndNavigate:
    async def test_search_finds_target(self):
        """Happy path: search bar found, target typed, result clicked."""
        page = AsyncMock()
        compose_loc = _make_locator(count=1)
        search_loc = _make_locator(count=1)
        result_loc = _make_locator(count=1)
        empty_loc = _make_locator(count=0)
        channel_loc = _make_locator(count=1, texts=["Engineering"])

        def locator_effect(selector):
            from browser.navigator import SEARCH_SELECTORS
            from browser.teams_poster import COMPOSE_SELECTORS, CHANNEL_NAME_SELECTORS
            if selector in SEARCH_SELECTORS:
                return search_loc
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

    async def test_search_no_search_bar(self):
        """Error when search bar not found."""
        page = AsyncMock()
        empty_loc = _make_locator(count=0)
        page.locator = MagicMock(return_value=empty_loc)

        nav = TeamsNavigator()
        result = await nav.search_and_navigate(page, "Engineering")

        assert result["status"] == "error"
        assert "search bar" in result["error"].lower()
```

**Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest tests/test_teams_navigator.py -v`
Expected: FAIL with "No module named 'browser.navigator'"

**Step 3: Write minimal implementation**

```python
# browser/navigator.py
"""Teams in-app navigation via the search bar."""

import asyncio
import logging
from typing import Tuple

from browser.teams_poster import (
    COMPOSE_SELECTORS,
    CHANNEL_NAME_SELECTORS,
    POST_TIMEOUT_MS,
)

logger = logging.getLogger(__name__)

# CSS selectors for the Teams search bar, tried in order.
# Populated after running scripts/teams_search_explore.py.
# Update these with the actual working selectors found during DOM exploration.
SEARCH_SELECTORS = (
    'input[aria-label*="Search"]',
    '[data-tid="search-input"]',
    '[data-tid="app-search-input"]',
    '[data-tid*="search"] input',
)

# Selector for search result items in the dropdown.
SEARCH_RESULT_SELECTORS = (
    '[data-tid="search-result"]',
    '[data-tid*="suggestion"]',
    'li[role="option"]',
    'div[role="option"]',
    'li[role="listitem"]',
)


class TeamsNavigator:
    """Navigate within the Teams SPA using the search bar."""

    @staticmethod
    async def _find_element(page, selectors: Tuple[str, ...], timeout_ms: int = 10_000):
        """Try each selector with retries. Returns first matching locator or None."""
        elapsed = 0
        interval_ms = 1_000
        while elapsed < timeout_ms:
            for selector in selectors:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    return locator
            await asyncio.sleep(interval_ms / 1_000)
            elapsed += interval_ms
        return None

    @staticmethod
    async def _detect_channel_name(page) -> str:
        """Detect active channel/conversation name from DOM."""
        for selector in CHANNEL_NAME_SELECTORS:
            try:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    text = await locator.first.inner_text()
                    text = text.strip()
                    if text:
                        return text
            except Exception:
                continue

        try:
            title = await page.title()
            if title and title not in ("Microsoft Teams", ""):
                for suffix in (" | Microsoft Teams", " - Microsoft Teams"):
                    if title.endswith(suffix):
                        title = title[: -len(suffix)]
                return title.strip() or "(unknown)"
        except Exception:
            pass

        return "(unknown)"

    async def search_and_navigate(self, page, target: str) -> dict:
        """Search for *target* in Teams and navigate to it.

        Returns a dict with:
        - ``"status": "navigated"`` and ``"detected_channel"`` on success
        - ``"status": "error"`` with ``"error"`` detail on failure
        """
        # Find the search bar
        search_bar = await self._find_element(page, SEARCH_SELECTORS, timeout_ms=10_000)
        if search_bar is None:
            return {
                "status": "error",
                "error": "Could not find Teams search bar. The UI may have changed.",
            }

        # Click search bar and type the target name
        await search_bar.click()
        await asyncio.sleep(0.5)
        await page.keyboard.type(target, delay=50)
        await asyncio.sleep(2)  # Wait for search results to populate

        # Find and click the first search result
        result_item = await self._find_element(
            page, SEARCH_RESULT_SELECTORS, timeout_ms=10_000
        )
        if result_item is None:
            # Press Escape to close search
            await page.keyboard.press("Escape")
            return {
                "status": "error",
                "error": f"No search results found for '{target}'.",
            }

        await result_item.first.click()
        await asyncio.sleep(2)  # Wait for navigation

        # Wait for compose box to confirm we're in a conversation
        compose = await self._find_element(
            page, COMPOSE_SELECTORS, timeout_ms=POST_TIMEOUT_MS
        )
        if compose is None:
            return {
                "status": "error",
                "error": (
                    f"Navigated to '{target}' but compose box not found. "
                    "May have landed on a non-conversation page."
                ),
            }

        detected = await self._detect_channel_name(page)
        return {
            "status": "navigated",
            "detected_channel": detected,
        }
```

**Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/test_teams_navigator.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add browser/navigator.py tests/test_teams_navigator.py
git commit -m "feat: add TeamsNavigator for search-based channel navigation"
```

---

### Task 5: Refactor PlaywrightTeamsPoster

Rewrite `PlaywrightTeamsPoster` to use `TeamsBrowserManager` + `TeamsNavigator` instead of launching/closing its own browser.

**Files:**
- Modify: `browser/teams_poster.py`
- Modify: `tests/test_teams_poster.py`

**Step 1: Write the failing tests**

Replace the existing test structure. The new poster:
- Connects to a running browser (no more launch)
- Uses navigator to search by name (no more URL)
- Keeps the two-phase prepare/confirm/cancel flow

```python
# tests/test_teams_poster.py — rewritten
"""Tests for browser.teams_poster — PlaywrightTeamsPoster."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser.teams_poster import PlaywrightTeamsPoster


@pytest.fixture
def poster():
    return PlaywrightTeamsPoster()


def _make_mock_page():
    page = AsyncMock()
    page.url = "https://teams.cloud.microsoft/"
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.title = AsyncMock(return_value="General | Microsoft Teams")
    return page


def _make_compose_locator(count=1):
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    loc.click = AsyncMock()
    loc.fill = AsyncMock()
    return loc


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

        from browser.teams_poster import COMPOSE_SELECTORS
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
            "error": "No results found for 'NonExistent'",
        })

        poster._manager = mock_mgr
        poster._navigator = mock_nav

        result = await poster.prepare_message("NonExistent", "Hello")

        assert result["status"] == "error"
        assert "NonExistent" in result["error"]


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

        from browser.teams_poster import CHANNEL_NAME_SELECTORS
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
        compose.fill.assert_awaited_once_with("Hello team")
        page.keyboard.press.assert_awaited_once_with("Enter")

    async def test_send_without_prepare(self, poster):
        result = await poster.send_prepared_message()
        assert result["status"] == "error"
        assert "No pending message" in result["error"]


@pytest.mark.asyncio
class TestCancelPreparedMessage:
    async def test_cancel_after_prepare(self, poster):
        poster._pw = AsyncMock()
        poster._page = AsyncMock()
        poster._compose = AsyncMock()
        poster._pending_message = "test"

        result = await poster.cancel_prepared_message()
        assert result["status"] == "cancelled"
        assert not poster.has_pending_message

    async def test_cancel_without_prepare(self, poster):
        result = await poster.cancel_prepared_message()
        assert result["status"] == "error"
```

**Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest tests/test_teams_poster.py -v`
Expected: FAIL (poster still uses old API)

**Step 3: Rewrite implementation**

Rewrite `browser/teams_poster.py`:

```python
# browser/teams_poster.py
"""Playwright-based Microsoft Teams message poster.

Uses a persistent browser managed by TeamsBrowserManager and navigates
to channels/people by name via TeamsNavigator.

Two-phase posting flow:
1. ``prepare_message`` — connects to running browser, navigates to
   target, detects active channel, returns confirmation info.
2. ``send_prepared_message`` — types the message and presses Enter.
3. ``cancel_prepared_message`` — disconnects without sending.
"""

import asyncio
import logging
from typing import Optional

from browser.manager import TeamsBrowserManager
from browser.navigator import TeamsNavigator

logger = logging.getLogger(__name__)

# Timeout (ms) for waiting for user to complete SSO authentication.
AUTH_TIMEOUT_MS = 120_000

# Timeout (ms) for finding the compose box.
POST_TIMEOUT_MS = 30_000

# URL substrings that indicate an SSO / login page.
LOGIN_PATTERNS = (
    "login.microsoftonline.com",
    ".okta.com",
    "login.microsoft.com",
    "login.srf",
)

# URL substrings that indicate we've landed on Teams.
TEAMS_PATTERNS = (
    "teams.microsoft.com",
    "teams.cloud.microsoft",
)

# CSS selectors to locate the Teams compose / reply box, tried in order.
COMPOSE_SELECTORS = (
    '[data-tid="ckeditor-replyConversation"]',
    'div[role="textbox"][aria-label*="message"]',
    'div[role="textbox"][aria-label*="Reply"]',
    'div[contenteditable="true"][data-tid]',
)

# CSS selectors to detect the active channel / conversation name.
CHANNEL_NAME_SELECTORS = (
    '[data-tid="chat-header-title"]',
    'h1[data-tid]',
    'h2[data-tid]',
    'span[data-tid="chat-header-channel-name"]',
    '[data-tid="thread-header"] h2',
    '[data-tid="channel-header"] span',
)


class PlaywrightTeamsPoster:
    """Post messages to Microsoft Teams via a persistent browser.

    Two-phase flow:
    1. :meth:`prepare_message` connects to the running browser,
       navigates to the target, and returns confirmation info.
    2. :meth:`send_prepared_message` types and sends the message.
    3. :meth:`cancel_prepared_message` disconnects without sending.
    """

    def __init__(
        self,
        manager: Optional[TeamsBrowserManager] = None,
        navigator: Optional[TeamsNavigator] = None,
    ):
        self._manager = manager or TeamsBrowserManager()
        self._navigator = navigator or TeamsNavigator()
        # Pending state for two-phase posting
        self._pw = None
        self._page = None
        self._compose = None
        self._pending_message: Optional[str] = None

    @property
    def has_pending_message(self) -> bool:
        return self._pending_message is not None and self._page is not None

    async def _disconnect(self) -> None:
        """Disconnect from browser (does NOT close the browser)."""
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._pw = None
        self._page = None
        self._compose = None
        self._pending_message = None

    @staticmethod
    async def _find_compose_box(page, timeout_ms: int = POST_TIMEOUT_MS):
        """Try each selector in COMPOSE_SELECTORS with retries."""
        elapsed = 0
        interval_ms = 2_000
        while elapsed < timeout_ms:
            for selector in COMPOSE_SELECTORS:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    return locator
            await asyncio.sleep(interval_ms / 1_000)
            elapsed += interval_ms
        return None

    @staticmethod
    async def _detect_channel_name(page) -> str:
        """Detect active channel/conversation name from DOM."""
        for selector in CHANNEL_NAME_SELECTORS:
            try:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    text = await locator.first.inner_text()
                    text = text.strip()
                    if text:
                        return text
            except Exception:
                continue
        try:
            title = await page.title()
            if title and title not in ("Microsoft Teams", ""):
                for suffix in (" | Microsoft Teams", " - Microsoft Teams"):
                    if title.endswith(suffix):
                        title = title[: -len(suffix)]
                return title.strip() or "(unknown)"
        except Exception:
            pass
        return "(unknown)"

    @staticmethod
    def _is_login_page(url: str) -> bool:
        return any(p in url for p in LOGIN_PATTERNS)

    @staticmethod
    def _is_teams_page(url: str) -> bool:
        return any(p in url for p in TEAMS_PATTERNS)

    async def prepare_message(self, target: str, message: str) -> dict:
        """Phase 1: connect to browser, navigate to target, return confirmation.

        Args:
            target: Channel name or person name to search for in Teams.
            message: The message text to post.
        """
        if not self._manager.is_alive():
            return {
                "status": "error",
                "error": "Browser is not running. Call open_teams_browser first.",
            }

        # Clean up previous pending state
        if self.has_pending_message:
            await self._disconnect()

        try:
            self._pw, browser = await self._manager.connect()
            ctx = browser.contexts[0]
            self._page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            # Navigate to target via search
            nav_result = await self._navigator.search_and_navigate(self._page, target)
            if nav_result["status"] != "navigated":
                await self._disconnect()
                return nav_result

            # Find compose box
            self._compose = await self._find_compose_box(self._page)
            if self._compose is None:
                await self._disconnect()
                return {
                    "status": "error",
                    "error": "Could not find compose box after navigation.",
                }

            detected = nav_result["detected_channel"]
            self._pending_message = message

            return {
                "status": "confirm_required",
                "detected_channel": detected,
                "message": message,
                "target": target,
            }

        except Exception as exc:
            logger.exception("Failed to prepare Teams message")
            await self._disconnect()
            return {"status": "error", "error": str(exc)}

    async def send_prepared_message(self) -> dict:
        """Phase 2: type and send the pending message."""
        if not self.has_pending_message:
            return {
                "status": "error",
                "error": "No pending message. Call prepare_message first.",
            }
        try:
            detected = await self._detect_channel_name(self._page)
            await self._compose.click()
            await self._compose.fill(self._pending_message)
            await self._page.keyboard.press("Enter")
            await self._page.wait_for_timeout(1_000)

            result = {
                "status": "sent",
                "detected_channel": detected,
                "message": self._pending_message,
            }
        except Exception as exc:
            logger.exception("Failed to send prepared Teams message")
            result = {"status": "error", "error": str(exc)}
        finally:
            await self._disconnect()
        return result

    async def cancel_prepared_message(self) -> dict:
        """Cancel and disconnect without sending."""
        had_pending = self.has_pending_message
        await self._disconnect()
        if had_pending:
            return {"status": "cancelled"}
        return {"status": "error", "error": "No pending message to cancel."}
```

**Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/test_teams_poster.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add browser/teams_poster.py tests/test_teams_poster.py
git commit -m "refactor: rewrite PlaywrightTeamsPoster to use persistent browser + navigator"
```

---

### Task 6: Update MCP Tools

Replace URL-based `post_teams_message` with name-based targeting, add `open_teams_browser` and `close_teams_browser` tools.

**Files:**
- Modify: `mcp_tools/teams_browser_tools.py`
- Modify: `tests/test_teams_browser_tools.py`

**Step 1: Write the failing tests**

```python
# tests/test_teams_browser_tools.py — rewritten
"""Tests for the Teams browser automation MCP tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mcp_server  # noqa: F401
from mcp_tools import teams_browser_tools

teams_browser_tools.register(mcp_server.mcp, mcp_server._state)
from mcp_tools.teams_browser_tools import (
    cancel_teams_post,
    close_teams_browser,
    confirm_teams_post,
    open_teams_browser,
    post_teams_message,
)


@pytest.mark.asyncio
class TestOpenTeamsBrowser:
    async def test_open_launches_browser(self):
        mock_mgr = MagicMock()
        mock_mgr.launch.return_value = {"status": "launched", "pid": 123, "cdp_port": 9222}
        mock_mgr.is_alive.return_value = True

        # Mock _wait_for_teams to return immediately
        with patch.object(teams_browser_tools, "_get_manager", return_value=mock_mgr):
            with patch.object(teams_browser_tools, "_wait_for_teams", new_callable=AsyncMock, return_value=True):
                raw = await open_teams_browser()

        result = json.loads(raw)
        assert result["status"] in ("launched", "running")

    async def test_open_already_running(self):
        mock_mgr = MagicMock()
        mock_mgr.launch.return_value = {"status": "already_running", "pid": 123}

        with patch.object(teams_browser_tools, "_get_manager", return_value=mock_mgr):
            with patch.object(teams_browser_tools, "_wait_for_teams", new_callable=AsyncMock, return_value=True):
                raw = await open_teams_browser()

        result = json.loads(raw)
        assert result["status"] in ("already_running", "running")


@pytest.mark.asyncio
class TestCloseTeamsBrowser:
    async def test_close_stops_browser(self):
        mock_mgr = MagicMock()
        mock_mgr.close.return_value = {"status": "closed"}

        with patch.object(teams_browser_tools, "_get_manager", return_value=mock_mgr):
            raw = await close_teams_browser()

        result = json.loads(raw)
        assert result["status"] == "closed"


@pytest.mark.asyncio
class TestPostTeamsMessage:
    async def test_post_returns_confirm(self):
        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "confirm_required",
            "detected_channel": "Engineering",
            "message": "Hello",
            "target": "Engineering",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await post_teams_message(target="Engineering", message="Hello")

        result = json.loads(raw)
        assert result["status"] == "confirm_required"
        assert result["detected_channel"] == "Engineering"
        mock_poster.prepare_message.assert_awaited_once_with("Engineering", "Hello")

    async def test_post_browser_not_running(self):
        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "error",
            "error": "Browser is not running.",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await post_teams_message(target="Engineering", message="Hello")

        result = json.loads(raw)
        assert result["status"] == "error"


@pytest.mark.asyncio
class TestConfirmTeamsPost:
    async def test_confirm_sends(self):
        mock_poster = AsyncMock()
        mock_poster.send_prepared_message.return_value = {
            "status": "sent",
            "detected_channel": "Engineering",
            "message": "Hello",
        }

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await confirm_teams_post()

        result = json.loads(raw)
        assert result["status"] == "sent"


@pytest.mark.asyncio
class TestCancelTeamsPost:
    async def test_cancel_works(self):
        mock_poster = AsyncMock()
        mock_poster.cancel_prepared_message.return_value = {"status": "cancelled"}

        with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
            raw = await cancel_teams_post()

        result = json.loads(raw)
        assert result["status"] == "cancelled"
```

**Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest tests/test_teams_browser_tools.py -v`
Expected: FAIL

**Step 3: Rewrite implementation**

```python
# mcp_tools/teams_browser_tools.py
"""Teams browser automation tools for MCP server.

Five tools:
1. ``open_teams_browser`` — launch persistent Chromium, navigate to Teams
2. ``post_teams_message`` — search for target by name, return confirmation
3. ``confirm_teams_post`` — send the prepared message
4. ``cancel_teams_post`` — cancel without sending
5. ``close_teams_browser`` — kill the browser process
"""

import asyncio
import json
import logging
import sys

logger = logging.getLogger(__name__)

_manager = None
_poster = None


def _get_manager():
    global _manager
    if _manager is None:
        from browser.manager import TeamsBrowserManager
        _manager = TeamsBrowserManager()
    return _manager


def _get_poster():
    global _poster
    if _poster is None:
        from browser.teams_poster import PlaywrightTeamsPoster
        _poster = PlaywrightTeamsPoster(manager=_get_manager())
    return _poster


async def _wait_for_teams(manager, timeout_s: int = 30) -> bool:
    """After launch, navigate to Teams and wait for it to load."""
    try:
        pw, browser = await manager.connect()
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        if "teams" not in page.url.lower():
            await page.goto("https://teams.cloud.microsoft/",
                            wait_until="domcontentloaded", timeout=30_000)

        await pw.stop()
        return True
    except Exception as exc:
        logger.warning("Failed to navigate to Teams: %s", exc)
        return False


def register(mcp, state):
    """Register Teams browser tools with the MCP server."""

    @mcp.tool()
    async def open_teams_browser() -> str:
        """Launch a persistent Chromium browser and navigate to Teams.

        The browser stays open in the background. If the Teams session
        has expired, authenticate manually in the browser window — the
        session is cached in the browser profile for future calls.

        Call this before using post_teams_message. Idempotent — returns
        current status if the browser is already running.
        """
        mgr = _get_manager()
        result = mgr.launch()

        if result["status"] in ("launched", "already_running"):
            await _wait_for_teams(mgr)
            result["status"] = "running"

        return json.dumps(result)

    @mcp.tool()
    async def post_teams_message(target: str, message: str) -> str:
        """Prepare a message for posting to a Teams channel or person.

        Connects to the running browser, uses the Teams search bar to
        find the target by name, navigates there, and returns
        confirmation info. Does NOT send the message yet.

        After this returns ``"confirm_required"``, call
        ``confirm_teams_post`` to send or ``cancel_teams_post`` to abort.

        Args:
            target: Channel name or person name (e.g. "Engineering", "John Smith")
            message: The message text to post
        """
        poster = _get_poster()
        result = await poster.prepare_message(target, message)
        return json.dumps(result)

    @mcp.tool()
    async def confirm_teams_post() -> str:
        """Send the previously prepared Teams message.

        Must be called after ``post_teams_message`` returned
        ``"confirm_required"``.
        """
        poster = _get_poster()
        result = await poster.send_prepared_message()
        return json.dumps(result)

    @mcp.tool()
    async def cancel_teams_post() -> str:
        """Cancel the previously prepared Teams message.

        Disconnects from the browser without sending.
        """
        poster = _get_poster()
        result = await poster.cancel_prepared_message()
        return json.dumps(result)

    @mcp.tool()
    async def close_teams_browser() -> str:
        """Close the persistent Teams browser.

        Sends SIGTERM to the Chromium process. Call ``open_teams_browser``
        to restart.
        """
        mgr = _get_manager()
        result = mgr.close()
        return json.dumps(result)

    # Expose at module level for test imports
    mod = sys.modules[__name__]
    mod.open_teams_browser = open_teams_browser
    mod.post_teams_message = post_teams_message
    mod.confirm_teams_post = confirm_teams_post
    mod.cancel_teams_post = cancel_teams_post
    mod.close_teams_browser = close_teams_browser
```

**Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/test_teams_browser_tools.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mcp_tools/teams_browser_tools.py tests/test_teams_browser_tools.py
git commit -m "feat: add open/close tools, switch to name-based targeting"
```

---

### Task 7: Update Capabilities Registry

Add tool schemas for `open_teams_browser` and `close_teams_browser`, update `post_teams_message` schema.

**Files:**
- Modify: `capabilities/registry.py`
- Modify: `tests/test_teams_capability.py`

**Step 1: Write the failing test**

```python
# tests/test_teams_capability.py — rewritten
"""Tests for teams_write capability."""

from capabilities.registry import (
    CAPABILITY_DEFINITIONS,
    TOOL_SCHEMAS,
    get_tools_for_capabilities,
    validate_capabilities,
)


def test_teams_write_capability_defined():
    defn = CAPABILITY_DEFINITIONS["teams_write"]
    assert "open_teams_browser" in defn.tool_names
    assert "post_teams_message" in defn.tool_names
    assert "confirm_teams_post" in defn.tool_names
    assert "cancel_teams_post" in defn.tool_names
    assert "close_teams_browser" in defn.tool_names


def test_teams_write_tool_schemas_exist():
    for name in ("open_teams_browser", "post_teams_message",
                 "confirm_teams_post", "cancel_teams_post", "close_teams_browser"):
        assert name in TOOL_SCHEMAS
        assert TOOL_SCHEMAS[name]["name"] == name


def test_post_teams_message_schema_has_target():
    schema = TOOL_SCHEMAS["post_teams_message"]
    props = schema["input_schema"]["properties"]
    assert "target" in props
    assert "message" in props
    # channel_url should NOT be in the schema anymore
    assert "channel_url" not in props


def test_teams_write_returns_all_tools():
    tools = get_tools_for_capabilities(["teams_write"])
    names = [t["name"] for t in tools]
    assert "open_teams_browser" in names
    assert "close_teams_browser" in names


def test_teams_write_validates():
    validated = validate_capabilities(["teams_write"])
    assert "teams_write" in validated
```

**Step 2: Run test to verify it fails**

Run: `python3.11 -m pytest tests/test_teams_capability.py -v`
Expected: FAIL

**Step 3: Update capabilities/registry.py**

Replace the existing `post_teams_message` schema block (lines 258-291) and `teams_write` capability (lines 749-753):

```python
# In TOOL_SCHEMAS dict, replace the teams block with:

    "open_teams_browser": {
        "name": "open_teams_browser",
        "description": "Launch persistent Chromium browser and navigate to Teams.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    "post_teams_message": {
        "name": "post_teams_message",
        "description": "Search for a Teams channel or person by name and prepare a message. Returns confirmation info — call confirm_teams_post to send.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Channel name or person name (e.g. 'Engineering', 'John Smith')",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to post",
                },
            },
            "required": ["target", "message"],
        },
    },
    "confirm_teams_post": {
        "name": "confirm_teams_post",
        "description": "Send the previously prepared Teams message after user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    "cancel_teams_post": {
        "name": "cancel_teams_post",
        "description": "Cancel the previously prepared Teams message and close the browser.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    "close_teams_browser": {
        "name": "close_teams_browser",
        "description": "Close the persistent Teams browser process.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
```

```python
# In CAPABILITY_DEFINITIONS dict, replace teams_write with:

    "teams_write": CapabilityDefinition(
        name="teams_write",
        description="Post messages to Microsoft Teams channels via persistent browser automation",
        tool_names=("open_teams_browser", "post_teams_message", "confirm_teams_post", "cancel_teams_post", "close_teams_browser"),
    ),
```

**Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/test_teams_capability.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add capabilities/registry.py tests/test_teams_capability.py
git commit -m "feat: update capability registry for persistent browser tools"
```

---

### Task 8: Update Humanizer Hook

The humanizer hook references `post_teams_message` which still exists but now takes `target` instead of `channel_url`. The `message` field is already in `TEXT_FIELDS`. Verify no changes needed.

**Files:**
- Check: `humanizer/hook.py`
- Modify: `tests/test_humanizer_hook.py` (update test to use `target` param)

**Step 1: Read humanizer hook and verify**

Check that `post_teams_message` is still in `OUTBOUND_TOOLS` and `"message"` is in `TEXT_FIELDS`. The hook humanizes the `message` field regardless of whether the other param is `channel_url` or `target` — so no code change needed in the hook itself.

**Step 2: Update the humanizer test**

In `tests/test_humanizer_hook.py`, find the test `test_humanize_hook_teams_message` and change `channel_url` to `target` in the tool_args:

```python
# In test_humanize_hook_teams_message, change:
tool_args = {"channel_url": "https://teams.microsoft.com/...", "message": "..."}
# To:
tool_args = {"target": "Engineering", "message": "..."}
```

Also update the assertion to check `target` is preserved instead of `channel_url`.

**Step 3: Run tests**

Run: `python3.11 -m pytest tests/test_humanizer_hook.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add tests/test_humanizer_hook.py
git commit -m "test: update humanizer test for target-based Teams tool"
```

---

### Task 9: Cleanup Old Code

Remove deprecated scripts and session management.

**Files:**
- Delete: `scripts/teams_auth_setup.py`
- Delete: `scripts/teams_url_monitor.py`
- Delete: `scripts/teams_test_post.py` (replaced by new test script)
- Delete: `scripts/teams_explore.py` (replaced by `teams_search_explore.py`)

**Step 1: Remove files**

```bash
git rm scripts/teams_auth_setup.py scripts/teams_url_monitor.py scripts/teams_test_post.py scripts/teams_explore.py
```

**Step 2: Run full test suite**

Run: `python3.11 -m pytest -x -q`
Expected: All tests pass

**Step 3: Commit**

```bash
git commit -m "chore: remove deprecated Teams scripts"
```

---

### Task 10: Integration Test Script

Create a test script for the full persistent browser flow.

**Files:**
- Create: `scripts/teams_persistent_test.py`

**Step 1: Write the test script**

```python
# scripts/teams_persistent_test.py
"""End-to-end test of the persistent Teams browser flow.

Usage: python3.11 scripts/teams_persistent_test.py [target] [message]

Steps:
1. Opens browser (or connects to existing)
2. Navigates to Teams
3. Searches for target
4. Shows detected channel and waits for confirmation (30s)
5. Sends message
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.manager import TeamsBrowserManager
from browser.teams_poster import PlaywrightTeamsPoster


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "General"
    message = sys.argv[2] if len(sys.argv) > 2 else "Test from persistent browser"

    print(f"Target: {target}")
    print(f"Message: {message}\n")

    mgr = TeamsBrowserManager()

    # Step 1: Ensure browser is running
    if not mgr.is_alive():
        print("Launching browser...")
        result = mgr.launch()
        print(f"Launch: {json.dumps(result, indent=2)}")
        if result["status"] == "error":
            sys.exit(1)
        print("Waiting 15s for Teams to load...")
        await asyncio.sleep(15)
    else:
        print("Browser already running.")

    # Step 2: Prepare message
    poster = PlaywrightTeamsPoster(manager=mgr)
    print(f"\nSearching for '{target}'...")
    result = await poster.prepare_message(target, message)
    print(f"Prepare result: {json.dumps(result, indent=2)}")

    if result["status"] != "confirm_required":
        print(f"\nCannot proceed: {result.get('error', 'unknown error')}")
        return

    print(f"\n*** Detected: {result['detected_channel']} ***")
    print(f"*** Message:  {result['message']} ***")
    print("\nSending in 30s... (Ctrl+C to cancel)")

    try:
        await asyncio.sleep(30)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nCancelling...")
        cancel = await poster.cancel_prepared_message()
        print(f"Cancel: {json.dumps(cancel, indent=2)}")
        return

    # Step 3: Send
    print("\nSending...")
    send = await poster.send_prepared_message()
    print(f"Send: {json.dumps(send, indent=2)}")

    print("\nBrowser is still running. Use close_teams_browser to stop it.")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Commit**

```bash
git add scripts/teams_persistent_test.py
git commit -m "feat: add persistent browser integration test script"
```

---

### Task 11: Full Test Suite Verification

**Step 1: Run all tests**

Run: `python3.11 -m pytest -x -q`
Expected: All tests pass with 0 failures

**Step 2: Verify no import errors**

Run: `python3.11 -c "from browser.manager import TeamsBrowserManager; from browser.navigator import TeamsNavigator; from browser.teams_poster import PlaywrightTeamsPoster; print('All imports OK')"`
Expected: "All imports OK"

**Step 3: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: test suite fixups for persistent browser"
```
