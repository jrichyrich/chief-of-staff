"""Tests for browser.manager — TeamsBrowserManager."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from browser.manager import TeamsBrowserManager


@pytest.fixture
def manager(tmp_path):
    return TeamsBrowserManager(
        state_path=tmp_path / "browser.json",
        profile_dir=tmp_path / "profile",
    )


class TestStateFile:
    def test_load_state_no_file(self, manager):
        """_load_state returns None when no state file exists."""
        assert manager._load_state() is None

    def test_save_and_load_state(self, manager):
        """Round-trip save and load returns the same state dict."""
        state = {"pid": 12345, "cdp_port": 9222}
        manager._save_state(state)
        loaded = manager._load_state()
        assert loaded == state

    def test_load_state_corrupt_json(self, manager):
        """_load_state returns None for malformed JSON."""
        manager.state_path.parent.mkdir(parents=True, exist_ok=True)
        manager.state_path.write_text("not json{{{")
        assert manager._load_state() is None


class TestHealthCheck:
    def test_is_alive_responds_200(self, manager):
        """is_alive returns True when CDP responds with 200."""
        with patch("browser.manager.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b'{"Browser":"Chrome"}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            assert manager.is_alive() is True

    def test_is_alive_connection_refused(self, manager):
        """is_alive returns False when connection is refused."""
        with patch("browser.manager.urlopen", side_effect=OSError("Connection refused")):
            assert manager.is_alive() is False


class TestFindChromium:
    def test_find_chromium_returns_path(self, manager):
        """_find_chromium_path locates the Playwright-bundled Chromium."""
        path = manager._find_chromium_path()
        assert path is not None
        assert Path(path).exists()


class TestLaunch:
    def test_launch_already_running(self, manager):
        """launch returns already_running when CDP is alive."""
        manager._save_state({"pid": 999, "cdp_port": 9222})
        with patch.object(manager, "is_alive", return_value=True):
            result = manager.launch()
        assert result["status"] == "already_running"
        assert result["pid"] == 999

    def test_launch_no_chromium(self, manager):
        """launch returns error when Chromium binary is not found."""
        with patch.object(manager, "is_alive", return_value=False):
            with patch.object(TeamsBrowserManager, "_find_chromium_path", return_value=None):
                result = manager.launch()
        assert result["status"] == "error"
        assert "Chromium not found" in result["error"]


class TestClose:
    def test_close_sends_sigterm(self, manager):
        """close sends SIGTERM to the stored PID and clears state."""
        manager._save_state({"pid": 12345, "cdp_port": 9222})
        with patch("os.kill") as mock_kill:
            with patch.object(manager, "is_alive", return_value=False):
                result = manager.close()
        mock_kill.assert_called_once_with(12345, 15)  # SIGTERM = 15
        assert result["status"] == "closed"
        assert manager._load_state() is None

    def test_close_no_state(self, manager):
        """close returns closed when no state file exists."""
        with patch.object(manager, "is_alive", return_value=False):
            result = manager.close()
        assert result["status"] == "closed"

    def test_close_process_already_dead(self, manager):
        """close handles ProcessLookupError gracefully."""
        manager._save_state({"pid": 99999, "cdp_port": 9222})
        with patch("os.kill", side_effect=ProcessLookupError):
            with patch.object(manager, "is_alive", return_value=False):
                result = manager.close()
        assert result["status"] == "closed"

    def test_close_browser_still_running(self, manager):
        """close returns error when browser survives SIGTERM."""
        manager._save_state({"pid": 12345, "cdp_port": 9222})
        with patch("os.kill"):
            with patch.object(manager, "is_alive", return_value=True):
                with patch("browser.manager.time.sleep"):
                    result = manager.close()
        assert result["status"] == "error"
        assert "still running" in result["error"]
