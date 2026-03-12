# tests/test_mail_graph.py
"""Tests for Graph API email backend routing in mcp_tools/mail_tools.py.

Verifies that send_email and reply_to_email correctly route to Graph API
when configured, fall back to Apple Mail on transient errors, and respect
the confirm_send safety gate regardless of backend.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mcp_server
from connectors.graph_client import GraphAPIError, GraphAuthError, GraphTransientError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mail_store():
    """Return a MagicMock that quacks like MailStore."""
    store = MagicMock()
    store.send_message.return_value = {"status": "sent", "to": ["alice@test.com"], "subject": "Test"}
    store.reply_message.return_value = {"status": "replied", "message_id": "msg-123", "reply_all": False}
    return store


@pytest.fixture
def mock_graph_client():
    """Return an AsyncMock that quacks like GraphClient."""
    client = AsyncMock()
    client.send_mail.return_value = {"status": "success"}
    client.reply_mail.return_value = {"status": "success"}
    return client


@pytest.fixture
def graph_state(mock_mail_store, mock_graph_client):
    """Inject mock mail store and graph client into mcp_server._state."""
    mcp_server._state["mail_store"] = mock_mail_store
    mcp_server._state["graph_client"] = mock_graph_client
    yield {"mail_store": mock_mail_store, "graph_client": mock_graph_client}
    mcp_server._state.pop("mail_store", None)
    mcp_server._state.pop("graph_client", None)


@pytest.fixture
def apple_state(mock_mail_store):
    """Inject mock mail store with no graph client into mcp_server._state."""
    mcp_server._state["mail_store"] = mock_mail_store
    mcp_server._state["graph_client"] = None
    yield {"mail_store": mock_mail_store}
    mcp_server._state.pop("mail_store", None)
    mcp_server._state.pop("graph_client", None)


# ---------------------------------------------------------------------------
# send_email — Graph backend
# ---------------------------------------------------------------------------


class TestSendEmailGraphBackend:
    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_send_email_graph_backend(self, graph_state):
        """Graph path succeeds — Apple Mail NOT called."""
        from mcp_tools.mail_tools import send_email

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        assert data["backend"] == "graph"
        graph_state["graph_client"].send_mail.assert_awaited_once()
        graph_state["mail_store"].send_message.assert_not_called()

    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_send_email_graph_with_cc(self, graph_state):
        """Graph path passes cc list correctly."""
        from mcp_tools.mail_tools import send_email

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            cc="bob@test.com, carol@test.com",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        call_kwargs = graph_state["graph_client"].send_mail.call_args[1]
        assert call_kwargs["cc"] == ["bob@test.com", "carol@test.com"]

    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_send_email_graph_with_html(self, graph_state):
        """Graph path sends HTML body with HTML content type when provided."""
        from mcp_tools.mail_tools import send_email

        result = await send_email(
            to="alice@test.com",
            subject="Brief",
            body="Plain fallback",
            html_body="<h1>Daily Brief</h1>",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        call_kwargs = graph_state["graph_client"].send_mail.call_args[1]
        assert call_kwargs["body"] == "<h1>Daily Brief</h1>"
        assert call_kwargs["content_type"] == "HTML"

    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_send_email_graph_with_bcc(self, graph_state):
        """Graph path passes bcc list correctly."""
        from mcp_tools.mail_tools import send_email

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            bcc="secret@test.com, hidden@test.com",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        call_kwargs = graph_state["graph_client"].send_mail.call_args[1]
        assert call_kwargs["bcc"] == ["secret@test.com", "hidden@test.com"]


# ---------------------------------------------------------------------------
# send_email — Graph fallback
# ---------------------------------------------------------------------------


class TestSendEmailGraphFallback:
    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_send_email_graph_transient_fallback(self, graph_state):
        """Graph fails with GraphTransientError — falls back to Apple Mail."""
        from mcp_tools.mail_tools import send_email

        graph_state["graph_client"].send_mail.side_effect = GraphTransientError("503 server error")

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        # Graph was attempted
        graph_state["graph_client"].send_mail.assert_awaited_once()
        # Apple Mail was called as fallback
        graph_state["mail_store"].send_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_send_email_graph_auth_fallback(self, graph_state):
        """Graph fails with GraphAuthError — falls back to Apple Mail."""
        from mcp_tools.mail_tools import send_email

        graph_state["graph_client"].send_mail.side_effect = GraphAuthError("Token refresh failed")

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        graph_state["graph_client"].send_mail.assert_awaited_once()
        graph_state["mail_store"].send_message.assert_called_once()


# ---------------------------------------------------------------------------
# send_email — Apple backend
# ---------------------------------------------------------------------------


class TestSendEmailAppleBackend:
    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "apple")
    async def test_send_email_apple_backend(self, graph_state):
        """Config set to apple — Graph not called, Apple Mail used directly."""
        from mcp_tools.mail_tools import send_email

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        graph_state["graph_client"].send_mail.assert_not_awaited()
        graph_state["mail_store"].send_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_send_email_graph_client_none(self, apple_state):
        """Backend is graph but graph_client is None — falls through to Apple Mail."""
        from mcp_tools.mail_tools import send_email

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        apple_state["mail_store"].send_message.assert_called_once()


# ---------------------------------------------------------------------------
# send_email — confirm_send gate
# ---------------------------------------------------------------------------


class TestSendEmailConfirmSendGate:
    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_send_email_confirm_send_false(self, graph_state):
        """confirm_send=False returns early regardless of backend."""
        from mcp_tools.mail_tools import send_email

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            confirm_send=False,
        )
        data = json.loads(result)

        assert "error" in data
        assert "confirm_send" in data["error"]
        graph_state["graph_client"].send_mail.assert_not_awaited()
        graph_state["mail_store"].send_message.assert_not_called()


# ---------------------------------------------------------------------------
# reply_to_email — Graph backend
# ---------------------------------------------------------------------------


class TestReplyEmailGraphBackend:
    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_reply_email_graph_backend(self, graph_state):
        """Graph reply path succeeds — Apple Mail NOT called."""
        from mcp_tools.mail_tools import reply_to_email

        result = await reply_to_email(
            message_id="msg-123",
            body="Thanks for the update.",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "replied"
        assert data["backend"] == "graph"
        graph_state["graph_client"].reply_mail.assert_awaited_once_with(
            message_id="msg-123",
            body="Thanks for the update.",
            reply_all=False,
            cc=None,
            bcc=None,
        )
        graph_state["mail_store"].reply_message.assert_not_called()

    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_reply_email_graph_reply_all(self, graph_state):
        """Graph reply path passes reply_all=True and cc/bcc correctly."""
        from mcp_tools.mail_tools import reply_to_email

        result = await reply_to_email(
            message_id="msg-456",
            body="Acknowledged.",
            reply_all=True,
            cc="extra@test.com",
            bcc="hidden@test.com",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "replied"
        assert data["backend"] == "graph"
        graph_state["graph_client"].reply_mail.assert_awaited_once_with(
            message_id="msg-456",
            body="Acknowledged.",
            reply_all=True,
            cc=["extra@test.com"],
            bcc=["hidden@test.com"],
        )
        graph_state["mail_store"].reply_message.assert_not_called()


# ---------------------------------------------------------------------------
# reply_to_email — Graph fallback
# ---------------------------------------------------------------------------


class TestReplyEmailGraphFallback:
    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_reply_email_graph_transient_fallback(self, graph_state):
        """Graph reply fails with transient error — falls back to Apple Mail."""
        from mcp_tools.mail_tools import reply_to_email

        graph_state["graph_client"].reply_mail.side_effect = GraphTransientError("Rate limited")

        result = await reply_to_email(
            message_id="msg-123",
            body="Thanks for the update.",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "replied"
        graph_state["graph_client"].reply_mail.assert_awaited_once()
        graph_state["mail_store"].reply_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_reply_email_graph_auth_fallback(self, graph_state):
        """Graph reply fails with auth error — falls back to Apple Mail."""
        from mcp_tools.mail_tools import reply_to_email

        graph_state["graph_client"].reply_mail.side_effect = GraphAuthError("Token expired")

        result = await reply_to_email(
            message_id="msg-123",
            body="Thanks for the update.",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "replied"
        graph_state["graph_client"].reply_mail.assert_awaited_once()
        graph_state["mail_store"].reply_message.assert_called_once()


# ---------------------------------------------------------------------------
# send_email — Broad exception fallback (AUD-009 / AUD-019)
# ---------------------------------------------------------------------------


class TestSendEmailBroadExceptionFallback:
    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_send_email_graph_api_error_fallback(self, graph_state):
        """Non-transient GraphAPIError (e.g. 400/404) triggers Apple Mail fallback."""
        from mcp_tools.mail_tools import send_email

        graph_state["graph_client"].send_mail.side_effect = GraphAPIError("400 Bad Request")

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        graph_state["graph_client"].send_mail.assert_awaited_once()
        graph_state["mail_store"].send_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_send_email_httpx_error_fallback(self, graph_state):
        """httpx-level connection error triggers Apple Mail fallback."""
        from mcp_tools.mail_tools import send_email

        graph_state["graph_client"].send_mail.side_effect = ConnectionError("Connection refused")

        result = await send_email(
            to="alice@test.com",
            subject="Hello",
            body="World",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "sent"
        graph_state["graph_client"].send_mail.assert_awaited_once()
        graph_state["mail_store"].send_message.assert_called_once()


class TestReplyEmailBroadExceptionFallback:
    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_reply_email_graph_api_error_fallback(self, graph_state):
        """Non-transient GraphAPIError triggers Apple Mail fallback for reply."""
        from mcp_tools.mail_tools import reply_to_email

        graph_state["graph_client"].reply_mail.side_effect = GraphAPIError("404 Not Found")

        result = await reply_to_email(
            message_id="msg-123",
            body="Thanks.",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "replied"
        graph_state["graph_client"].reply_mail.assert_awaited_once()
        graph_state["mail_store"].reply_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_reply_email_httpx_error_fallback(self, graph_state):
        """httpx-level exception triggers Apple Mail fallback for reply."""
        from mcp_tools.mail_tools import reply_to_email

        graph_state["graph_client"].reply_mail.side_effect = TimeoutError("Request timed out")

        result = await reply_to_email(
            message_id="msg-123",
            body="Thanks.",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "replied"
        graph_state["graph_client"].reply_mail.assert_awaited_once()
        graph_state["mail_store"].reply_message.assert_called_once()


# ---------------------------------------------------------------------------
# reply_to_email — Apple backend
# ---------------------------------------------------------------------------


class TestReplyEmailAppleBackend:
    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "apple")
    async def test_reply_email_apple_backend(self, graph_state):
        """Config set to apple — Graph not called for reply."""
        from mcp_tools.mail_tools import reply_to_email

        result = await reply_to_email(
            message_id="msg-123",
            body="Thanks.",
            confirm_send=True,
        )
        data = json.loads(result)

        assert data["status"] == "replied"
        graph_state["graph_client"].reply_mail.assert_not_awaited()
        graph_state["mail_store"].reply_message.assert_called_once()


# ---------------------------------------------------------------------------
# reply_to_email — confirm_send gate
# ---------------------------------------------------------------------------


class TestReplyEmailConfirmSendGate:
    @pytest.mark.asyncio
    @patch("config.EMAIL_SEND_BACKEND", "graph")
    async def test_reply_email_confirm_send_false(self, graph_state):
        """confirm_send=False returns early regardless of backend for reply."""
        from mcp_tools.mail_tools import reply_to_email

        result = await reply_to_email(
            message_id="msg-123",
            body="Reply text",
            confirm_send=False,
        )
        data = json.loads(result)

        assert "error" in data
        assert "confirm_send" in data["error"]
        graph_state["graph_client"].reply_mail.assert_not_awaited()
        graph_state["mail_store"].reply_message.assert_not_called()
