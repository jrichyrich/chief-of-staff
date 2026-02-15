# tests/test_apple_notifications.py
"""Unit tests for Notifier (apple_notifications/notifier.py).

All subprocess calls are mocked so osascript is never actually invoked.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Tests: send()
# ---------------------------------------------------------------------------


class TestSendNotification:
    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_send_basic(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.return_value = MagicMock(returncode=0)

        result = Notifier.send("Test Title", "Hello world")

        assert result["status"] == "sent"
        assert result["title"] == "Test Title"
        assert result["message"] == "Hello world"
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        script = call_args[0][0][2]  # ["osascript", "-e", script]
        assert 'display notification "Hello world" with title "Test Title"' in script
        assert 'sound name "default"' in script

    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_send_with_subtitle(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.return_value = MagicMock(returncode=0)

        result = Notifier.send("Title", "Message", subtitle="Sub")

        assert result["status"] == "sent"
        script = mock_run.call_args[0][0][2]
        assert 'subtitle "Sub"' in script

    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_send_with_custom_sound(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.return_value = MagicMock(returncode=0)

        result = Notifier.send("Title", "Message", sound="Ping")

        assert result["status"] == "sent"
        script = mock_run.call_args[0][0][2]
        assert 'sound name "Ping"' in script

    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_send_no_sound(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.return_value = MagicMock(returncode=0)

        result = Notifier.send("Title", "Message", sound=None)

        assert result["status"] == "sent"
        script = mock_run.call_args[0][0][2]
        assert "sound name" not in script


# ---------------------------------------------------------------------------
# Tests: send_alert()
# ---------------------------------------------------------------------------


class TestSendAlert:
    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_send_alert_basic(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.return_value = MagicMock(returncode=0)

        result = Notifier.send_alert("Alert Title", "Alert message")

        assert result["status"] == "sent"
        assert result["title"] == "Alert Title"
        mock_run.assert_called_once()
        script = mock_run.call_args[0][0][2]
        assert 'display alert "Alert Title" message "Alert message"' in script


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


class TestNotificationErrors:
    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_subprocess_failure(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.side_effect = subprocess.CalledProcessError(
            1, "osascript", stderr="some error"
        )

        result = Notifier.send("Title", "Message")

        assert "error" in result
        assert "osascript failed" in result["error"]

    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_timeout(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.side_effect = subprocess.TimeoutExpired("osascript", 5)

        result = Notifier.send("Title", "Message")

        assert "error" in result
        assert "timed out" in result["error"]

    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_osascript_not_found(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.side_effect = FileNotFoundError()

        result = Notifier.send("Title", "Message")

        assert "error" in result
        assert "osascript not found" in result["error"]

    @patch("apple_notifications.notifier._IS_MACOS", False)
    def test_non_darwin_platform_send(self):
        from apple_notifications.notifier import Notifier

        result = Notifier.send("Title", "Message")

        assert "error" in result
        assert "only available on macOS" in result["error"]

    @patch("apple_notifications.notifier._IS_MACOS", False)
    def test_non_darwin_platform_send_alert(self):
        from apple_notifications.notifier import Notifier

        result = Notifier.send_alert("Title", "Message")

        assert "error" in result
        assert "only available on macOS" in result["error"]

    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_alert_timeout(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.side_effect = subprocess.TimeoutExpired("osascript", 30)

        result = Notifier.send_alert("Title", "Message")

        assert "error" in result
        assert "timed out" in result["error"]

    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_alert_subprocess_failure(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.side_effect = subprocess.CalledProcessError(
            1, "osascript", stderr="alert error"
        )

        result = Notifier.send_alert("Title", "Message")

        assert "error" in result
        assert "osascript failed" in result["error"]


# ---------------------------------------------------------------------------
# Tests: input sanitization
# ---------------------------------------------------------------------------


class TestInputSanitization:
    def test_escape_quotes_in_title(self):
        from apple_notifications.notifier import _escape_osascript

        result = _escape_osascript('He said "hello"')
        assert result == 'He said \\"hello\\"'

    def test_escape_backslashes(self):
        from apple_notifications.notifier import _escape_osascript

        result = _escape_osascript("path\\to\\file")
        assert result == "path\\\\to\\\\file"

    def test_escape_both(self):
        from apple_notifications.notifier import _escape_osascript

        result = _escape_osascript('quote\\" and backslash\\')
        assert result == 'quote\\\\\\" and backslash\\\\'

    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_quotes_escaped_in_notification(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.return_value = MagicMock(returncode=0)

        Notifier.send('Say "hi"', 'He said "bye"')

        script = mock_run.call_args[0][0][2]
        assert 'Say \\"hi\\"' in script
        assert 'He said \\"bye\\"' in script

    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_quotes_escaped_in_alert(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.return_value = MagicMock(returncode=0)

        Notifier.send_alert('Say "hi"', 'He said "bye"')

        script = mock_run.call_args[0][0][2]
        assert 'Say \\"hi\\"' in script
        assert 'He said \\"bye\\"' in script

    @patch("apple_notifications.notifier._IS_MACOS", True)
    @patch("apple_notifications.notifier.subprocess.run")
    def test_quotes_escaped_in_subtitle(self, mock_run):
        from apple_notifications.notifier import Notifier

        mock_run.return_value = MagicMock(returncode=0)

        Notifier.send("Title", "Message", subtitle='A "test"')

        script = mock_run.call_args[0][0][2]
        assert 'subtitle "A \\"test\\""' in script
