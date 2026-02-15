# tests/test_apple_mail.py
"""Unit tests for MailStore (apple_mail/mail.py).

All AppleScript calls are mocked via _run_applescript so osascript is never invoked.
"""

import base64
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from apple_mail.mail import (
    MailStore,
    _escape_osascript,
    _parse_fields,
    _parse_records,
    _run_applescript,
)


# ---------------------------------------------------------------------------
# Tests: _escape_osascript
# ---------------------------------------------------------------------------


class TestEscapeOsascript:
    def test_escape_quotes(self):
        assert _escape_osascript('He said "hello"') == 'He said \\"hello\\"'

    def test_escape_backslashes(self):
        assert _escape_osascript("path\\to\\file") == "path\\\\to\\\\file"

    def test_escape_both(self):
        result = _escape_osascript('quote\\" and backslash\\')
        assert result == 'quote\\\\\\" and backslash\\\\'

    def test_escape_empty_string(self):
        assert _escape_osascript("") == ""


# ---------------------------------------------------------------------------
# Tests: _run_applescript
# ---------------------------------------------------------------------------


class TestRunApplescript:
    @patch("apple_mail.mail._IS_MACOS", True)
    @patch("apple_mail.mail.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout="  hello world  ", returncode=0)
        result = _run_applescript("some script")
        assert result == {"output": "hello world"}
        mock_run.assert_called_once()

    @patch("apple_mail.mail._IS_MACOS", True)
    @patch("apple_mail.mail.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("osascript", 15)
        result = _run_applescript("some script")
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("apple_mail.mail._IS_MACOS", True)
    @patch("apple_mail.mail.subprocess.run")
    def test_called_process_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "osascript", stderr="bad script"
        )
        result = _run_applescript("some script")
        assert "error" in result
        assert "osascript failed" in result["error"]

    @patch("apple_mail.mail._IS_MACOS", True)
    @patch("apple_mail.mail.subprocess.run")
    def test_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = _run_applescript("some script")
        assert "error" in result
        assert "osascript not found" in result["error"]

    @patch("apple_mail.mail._IS_MACOS", False)
    def test_non_darwin(self):
        result = _run_applescript("some script")
        assert "error" in result
        assert "only available on macOS" in result["error"]


# ---------------------------------------------------------------------------
# Tests: _parse_records
# ---------------------------------------------------------------------------


class TestParseRecords:
    def test_single_record(self):
        raw = "INBOX|||Work|||5"
        records = _parse_records(raw)
        assert len(records) == 1
        assert records[0] == "INBOX|||Work|||5"

    def test_multiple_records(self):
        raw = "INBOX|||Work|||5\n~~~RECORD~~~\nSent|||Work|||0\n~~~RECORD~~~\n"
        records = _parse_records(raw)
        assert len(records) == 2
        assert records[0] == "INBOX|||Work|||5"
        assert records[1] == "Sent|||Work|||0"

    def test_empty(self):
        assert _parse_records("") == []
        assert _parse_records("   ") == []
        assert _parse_records(None) == []


# ---------------------------------------------------------------------------
# Tests: _parse_fields
# ---------------------------------------------------------------------------


class TestParseFields:
    def test_normal_fields(self):
        record = "INBOX|||Work Account|||5"
        fields = _parse_fields(record)
        assert fields == ["INBOX", "Work Account", "5"]

    def test_missing_fields(self):
        record = "INBOX"
        fields = _parse_fields(record)
        assert fields == ["INBOX"]

    def test_empty(self):
        assert _parse_fields("") == []
        assert _parse_fields(None) == []


# ---------------------------------------------------------------------------
# Tests: MailStore.list_mailboxes
# ---------------------------------------------------------------------------


class TestListMailboxes:
    def test_multiple_mailboxes(self):
        store = MailStore()
        mock_output = "INBOX|||Work Account|||5\n~~~RECORD~~~\nSent|||Work Account|||0\n~~~RECORD~~~\n"
        with patch("apple_mail.mail._run_applescript", return_value={"output": mock_output}):
            result = store.list_mailboxes()
            assert len(result) == 2
            assert result[0] == {"name": "INBOX", "account": "Work Account", "unread_count": 5}
            assert result[1] == {"name": "Sent", "account": "Work Account", "unread_count": 0}

    def test_empty(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": ""}):
            result = store.list_mailboxes()
            assert result == []

    def test_error_from_script(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"error": "Mail operation timed out"}):
            result = store.list_mailboxes()
            assert len(result) == 1
            assert result[0] == {"error": "Mail operation timed out"}


# ---------------------------------------------------------------------------
# Tests: MailStore.get_messages
# ---------------------------------------------------------------------------


class TestGetMessages:
    def test_get_recent(self):
        store = MailStore()
        mock_output = (
            "msg-1|||Subject One|||sender@test.com|||Jan 1, 2025|||true|||false\n"
            "~~~RECORD~~~\n"
            "msg-2|||Subject Two|||other@test.com|||Jan 2, 2025|||false|||true\n"
            "~~~RECORD~~~\n"
        )
        with patch("apple_mail.mail._run_applescript", return_value={"output": mock_output}):
            result = store.get_messages()
            assert len(result) == 2
            assert result[0]["message_id"] == "msg-1"
            assert result[0]["subject"] == "Subject One"
            assert result[0]["read"] is True
            assert result[0]["flagged"] is False
            assert result[1]["read"] is False
            assert result[1]["flagged"] is True

    def test_with_account_filter(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": ""}) as mock_run:
            store.get_messages(mailbox="INBOX", account="Work")
            # Verify the script includes the account reference
            call_args = mock_run.call_args[0][0]
            assert 'account "Work"' in call_args

    def test_empty(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": ""}):
            result = store.get_messages()
            assert result == []

    def test_limit_capped_at_100(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": ""}) as mock_run:
            store.get_messages(limit=500)
            call_args = mock_run.call_args[0][0]
            assert "100" in call_args

    def test_error(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"error": "timeout"}):
            result = store.get_messages()
            assert len(result) == 1
            assert result[0] == {"error": "timeout"}


# ---------------------------------------------------------------------------
# Tests: MailStore.get_message
# ---------------------------------------------------------------------------


class TestGetMessage:
    def test_full_message_with_body_decode(self):
        store = MailStore()
        body_text = "Hello, this is the email body."
        b64_body = base64.b64encode(body_text.encode("utf-8")).decode("utf-8")
        mock_output = (
            f"Test Subject|||sender@test.com|||Jan 1, 2025|||true|||false"
            f"|||alice@test.com,bob@test.com,|||cc@test.com,|||{b64_body}"
        )
        with patch("apple_mail.mail._run_applescript", return_value={"output": mock_output}):
            result = store.get_message("msg-123")
            assert result["message_id"] == "msg-123"
            assert result["subject"] == "Test Subject"
            assert result["sender"] == "sender@test.com"
            assert result["read"] is True
            assert result["flagged"] is False
            assert result["to"] == ["alice@test.com", "bob@test.com"]
            assert result["cc"] == ["cc@test.com"]
            assert result["body"] == body_text

    def test_not_found(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "ERROR: Message not found"}):
            result = store.get_message("missing-id")
            assert "error" in result
            assert "not found" in result["error"]

    def test_error(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"error": "osascript failed: bad"}):
            result = store.get_message("msg-123")
            assert "error" in result
            assert "osascript failed" in result["error"]


# ---------------------------------------------------------------------------
# Tests: MailStore.search_messages
# ---------------------------------------------------------------------------


class TestSearchMessages:
    def test_results_found(self):
        store = MailStore()
        mock_output = (
            "msg-10|||Meeting Notes|||boss@co.com|||Jan 5, 2025|||false|||false\n"
            "~~~RECORD~~~\n"
        )
        with patch("apple_mail.mail._run_applescript", return_value={"output": mock_output}):
            result = store.search_messages("Meeting")
            assert len(result) == 1
            assert result[0]["subject"] == "Meeting Notes"
            assert result[0]["mailbox"] == "INBOX"

    def test_no_results(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": ""}):
            result = store.search_messages("nonexistent")
            assert result == []

    def test_with_account_filter(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": ""}) as mock_run:
            store.search_messages("test", account="Personal")
            call_args = mock_run.call_args[0][0]
            assert 'account "Personal"' in call_args


# ---------------------------------------------------------------------------
# Tests: MailStore.mark_read
# ---------------------------------------------------------------------------


class TestMarkRead:
    def test_mark_read(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "OK"}):
            result = store.mark_read("msg-1", read=True)
            assert result["status"] == "ok"
            assert result["read"] is True

    def test_mark_unread(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "OK"}):
            result = store.mark_read("msg-1", read=False)
            assert result["status"] == "ok"
            assert result["read"] is False

    def test_not_found(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "ERROR: Message not found"}):
            result = store.mark_read("missing-id")
            assert "error" in result
            assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Tests: MailStore.mark_flagged
# ---------------------------------------------------------------------------


class TestMarkFlagged:
    def test_flag(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "OK"}):
            result = store.mark_flagged("msg-1", flagged=True)
            assert result["status"] == "ok"
            assert result["flagged"] is True

    def test_unflag(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "OK"}):
            result = store.mark_flagged("msg-1", flagged=False)
            assert result["status"] == "ok"
            assert result["flagged"] is False

    def test_not_found(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "ERROR: Message not found"}):
            result = store.mark_flagged("missing-id")
            assert "error" in result
            assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Tests: MailStore.move_message
# ---------------------------------------------------------------------------


class TestMoveMessage:
    def test_success(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "OK"}):
            result = store.move_message("msg-1", "Archive")
            assert result["status"] == "ok"
            assert result["moved_to"] == "Archive"

    def test_not_found(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "ERROR: Message not found"}):
            result = store.move_message("missing-id", "Archive")
            assert "error" in result
            assert "not found" in result["error"]

    def test_with_account(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "OK"}) as mock_run:
            store.move_message("msg-1", "Archive", target_account="Work")
            call_args = mock_run.call_args[0][0]
            assert 'account "Work"' in call_args


# ---------------------------------------------------------------------------
# Tests: MailStore.send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    @patch("apple_mail.mail.Notifier")
    def test_success(self, mock_notifier_cls):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"output": "OK"}):
            result = store.send_message(
                to=["alice@test.com"],
                subject="Hello",
                body="World",
                confirm_send=True,
            )
            assert result["status"] == "sent"
            assert result["to"] == ["alice@test.com"]
            mock_notifier_cls.send.assert_called_once()

    def test_confirm_send_false(self):
        store = MailStore()
        result = store.send_message(
            to=["alice@test.com"],
            subject="Hello",
            body="World",
            confirm_send=False,
        )
        assert "error" in result
        assert "confirm_send" in result["error"]

    @patch("apple_mail.mail.Notifier")
    def test_send_failure(self, mock_notifier_cls):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"error": "osascript failed: send error"}):
            result = store.send_message(
                to=["alice@test.com"],
                subject="Hello",
                body="World",
                confirm_send=True,
            )
            assert "error" in result
            mock_notifier_cls.send.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: get_unread_count (derived from list_mailboxes)
# ---------------------------------------------------------------------------


class TestGetUnreadCount:
    def test_has_unread(self):
        store = MailStore()
        mock_output = "INBOX|||Work|||3\n~~~RECORD~~~\nSent|||Work|||0\n~~~RECORD~~~\n"
        with patch("apple_mail.mail._run_applescript", return_value={"output": mock_output}):
            mailboxes = store.list_mailboxes()
            total_unread = sum(mb.get("unread_count", 0) for mb in mailboxes)
            assert total_unread == 3

    def test_zero(self):
        store = MailStore()
        mock_output = "INBOX|||Work|||0\n~~~RECORD~~~\n"
        with patch("apple_mail.mail._run_applescript", return_value={"output": mock_output}):
            mailboxes = store.list_mailboxes()
            total_unread = sum(mb.get("unread_count", 0) for mb in mailboxes)
            assert total_unread == 0

    def test_error(self):
        store = MailStore()
        with patch("apple_mail.mail._run_applescript", return_value={"error": "Mail not running"}):
            result = store.list_mailboxes()
            assert len(result) == 1
            assert "error" in result[0]
