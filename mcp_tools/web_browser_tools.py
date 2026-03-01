"""General-purpose web browsing tools powered by agent-browser.

Seven tools for navigating, interacting with, and extracting data from
web pages via the agent-browser CLI's accessibility-tree snapshot system.
"""

import json
import logging
import sys

import config as app_config

logger = logging.getLogger(__name__)

_browser = None


def _get_browser():
    """Lazy-initialize the AgentBrowser singleton on first use."""
    global _browser
    if _browser is None:
        from browser.agent_browser import AgentBrowser

        app_config.AGENT_BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        _browser = AgentBrowser(
            bin_path=app_config.AGENT_BROWSER_BIN,
            data_dir=app_config.AGENT_BROWSER_DATA_DIR,
            timeout=app_config.AGENT_BROWSER_TIMEOUT,
        )
    return _browser


def register(mcp, state):
    """Register web browser tools with the MCP server."""

    @mcp.tool()
    async def web_open(url: str) -> str:
        """Open a URL in the agent-browser.

        Launches a headless browser and navigates to the given URL.
        Call web_snapshot after this to see the page content.

        Args:
            url: The URL to navigate to.
        """
        from browser.agent_browser import AgentBrowserError

        browser = state.agent_browser or _get_browser()
        try:
            result = await browser.open(url)
            return json.dumps({"status": "ok", "url": url, **result})
        except AgentBrowserError as exc:
            return json.dumps({"status": "error", "error": str(exc)})

    @mcp.tool()
    async def web_snapshot() -> str:
        """Get an accessibility tree snapshot of the current page.

        Returns a structured snapshot with element reference IDs (e.g. @e1,
        @e2) that can be used with web_click, web_fill, and web_get_text.
        This is the primary way to understand page content — much more
        compact than raw HTML.
        """
        from browser.agent_browser import AgentBrowserError

        browser = state.agent_browser or _get_browser()
        try:
            result = await browser.snapshot()
            return json.dumps({"status": "ok", **result})
        except AgentBrowserError as exc:
            return json.dumps({"status": "error", "error": str(exc)})

    @mcp.tool()
    async def web_click(ref: str) -> str:
        """Click an element by its reference ID from a snapshot.

        Args:
            ref: Element reference ID (e.g. '@e1') from web_snapshot output.
        """
        from browser.agent_browser import AgentBrowserError

        browser = state.agent_browser or _get_browser()
        try:
            result = await browser.click(ref)
            return json.dumps({"status": "ok", "clicked": ref, **result})
        except AgentBrowserError as exc:
            return json.dumps({"status": "error", "error": str(exc)})

    @mcp.tool()
    async def web_fill(ref: str, value: str) -> str:
        """Fill an input field identified by its reference ID.

        Args:
            ref: Element reference ID (e.g. '@e3') from web_snapshot output.
            value: The text to type into the input field.
        """
        from browser.agent_browser import AgentBrowserError

        browser = state.agent_browser or _get_browser()
        try:
            result = await browser.fill(ref, value)
            return json.dumps({"status": "ok", "filled": ref, **result})
        except AgentBrowserError as exc:
            return json.dumps({"status": "error", "error": str(exc)})

    @mcp.tool()
    async def web_get_text(ref: str) -> str:
        """Extract text content from an element by its reference ID.

        Args:
            ref: Element reference ID (e.g. '@e5') from web_snapshot output.
        """
        from browser.agent_browser import AgentBrowserError

        browser = state.agent_browser or _get_browser()
        try:
            result = await browser.get_text(ref)
            return json.dumps({"status": "ok", "ref": ref, **result})
        except AgentBrowserError as exc:
            return json.dumps({"status": "error", "error": str(exc)})

    @mcp.tool()
    async def web_screenshot() -> str:
        """Capture a screenshot of the current page.

        Returns the screenshot as base64-encoded image data.
        """
        from browser.agent_browser import AgentBrowserError

        browser = state.agent_browser or _get_browser()
        try:
            result = await browser.screenshot()
            return json.dumps({"status": "ok", **result})
        except AgentBrowserError as exc:
            return json.dumps({"status": "error", "error": str(exc)})

    @mcp.tool()
    async def web_execute_js(code: str) -> str:
        """Execute JavaScript in the current page context.

        Args:
            code: JavaScript code to evaluate in the page.
        """
        from browser.agent_browser import AgentBrowserError

        browser = state.agent_browser or _get_browser()
        try:
            result = await browser.execute_js(code)
            return json.dumps({"status": "ok", **result})
        except AgentBrowserError as exc:
            return json.dumps({"status": "error", "error": str(exc)})

    # Expose at module level for test imports
    mod = sys.modules[__name__]
    mod.web_open = web_open
    mod.web_snapshot = web_snapshot
    mod.web_click = web_click
    mod.web_fill = web_fill
    mod.web_get_text = web_get_text
    mod.web_screenshot = web_screenshot
    mod.web_execute_js = web_execute_js
