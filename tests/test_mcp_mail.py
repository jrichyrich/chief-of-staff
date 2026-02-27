# tests/test_mcp_mail.py
"""Tests for the MCP mail tool functions in mcp_server.py.

Follows the same pattern as tests/test_mcp_reminders.py: inject a mock
MailStore into mcp_server._state["mail_store"] and call the async tool
functions directly.
"""

import json
from unittest.mock import MagicMock

import pytest

import mcp_server


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mail_store():
    """Return a MagicMock that quacks like MailStore."""
    store = MagicMock()
    store.list_mailboxes.return_value = []
    store.get_messages.return_value = []
    store.get_message.return_value = {}
    store.search_messages.return_value = []
    store.mark_read.return_value = {}
    store.mark_flagged.return_value = {}
    store.move_message.return_value = {}
    store.reply_message.return_value = {}
    store.send_message.return_value = {}
    return store


@pytest.fixture
def mail_state(mock_mail_store):
    """Inject mock mail store into mcp_server._state, then clean up."""
    mcp_server._state["mail_store"] = mock_mail_store
    yield mock_mail_store
    mcp_server._state.pop("mail_store", None)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestMailToolsRegistered:
    def test_all_mail_tools_registered(self):
        """Verify all 9 mail tools are registered on the MCP server."""
        tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
        expected = [
            "list_mailboxes",
            "get_mail_messages",
            "get_mail_message",
            "search_mail",
            "mark_mail_read",
            "mark_mail_flagged",
            "move_mail_message",
            "reply_to_email",
            "send_email",
        ]
        for name in expected:
            assert name in tool_names, f"Mail tool '{name}' not registered"


# ---------------------------------------------------------------------------
# list_mailboxes
# ---------------------------------------------------------------------------


class TestListMailboxesTool:
    @pytest.mark.asyncio
    async def test_basic_call(self, mail_state):
        from mcp_tools.mail_tools import list_mailboxes

        mail_state.list_mailboxes.return_value = [
            {"name": "INBOX", "account": "Work", "unread_count": 5},
            {"name": "Sent", "account": "Work", "unread_count": 0},
        ]

        result = await list_mailboxes()
        data = json.loads(result)

        assert "results" in data
        assert len(data["results"]) == 2
        assert data["results"][0]["name"] == "INBOX"
        mail_state.list_mailboxes.assert_called_once()


# ---------------------------------------------------------------------------
# get_mail_messages
# ---------------------------------------------------------------------------


class TestGetMailMessagesTool:
    @pytest.mark.asyncio
    async def test_with_defaults(self, mail_state):
        from mcp_tools.mail_tools import get_mail_messages

        mail_state.get_messages.return_value = [
            {"message_id": "m1", "subject": "Test", "sender": "a@b.com"},
        ]

        result = await get_mail_messages()
        data = json.loads(result)

        assert len(data["results"]) == 1
        mail_state.get_messages.assert_called_once_with(
            mailbox="INBOX", account="", limit=25
        )

    @pytest.mark.asyncio
    async def test_with_filters(self, mail_state):
        from mcp_tools.mail_tools import get_mail_messages

        mail_state.get_messages.return_value = []

        result = await get_mail_messages(mailbox="Sent", account="Personal", limit=10)
        data = json.loads(result)

        assert data["results"] == []
        mail_state.get_messages.assert_called_once_with(
            mailbox="Sent", account="Personal", limit=10
        )


# ---------------------------------------------------------------------------
# get_mail_message
# ---------------------------------------------------------------------------


class TestGetMailMessageTool:
    @pytest.mark.asyncio
    async def test_found(self, mail_state):
        from mcp_tools.mail_tools import get_mail_message

        mail_state.get_message.return_value = {
            "message_id": "msg-1",
            "subject": "Hello",
            "body": "World",
        }

        result = await get_mail_message(message_id="msg-1")
        data = json.loads(result)

        assert data["message_id"] == "msg-1"
        assert data["body"] == "World"
        mail_state.get_message.assert_called_once_with("msg-1")

    @pytest.mark.asyncio
    async def test_not_found(self, mail_state):
        from mcp_tools.mail_tools import get_mail_message

        mail_state.get_message.return_value = {"error": "ERROR: Message not found"}

        result = await get_mail_message(message_id="missing")
        data = json.loads(result)

        assert "error" in data


# ---------------------------------------------------------------------------
# search_mail
# ---------------------------------------------------------------------------


class TestSearchMailTool:
    @pytest.mark.asyncio
    async def test_basic_search(self, mail_state):
        from mcp_tools.mail_tools import search_mail

        mail_state.search_messages.return_value = [
            {"message_id": "s1", "subject": "Meeting Notes"},
        ]

        result = await search_mail(query="Meeting")
        data = json.loads(result)

        assert len(data["results"]) == 1
        mail_state.search_messages.assert_called_once_with(
            query="Meeting", mailbox="INBOX", account="", limit=25
        )

    @pytest.mark.asyncio
    async def test_with_filters(self, mail_state):
        from mcp_tools.mail_tools import search_mail

        mail_state.search_messages.return_value = []

        result = await search_mail(query="report", mailbox="Sent", account="Work", limit=10)
        data = json.loads(result)

        assert data["results"] == []
        mail_state.search_messages.assert_called_once_with(
            query="report", mailbox="Sent", account="Work", limit=10
        )


# ---------------------------------------------------------------------------
# mark_mail_read
# ---------------------------------------------------------------------------


class TestMarkMailReadTool:
    @pytest.mark.asyncio
    async def test_mark_read(self, mail_state):
        from mcp_tools.mail_tools import mark_mail_read

        mail_state.mark_read.return_value = {"status": "ok", "message_id": "m1", "read": True}

        result = await mark_mail_read(message_id="m1", read="true")
        data = json.loads(result)

        assert data["status"] == "ok"
        assert data["read"] is True
        mail_state.mark_read.assert_called_once_with("m1", read=True)

    @pytest.mark.asyncio
    async def test_mark_unread(self, mail_state):
        from mcp_tools.mail_tools import mark_mail_read

        mail_state.mark_read.return_value = {"status": "ok", "message_id": "m1", "read": False}

        result = await mark_mail_read(message_id="m1", read="false")
        data = json.loads(result)

        assert data["read"] is False
        mail_state.mark_read.assert_called_once_with("m1", read=False)

    @pytest.mark.asyncio
    async def test_string_true_false_conversion(self, mail_state):
        """Verify string 'true'/'false' is converted to bool for MailStore."""
        from mcp_tools.mail_tools import mark_mail_read

        mail_state.mark_read.return_value = {"status": "ok"}

        await mark_mail_read(message_id="m1", read="TRUE")
        mail_state.mark_read.assert_called_with("m1", read=True)

        await mark_mail_read(message_id="m1", read="False")
        mail_state.mark_read.assert_called_with("m1", read=False)


# ---------------------------------------------------------------------------
# mark_mail_flagged
# ---------------------------------------------------------------------------


class TestMarkMailFlaggedTool:
    @pytest.mark.asyncio
    async def test_flag(self, mail_state):
        from mcp_tools.mail_tools import mark_mail_flagged

        mail_state.mark_flagged.return_value = {"status": "ok", "message_id": "m1", "flagged": True}

        result = await mark_mail_flagged(message_id="m1", flagged="true")
        data = json.loads(result)

        assert data["status"] == "ok"
        mail_state.mark_flagged.assert_called_once_with("m1", flagged=True)

    @pytest.mark.asyncio
    async def test_unflag(self, mail_state):
        from mcp_tools.mail_tools import mark_mail_flagged

        mail_state.mark_flagged.return_value = {"status": "ok", "message_id": "m1", "flagged": False}

        result = await mark_mail_flagged(message_id="m1", flagged="false")
        data = json.loads(result)

        assert data["flagged"] is False
        mail_state.mark_flagged.assert_called_once_with("m1", flagged=False)


# ---------------------------------------------------------------------------
# move_mail_message
# ---------------------------------------------------------------------------


class TestMoveMailMessageTool:
    @pytest.mark.asyncio
    async def test_success(self, mail_state):
        from mcp_tools.mail_tools import move_mail_message

        mail_state.move_message.return_value = {"status": "ok", "moved_to": "Archive"}

        result = await move_mail_message(message_id="m1", target_mailbox="Archive")
        data = json.loads(result)

        assert data["status"] == "ok"
        assert data["moved_to"] == "Archive"
        mail_state.move_message.assert_called_once_with(
            "m1", target_mailbox="Archive", target_account=""
        )

    @pytest.mark.asyncio
    async def test_with_account(self, mail_state):
        from mcp_tools.mail_tools import move_mail_message

        mail_state.move_message.return_value = {"status": "ok", "moved_to": "Archive"}

        result = await move_mail_message(
            message_id="m1", target_mailbox="Archive", target_account="Work"
        )
        data = json.loads(result)

        assert data["status"] == "ok"
        mail_state.move_message.assert_called_once_with(
            "m1", target_mailbox="Archive", target_account="Work"
        )


# ---------------------------------------------------------------------------
# reply_to_email
# ---------------------------------------------------------------------------


class TestReplyToEmailTool:
    @pytest.mark.asyncio
    async def test_basic_reply(self, mail_state):
        from mcp_tools.mail_tools import reply_to_email

        mail_state.reply_message.return_value = {
            "status": "replied",
            "message_id": "msg-123",
            "reply_all": False,
        }

        result = await reply_to_email(
            message_id="msg-123",
            body="Thanks for the update.",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "replied"
        assert data["message_id"] == "msg-123"
        assert data["reply_all"] is False
        mail_state.reply_message.assert_called_once_with(
            message_id="msg-123",
            body="Thanks for the update.",
            reply_all=False,
            cc=None,
            bcc=None,
            html_body=None,
            confirm_send=True,
        )

    @pytest.mark.asyncio
    async def test_reply_all(self, mail_state):
        from mcp_tools.mail_tools import reply_to_email

        mail_state.reply_message.return_value = {
            "status": "replied",
            "message_id": "msg-456",
            "reply_all": True,
        }

        result = await reply_to_email(
            message_id="msg-456",
            body="Replying to all.",
            reply_all=True,
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["reply_all"] is True
        call_kwargs = mail_state.reply_message.call_args[1]
        assert call_kwargs["reply_all"] is True

    @pytest.mark.asyncio
    async def test_reply_with_cc_bcc(self, mail_state):
        from mcp_tools.mail_tools import reply_to_email

        mail_state.reply_message.return_value = {"status": "replied", "message_id": "msg-789", "reply_all": False}

        result = await reply_to_email(
            message_id="msg-789",
            body="Adding people.",
            cc="extra@test.com, another@test.com",
            bcc="hidden@test.com",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "replied"
        call_kwargs = mail_state.reply_message.call_args[1]
        assert call_kwargs["cc"] == ["extra@test.com", "another@test.com"]
        assert call_kwargs["bcc"] == ["hidden@test.com"]

    @pytest.mark.asyncio
    async def test_confirm_send_false(self, mail_state):
        from mcp_tools.mail_tools import reply_to_email

        mail_state.reply_message.return_value = {
            "error": "confirm_send must be True. Please confirm with the user before sending."
        }

        result = await reply_to_email(
            message_id="msg-123",
            body="Reply text",
            confirm_send=False,
        )
        data = json.loads(result)

        assert "error" in data
        assert "confirm_send" in data["error"]

    @pytest.mark.asyncio
    async def test_reply_error(self, mail_state):
        from mcp_tools.mail_tools import reply_to_email

        mail_state.reply_message.side_effect = RuntimeError("Mail connection lost")

        result = await reply_to_email(
            message_id="msg-123",
            body="Reply text",
            confirm_send=True,
        )
        data = json.loads(result)

        assert "error" in data
        assert "Mail connection lost" in data["error"]

    @pytest.mark.asyncio
    async def test_reply_with_html_body(self, mail_state):
        from mcp_tools.mail_tools import reply_to_email

        mail_state.reply_message.return_value = {"status": "replied", "message_id": "msg-h", "reply_all": False}

        await reply_to_email(
            message_id="msg-h",
            body="Plain fallback",
            html_body="<p>Rich reply</p>",
            confirm_send=True,
        )
        call_kwargs = mail_state.reply_message.call_args[1]
        assert call_kwargs["html_body"] == "<p>Rich reply</p>"

    @pytest.mark.asyncio
    async def test_reply_empty_html_body_passes_none(self, mail_state):
        from mcp_tools.mail_tools import reply_to_email

        mail_state.reply_message.return_value = {"status": "replied", "message_id": "msg-p", "reply_all": False}

        await reply_to_email(
            message_id="msg-p",
            body="Plain only",
            html_body="",
            confirm_send=True,
        )
        call_kwargs = mail_state.reply_message.call_args[1]
        assert call_kwargs["html_body"] is None


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------


class TestSendEmailTool:
    @pytest.mark.asyncio
    async def test_basic_send(self, mail_state):
        from mcp_tools.mail_tools import send_email

        mail_state.send_message.return_value = {
            "status": "sent",
            "to": ["alice@test.com", "bob@test.com"],
            "subject": "Hello",
        }

        result = await send_email(
            to="alice@test.com, bob@test.com",
            subject="Hello",
            body="World",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        # Verify comma-split happened correctly
        call_kwargs = mail_state.send_message.call_args[1]
        assert call_kwargs["to"] == ["alice@test.com", "bob@test.com"]
        assert call_kwargs["subject"] == "Hello"
        assert call_kwargs["body"] == "World"
        assert call_kwargs["confirm_send"] is True

    @pytest.mark.asyncio
    async def test_confirm_send_false(self, mail_state):
        from mcp_tools.mail_tools import send_email

        mail_state.send_message.return_value = {
            "error": "confirm_send must be True. Please confirm with the user before sending."
        }

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            confirm_send=False,
        )
        data = json.loads(result)

        assert "error" in data
        assert "confirm_send" in data["error"]

    @pytest.mark.asyncio
    async def test_send_error(self, mail_state):
        from mcp_tools.mail_tools import send_email

        mail_state.send_message.return_value = {"error": "osascript failed: send error"}

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            confirm_send=True,
        )
        data = json.loads(result)

        assert "error" in data

    @pytest.mark.asyncio
    async def test_send_with_html_body(self, mail_state):
        from mcp_tools.mail_tools import send_email

        mail_state.send_message.return_value = {"status": "sent", "to": ["alice@test.com"], "subject": "Brief"}

        await send_email(
            to="alice@test.com",
            subject="Brief",
            body="Plain fallback",
            html_body="<h1>Daily Brief</h1>",
            confirm_send=True,
        )
        call_kwargs = mail_state.send_message.call_args[1]
        assert call_kwargs["html_body"] == "<h1>Daily Brief</h1>"

    @pytest.mark.asyncio
    async def test_send_empty_html_body_passes_none(self, mail_state):
        from mcp_tools.mail_tools import send_email

        mail_state.send_message.return_value = {"status": "sent", "to": ["alice@test.com"], "subject": "Plain"}

        await send_email(
            to="alice@test.com",
            subject="Plain",
            body="No HTML",
            html_body="",
            confirm_send=True,
        )
        call_kwargs = mail_state.send_message.call_args[1]
        assert call_kwargs["html_body"] is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestMailToolErrorHandling:
    @pytest.mark.asyncio
    async def test_exception_propagation(self, mail_state):
        """When the store raises an exception, the tool should catch and return error JSON."""
        from mcp_tools.mail_tools import list_mailboxes

        mail_state.list_mailboxes.side_effect = RuntimeError("Connection failed")

        result = await list_mailboxes()
        data = json.loads(result)

        assert "error" in data
        assert "Connection failed" in data["error"]

    @pytest.mark.asyncio
    async def test_get_messages_exception(self, mail_state):
        from mcp_tools.mail_tools import get_mail_messages

        mail_state.get_messages.side_effect = RuntimeError("Unexpected")

        result = await get_mail_messages()
        data = json.loads(result)

        assert "error" in data
        assert "Unexpected" in data["error"]

    @pytest.mark.asyncio
    async def test_search_exception(self, mail_state):
        from mcp_tools.mail_tools import search_mail

        mail_state.search_messages.side_effect = RuntimeError("Search broke")

        result = await search_mail(query="test")
        data = json.loads(result)

        assert "error" in data
        assert "Search broke" in data["error"]
