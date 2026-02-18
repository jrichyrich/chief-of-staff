import json
from unittest.mock import MagicMock

import pytest

import mcp_server


@pytest.fixture
def mock_messages_store():
    store = MagicMock()
    store.get_messages.return_value = []
    store.list_threads.return_value = []
    store.get_thread_messages.return_value = []
    store.get_thread_context.return_value = {}
    store.search_messages.return_value = []
    store.send_message.return_value = {"status": "preview"}
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
        assert "get_imessage_threads" in tool_names
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
