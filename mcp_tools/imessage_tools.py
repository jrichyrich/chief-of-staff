"""iMessage tools for MCP server."""

import json
import logging

logger = logging.getLogger(__name__)


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
        except (OSError, PermissionError) as e:
            return json.dumps({"error": f"iMessage access error: {e}"})
        except Exception as e:
            logger.exception("Unexpected error in get_imessages")
            return json.dumps({"error": f"Unexpected error: {e}"})

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
        except (OSError, PermissionError) as e:
            return json.dumps({"error": f"iMessage access error: {e}"})
        except Exception as e:
            logger.exception("Unexpected error in list_imessage_threads")
            return json.dumps({"error": f"Unexpected error: {e}"})

    # Keep as a plain alias for backward-compat test imports (not an MCP tool)
    async def get_imessage_threads(minutes: int = 7 * 24 * 60, limit: int = 50) -> str:
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
        except (OSError, PermissionError) as e:
            return json.dumps({"error": f"iMessage access error: {e}"})
        except Exception as e:
            logger.exception("Unexpected error in get_imessage_thread_messages")
            return json.dumps({"error": f"Unexpected error: {e}"})

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
        except (OSError, PermissionError) as e:
            return json.dumps({"error": f"iMessage access error: {e}"})
        except Exception as e:
            logger.exception("Unexpected error in get_thread_context")
            return json.dumps({"error": f"Unexpected error: {e}"})

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
        except (OSError, PermissionError) as e:
            return json.dumps({"error": f"iMessage access error: {e}"})
        except Exception as e:
            logger.exception("Unexpected error in search_imessages")
            return json.dumps({"error": f"Unexpected error: {e}"})

    def _verify_recipient(to: str, recipient_name: str) -> dict:
        """Cross-check a recipient handle against identity store and thread profiles.

        Returns dict with verified, resolved_name, match_type, warning (if any), sources_checked.
        """
        sources_checked = []
        resolved_name = None
        match_type = None

        # 1. Check identity store
        memory_store = state.memory_store
        if memory_store:
            try:
                identity_result = memory_store.resolve_handle_to_name(to)
                sources_checked.append("identity_store")
                if identity_result.get("canonical_name"):
                    resolved_name = identity_result["canonical_name"]
                    match_type = identity_result["match_type"]
                    # Check if the resolved name matches the intended recipient
                    rn_lower = recipient_name.lower()
                    cn_lower = resolved_name.lower()
                    if rn_lower in cn_lower or cn_lower in rn_lower:
                        return {
                            "verified": True,
                            "resolved_name": resolved_name,
                            "match_type": match_type,
                            "sources_checked": sources_checked,
                        }
                    else:
                        return {
                            "verified": False,
                            "resolved_name": resolved_name,
                            "match_type": match_type,
                            "warning": f"RECIPIENT MISMATCH: Handle {to} is linked to '{resolved_name}', not '{recipient_name}'",
                            "sources_checked": sources_checked,
                        }
            except Exception:
                logger.debug("Failed to check identity store for recipient verification", exc_info=True)

        # 2. Check thread profiles
        messages_store = state.messages_store
        if messages_store:
            try:
                thread_result = messages_store.verify_handle(to)
                sources_checked.append("thread_profiles")
                if thread_result.get("found_in_threads") and thread_result.get("display_names"):
                    for display_name in thread_result["display_names"]:
                        dn_lower = display_name.lower()
                        rn_lower = recipient_name.lower()
                        if rn_lower in dn_lower or dn_lower in rn_lower:
                            return {
                                "verified": True,
                                "resolved_name": display_name,
                                "match_type": "thread_profile",
                                "sources_checked": sources_checked,
                            }
            except Exception:
                logger.debug("Failed to check thread profiles for recipient verification", exc_info=True)

        # 3. Fallback: resolve_sender
        if memory_store:
            try:
                sender_name = memory_store.resolve_sender("imessage", to)
                sources_checked.append("resolve_sender")
                if sender_name:
                    sn_lower = sender_name.lower()
                    rn_lower = recipient_name.lower()
                    if rn_lower in sn_lower or sn_lower in rn_lower:
                        return {
                            "verified": True,
                            "resolved_name": sender_name,
                            "match_type": "resolve_sender",
                            "sources_checked": sources_checked,
                        }
                    else:
                        return {
                            "verified": False,
                            "resolved_name": sender_name,
                            "match_type": "resolve_sender",
                            "warning": f"RECIPIENT MISMATCH: Handle {to} resolves to '{sender_name}', not '{recipient_name}'",
                            "sources_checked": sources_checked,
                        }
            except Exception:
                logger.debug("Failed to resolve sender for recipient verification", exc_info=True)

        return {
            "verified": False,
            "resolved_name": None,
            "match_type": None,
            "warning": f"UNVERIFIED RECIPIENT: Could not verify that {to} belongs to '{recipient_name}'. Sources checked: {', '.join(sources_checked) or 'none'}",
            "sources_checked": sources_checked,
        }

    @mcp.tool()
    async def send_imessage_reply(
        to: str = "",
        body: str = "",
        confirm_send: bool = False,
        chat_identifier: str = "",
        recipient_name: str = "",
    ) -> str:
        """Send an iMessage reply. REQUIRES confirm_send=true after explicit user confirmation.

        WARNING: This sends a real iMessage when confirm_send is true.

        Args:
            to: Recipient handle (phone, email, or 'self'). Optional when chat_identifier is provided.
            body: Message content
            confirm_send: Must be true to actually send
            chat_identifier: Optional thread identifier for thread-aware reply
            recipient_name: Optional intended recipient name for verification safety check
        """
        messages_store = state.messages_store
        try:
            result = messages_store.send_message(
                to=to,
                body=body,
                confirm_send=confirm_send,
                chat_identifier=chat_identifier,
            )
            # Run recipient verification when recipient_name is provided
            recipient_name_clean = (recipient_name or "").strip()
            to_clean = (to or "").strip().lower()
            if recipient_name_clean and to_clean != "self":
                verification = _verify_recipient(to, recipient_name_clean)
                result["recipient_verification"] = verification

            return json.dumps(result)
        except (OSError, PermissionError) as e:
            return json.dumps({"error": f"iMessage access error: {e}"})
        except Exception as e:
            logger.exception("Unexpected error in send_imessage_reply")
            return json.dumps({"error": f"Unexpected error: {e}"})

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
