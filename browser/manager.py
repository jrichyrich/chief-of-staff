"""Persistent Chromium browser manager using CDP.

Launches Chromium as a detached subprocess with --remote-debugging-port.
Reconnects via CDP for each tool call. The browser survives MCP server restarts.
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

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

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

    def is_alive(self) -> bool:
        """Check if the CDP endpoint is responding."""
        try:
            url = f"http://127.0.0.1:{self.cdp_port}/json/version"
            with urlopen(url, timeout=2) as resp:
                return resp.status == 200
        except (URLError, OSError, TimeoutError):
            return False

    @staticmethod
    def _find_chromium_path() -> Optional[str]:
        """Find the Playwright-bundled Chromium executable."""
        if platform.system() == "Darwin":
            cache = Path.home() / "Library" / "Caches" / "ms-playwright"
        else:
            cache = Path.home() / ".cache" / "ms-playwright"

        for chromium_dir in sorted(cache.glob("chromium-*"), reverse=True):
            if platform.system() == "Darwin":
                candidate = (chromium_dir / "chrome-mac" / "Chromium.app"
                             / "Contents" / "MacOS" / "Chromium")
            else:
                candidate = chromium_dir / "chrome-linux" / "chrome"
            if candidate.exists():
                return str(candidate)
        return None

    def launch(self) -> dict:
        """Launch Chromium as a detached subprocess.

        Returns a status dict with pid and cdp_port.
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
            [chromium, f"--remote-debugging-port={self.cdp_port}",
             f"--user-data-dir={self.profile_dir}",
             "--no-first-run", "--no-default-browser-check",
             "--disable-features=ThirdPartyCookieBlocking"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        for _ in range(30):
            if self.is_alive():
                state = {"pid": proc.pid, "cdp_port": self.cdp_port}
                self._save_state(state)
                logger.info("Chromium launched (pid=%d, port=%d)",
                            proc.pid, self.cdp_port)
                return {"status": "launched", **state}
            time.sleep(0.5)

        return {
            "status": "error",
            "error": (
                f"Chromium started (pid={proc.pid}) but CDP not "
                f"responding on port {self.cdp_port}"
            ),
        }

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
            f"http://127.0.0.1:{self.cdp_port}",
            timeout=10_000,
        )
        return pw, browser

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
        # Brief wait for process to exit after SIGTERM
        for _ in range(6):
            if not self.is_alive():
                return {"status": "closed"}
            time.sleep(0.5)
        return {"status": "error", "error": "Browser still running after SIGTERM"}
