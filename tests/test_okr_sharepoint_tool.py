"""Tests for the refresh_okr_from_sharepoint MCP tool."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from okr.models import Initiative, KeyResult, Objective, OKRSnapshot
from okr.store import OKRStore

# Trigger tool registration so module-level functions exist
import mcp_server  # noqa: F401
from mcp_tools import okr_tools


def _make_snapshot():
    return OKRSnapshot(
        timestamp="2026-02-27T10:00:00",
        source_file="test.xlsx",
        objectives=[
            Objective(okr_id="OKR 1", name="Trusted Controls", statement="",
                      owner="Jason", team="ISP", year="2026", status="On Track",
                      pct_complete=0.15),
        ],
        key_results=[
            KeyResult(kr_id="KR 1.1", okr_id="OKR 1", name="Provisioning time",
                      status="Not Started", owner="Shawn", team="IAM"),
        ],
        initiatives=[
            Initiative(initiative_id="ISP-003", kr_ids="KR 1.1", okr_id="OKR 1",
                       name="RBAC Automation", status="On Track", owner="Shawn",
                       team="IAM", investment_dollars=380000),
        ],
    )


@pytest.fixture
def okr_store(tmp_path):
    store = OKRStore(tmp_path / "okr")
    old = mcp_server._state.okr_store
    mcp_server._state.okr_store = store
    yield store
    mcp_server._state.okr_store = old


class TestRefreshOkrFromSharepoint:
    @pytest.mark.asyncio
    async def test_happy_path(self, okr_store, tmp_path):
        dest = tmp_path / "okr" / "test.xlsx"
        snapshot = _make_snapshot()

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True

        mock_dl = AsyncMock(return_value={
            "status": "downloaded",
            "path": str(dest),
            "size_bytes": 12345,
        })

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
             patch("okr.parser.parse_okr_spreadsheet", return_value=snapshot), \
             patch("mcp_tools.okr_tools.app_config") as mock_config:

            mock_config.OKR_SHAREPOINT_URL = "https://sp.com/doc?action=default"
            mock_config.OKR_SPREADSHEET_DEFAULT = dest

            result = json.loads(await okr_tools.refresh_okr_from_sharepoint())

            assert result["status"] == "refreshed"
            assert result["download"]["size_bytes"] == 12345
            assert result["parsed"]["objectives"] == 1

    @pytest.mark.asyncio
    async def test_browser_launch_failure(self, okr_store, tmp_path):
        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = False
        mock_manager.launch.return_value = {
            "status": "error",
            "error": "Chromium not found.",
        }

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("mcp_tools.okr_tools.app_config") as mock_config:
            mock_config.OKR_SHAREPOINT_URL = "https://sp.com/doc"
            mock_config.OKR_SPREADSHEET_DEFAULT = tmp_path / "out.xlsx"

            result = json.loads(await okr_tools.refresh_okr_from_sharepoint())

            assert result["status"] == "error"
            assert result["step"] == "browser_launch"

    @pytest.mark.asyncio
    async def test_browser_auto_launch(self, okr_store, tmp_path):
        """Browser not running but launch succeeds, then download works."""
        dest = tmp_path / "out.xlsx"
        snapshot = _make_snapshot()

        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = False
        mock_manager.launch.return_value = {"status": "launched", "pid": 1234}

        mock_dl = AsyncMock(return_value={
            "status": "downloaded",
            "path": str(dest),
            "size_bytes": 5000,
        })

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
             patch("okr.parser.parse_okr_spreadsheet", return_value=snapshot), \
             patch("mcp_tools.okr_tools.app_config") as mock_config:

            mock_config.OKR_SHAREPOINT_URL = "https://sp.com/doc"
            mock_config.OKR_SPREADSHEET_DEFAULT = dest

            result = json.loads(await okr_tools.refresh_okr_from_sharepoint())

            assert result["status"] == "refreshed"
            mock_manager.launch.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_failure(self, okr_store, tmp_path):
        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True

        mock_dl = AsyncMock(return_value={
            "status": "auth_required",
            "error": "Timed out",
        })

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
             patch("mcp_tools.okr_tools.app_config") as mock_config:

            mock_config.OKR_SHAREPOINT_URL = "https://sp.com/doc"
            mock_config.OKR_SPREADSHEET_DEFAULT = tmp_path / "out.xlsx"

            result = json.loads(await okr_tools.refresh_okr_from_sharepoint())

            assert result["status"] == "auth_required"
            assert result["step"] == "download"

    @pytest.mark.asyncio
    async def test_parse_failure(self, okr_store, tmp_path):
        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True

        mock_dl = AsyncMock(return_value={
            "status": "downloaded",
            "path": str(tmp_path / "out.xlsx"),
            "size_bytes": 5000,
        })

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
             patch("okr.parser.parse_okr_spreadsheet", side_effect=ValueError("Bad format")), \
             patch("mcp_tools.okr_tools.app_config") as mock_config:

            mock_config.OKR_SHAREPOINT_URL = "https://sp.com/doc"
            mock_config.OKR_SPREADSHEET_DEFAULT = tmp_path / "out.xlsx"

            result = json.loads(await okr_tools.refresh_okr_from_sharepoint())

            assert result["status"] == "error"
            assert result["step"] == "parse"
            assert "Bad format" in result["error"]

    @pytest.mark.asyncio
    async def test_custom_url(self, okr_store, tmp_path):
        mock_manager = MagicMock()
        mock_manager.is_alive.return_value = True
        snapshot = _make_snapshot()

        mock_dl = AsyncMock(return_value={
            "status": "downloaded",
            "path": str(tmp_path / "out.xlsx"),
            "size_bytes": 9999,
        })

        with patch("browser.manager.TeamsBrowserManager", return_value=mock_manager), \
             patch("browser.sharepoint_download.download_sharepoint_file", mock_dl), \
             patch("okr.parser.parse_okr_spreadsheet", return_value=snapshot), \
             patch("mcp_tools.okr_tools.app_config") as mock_config:

            mock_config.OKR_SHAREPOINT_URL = "https://default.com/doc"
            mock_config.OKR_SPREADSHEET_DEFAULT = tmp_path / "out.xlsx"

            custom_url = "https://custom.sharepoint.com/doc?action=view"
            result = json.loads(await okr_tools.refresh_okr_from_sharepoint(
                sharepoint_url=custom_url
            ))

            assert result["status"] == "refreshed"
            # Verify the custom URL was passed to download
            mock_dl.assert_called_once()
            call_args = mock_dl.call_args
            assert call_args[0][1] == custom_url
