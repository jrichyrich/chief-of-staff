"""Tests for Teams Graph API integration in teams_browser_tools.

Tests Graph send/read paths, fallback to browser/m365-bridge, and
config-based backend routing.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mcp_server  # noqa: F401 — triggers tool registrations
from mcp_tools import teams_browser_tools

teams_browser_tools.register(mcp_server.mcp, mcp_server._state)
from mcp_tools.teams_browser_tools import post_teams_message, read_teams_messages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_client(**overrides) -> AsyncMock:
    """Create a mock GraphClient with sensible defaults."""
    gc = AsyncMock()
    gc.list_chats = AsyncMock(return_value=[
        {
            "id": "chat-001",
            "topic": "Engineering",
            "members": [
                {"displayName": "Alice Smith", "email": "alice@example.com"},
                {"displayName": "Bob Jones", "email": "bob@example.com"},
            ],
        },
    ])
    gc.get_chat_messages = AsyncMock(return_value=[
        {
            "id": "msg-001",
            "body": {"content": "Hello from Alice", "contentType": "text"},
            "createdDateTime": "2026-03-12T10:00:00Z",
            "from": {"user": {"displayName": "Alice Smith"}},
        },
    ])
    gc.send_chat_message = AsyncMock(return_value={"id": "msg-new-001"})
    gc.find_chat_by_members = AsyncMock(return_value="chat-001")
    gc.create_chat = AsyncMock(return_value={"id": "chat-new-001"})
    for k, v in overrides.items():
        setattr(gc, k, v)
    return gc


# ---------------------------------------------------------------------------
# post_teams_message: Graph backend succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPostTeamsMessageGraphBackend:
    """Graph path succeeds — message sent via Graph API."""

    async def test_post_teams_message_graph_backend(self):
        """When send backend is graph and graph_client is set, send via Graph."""
        gc = _make_graph_client()
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            raw = await post_teams_message(
                target="alice@example.com",
                message="Hello via Graph!",
            )

        result = json.loads(raw)
        assert result["status"] == "sent"
        assert result["backend"] == "graph"
        assert result["chat_id"] == "chat-001"
        gc.find_chat_by_members.assert_awaited_once_with(["alice@example.com"])
        gc.send_chat_message.assert_awaited_once_with("chat-001", "Hello via Graph!")

        mcp_server._state.graph_client = None  # cleanup

    async def test_post_teams_message_graph_display_name_match(self):
        """Graph resolves a display name to a chat via member search."""
        gc = _make_graph_client(
            find_chat_by_members=AsyncMock(return_value=None),  # no email match
        )
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            raw = await post_teams_message(
                target="Alice Smith",
                message="Hey Alice!",
            )

        result = json.loads(raw)
        assert result["status"] == "sent"
        assert result["backend"] == "graph"
        assert result["chat_id"] == "chat-001"
        gc.send_chat_message.assert_awaited_once_with("chat-001", "Hey Alice!")

        mcp_server._state.graph_client = None

    async def test_post_teams_message_graph_exact_match_preferred(self):
        """Exact display name match is preferred over substring match."""
        gc = _make_graph_client(
            find_chat_by_members=AsyncMock(return_value=None),
            list_chats=AsyncMock(return_value=[
                {
                    "id": "chat-partial",
                    "topic": None,
                    "members": [{"displayName": "Alice Smith-Jones", "email": "asj@example.com"}],
                },
                {
                    "id": "chat-exact",
                    "topic": None,
                    "members": [{"displayName": "Alice Smith", "email": "alice@example.com"}],
                },
            ]),
        )
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            raw = await post_teams_message(target="Alice Smith", message="Hi exact!")

        result = json.loads(raw)
        assert result["status"] == "sent"
        assert result["chat_id"] == "chat-exact"
        gc.send_chat_message.assert_awaited_once_with("chat-exact", "Hi exact!")

        mcp_server._state.graph_client = None

    async def test_post_teams_message_graph_ambiguous_display_name(self):
        """Multiple substring matches return an ambiguous error."""
        gc = _make_graph_client(
            find_chat_by_members=AsyncMock(return_value=None),
            list_chats=AsyncMock(return_value=[
                {
                    "id": "chat-a",
                    "topic": None,
                    "members": [{"displayName": "Alice Smith-Jones", "email": "asj@example.com"}],
                },
                {
                    "id": "chat-b",
                    "topic": None,
                    "members": [{"displayName": "Alice Smith-Brown", "email": "asb@example.com"}],
                },
            ]),
        )
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            raw = await post_teams_message(target="Alice Smith", message="Who?")

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "Ambiguous" in result["error"]
        assert "Alice Smith-Jones" in result["error"]
        assert "Alice Smith-Brown" in result["error"]
        gc.send_chat_message.assert_not_awaited()

        mcp_server._state.graph_client = None

    async def test_post_teams_message_graph_creates_new_chat(self):
        """Graph creates a new chat when no existing chat matches."""
        gc = _make_graph_client(
            find_chat_by_members=AsyncMock(return_value=None),
            list_chats=AsyncMock(return_value=[]),  # no chats at all
        )
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            raw = await post_teams_message(
                target="newperson@example.com",
                message="First message!",
            )

        result = json.loads(raw)
        assert result["status"] == "sent"
        assert result["backend"] == "graph"
        gc.create_chat.assert_awaited_once_with(
            ["newperson@example.com"], message="First message!"
        )

        mcp_server._state.graph_client = None


# ---------------------------------------------------------------------------
# post_teams_message: Graph fails, falls back to browser
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPostTeamsMessageGraphFallback:
    """Graph path fails with transient/auth error — falls back to browser."""

    async def test_post_teams_message_graph_fallback(self):
        """GraphTransientError triggers fallback to browser poster."""
        from connectors.graph_client import GraphTransientError as RealGTE

        gc = AsyncMock()
        # list_chats is called for non-email targets — make it raise
        gc.list_chats = AsyncMock(side_effect=RealGTE("503 Service Unavailable"))
        mcp_server._state.graph_client = gc

        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "confirm_required",
            "detected_channel": "Engineering",
            "message": "Hello",
            "target": "Engineering",
        }

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
                raw = await post_teams_message(target="Engineering", message="Hello")

        result = json.loads(raw)
        assert result["status"] == "confirm_required"
        mock_poster.prepare_message.assert_awaited_once_with("Engineering", "Hello")

        mcp_server._state.graph_client = None

    async def test_post_teams_message_graph_auth_error_fallback(self):
        """GraphAuthError triggers fallback to browser poster."""
        from connectors.graph_client import GraphAuthError as RealGAE

        gc = AsyncMock()
        # list_chats is called for non-email targets — make it raise auth error
        gc.list_chats = AsyncMock(side_effect=RealGAE("Token expired"))
        mcp_server._state.graph_client = gc

        mock_poster = AsyncMock()
        mock_poster.send_message = AsyncMock(return_value={
            "status": "sent",
            "detected_channel": "Jonas",
        })

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
                raw = await post_teams_message(
                    target="Jonas", message="Hey", auto_send=True
                )

        result = json.loads(raw)
        assert result["status"] == "sent"
        mock_poster.send_message.assert_awaited_once()

        mcp_server._state.graph_client = None

    async def test_post_teams_message_graph_unexpected_exception_not_caught_as_fallback(self):
        """Unexpected (non-Graph) exceptions are re-raised, not caught for fallback.

        The @tool_errors decorator at the outermost layer converts them to
        JSON error responses, but the important thing is they do NOT fall
        through to the browser poster path.
        """
        gc = AsyncMock()
        gc.find_chat_by_members = AsyncMock(side_effect=ValueError("unexpected bug"))
        mcp_server._state.graph_client = gc

        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {"status": "confirm_required"}

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
                raw = await post_teams_message(target="someone@example.com", message="Hi")

        result = json.loads(raw)
        # Should be an error, NOT a fallback to browser
        assert "error" in result
        assert "Unexpected error" in result["error"]
        # Browser poster should NOT have been called
        mock_poster.prepare_message.assert_not_awaited()
        mock_poster.send_message.assert_not_awaited()

        mcp_server._state.graph_client = None

    async def test_post_teams_message_graph_client_none_fallback(self):
        """If graph_client is None, fall through to browser even when backend=graph."""
        mcp_server._state.graph_client = None

        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "confirm_required",
            "detected_channel": "General",
        }

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
                raw = await post_teams_message(target="General", message="Hi")

        result = json.loads(raw)
        assert result["status"] == "confirm_required"
        mock_poster.prepare_message.assert_awaited_once()


# ---------------------------------------------------------------------------
# post_teams_message: Browser backend — Graph not called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPostTeamsMessageBrowserBackend:
    """Config set to agent-browser — Graph is never called."""

    async def test_post_teams_message_browser_backend(self):
        """When send backend is agent-browser, Graph client is not touched."""
        gc = _make_graph_client()
        mcp_server._state.graph_client = gc

        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "confirm_required",
            "detected_channel": "Engineering",
        }

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="agent-browser"):
            with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
                raw = await post_teams_message(target="Engineering", message="Hello")

        result = json.loads(raw)
        assert result["status"] == "confirm_required"
        # Graph client methods should NOT have been called
        gc.find_chat_by_members.assert_not_awaited()
        gc.send_chat_message.assert_not_awaited()
        gc.list_chats.assert_not_awaited()

        mcp_server._state.graph_client = None

    async def test_post_teams_message_playwright_backend(self):
        """When send backend is playwright, Graph client is not touched."""
        gc = _make_graph_client()
        mcp_server._state.graph_client = gc

        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "confirm_required",
            "detected_channel": "Design",
        }

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="playwright"):
            with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
                raw = await post_teams_message(target="Design", message="Hello")

        result = json.loads(raw)
        assert result["status"] == "confirm_required"
        gc.find_chat_by_members.assert_not_awaited()

        mcp_server._state.graph_client = None


# ---------------------------------------------------------------------------
# read_teams_messages: Graph backend succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReadTeamsMessagesGraphBackend:
    """Graph read path succeeds."""

    async def test_read_teams_messages_graph_backend(self):
        """Graph path returns messages from chats."""
        gc = _make_graph_client()
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_read_backend", return_value="graph"):
            raw = await read_teams_messages(query="Hello", limit=10)

        result = json.loads(raw)
        assert result["backend"] == "graph"
        assert result["count"] == 1
        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert msg["sender"] == "Alice Smith"
        assert "Hello" in msg["content"]
        assert msg["chat_id"] == "chat-001"

        gc.list_chats.assert_awaited_once()
        gc.get_chat_messages.assert_awaited_once()

        mcp_server._state.graph_client = None

    async def test_read_teams_messages_graph_no_query(self):
        """Graph read with no query returns all messages."""
        gc = _make_graph_client()
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_read_backend", return_value="graph"):
            raw = await read_teams_messages()

        result = json.loads(raw)
        assert result["backend"] == "graph"
        assert result["count"] == 1

        mcp_server._state.graph_client = None

    async def test_read_teams_messages_graph_filters_by_datetime(self):
        """Messages before after_datetime are excluded."""
        gc = _make_graph_client()
        # Message timestamp is 2026-03-12T10:00:00Z — filter to after 11:00
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_read_backend", return_value="graph"):
            raw = await read_teams_messages(after_datetime="2026-03-12T11:00:00Z")

        result = json.loads(raw)
        assert result["backend"] == "graph"
        assert result["count"] == 0
        assert len(result["messages"]) == 0

        mcp_server._state.graph_client = None


# ---------------------------------------------------------------------------
# read_teams_messages: Graph fails, falls back to bridge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReadTeamsMessagesFallback:
    """Graph read fails — falls back to m365-bridge."""

    async def test_read_teams_messages_fallback(self):
        """GraphTransientError on read triggers m365-bridge fallback."""
        from connectors.graph_client import GraphTransientError as RealGTE

        gc = AsyncMock()
        gc.list_chats = AsyncMock(side_effect=RealGTE("429 rate limited"))
        mcp_server._state.graph_client = gc

        mock_bridge = MagicMock()
        mock_bridge._sanitize_for_prompt = MagicMock(side_effect=lambda x: x)
        mock_bridge._invoke_structured = MagicMock(return_value={
            "results": [
                {
                    "chat_name": "Engineering",
                    "sender": "Alice",
                    "content": "Bridge message",
                    "timestamp": "2026-03-12T10:00:00Z",
                },
            ],
        })
        mcp_server._state.m365_bridge = mock_bridge

        with patch.object(teams_browser_tools, "_get_read_backend", return_value="graph"):
            raw = await read_teams_messages(query="test")

        result = json.loads(raw)
        assert result["backend"] == "m365-bridge"
        assert result["count"] == 1
        assert result["messages"][0]["sender"] == "Alice"

        mock_bridge._invoke_structured.assert_called_once()

        mcp_server._state.graph_client = None
        mcp_server._state.m365_bridge = None

    async def test_read_teams_messages_unexpected_exception_not_caught_as_fallback(self):
        """Unexpected (non-Graph) exceptions are re-raised, not caught for fallback.

        The @tool_errors decorator converts them to JSON error responses, but
        they do NOT fall through to the m365-bridge path.
        """
        gc = AsyncMock()
        gc.list_chats = AsyncMock(side_effect=RuntimeError("unexpected read bug"))
        mcp_server._state.graph_client = gc

        mock_bridge = MagicMock()
        mock_bridge._sanitize_for_prompt = MagicMock(side_effect=lambda x: x)
        mock_bridge._invoke_structured = MagicMock(return_value={"results": []})
        mcp_server._state.m365_bridge = mock_bridge

        with patch.object(teams_browser_tools, "_get_read_backend", return_value="graph"):
            raw = await read_teams_messages()

        result = json.loads(raw)
        # Should be an error, NOT a fallback to m365-bridge
        assert "error" in result
        assert "Unexpected error" in result["error"]
        # Bridge should NOT have been called
        mock_bridge._invoke_structured.assert_not_called()

        mcp_server._state.graph_client = None
        mcp_server._state.m365_bridge = None

    async def test_read_teams_messages_graph_client_none_uses_bridge(self):
        """When graph_client is None, reads via m365-bridge."""
        mcp_server._state.graph_client = None

        mock_bridge = MagicMock()
        mock_bridge._sanitize_for_prompt = MagicMock(side_effect=lambda x: x)
        mock_bridge._invoke_structured = MagicMock(return_value={"results": []})
        mcp_server._state.m365_bridge = mock_bridge

        with patch.object(teams_browser_tools, "_get_read_backend", return_value="graph"):
            raw = await read_teams_messages()

        result = json.loads(raw)
        assert result["backend"] == "m365-bridge"
        assert result["count"] == 0

        mcp_server._state.m365_bridge = None

    async def test_read_teams_messages_m365_bridge_backend(self):
        """When read backend is m365-bridge, Graph is not called."""
        gc = _make_graph_client()
        mcp_server._state.graph_client = gc

        mock_bridge = MagicMock()
        mock_bridge._sanitize_for_prompt = MagicMock(side_effect=lambda x: x)
        mock_bridge._invoke_structured = MagicMock(return_value={
            "results": [{"chat_name": "General", "sender": "Bob", "content": "Hi", "timestamp": "2026-03-12T09:00:00Z"}],
        })
        mcp_server._state.m365_bridge = mock_bridge

        with patch.object(teams_browser_tools, "_get_read_backend", return_value="m365-bridge"):
            raw = await read_teams_messages()

        result = json.loads(raw)
        assert result["backend"] == "m365-bridge"
        assert result["count"] == 1
        # Graph should NOT have been called
        gc.list_chats.assert_not_awaited()

        mcp_server._state.graph_client = None
        mcp_server._state.m365_bridge = None

    async def test_read_teams_messages_no_bridge_returns_error(self):
        """When m365-bridge fallback is needed but bridge is None, return error."""
        mcp_server._state.graph_client = None
        mcp_server._state.m365_bridge = None

        with patch.object(teams_browser_tools, "_get_read_backend", return_value="m365-bridge"):
            raw = await read_teams_messages()

        result = json.loads(raw)
        assert "error" in result
        assert result["messages"] == []
