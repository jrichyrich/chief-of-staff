"""Tests for browser.sharepoint_download."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser.sharepoint_download import (
    _extract_filename,
    _extract_site_base,
    _extract_unique_id,
    _make_download_url,
    download_sharepoint_file,
)


def _make_download_info(mock_download):
    """Create a mock matching Playwright's EventContextManager.value (a Future)."""
    future = asyncio.get_event_loop().create_future()
    future.set_result(mock_download)
    return MagicMock(value=future)


# --- helper function tests ---

class TestExtractUniqueId:
    def test_extracts_guid(self):
        url = "https://sp.com/doc?sourcedoc=%7BDFD697F4-04F3-4583-BC4E-FC55BE913409%7D&file=test.xlsx"
        assert _extract_unique_id(url) == "DFD697F4-04F3-4583-BC4E-FC55BE913409"

    def test_case_insensitive(self):
        url = "https://sp.com/doc?sourcedoc=%7bdfd697f4-04f3-4583-bc4e-fc55be913409%7d"
        assert _extract_unique_id(url) == "dfd697f4-04f3-4583-bc4e-fc55be913409"

    def test_returns_none_when_missing(self):
        assert _extract_unique_id("https://sp.com/doc?file=test.xlsx") is None


class TestExtractSiteBase:
    def test_with_sites_path(self):
        url = "https://chgcloud.sharepoint.com/sites/ISPTeam/_layouts/15/Doc.aspx?foo=1"
        assert _extract_site_base(url) == "https://chgcloud.sharepoint.com/sites/ISPTeam"

    def test_sharing_link_prefix(self):
        url = "https://chgcloud.sharepoint.com/:x:/r/sites/ISPTeam/_layouts/15/Doc.aspx?foo=1"
        assert _extract_site_base(url) == "https://chgcloud.sharepoint.com/sites/ISPTeam"

    def test_root_site(self):
        url = "https://sp.com/doc"
        assert _extract_site_base(url) == "https://sp.com"

    def test_personal_onedrive(self):
        url = "https://chgcloud-my.sharepoint.com/:p:/r/personal/jasricha_mychg_com/_layouts/15/Doc.aspx?foo=1"
        assert _extract_site_base(url) == "https://chgcloud-my.sharepoint.com/personal/jasricha_mychg_com"

    def test_returns_none_for_garbage(self):
        assert _extract_site_base("not-a-url") is None


class TestExtractFilename:
    def test_extracts(self):
        url = "https://sp.com/doc?file=2026_OKR.xlsx&action=default"
        assert _extract_filename(url) == "2026_OKR.xlsx"

    def test_none_when_missing(self):
        assert _extract_filename("https://sp.com/doc") is None


# --- _make_download_url tests ---

class TestMakeDownloadUrl:
    def test_uses_download_aspx_when_guid_present(self):
        url = (
            "https://chgcloud.sharepoint.com/:x:/r/sites/ISPTeam/_layouts/15/Doc.aspx"
            "?sourcedoc=%7BDFD697F4-04F3-4583-BC4E-FC55BE913409%7D"
            "&file=test.xlsx&action=default&mobileredirect=true"
        )
        result = _make_download_url(url)
        assert result == (
            "https://chgcloud.sharepoint.com/sites/ISPTeam"
            "/_layouts/15/download.aspx"
            "?UniqueId=%7BDFD697F4-04F3-4583-BC4E-FC55BE913409%7D"
        )

    def test_falls_back_to_action_download(self):
        url = "https://sp.com/doc?action=edit&other=1"
        result = _make_download_url(url)
        assert "action=download" in result
        assert "action=edit" not in result

    def test_appends_action_when_missing(self):
        url = "https://sp.com/doc?file=test.xlsx"
        result = _make_download_url(url)
        assert result.endswith("&action=download")

    def test_appends_with_question_mark_when_no_params(self):
        url = "https://sp.com/doc"
        result = _make_download_url(url)
        assert result == "https://sp.com/doc?action=download"


# --- download_sharepoint_file tests ---

def _mock_page_with_download(mock_download):
    """Create a mock page that successfully downloads via expect_download."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.close = AsyncMock()

    download_cm = AsyncMock()
    download_cm.__aenter__ = AsyncMock(
        return_value=_make_download_info(mock_download)
    )
    download_cm.__aexit__ = AsyncMock(return_value=False)
    mock_page.expect_download = MagicMock(return_value=download_cm)
    return mock_page


def _mock_manager(mock_page):
    """Create a mock manager that returns a browser with one context + page."""
    manager = MagicMock()
    manager.is_alive.return_value = True

    mock_ctx = MagicMock()
    mock_ctx.new_page = AsyncMock(return_value=mock_page)

    mock_browser = MagicMock()
    mock_browser.contexts = [mock_ctx]

    mock_pw = AsyncMock()
    manager.connect = AsyncMock(return_value=(mock_pw, mock_browser))
    return manager


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
    async def test_happy_path_direct_download(self, tmp_path):
        dest = tmp_path / "subdir" / "out.xlsx"

        mock_download = AsyncMock()
        mock_download.failure = AsyncMock(return_value=None)

        async def fake_save_as(path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"PK\x03\x04fake-xlsx-content")
        mock_download.save_as = fake_save_as

        mock_page = _mock_page_with_download(mock_download)
        manager = _mock_manager(mock_page)

        result = await download_sharepoint_file(
            manager, "https://sp.com/doc?action=default", dest
        )
        assert result["status"] == "downloaded"
        assert result["size_bytes"] > 0
        assert result["method"] == "direct_url"
        assert dest.exists()

    @pytest.mark.asyncio
    async def test_download_failure_reported(self, tmp_path):
        mock_download = AsyncMock()
        mock_download.failure = AsyncMock(return_value="net::ERR_FAILED")

        mock_page = _mock_page_with_download(mock_download)
        manager = _mock_manager(mock_page)

        result = await download_sharepoint_file(
            manager, "https://sp.com/doc", tmp_path / "out.xlsx"
        )
        # Direct download raises RuntimeError from failure, which is caught
        # Then the fallback will run (and may fail too in test context)
        assert result["status"] in ("error", "auth_required")

    @pytest.mark.asyncio
    async def test_empty_file(self, tmp_path):
        dest = tmp_path / "out.xlsx"

        mock_download = AsyncMock()
        mock_download.failure = AsyncMock(return_value=None)

        async def fake_save_empty(path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"")
        mock_download.save_as = fake_save_empty

        mock_page = _mock_page_with_download(mock_download)
        manager = _mock_manager(mock_page)

        result = await download_sharepoint_file(
            manager, "https://sp.com/doc", dest
        )
        assert result["status"] in ("error", "auth_required")
