"""Tests for browser.agent_browser — async subprocess wrapper."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser.agent_browser import AgentBrowser, AgentBrowserError


def _make_process(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    """Create a mock subprocess with the given output."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


@pytest.mark.asyncio
class TestAgentBrowserRun:
    async def test_successful_json_output(self):
        payload = {"snapshot": "...", "refs": ["@e1"]}
        proc = _make_process(stdout=json.dumps(payload).encode())

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            browser = AgentBrowser(bin_path="/usr/bin/agent-browser", timeout=10)
            result = await browser._run("snapshot")

        assert result == payload

    async def test_empty_stdout_returns_ok(self):
        proc = _make_process(stdout=b"")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            browser = AgentBrowser()
            result = await browser._run("close")

        assert result == {"ok": True}

    async def test_non_json_stdout_returns_text(self):
        proc = _make_process(stdout=b"Page loaded successfully")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            browser = AgentBrowser()
            result = await browser._run("open", "https://example.com")

        assert result == {"ok": True, "text": "Page loaded successfully"}

    async def test_nonzero_exit_raises(self):
        proc = _make_process(stderr=b"Error: browser crashed", returncode=1)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            browser = AgentBrowser()
            with pytest.raises(AgentBrowserError, match="exited with code 1"):
                await browser._run("snapshot")

    async def test_timeout_kills_process(self):
        proc = AsyncMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        proc.kill = MagicMock()
        proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            browser = AgentBrowser(timeout=1)
            with pytest.raises(AgentBrowserError, match="timed out"):
                await browser._run("snapshot")

        proc.kill.assert_called_once()

    async def test_binary_not_found_raises(self):
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError),
        ):
            browser = AgentBrowser(bin_path="/nonexistent/agent-browser")
            with pytest.raises(AgentBrowserError, match="not found"):
                await browser._run("open", "https://example.com")

    async def test_data_dir_passed_as_arg(self):
        proc = _make_process(stdout=b'{"ok": true}')
        mock_exec = AsyncMock(return_value=proc)

        with patch("asyncio.create_subprocess_exec", mock_exec):
            browser = AgentBrowser(bin_path="ab", data_dir="/tmp/ab-data")
            await browser._run("snapshot")

        call_args = mock_exec.call_args[0]
        assert "--data-dir" in call_args
        assert "/tmp/ab-data" in call_args


@pytest.mark.asyncio
class TestAgentBrowserMethods:
    async def test_open(self):
        proc = _make_process(stdout=b'{"navigated": true}')

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
            browser = AgentBrowser()
            result = await browser.open("https://example.com")

        assert result == {"navigated": True}
        cmd = mock_exec.call_args[0]
        assert "open" in cmd
        assert "https://example.com" in cmd

    async def test_snapshot(self):
        snapshot_data = {"tree": "[document] ...", "refs": {"@e1": "button"}}
        proc = _make_process(stdout=json.dumps(snapshot_data).encode())

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            browser = AgentBrowser()
            result = await browser.snapshot()

        assert result == snapshot_data

    async def test_click(self):
        proc = _make_process(stdout=b'{"clicked": true}')

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
            browser = AgentBrowser()
            result = await browser.click("@e1")

        assert result == {"clicked": True}
        assert "@e1" in mock_exec.call_args[0]

    async def test_fill(self):
        proc = _make_process(stdout=b'{"filled": true}')

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
            browser = AgentBrowser()
            result = await browser.fill("@e3", "hello world")

        assert result == {"filled": True}
        args = mock_exec.call_args[0]
        assert "@e3" in args
        assert "hello world" in args

    async def test_get_text(self):
        proc = _make_process(stdout=b'{"text": "Welcome to Example"}')

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
            browser = AgentBrowser()
            result = await browser.get_text("@e5")

        assert result["text"] == "Welcome to Example"
        args = mock_exec.call_args[0]
        assert "get" in args
        assert "text" in args
        assert "@e5" in args

    async def test_screenshot(self):
        proc = _make_process(stdout=b'{"base64": "iVBORw0KGgo..."}')

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            browser = AgentBrowser()
            result = await browser.screenshot()

        assert "base64" in result

    async def test_execute_js(self):
        proc = _make_process(stdout=b'{"result": 42}')

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
            browser = AgentBrowser()
            result = await browser.execute_js("document.title")

        assert result == {"result": 42}
        args = mock_exec.call_args[0]
        assert "evaluate" in args
        assert "document.title" in args

    async def test_close_success(self):
        proc = _make_process(stdout=b'{"closed": true}')

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            browser = AgentBrowser()
            result = await browser.close()

        assert result == {"closed": True}

    async def test_close_already_closed(self):
        """close() swallows errors and returns ok."""
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError),
        ):
            browser = AgentBrowser()
            result = await browser.close()

        assert result["ok"] is True
        assert "already closed" in result.get("detail", "")
