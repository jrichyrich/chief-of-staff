"""Tests for the web browser MCP tools (agent-browser integration)."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import mcp_server  # noqa: F401 — triggers tool registrations
from mcp_tools import web_browser_tools

web_browser_tools.register(mcp_server.mcp, mcp_server._state)
from mcp_tools.web_browser_tools import (
    web_click,
    web_execute_js,
    web_fill,
    web_get_text,
    web_open,
    web_screenshot,
    web_snapshot,
)


def _mock_browser(**method_returns):
    """Create a mock AgentBrowser with preconfigured return values."""
    browser = AsyncMock()
    for method, value in method_returns.items():
        getattr(browser, method).return_value = value
    return browser


@pytest.mark.asyncio
class TestWebOpen:
    async def test_open_success(self):
        mock = _mock_browser(open={"navigated": True})
        mcp_server._state.agent_browser = mock

        raw = await web_open(url="https://example.com")
        result = json.loads(raw)

        assert result["status"] == "ok"
        assert result["url"] == "https://example.com"
        mock.open.assert_awaited_once_with("https://example.com")

        mcp_server._state.agent_browser = None

    async def test_open_error(self):
        from browser.agent_browser import AgentBrowserError

        mock = AsyncMock()
        mock.open = AsyncMock(side_effect=AgentBrowserError("binary not found"))
        mcp_server._state.agent_browser = mock

        raw = await web_open(url="https://example.com")
        result = json.loads(raw)

        assert result["status"] == "error"
        assert "not found" in result["error"]

        mcp_server._state.agent_browser = None


@pytest.mark.asyncio
class TestWebSnapshot:
    async def test_snapshot_success(self):
        snapshot_data = {"tree": "[document]", "refs": {"@e1": "button"}}
        mock = _mock_browser(snapshot=snapshot_data)
        mcp_server._state.agent_browser = mock

        raw = await web_snapshot()
        result = json.loads(raw)

        assert result["status"] == "ok"
        assert result["tree"] == "[document]"
        mock.snapshot.assert_awaited_once()

        mcp_server._state.agent_browser = None

    async def test_snapshot_error(self):
        from browser.agent_browser import AgentBrowserError

        mock = AsyncMock()
        mock.snapshot = AsyncMock(side_effect=AgentBrowserError("no page open"))
        mcp_server._state.agent_browser = mock

        raw = await web_snapshot()
        result = json.loads(raw)

        assert result["status"] == "error"

        mcp_server._state.agent_browser = None


@pytest.mark.asyncio
class TestWebClick:
    async def test_click_success(self):
        mock = _mock_browser(click={"ok": True})
        mcp_server._state.agent_browser = mock

        raw = await web_click(ref="@e1")
        result = json.loads(raw)

        assert result["status"] == "ok"
        assert result["clicked"] == "@e1"
        mock.click.assert_awaited_once_with("@e1")

        mcp_server._state.agent_browser = None


@pytest.mark.asyncio
class TestWebFill:
    async def test_fill_success(self):
        mock = _mock_browser(fill={"ok": True})
        mcp_server._state.agent_browser = mock

        raw = await web_fill(ref="@e3", value="hello")
        result = json.loads(raw)

        assert result["status"] == "ok"
        assert result["filled"] == "@e3"
        mock.fill.assert_awaited_once_with("@e3", "hello")

        mcp_server._state.agent_browser = None


@pytest.mark.asyncio
class TestWebGetText:
    async def test_get_text_success(self):
        mock = _mock_browser(get_text={"text": "Welcome"})
        mcp_server._state.agent_browser = mock

        raw = await web_get_text(ref="@e5")
        result = json.loads(raw)

        assert result["status"] == "ok"
        assert result["text"] == "Welcome"
        mock.get_text.assert_awaited_once_with("@e5")

        mcp_server._state.agent_browser = None


@pytest.mark.asyncio
class TestWebScreenshot:
    async def test_screenshot_success(self):
        mock = _mock_browser(screenshot={"base64": "iVBORw0..."})
        mcp_server._state.agent_browser = mock

        raw = await web_screenshot()
        result = json.loads(raw)

        assert result["status"] == "ok"
        assert "base64" in result
        mock.screenshot.assert_awaited_once()

        mcp_server._state.agent_browser = None


@pytest.mark.asyncio
class TestWebExecuteJs:
    async def test_execute_js_success(self):
        mock = _mock_browser(execute_js={"result": 42})
        mcp_server._state.agent_browser = mock

        raw = await web_execute_js(code="document.title")
        result = json.loads(raw)

        assert result["status"] == "ok"
        assert result["result"] == 42
        mock.execute_js.assert_awaited_once_with("document.title")

        mcp_server._state.agent_browser = None

    async def test_execute_js_error(self):
        from browser.agent_browser import AgentBrowserError

        mock = AsyncMock()
        mock.execute_js = AsyncMock(side_effect=AgentBrowserError("eval failed"))
        mcp_server._state.agent_browser = mock

        raw = await web_execute_js(code="bad()")
        result = json.loads(raw)

        assert result["status"] == "error"
        assert "eval failed" in result["error"]

        mcp_server._state.agent_browser = None


@pytest.mark.asyncio
class TestLazySingleton:
    async def test_falls_back_to_lazy_init(self):
        """When state.agent_browser is None, _get_browser() is called."""
        mcp_server._state.agent_browser = None

        mock_browser = _mock_browser(snapshot={"tree": "..."})
        with patch.object(web_browser_tools, "_get_browser", return_value=mock_browser):
            raw = await web_snapshot()

        result = json.loads(raw)
        assert result["status"] == "ok"
