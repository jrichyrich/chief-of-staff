"""iMessage tools for MCP server."""

import json


def register(mcp, state):
    """Register iMessage tools with the MCP server."""

    @mcp.tool()
    async def get_imessages(
        minutes: int = 60,
        limit: int = 25,
        include_from_me: bool = True,
        conversation: str = "",
    ) -> str:
        """Get recent iMessages from Messages.app chat history.

        Args:
            minutes: Lookback window in minutes (default: 60)
            limit: Maximum number of messages to return (default: 25, max: 200)
            include_from_me: Include your own sent messages (default: True)
            conversation: Optional sender/chat identifier filter
        """
        messages_store = state.messages_store
        try:
            messages = messages_store.get_messages(
                minutes=minutes,
                limit=limit,
                include_from_me=include_from_me,
                conversation=conversation,
            )
            return json.dumps({"results": messages})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def list_imessage_threads(minutes: int = 7 * 24 * 60, limit: int = 50) -> str:
        """List active iMessage threads with persisted profile metadata.

        Args:
            minutes: Lookback window in minutes (default: 10080 / 7 days)
            limit: Maximum number of threads to return (default: 50, max: 200)
        """
        messages_store = state.messages_store
        try:
            threads = messages_store.list_threads(minutes=minutes, limit=limit)
            return json.dumps({"results": threads})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_imessage_threads(minutes: int = 7 * 24 * 60, limit: int = 50) -> str:
        """Alias of list_imessage_threads for compatibility with prior plans/prompts.

        Args:
            minutes: Lookback window in minutes (default: 10080 / 7 days)
            limit: Maximum number of threads to return (default: 50, max: 200)
        """
        return await list_imessage_threads(minutes=minutes, limit=limit)

    @mcp.tool()
    async def get_imessage_thread_messages(
        chat_identifier: str,
        minutes: int = 7 * 24 * 60,
        limit: int = 50,
        include_from_me: bool = True,
    ) -> str:
        """Get messages for a specific iMessage thread by chat_identifier.

        Args:
            chat_identifier: iMessage thread identifier (required)
            minutes: Lookback window in minutes (default: 10080 / 7 days)
            limit: Maximum number of messages to return (default: 50, max: 200)
            include_from_me: Include your own sent messages (default: True)
        """
        messages_store = state.messages_store
        try:
            messages = messages_store.get_thread_messages(
                chat_identifier=chat_identifier,
                minutes=minutes,
                limit=limit,
                include_from_me=include_from_me,
            )
            return json.dumps({"results": messages})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_thread_context(
        chat_identifier: str,
        minutes: int = 7 * 24 * 60,
        limit: int = 20,
    ) -> str:
        """Get thread profile and recent messages for an iMessage conversation.

        Args:
            chat_identifier: iMessage thread identifier (required)
            minutes: Lookback window in minutes (default: 10080 / 7 days)
            limit: Maximum number of recent messages to include (default: 20, max: 200)
        """
        messages_store = state.messages_store
        try:
            context = messages_store.get_thread_context(
                chat_identifier=chat_identifier,
                minutes=minutes,
                limit=limit,
            )
            return json.dumps(context)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def search_imessages(
        query: str,
        minutes: int = 24 * 60,
        limit: int = 25,
        include_from_me: bool = True,
    ) -> str:
        """Search iMessages by text, sender, or chat identifier.

        Args:
            query: Search text (required)
            minutes: Lookback window in minutes (default: 1440 / 1 day)
            limit: Maximum number of messages to return (default: 25, max: 200)
            include_from_me: Include your own sent messages (default: True)
        """
        messages_store = state.messages_store
        try:
            messages = messages_store.search_messages(
                query=query,
                minutes=minutes,
                limit=limit,
                include_from_me=include_from_me,
            )
            return json.dumps({"results": messages})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def send_imessage_reply(to: str = "", body: str = "", confirm_send: bool = False, chat_identifier: str = "") -> str:
        """Send an iMessage reply. REQUIRES confirm_send=true after explicit user confirmation.

        WARNING: This sends a real iMessage when confirm_send is true.

        Args:
            to: Recipient handle (phone, email, or 'self'). Optional when chat_identifier is provided.
            body: Message content
            confirm_send: Must be true to actually send
            chat_identifier: Optional thread identifier for thread-aware reply
        """
        messages_store = state.messages_store
        try:
            result = messages_store.send_message(
                to=to,
                body=body,
                confirm_send=confirm_send,
                chat_identifier=chat_identifier,
            )
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.get_imessages = get_imessages
    module.list_imessage_threads = list_imessage_threads
    module.get_imessage_threads = get_imessage_threads
    module.get_imessage_thread_messages = get_imessage_thread_messages
    module.get_thread_context = get_thread_context
    module.search_imessages = search_imessages
    module.send_imessage_reply = send_imessage_reply
