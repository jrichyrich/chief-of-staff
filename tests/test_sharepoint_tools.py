"""Tests for the generic download_from_sharepoint MCP tool."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Trigger tool registration so module-level functions exist
import mcp_server  # noqa: F401
from mcp_tools import sharepoint_tools
from mcp_tools.sharepoint_tools import _infer_filename


class TestInferFilename:
    def test_from_file_param(self):
        url = "https://sp.com/doc?sourcedoc=%7Babc%7D&file=Report.xlsx&action=default"
        assert _infer_filename(url) == "Report.xlsx"

    def test_from_path_segment(self):
        url = "https://sp.com/sites/Team/Shared%20Documents/Budget.pdf"
        assert _infer_filename(url) == "Budget.pdf"

    def test_from_path_with_query(self):
        url = "https://sp.com/sites/Team/docs/slides.pptx?action=view"
        assert _infer_filename(url) == "slides.pptx"

    def test_fallback_default(self):
        url = "https://sp.com/:x:/r/sites/Team/_layouts/15/Doc.aspx?sourcedoc=%7Babc%7D"
        assert _infer_filename(url) == "sharepoint_download"

    def test_file_param_takes_precedence(self):
        url = "https://sp.com/sites/Team/data.xlsx?file=Override.xlsx"
        assert _infer_filename(url) == "Override.xlsx"


class TestDownloadFromSharepoint:
    @pytest.mark.asyncio
    async def test_happy_path(self, tmp_path):
        dest_dir = tmp_path / "downloads"
        dest_dir.mkdir()

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True

        expected_path = str(dest_dir / "Report.xlsx")
        mock_dl = AsyncMock(return_value={
            "status": "downloaded",
            "path": expected_path,
            "size_bytes": 54321,
            "method": "direct_url",
        })

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
             patch("mcp_tools.sharepoint_tools.app_config") as mock_config:

            mock_config.SHAREPOINT_DOWNLOAD_DIR = dest_dir
            mock_config.DATA_DIR = tmp_path

            url = "https://chgcloud.sharepoint.com/doc?file=Report.xlsx"
            result = json.loads(await sharepoint_tools.download_from_sharepoint(
                sharepoint_url=url,
            ))

            assert result["status"] == "downloaded"
            assert result["filename"] == "Report.xlsx"
            assert result["size_bytes"] == 54321
            assert result["method"] == "direct_url"
            mock_dl.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_destination_dir(self, tmp_path):
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True

        mock_dl = AsyncMock(return_value={
            "status": "downloaded",
            "path": str(custom_dir / "data.pdf"),
            "size_bytes": 10000,
            "method": "direct_url",
        })

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
             patch("mcp_tools.sharepoint_tools.app_config") as mock_config:

            mock_config.SHAREPOINT_DOWNLOAD_DIR = tmp_path / "sp"
            mock_config.DATA_DIR = tmp_path

            url = "https://sp.com/sites/Team/docs/data.pdf"
            result = json.loads(await sharepoint_tools.download_from_sharepoint(
                sharepoint_url=url,
                destination_dir=str(custom_dir),
            ))

            assert result["status"] == "downloaded"
            assert result["filename"] == "data.pdf"
            # Verify destination was passed correctly
            call_dest = mock_dl.call_args[0][2]
            assert call_dest == custom_dir / "data.pdf"

    @pytest.mark.asyncio
    async def test_custom_filename(self, tmp_path):
        dest_dir = tmp_path / "downloads"
        dest_dir.mkdir()

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True

        mock_dl = AsyncMock(return_value={
            "status": "downloaded",
            "path": str(dest_dir / "my_report.xlsx"),
            "size_bytes": 8000,
            "method": "direct_url",
        })

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
             patch("mcp_tools.sharepoint_tools.app_config") as mock_config:

            mock_config.SHAREPOINT_DOWNLOAD_DIR = dest_dir
            mock_config.DATA_DIR = tmp_path

            url = "https://sp.com/doc?file=Original.xlsx"
            result = json.loads(await sharepoint_tools.download_from_sharepoint(
                sharepoint_url=url,
                filename="my_report.xlsx",
            ))

            assert result["status"] == "downloaded"
            assert result["filename"] == "my_report.xlsx"
            call_dest = mock_dl.call_args[0][2]
            assert call_dest.name == "my_report.xlsx"

    @pytest.mark.asyncio
    async def test_empty_url_rejected(self, tmp_path):
        result = json.loads(await sharepoint_tools.download_from_sharepoint(
            sharepoint_url="",
        ))
        assert result["status"] == "error"
        assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_disallowed_extension(self, tmp_path):
        dest_dir = tmp_path / "downloads"
        dest_dir.mkdir()

        with patch("mcp_tools.sharepoint_tools.app_config") as mock_config:
            mock_config.SHAREPOINT_DOWNLOAD_DIR = dest_dir
            mock_config.DATA_DIR = tmp_path

            url = "https://sp.com/doc?file=malware.exe"
            result = json.loads(await sharepoint_tools.download_from_sharepoint(
                sharepoint_url=url,
            ))

            assert result["status"] == "error"
            assert "not allowed" in result["error"]

    @pytest.mark.asyncio
    async def test_disallowed_destination(self, tmp_path):
        with patch("mcp_tools.sharepoint_tools.app_config") as mock_config:
            mock_config.SHAREPOINT_DOWNLOAD_DIR = tmp_path / "sp"
            mock_config.DATA_DIR = tmp_path

            url = "https://sp.com/doc?file=report.xlsx"
            result = json.loads(await sharepoint_tools.download_from_sharepoint(
                sharepoint_url=url,
                destination_dir="/etc/evil",
            ))

            assert result["status"] == "error"
            assert "Access denied" in result["error"]

    @pytest.mark.asyncio
    async def test_browser_auto_launch(self, tmp_path):
        dest_dir = tmp_path / "downloads"
        dest_dir.mkdir()

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = False
        mock_manager.launch.return_value = {"status": "launched", "pid": 9999}

        mock_dl = AsyncMock(return_value={
            "status": "downloaded",
            "path": str(dest_dir / "doc.docx"),
            "size_bytes": 3000,
            "method": "direct_url",
        })

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
             patch("mcp_tools.sharepoint_tools.app_config") as mock_config:

            mock_config.SHAREPOINT_DOWNLOAD_DIR = dest_dir
            mock_config.DATA_DIR = tmp_path

            url = "https://sp.com/doc?file=doc.docx"
            result = json.loads(await sharepoint_tools.download_from_sharepoint(
                sharepoint_url=url,
            ))

            assert result["status"] == "downloaded"
            mock_manager.launch.assert_called_once()

    @pytest.mark.asyncio
    async def test_browser_launch_failure(self, tmp_path):
        dest_dir = tmp_path / "downloads"
        dest_dir.mkdir()

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = False
        mock_manager.launch.return_value = {
            "status": "error",
            "error": "Chromium binary not found",
        }

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("mcp_tools.sharepoint_tools.app_config") as mock_config:

            mock_config.SHAREPOINT_DOWNLOAD_DIR = dest_dir
            mock_config.DATA_DIR = tmp_path

            url = "https://sp.com/doc?file=report.xlsx"
            result = json.loads(await sharepoint_tools.download_from_sharepoint(
                sharepoint_url=url,
            ))

            assert result["status"] == "error"
            assert result["step"] == "browser_launch"

    @pytest.mark.asyncio
    async def test_download_failure_passthrough(self, tmp_path):
        dest_dir = tmp_path / "downloads"
        dest_dir.mkdir()

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True

        mock_dl = AsyncMock(return_value={
            "status": "auth_required",
            "error": "Both download strategies failed.",
        })

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
             patch("mcp_tools.sharepoint_tools.app_config") as mock_config:

            mock_config.SHAREPOINT_DOWNLOAD_DIR = dest_dir
            mock_config.DATA_DIR = tmp_path

            url = "https://sp.com/doc?file=report.xlsx"
            result = json.loads(await sharepoint_tools.download_from_sharepoint(
                sharepoint_url=url,
            ))

            assert result["status"] == "auth_required"

    @pytest.mark.asyncio
    async def test_various_file_types(self, tmp_path):
        """Verify different file types are accepted."""
        dest_dir = tmp_path / "downloads"
        dest_dir.mkdir()

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True

        for ext in [".pdf", ".docx", ".pptx", ".csv", ".xlsx", ".txt", ".zip"]:
            filename = f"test_file{ext}"
            mock_dl = AsyncMock(return_value={
                "status": "downloaded",
                "path": str(dest_dir / filename),
                "size_bytes": 1000,
                "method": "direct_url",
            })

            with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
                 patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
                 patch("mcp_tools.sharepoint_tools.app_config") as mock_config:

                mock_config.SHAREPOINT_DOWNLOAD_DIR = dest_dir
                mock_config.DATA_DIR = tmp_path

                url = f"https://sp.com/doc?file={filename}"
                result = json.loads(await sharepoint_tools.download_from_sharepoint(
                    sharepoint_url=url,
                ))

                assert result["status"] == "downloaded", f"Failed for {ext}"
                assert result["filename"] == filename
