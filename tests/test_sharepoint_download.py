"""Tests for browser.sharepoint_download."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser.sharepoint_download import _make_download_url, download_sharepoint_file


def _make_download_info(mock_download):
    """Create a mock matching Playwright's EventContextManager.value (a Future)."""
    future = asyncio.get_event_loop().create_future()
    future.set_result(mock_download)
    return MagicMock(value=future)


# --- _make_download_url tests ---

class TestMakeDownloadUrl:
    def test_replaces_action_default(self):
        url = (
            "https://chgcloud.sharepoint.com/:x:/r/sites/ISPTeam/_layouts/15/Doc.aspx"
            "?sourcedoc=%7BDFD697F4%7D&file=test.xlsx&action=default&mobileredirect=true"
        )
        result = _make_download_url(url)
        assert "action=download" in result
        assert "action=default" not in result

    def test_replaces_action_edit(self):
        url = "https://example.sharepoint.com/doc?action=edit&other=1"
        result = _make_download_url(url)
        assert "action=download" in result
        assert "action=edit" not in result

    def test_preserves_other_params(self):
        url = "https://sp.com/doc?sourcedoc=abc&file=test.xlsx&action=view&mobile=true"
        result = _make_download_url(url)
        assert "sourcedoc=abc" in result
        assert "file=test.xlsx" in result
        assert "mobile=true" in result
        assert "action=download" in result

    def test_appends_action_when_missing(self):
        url = "https://sp.com/doc?file=test.xlsx"
        result = _make_download_url(url)
        assert result.endswith("&action=download")

    def test_appends_with_question_mark_when_no_params(self):
        url = "https://sp.com/doc"
        result = _make_download_url(url)
        assert result == "https://sp.com/doc?action=download"

    def test_action_as_first_param(self):
        url = "https://sp.com/doc?action=view&file=test.xlsx"
        result = _make_download_url(url)
        assert "?action=download" in result
        assert "file=test.xlsx" in result


# --- download_sharepoint_file tests ---

class TestDownloadSharepointFile:
    @pytest.mark.asyncio
    async def test_browser_not_running(self, tmp_path):
        manager = MagicMock()
        manager.is_alive.return_value = False

        result = await download_sharepoint_file(
            manager, "https://sp.com/doc", tmp_path / "out.xlsx"
        )
        assert result["status"] == "error"
        assert "not running" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_happy_path(self, tmp_path):
        dest = tmp_path / "subdir" / "out.xlsx"
        # Pre-create the file to simulate save_as writing content
        dest.parent.mkdir(parents=True, exist_ok=True)

        manager = MagicMock()
        manager.is_alive.return_value = True

        mock_download = AsyncMock()
        mock_download.failure = AsyncMock(return_value=None)
        async def fake_save_as(path):
            Path(path).write_bytes(b"PK\x03\x04fake-xlsx-content")
        mock_download.save_as = fake_save_as

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()

        # Create an async context manager for expect_download
        download_cm = AsyncMock()
        download_cm.__aenter__ = AsyncMock(return_value=_make_download_info(mock_download))
        download_cm.__aexit__ = AsyncMock(return_value=False)
        mock_page.expect_download = MagicMock(return_value=download_cm)

        mock_ctx = MagicMock()
        mock_ctx.new_page = AsyncMock(return_value=mock_page)

        mock_browser = MagicMock()
        mock_browser.contexts = [mock_ctx]

        mock_pw = AsyncMock()
        manager.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        result = await download_sharepoint_file(
            manager, "https://sp.com/doc?action=default", dest
        )
        assert result["status"] == "downloaded"
        assert result["size_bytes"] > 0
        assert dest.exists()

    @pytest.mark.asyncio
    async def test_download_timeout(self, tmp_path):
        manager = MagicMock()
        manager.is_alive.return_value = True

        mock_page = AsyncMock()
        mock_page.close = AsyncMock()

        download_cm = AsyncMock()
        download_cm.__aenter__ = AsyncMock(side_effect=TimeoutError("timed out"))
        download_cm.__aexit__ = AsyncMock(return_value=False)
        mock_page.expect_download = MagicMock(return_value=download_cm)

        mock_ctx = MagicMock()
        mock_ctx.new_page = AsyncMock(return_value=mock_page)

        mock_browser = MagicMock()
        mock_browser.contexts = [mock_ctx]

        mock_pw = AsyncMock()
        manager.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        result = await download_sharepoint_file(
            manager, "https://sp.com/doc", tmp_path / "out.xlsx"
        )
        assert result["status"] == "auth_required"
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_download_failure_reported(self, tmp_path):
        manager = MagicMock()
        manager.is_alive.return_value = True

        mock_download = AsyncMock()
        mock_download.failure = AsyncMock(return_value="net::ERR_FAILED")

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()

        download_cm = AsyncMock()
        download_cm.__aenter__ = AsyncMock(return_value=_make_download_info(mock_download))
        download_cm.__aexit__ = AsyncMock(return_value=False)
        mock_page.expect_download = MagicMock(return_value=download_cm)

        mock_ctx = MagicMock()
        mock_ctx.new_page = AsyncMock(return_value=mock_page)

        mock_browser = MagicMock()
        mock_browser.contexts = [mock_ctx]

        mock_pw = AsyncMock()
        manager.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        result = await download_sharepoint_file(
            manager, "https://sp.com/doc", tmp_path / "out.xlsx"
        )
        assert result["status"] == "error"
        assert "net::ERR_FAILED" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_file(self, tmp_path):
        dest = tmp_path / "out.xlsx"

        manager = MagicMock()
        manager.is_alive.return_value = True

        mock_download = AsyncMock()
        mock_download.failure = AsyncMock(return_value=None)
        async def fake_save_empty(path):
            Path(path).write_bytes(b"")
        mock_download.save_as = fake_save_empty

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()

        download_cm = AsyncMock()
        download_cm.__aenter__ = AsyncMock(return_value=_make_download_info(mock_download))
        download_cm.__aexit__ = AsyncMock(return_value=False)
        mock_page.expect_download = MagicMock(return_value=download_cm)

        mock_ctx = MagicMock()
        mock_ctx.new_page = AsyncMock(return_value=mock_page)

        mock_browser = MagicMock()
        mock_browser.contexts = [mock_ctx]

        mock_pw = AsyncMock()
        manager.connect = AsyncMock(return_value=(mock_pw, mock_browser))

        result = await download_sharepoint_file(
            manager, "https://sp.com/doc", dest
        )
        assert result["status"] == "error"
        assert "empty" in result["error"].lower()
