"""Async subprocess wrapper for the agent-browser CLI.

agent-browser is a Rust+Node.js CLI that wraps Playwright with an
accessibility-tree snapshot system.  Each method shells out via
``asyncio.create_subprocess_exec``, captures JSON stdout, and enforces
a configurable timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AgentBrowserError(Exception):
    """Raised when the agent-browser CLI returns an error."""


class AgentBrowser:
    """Thin async wrapper around the ``agent-browser`` CLI binary."""

    def __init__(
        self,
        bin_path: str = "agent-browser",
        data_dir: str | Path | None = None,
        timeout: int = 30,
    ) -> None:
        self.bin_path = bin_path
        self.data_dir = str(data_dir) if data_dir else None
        self.timeout = timeout

    async def _run(self, *args: str) -> dict[str, Any]:
        """Execute an agent-browser subcommand and return parsed JSON output."""
        cmd = [self.bin_path]
        if self.data_dir:
            cmd.extend(["--data-dir", self.data_dir])
        cmd.extend(args)

        logger.debug("agent-browser exec: %s", " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            raise AgentBrowserError(
                f"agent-browser timed out after {self.timeout}s: {' '.join(cmd)}"
            )
        except FileNotFoundError:
            raise AgentBrowserError(
                f"agent-browser binary not found at '{self.bin_path}'. "
                "Install with: npm install -g agent-browser && agent-browser install"
            )

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="replace").strip()
            raise AgentBrowserError(
                f"agent-browser exited with code {proc.returncode}: {err_text}"
            )

        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return {"ok": True}

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": True, "text": raw}

    async def open(self, url: str) -> dict[str, Any]:
        """Launch browser and navigate to *url*."""
        return await self._run("open", url)

    async def snapshot(self) -> dict[str, Any]:
        """Get the current page's accessibility tree snapshot with ref IDs."""
        return await self._run("snapshot")

    async def click(self, ref: str) -> dict[str, Any]:
        """Click the element identified by *ref* ID."""
        return await self._run("click", ref)

    async def fill(self, ref: str, value: str) -> dict[str, Any]:
        """Fill the input element *ref* with *value*."""
        return await self._run("fill", ref, value)

    async def get_text(self, ref: str) -> dict[str, Any]:
        """Extract text content from the element identified by *ref*."""
        return await self._run("get", "text", ref)

    async def screenshot(self) -> dict[str, Any]:
        """Capture a screenshot of the current page."""
        return await self._run("screenshot")

    async def execute_js(self, code: str) -> dict[str, Any]:
        """Execute JavaScript in the page context."""
        return await self._run("evaluate", code)

    async def close(self) -> dict[str, Any]:
        """Close the browser and clean up."""
        try:
            return await self._run("close")
        except AgentBrowserError:
            return {"ok": True, "detail": "browser already closed"}
