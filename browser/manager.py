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

logger = logging.getLogger(__name__)

DEFAULT_CDP_PORT = 9222
DEFAULT_STATE_PATH = DATA_DIR / "playwright" / "browser.json"
DEFAULT_PROFILE_DIR = DATA_DIR / "playwright" / "profile"


class TeamsBrowserManager:
    """Manage a persistent Chromium browser process."""

    def __init__(self, cdp_port=DEFAULT_CDP_PORT, state_path=None, profile_dir=None):
        self.cdp_port = cdp_port
        self.state_path = state_path or DEFAULT_STATE_PATH
        self.profile_dir = profile_dir or DEFAULT_PROFILE_DIR

    def _load_state(self):
        try:
            return json.loads(self.state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _save_state(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2))

    def _clear_state(self):
        try:
            self.state_path.unlink()
        except FileNotFoundError:
            pass

    def is_alive(self):
        try:
            url = f"http://localhost:{self.cdp_port}/json/version"
            with urlopen(url, timeout=2) as resp:
                return resp.status == 200
        except (URLError, OSError, TimeoutError):
            return False

    @staticmethod
    def _find_chromium_path():
        if platform.system() == "Darwin":
            cache = Path.home() / "Library" / "Caches" / "ms-playwright"
        else:
            cache = Path.home() / ".cache" / "ms-playwright"

        for chromium_dir in sorted(cache.glob("chromium-*"), reverse=True):
            if platform.system() == "Darwin":
                candidate = (chromium_dir / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium")
            else:
                candidate = chromium_dir / "chrome-linux" / "chrome"
            if candidate.exists():
                return str(candidate)
        return None

    def launch(self):
        if self.is_alive():
            state = self._load_state() or {}
            return {"status": "already_running", **state}

        chromium = self._find_chromium_path()
        if chromium is None:
            return {"status": "error", "error": "Chromium not found. Run: playwright install chromium"}

        self.profile_dir.mkdir(parents=True, exist_ok=True)

        proc = subprocess.Popen(
            [chromium, f"--remote-debugging-port={self.cdp_port}",
             f"--user-data-dir={self.profile_dir}",
             "--no-first-run", "--no-default-browser-check"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        for _ in range(30):
            if self.is_alive():
                state = {"pid": proc.pid, "cdp_port": self.cdp_port}
                self._save_state(state)
                return {"status": "launched", **state}
            time.sleep(0.5)

        return {"status": "error", "error": f"Chromium started (pid={proc.pid}) but CDP not responding on port {self.cdp_port}"}

    def close(self):
        state = self._load_state()
        if state and "pid" in state:
            try:
                os.kill(state["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        self._clear_state()
        if self.is_alive():
            return {"status": "error", "error": "Browser still running after SIGTERM"}
        return {"status": "closed"}
