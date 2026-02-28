import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import mcp_server
from memory.store import MemoryStore


@pytest.fixture
def mock_messages_store():
    store = MagicMock()
    store.get_messages.return_value = []
    store.list_threads.return_value = []
    store.get_thread_messages.return_value = []
    store.get_thread_context.return_value = {}
    store.search_messages.return_value = []
    store.send_message.return_value = {"status": "preview"}
    store.verify_handle.return_value = {
        "handle": "",
        "found_in_threads": False,
        "chat_identifiers": [],
        "display_names": [],
    }
    return store


@pytest.fixture
def messages_state(mock_messages_store):
    mcp_server._state["messages_store"] = mock_messages_store
    yield mock_messages_store
    mcp_server._state.pop("messages_store", None)


class TestIMessageToolsRegistered:
    def test_imessage_tools_registered(self):
        tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
        assert "get_imessages" in tool_names
        assert "list_imessage_threads" in tool_names
        # get_imessage_threads removed (duplicate of list_imessage_threads)
        assert "get_imessage_threads" not in tool_names
        assert "get_imessage_thread_messages" in tool_names
        assert "get_thread_context" in tool_names
        assert "search_imessages" in tool_names
        assert "send_imessage_reply" in tool_names


class TestGetIMessagesTool:
    @pytest.mark.asyncio
    async def test_defaults(self, messages_state):
        from mcp_tools.imessage_tools import get_imessages

        messages_state.get_messages.return_value = [{"guid": "g1", "text": "hello"}]
        result = await get_imessages()
        data = json.loads(result)
        assert len(data["results"]) == 1
        messages_state.get_messages.assert_called_once_with(
            minutes=60,
            limit=25,
            include_from_me=True,
            conversation="",
        )

    @pytest.mark.asyncio
    async def test_custom_filters(self, messages_state):
        from mcp_tools.imessage_tools import get_imessages

        await get_imessages(minutes=120, limit=10, include_from_me=False, conversation="+1555")
        messages_state.get_messages.assert_called_once_with(
            minutes=120,
            limit=10,
            include_from_me=False,
            conversation="+1555",
        )


class TestIMessageThreadsTools:
    @pytest.mark.asyncio
    async def test_list_threads_defaults(self, messages_state):
        from mcp_tools.imessage_tools import list_imessage_threads

        messages_state.list_threads.return_value = [{"chat_identifier": "chat-team"}]
        result = await list_imessage_threads()
        data = json.loads(result)
        assert len(data["results"]) == 1
        messages_state.list_threads.assert_called_once_with(minutes=7 * 24 * 60, limit=50)

    @pytest.mark.asyncio
    async def test_get_threads_alias(self, messages_state):
        from mcp_tools.imessage_tools import get_imessage_threads

        await get_imessage_threads(minutes=60, limit=10)
        messages_state.list_threads.assert_called_once_with(minutes=60, limit=10)

    @pytest.mark.asyncio
    async def test_get_thread_messages(self, messages_state):
        from mcp_tools.imessage_tools import get_imessage_thread_messages

        messages_state.get_thread_messages.return_value = [{"guid": "g1"}]
        result = await get_imessage_thread_messages(
            chat_identifier="chat-team",
            minutes=120,
            limit=5,
            include_from_me=False,
        )
        data = json.loads(result)
        assert len(data["results"]) == 1
        messages_state.get_thread_messages.assert_called_once_with(
            chat_identifier="chat-team",
            minutes=120,
            limit=5,
            include_from_me=False,
        )

    @pytest.mark.asyncio
    async def test_get_thread_context(self, messages_state):
        from mcp_tools.imessage_tools import get_thread_context

        messages_state.get_thread_context.return_value = {"chat_identifier": "chat-team"}
        result = await get_thread_context(chat_identifier="chat-team", minutes=180, limit=15)
        data = json.loads(result)
        assert data["chat_identifier"] == "chat-team"
        messages_state.get_thread_context.assert_called_once_with(
            chat_identifier="chat-team",
            minutes=180,
            limit=15,
        )


class TestSearchIMessagesTool:
    @pytest.mark.asyncio
    async def test_search(self, messages_state):
        from mcp_tools.imessage_tools import search_imessages

        messages_state.search_messages.return_value = [{"guid": "g1", "text": "status update"}]
        result = await search_imessages(query="status", minutes=1440, limit=5, include_from_me=False)
        data = json.loads(result)
        assert len(data["results"]) == 1
        messages_state.search_messages.assert_called_once_with(
            query="status",
            minutes=1440,
            limit=5,
            include_from_me=False,
        )


class TestSendIMessagesTool:
    @pytest.mark.asyncio
    async def test_preview(self, messages_state):
        from mcp_tools.imessage_tools import send_imessage_reply

        messages_state.send_message.return_value = {"status": "preview", "requires_confirmation": True}
        result = await send_imessage_reply(to="+15555550123", body="Hi", confirm_send=False)
        data = json.loads(result)
        assert data["status"] == "preview"
        messages_state.send_message.assert_called_once_with(
            to="+15555550123",
            body="Hi",
            confirm_send=False,
            chat_identifier="",
        )

    @pytest.mark.asyncio
    async def test_send(self, messages_state):
        from mcp_tools.imessage_tools import send_imessage_reply

        messages_state.send_message.return_value = {"status": "sent", "channel": "imessage"}
        result = await send_imessage_reply(to="self", body="Done", confirm_send=True)
        data = json.loads(result)
        assert data["status"] == "sent"
        messages_state.send_message.assert_called_once_with(
            to="self",
            body="Done",
            confirm_send=True,
            chat_identifier="",
        )

    @pytest.mark.asyncio
    async def test_send_by_chat_identifier(self, messages_state):
        from mcp_tools.imessage_tools import send_imessage_reply

        messages_state.send_message.return_value = {
            "status": "sent",
            "channel": "imessage",
            "chat_identifier": "chat-team",
        }
        result = await send_imessage_reply(
            body="Thread update",
            confirm_send=True,
            chat_identifier="chat-team",
        )
        data = json.loads(result)
        assert data["status"] == "sent"
        assert data["chat_identifier"] == "chat-team"
        messages_state.send_message.assert_called_once_with(
            to="",
            body="Thread update",
            confirm_send=True,
            chat_identifier="chat-team",
        )


class TestSendIMessageRecipientVerification:
    """Tests for the recipient_name verification safety check."""

    @pytest.fixture
    def memory_store(self, tmp_path):
        store = MemoryStore(tmp_path / "test.db")
        yield store
        store.close()

    @pytest.fixture
    def verified_state(self, mock_messages_store, memory_store):
        """State with both messages_store and memory_store for verification tests."""
        mcp_server._state["messages_store"] = mock_messages_store
        mcp_server._state["memory_store"] = memory_store
        yield {"messages_store": mock_messages_store, "memory_store": memory_store}
        mcp_server._state.pop("messages_store", None)
        mcp_server._state.pop("memory_store", None)

    @pytest.mark.asyncio
    async def test_verified_recipient_identity_match(self, verified_state):
        """Identity confirms handle belongs to intended recipient — no warning."""
        from mcp_tools.imessage_tools import send_imessage_reply

        ms = verified_state["messages_store"]
        mem = verified_state["memory_store"]
        mem.link_identity("Ross Young", "imessage", "+17035551234")
        ms.send_message.return_value = {"status": "preview", "to": "+17035551234", "requires_confirmation": True}

        result = await send_imessage_reply(
            to="+17035551234", body="Hey Ross", confirm_send=False, recipient_name="Ross Young"
        )
        data = json.loads(result)
        assert data["status"] == "preview"
        assert "recipient_verification" in data
        assert data["recipient_verification"]["verified"] is True
        assert "warning" not in data["recipient_verification"]

    @pytest.mark.asyncio
    async def test_mismatch_warns(self, verified_state):
        """Identity shows different person for handle — RECIPIENT MISMATCH warning."""
        from mcp_tools.imessage_tools import send_imessage_reply

        ms = verified_state["messages_store"]
        mem = verified_state["memory_store"]
        # The handle is linked to "John Smith", not "Ross Young"
        mem.link_identity("John Smith", "imessage", "+17035551234")
        ms.send_message.return_value = {"status": "preview", "to": "+17035551234", "requires_confirmation": True}

        result = await send_imessage_reply(
            to="+17035551234", body="Hey Ross", confirm_send=False, recipient_name="Ross Young"
        )
        data = json.loads(result)
        assert "recipient_verification" in data
        assert data["recipient_verification"]["verified"] is False
        assert "RECIPIENT MISMATCH" in data["recipient_verification"]["warning"]
        assert "John Smith" in data["recipient_verification"]["warning"]

    @pytest.mark.asyncio
    async def test_unverified_warns(self, verified_state):
        """No identity found for handle — UNVERIFIED RECIPIENT warning."""
        from mcp_tools.imessage_tools import send_imessage_reply

        ms = verified_state["messages_store"]
        ms.send_message.return_value = {"status": "preview", "to": "+17035551234", "requires_confirmation": True}
        ms.verify_handle.return_value = {
            "handle": "+17035551234",
            "found_in_threads": False,
            "chat_identifiers": [],
            "display_names": [],
        }

        result = await send_imessage_reply(
            to="+17035551234", body="Hey Ross", confirm_send=False, recipient_name="Ross Young"
        )
        data = json.loads(result)
        assert "recipient_verification" in data
        assert data["recipient_verification"]["verified"] is False
        assert "UNVERIFIED RECIPIENT" in data["recipient_verification"]["warning"]

    @pytest.mark.asyncio
    async def test_no_recipient_name_skips_verification(self, verified_state):
        """Backward compat: no recipient_name means no verification added."""
        from mcp_tools.imessage_tools import send_imessage_reply

        ms = verified_state["messages_store"]
        ms.send_message.return_value = {"status": "preview", "to": "+17035551234", "requires_confirmation": True}

        result = await send_imessage_reply(
            to="+17035551234", body="Hey", confirm_send=False
        )
        data = json.loads(result)
        assert "recipient_verification" not in data

    @pytest.mark.asyncio
    async def test_self_target_skips_verification(self, verified_state):
        """to='self' never triggers verification."""
        from mcp_tools.imessage_tools import send_imessage_reply

        ms = verified_state["messages_store"]
        ms.send_message.return_value = {"status": "preview", "to": "self", "requires_confirmation": True}

        result = await send_imessage_reply(
            to="self", body="Note to self", confirm_send=False, recipient_name="Ross Young"
        )
        data = json.loads(result)
        assert "recipient_verification" not in data

    @pytest.mark.asyncio
    async def test_partial_name_match_verified(self, verified_state):
        """Substring match: 'Ross' matches 'Ross Young' in identity store."""
        from mcp_tools.imessage_tools import send_imessage_reply

        ms = verified_state["messages_store"]
        mem = verified_state["memory_store"]
        mem.link_identity("Ross Young", "imessage", "+17035551234")
        ms.send_message.return_value = {"status": "preview", "to": "+17035551234", "requires_confirmation": True}

        result = await send_imessage_reply(
            to="+17035551234", body="Hey", confirm_send=False, recipient_name="Ross"
        )
        data = json.loads(result)
        assert data["recipient_verification"]["verified"] is True
        assert "warning" not in data["recipient_verification"]

    @pytest.mark.asyncio
    async def test_thread_profile_verification(self, verified_state):
        """Thread profile display_name matches intended recipient — verified."""
        from mcp_tools.imessage_tools import send_imessage_reply

        ms = verified_state["messages_store"]
        ms.send_message.return_value = {"status": "preview", "to": "+17035551234", "requires_confirmation": True}
        ms.verify_handle.return_value = {
            "handle": "+17035551234",
            "found_in_threads": True,
            "chat_identifiers": ["chat-ross"],
            "display_names": ["Ross Young"],
        }

        result = await send_imessage_reply(
            to="+17035551234", body="Hey Ross", confirm_send=False, recipient_name="Ross Young"
        )
        data = json.loads(result)
        assert data["recipient_verification"]["verified"] is True
