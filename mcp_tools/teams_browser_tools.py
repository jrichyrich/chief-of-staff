"""Teams browser automation tools for MCP server.

Six tools:
1. ``open_teams_browser`` -- launch persistent browser, navigate to Teams
2. ``post_teams_message`` -- search for target by name, return confirmation
3. ``confirm_teams_post`` -- send the prepared message
4. ``cancel_teams_post`` -- cancel without sending
5. ``close_teams_browser`` -- close the browser
6. ``read_teams_messages`` -- read/search Teams chat messages

Supports three send backends controlled by ``TEAMS_SEND_BACKEND`` in config:
- ``"graph"`` (default when Graph configured): Microsoft Graph API direct
- ``"agent-browser"``: Uses accessibility-tree snapshots via agent-browser CLI
- ``"playwright"``: Uses CSS selectors via Playwright CDP

Graph send falls back to browser on transient/auth errors.

Read backend controlled by ``TEAMS_READ_BACKEND``:
- ``"graph"``: Microsoft Graph API direct
- ``"m365-bridge"``: Claude CLI subprocess bridge
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from typing import Optional

from .decorators import tool_errors

# Guarded import for Graph exceptions
try:
    from connectors.graph_client import GraphAPIError, GraphAuthError, GraphTransientError
except ImportError:
    GraphAPIError = None  # type: ignore[assignment,misc]
    GraphAuthError = None  # type: ignore[assignment,misc]
    GraphTransientError = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


# Chat type priority for sorting (lower = preferred)
_CHAT_TYPE_PRIORITY = {
    "oneOnOne": 0,
    "unknown": 1,
    "group": 2,
    "meeting": 2,
    "channel": 3,
}


def _chat_type_from_id(chat_id: str) -> str:
    """Derive the chat type from a Teams chat ID string."""
    if "@unq.gbl.spaces" in chat_id:
        return "oneOnOne"
    elif "@thread.tacv2" in chat_id:
        return "channel"
    elif "@thread.v2" in chat_id:
        return "group"
    return "unknown"


def _chat_type_priority(chat_id: str, chat_type_field: str = "") -> int:
    """Return sort priority for a chat. Lower = preferred.

    Uses the ``chatType`` field from Graph API if available,
    falls back to inferring from the chat ID string.
    """
    ct = chat_type_field or _chat_type_from_id(chat_id)
    return _CHAT_TYPE_PRIORITY.get(ct, 2)


# Pre-compute Graph exception tuple once at import time (avoids per-call rebuild)
_GRAPH_FALLBACK_EXCEPTIONS: tuple = tuple(
    exc for exc in (GraphAPIError, GraphTransientError, GraphAuthError) if exc is not None
)

_manager = None
_poster = None
_ab = None


def _get_send_backend() -> str:
    from config import TEAMS_SEND_BACKEND
    return TEAMS_SEND_BACKEND


def _get_read_backend() -> str:
    from config import TEAMS_READ_BACKEND
    return TEAMS_READ_BACKEND


def _get_ab():
    """Return the singleton AgentBrowser instance (agent-browser backend)."""
    global _ab
    if _ab is None:
        from browser.agent_browser import AgentBrowser
        from config import AGENT_BROWSER_BIN, AGENT_BROWSER_DATA_DIR, AGENT_BROWSER_TIMEOUT, AGENT_BROWSER_HEADED
        _ab = AgentBrowser(
            bin_path=AGENT_BROWSER_BIN,
            profile_dir=AGENT_BROWSER_DATA_DIR,
            timeout=AGENT_BROWSER_TIMEOUT,
            headed=AGENT_BROWSER_HEADED,
        )
    return _ab


def _get_manager():
    """Return the singleton TeamsBrowserManager (playwright backend)."""
    global _manager
    if _manager is None:
        from browser.manager import TeamsBrowserManager
        _manager = TeamsBrowserManager()
    return _manager


def _get_poster():
    global _poster
    if _poster is None:
        backend = _get_send_backend()
        if backend == "agent-browser":
            from browser.ab_poster import ABTeamsPoster
            _poster = ABTeamsPoster(ab=_get_ab())
        else:
            from browser.teams_poster import PlaywrightTeamsPoster
            _poster = PlaywrightTeamsPoster(manager=_get_manager())
    return _poster


async def _wait_for_teams(manager, timeout_s: int = 30) -> dict:
    """After launch, navigate through Okta to Teams and wait for it to load.

    Returns a dict with 'ok' (bool) and optional 'detail' message.
    """
    pw = None
    try:
        pw, browser = await manager.connect()
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # If already on Teams, nothing to do
        if any(p in page.url.lower() for p in ("teams.microsoft.com", "teams.cloud.microsoft")):
            return {"ok": True}

        # Go through Okta auth -> tile click -> Teams
        from browser.okta_auth import ensure_okta_and_open_teams
        await ensure_okta_and_open_teams(page, ctx)

        return {"ok": True}
    except RuntimeError as exc:
        msg = str(exc)
        logger.warning("Teams navigation: %s", msg)
        if "authentication timed out" in msg.lower():
            return {
                "ok": False,
                "detail": "Okta auth required. Authenticate in the browser, then call open_teams_browser again.",
            }
        return {"ok": False, "detail": msg}
    except Exception as exc:
        logger.warning("Failed to navigate to Teams via Okta: %s", exc)
        return {"ok": False, "detail": str(exc)}
    finally:
        if pw is not None:
            await pw.stop()


async def _graph_send_message(
    graph_client, target: str, message: str,
    content_type: str = "text", mentions: list[dict] | None = None,
) -> dict:
    """Send a Teams message via Graph API, resolving target to a chat.

    Resolution strategies (in order):
    0. Direct chat ID (starts with ``19:``)
    0.5. Comma-separated names -> resolve each via /users, create group chat
    1. Email target(s) -> find existing chat by member emails
    1.5. Single display name -> resolve to email via /users -> find chat
    2. Display name search across chat list (exact then substring)
    3. Create new chat if target is email(s) and no chat found

    Raises ``GraphAPIError`` on resolution failure so the caller can
    fall back to the browser poster.
    """
    # --- Parse target into emails and/or names ---
    target_emails: list[str] = []
    target_names: list[str] = []
    if "," in target:
        parts = [t.strip() for t in target.split(",") if t.strip()]
        target_emails = [p for p in parts if "@" in p]
        target_names = [p for p in parts if "@" not in p]
    elif "@" in target:
        target_emails = [target.strip()]
    else:
        target_names = [target.strip()]

    chat_id = None

    # Priority 0: Direct chat ID — skip all resolution
    if target.startswith("19:"):
        chat_id = target
    else:
        # Strategy 0.5: Resolve display names to emails
        if target_names:
            resolved_emails: list[str | None] = []
            for name in target_names:
                email = await graph_client.resolve_user_email(name)
                resolved_emails.append(email)

            if all(resolved_emails):
                # All names resolved — merge with any email targets
                target_emails = target_emails + [e for e in resolved_emails if e]
            elif len(target_names) > 1:
                # Group chat requires all names resolved — raise to trigger fallback
                failed = [n for n, e in zip(target_names, resolved_emails) if e is None]
                raise GraphAPIError(
                    f"Could not resolve group chat members: {', '.join(failed)}"
                )
            # Single unresolved name: fall through to Strategy 2 (display name search)

        # Strategy 1: Find chat by member email(s)
        if target_emails:
            chat_id = await graph_client.find_chat_by_members(target_emails)

        # Strategy 2: Search through chats by display name match
        # Only for single-name targets where email resolution failed
        if chat_id is None and len(target_names) == 1 and not target_emails:
            target_lower = target_names[0].lower()
            chats = await graph_client.list_chats(limit=50)
            substring_matches: list[tuple[str, str, int, int]] = []

            # Pass 1: exact match on topic or displayName
            exact_matches: list[tuple[str, int, int]] = []  # (chat_id, type_priority, member_count)
            for chat in chats:
                topic = (chat.get("topic") or "").lower()
                members = chat.get("members", [])
                member_count = len(members)
                chat_id_candidate = chat.get("id", "")
                type_prio = _chat_type_priority(chat_id_candidate, chat.get("chatType", ""))
                if topic and target_lower == topic:
                    exact_matches.append((chat_id_candidate, type_prio, member_count))
                    continue
                for m in members:
                    display = (m.get("displayName") or "").lower()
                    if target_lower == display:
                        exact_matches.append((chat_id_candidate, type_prio, member_count))
                        break

            if exact_matches:
                # Sort by: chat type priority (oneOnOne first), then member count
                exact_matches.sort(key=lambda x: (x[1], x[2]))
                chat_id = exact_matches[0][0]

            # Pass 2: substring match (only if no exact match found)
            if chat_id is None:
                for chat in chats:
                    topic = (chat.get("topic") or "").lower()
                    members = chat.get("members", [])
                    member_count = len(members)
                    chat_id_candidate = chat.get("id", "")
                    type_prio = _chat_type_priority(chat_id_candidate, chat.get("chatType", ""))
                    if topic and target_lower in topic:
                        substring_matches.append((chat_id_candidate, chat.get("topic") or "", type_prio, member_count))
                        continue
                    for m in members:
                        display = (m.get("displayName") or "").lower()
                        if target_lower in display:
                            substring_matches.append((chat_id_candidate, m.get("displayName") or "", type_prio, member_count))
                            break

                if len(substring_matches) == 1:
                    chat_id = substring_matches[0][0]
                elif len(substring_matches) > 1:
                    # Sort by chat type priority, then member count
                    substring_matches.sort(key=lambda x: (x[2], x[3]))
                    # Only ambiguous if top two have same priority AND member count
                    if (substring_matches[0][2], substring_matches[0][3]) < (substring_matches[1][2], substring_matches[1][3]):
                        chat_id = substring_matches[0][0]
                    else:
                        match_names = [name for _, name, _, _ in substring_matches]
                        raise GraphAPIError(
                            f"Ambiguous target '{target}' matched multiple chats: {match_names}. "
                            "Please use a more specific name or an email address."
                        )

    # Strategy 3: If target is email(s), create a new chat
    if chat_id is None and target_emails:
        result = await graph_client.create_chat(target_emails)
        new_chat_id = result.get("id")
        if not new_chat_id:
            raise GraphAPIError("create_chat returned no id — message not sent")
        await graph_client.send_chat_message(new_chat_id, message, content_type=content_type, mentions=mentions)
        return {
            "status": "sent",
            "backend": "graph",
            "chat_id": new_chat_id,
            "detail": f"Created new chat and sent message to {', '.join(target_emails)}",
        }

    if chat_id is None:
        raise GraphAPIError(
            f"Could not resolve target '{target}' to a Teams chat. "
            "Try using an email address instead of a display name."
        )

    # Send to the resolved chat
    result = await graph_client.send_chat_message(chat_id, message, content_type=content_type, mentions=mentions)
    return {
        "status": "sent",
        "backend": "graph",
        "chat_id": chat_id,
        "message_id": result.get("id"),
    }


async def _read_via_m365_bridge(state, query: Optional[str], after_datetime: Optional[str], limit: int) -> dict:
    """Read Teams messages using the Claude M365 Bridge subprocess."""
    if state.m365_bridge is None:
        return {"error": "M365 bridge not configured", "messages": []}

    bridge = state.m365_bridge
    schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "chat_name": {"type": "string"},
                        "sender": {"type": "string"},
                        "content": {"type": "string"},
                        "timestamp": {"type": "string"},
                    },
                },
            },
        },
        "required": ["results"],
    }
    query_clause = f"Search for: {bridge._sanitize_for_prompt(query)}. " if query else ""
    time_clause = f"Only include messages after {after_datetime}. " if after_datetime else ""
    prompt = (
        "Use only Microsoft 365 MCP connector tools to search Teams chat messages. "
        f"{query_clause}{time_clause}"
        f"Return up to {limit} recent messages. "
        "Return each message with: chat_name, sender, content, timestamp."
    )
    data = bridge._invoke_structured(prompt, schema)
    if data.get("error"):
        return {"error": data["error"], "messages": [], "backend": "m365-bridge"}
    messages = [dict(row) for row in data.get("results", []) if isinstance(row, dict)]
    return {"messages": messages, "count": len(messages), "backend": "m365-bridge"}


def register(mcp, state):
    """Register Teams browser tools with the MCP server."""

    @mcp.tool()
    @tool_errors("Teams browser error")
    async def open_teams_browser() -> str:
        """Launch a persistent browser and navigate to Teams.

        The browser stays open in the background. If the Teams session
        has expired, authenticate manually in the browser window -- the
        session is cached in the browser profile for future calls.

        Call this before using post_teams_message. Idempotent -- returns
        current status if the browser is already running.
        """
        backend = _get_send_backend()

        if backend == "agent-browser":
            ab = _get_ab()
            try:
                await ab.open("https://teams.microsoft.com")
                return json.dumps({"status": "running", "backend": "agent-browser"})
            except Exception as exc:
                logger.exception("Failed to open Teams via agent-browser")
                return json.dumps({"status": "error", "error": str(exc)})
        else:
            mgr = _get_manager()
            result = mgr.launch()

            if result["status"] in ("launched", "already_running"):
                nav = await _wait_for_teams(mgr)
                if nav["ok"]:
                    result["status"] = "running"
                else:
                    result["status"] = "awaiting_action"
                    result["detail"] = nav.get("detail", "Teams navigation incomplete")

            return json.dumps(result)

    @mcp.tool()
    @tool_errors("Teams browser error")
    async def post_teams_message(
        target: str, message: str, auto_send: bool = False,
        content_type: str = "text", mention_emails: list[str] | None = None,
        prefer_backend: str = "",
    ) -> str:
        """Prepare a message for posting to a Teams channel, person, or group.

        Connects to the running browser, uses the Teams search bar to
        find the target by name, navigates there, and returns
        confirmation info. Does NOT send the message yet (unless auto_send=True).

        When ``TEAMS_SEND_BACKEND=graph``, sends directly via Microsoft Graph
        API (no browser needed). Falls back to browser on transient errors.

        After this returns ``"confirm_required"``, call
        ``confirm_teams_post`` to send or ``cancel_teams_post`` to abort.

        For group chats, pass multiple names separated by commas
        (e.g. "Alice, Bob, Charlie"). This creates a new group chat
        with all recipients.

        When mention_emails are provided, users are @mentioned in the message.
        The content_type is automatically set to 'html' when mentions are used.

        Args:
            target: Channel name, person name, email, or comma-separated names for group chat
            message: The message text to post
            auto_send: If True, send immediately without confirmation step
            content_type: 'text' (default) or 'html' for rich formatting
            mention_emails: Optional list of email addresses to @mention
            prefer_backend: Force a specific backend: 'graph' (no browser fallback),
                'browser' (skip Graph), or '' (default: Graph with browser fallback)
        """
        send_backend = _get_send_backend()
        # Allow caller to override the backend selection
        use_graph = (prefer_backend == "graph") or (send_backend == "graph" and prefer_backend != "browser")
        graph_only = prefer_backend == "graph"
        graph_error_msg = ""

        # --- Graph API path ---
        if use_graph:
            graph_client = state.graph_client
            if graph_client is not None:
                # --- Resolve @mentions if requested ---
                mentions = None
                failed_mention_emails: list[str] = []
                if mention_emails and graph_client is not None:
                    content_type = "html"
                    mentions = []
                    mention_tags: list[str] = []
                    for idx, email in enumerate(mention_emails):
                        user = await graph_client.get_user_by_email(email)
                        if user:
                            display_name = user["displayName"]
                            mentions.append({
                                "id": idx,
                                "mentionText": display_name,
                                "mentioned": {
                                    "user": {
                                        "id": user["id"],
                                        "displayName": display_name,
                                        "userIdentityType": "aadUser",
                                    }
                                },
                            })
                            mention_tags.append(f'<at id="{idx}">{display_name}</at>')
                        else:
                            failed_mention_emails.append(email)
                    if mention_tags:
                        message = " ".join(mention_tags) + " " + message

                _graph_exceptions = _GRAPH_FALLBACK_EXCEPTIONS
                try:
                    result = await _graph_send_message(graph_client, target, message, content_type=content_type, mentions=mentions)
                    if failed_mention_emails:
                        result["unresolved_mentions"] = failed_mention_emails
                    return json.dumps(result)
                except Exception as exc:
                    if _graph_exceptions and isinstance(exc, _graph_exceptions):
                        graph_error_msg = f"{type(exc).__name__}: {exc}"
                        if graph_only:
                            return json.dumps({
                                "status": "error",
                                "backend": "graph",
                                "error": graph_error_msg,
                            })
                        logger.warning(
                            "Graph API send failed (%s), falling back to browser",
                            graph_error_msg,
                        )
                    else:
                        raise  # Don't mask programming bugs
            else:
                graph_error_msg = "Graph client not configured"
                if graph_only:
                    return json.dumps({
                        "status": "error",
                        "backend": "graph",
                        "error": graph_error_msg,
                    })
                logger.warning("Graph client not configured, falling back to browser")

        # --- Browser path (agent-browser or playwright) ---
        poster = _get_poster()

        # Detect group chat: comma-separated names -> list
        parsed_target = target
        if "," in target:
            names = [n.strip() for n in target.split(",") if n.strip()]
            if len(names) > 1:
                parsed_target = names

        if auto_send:
            result = await poster.send_message(parsed_target, message)
        else:
            result = await poster.prepare_message(parsed_target, message)

        # Surface any Graph error that triggered the fallback
        if graph_error_msg and isinstance(result, dict):
            result["graph_error"] = graph_error_msg
        return json.dumps(result)

    @mcp.tool()
    @tool_errors("Teams browser error")
    async def confirm_teams_post() -> str:
        """Send the previously prepared Teams message.

        Must be called after ``post_teams_message`` returned
        ``"confirm_required"``.
        """
        poster = _get_poster()
        result = await poster.send_prepared_message()
        return json.dumps(result)

    @mcp.tool()
    @tool_errors("Teams browser error")
    async def cancel_teams_post() -> str:
        """Cancel the previously prepared Teams message.

        Disconnects from the browser without sending.
        """
        poster = _get_poster()
        result = await poster.cancel_prepared_message()
        return json.dumps(result)

    @mcp.tool()
    @tool_errors("Teams browser error")
    async def close_teams_browser() -> str:
        """Close the persistent Teams browser.

        Call ``open_teams_browser`` to restart.
        """
        backend = _get_send_backend()

        if backend == "agent-browser":
            ab = _get_ab()
            try:
                await ab.close()
                return json.dumps({"status": "closed", "backend": "agent-browser"})
            except Exception as exc:
                logger.warning("Failed to close agent-browser: %s", exc)
                return json.dumps({"status": "closed", "detail": str(exc)})
        else:
            mgr = _get_manager()
            result = mgr.close()
            return json.dumps(result)

    @mcp.tool()
    @tool_errors("Teams read error")
    async def read_teams_messages(
        query: str = "",
        after_datetime: str = "",
        limit: int = 25,
    ) -> str:
        """Read recent Teams chat messages.

        Searches across the authenticated user's Teams chats and returns
        matching messages. Uses Microsoft Graph API when configured, with
        fallback to the Claude M365 Bridge.

        Args:
            query: Optional search term to filter messages
            after_datetime: Optional ISO datetime; only return messages after this time
            limit: Maximum number of messages to return (default 25)
        """
        read_backend = _get_read_backend()

        # --- Graph API path ---
        if read_backend == "graph":
            graph_client = state.graph_client
            if graph_client is not None:
                _graph_exceptions = _GRAPH_FALLBACK_EXCEPTIONS
                try:
                    messages = []
                    chats = await graph_client.list_chats(limit=50)
                    query_lower = query.lower() if query else ""

                    # Parse after_datetime once for proper ISO comparison
                    after_dt = None
                    if after_datetime:
                        try:
                            after_dt = datetime.fromisoformat(after_datetime.replace('Z', '+00:00'))
                        except ValueError:
                            pass

                    # Fetch messages from all chats in parallel (max 10 concurrent)
                    sem = asyncio.Semaphore(10)

                    async def _fetch(cid):
                        async with sem:
                            return await graph_client.get_chat_messages(cid, limit=25)

                    chat_index = [chat for chat in chats if chat.get("id")]
                    tasks = [_fetch(chat["id"]) for chat in chat_index]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for chat, chat_result in zip(chat_index, results):
                        if len(messages) >= limit:
                            break
                        if isinstance(chat_result, BaseException):
                            logger.warning("Failed to fetch messages for chat %s: %s", chat.get("id"), chat_result)
                            continue
                        chat_id = chat.get("id", "")
                        chat_topic = chat.get("topic") or None
                        chat_members_list = [
                            m.get("displayName", "")
                            for m in chat.get("members", [])
                            if m.get("displayName")
                        ]
                        chat_name = chat_topic or ", ".join(chat_members_list)
                        chat_type = _chat_type_from_id(chat_id)
                        for msg in chat_result:
                            body = msg.get("body", {})
                            content = body.get("content", "") if isinstance(body, dict) else str(body)
                            timestamp = msg.get("createdDateTime", "")
                            sender_info = msg.get("from", {}) or {}
                            user_info = sender_info.get("user", {}) or {}
                            sender = user_info.get("displayName", "Unknown")

                            # Filter by after_datetime (proper ISO comparison)
                            if after_dt and timestamp:
                                try:
                                    msg_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                    if msg_dt < after_dt:
                                        continue
                                except ValueError:
                                    pass

                            # Filter by query
                            if query_lower and query_lower not in content.lower() and query_lower not in sender.lower():
                                continue

                            messages.append({
                                "chat_id": chat_id,
                                "chat_type": chat_type,
                                "chat_topic": chat_topic,
                                "chat_members": chat_members_list,
                                "chat_name": chat_name,
                                "sender": sender,
                                "content": content,
                                "timestamp": timestamp,
                                "message_id": msg.get("id"),
                            })

                            if len(messages) >= limit:
                                break

                    return json.dumps({
                        "messages": messages,
                        "count": len(messages),
                        "backend": "graph",
                    })
                except Exception as exc:
                    if _graph_exceptions and isinstance(exc, _graph_exceptions):
                        logger.warning(
                            "Graph API read failed (%s: %s), falling back to m365-bridge",
                            type(exc).__name__,
                            exc,
                        )
                    else:
                        raise  # Don't mask programming bugs
            else:
                logger.warning("Graph client not configured, falling back to m365-bridge")

        # --- M365 Bridge fallback ---
        result = await _read_via_m365_bridge(
            state,
            query=query or None,
            after_datetime=after_datetime or None,
            limit=limit,
        )
        return json.dumps(result)

    @mcp.tool()
    @tool_errors("Teams reply error")
    async def reply_to_teams_message(
        chat_id: str,
        message_id: str,
        message: str,
        content_type: str = "text",
        mention_emails: list[str] | None = None,
    ) -> str:
        """Reply to a specific message in a Teams chat (creates a threaded reply).

        The chat_id and message_id can be obtained from read_teams_messages results.

        When mention_emails are provided, users are @mentioned in the reply.
        The content_type is automatically set to 'html' when mentions are used.

        Args:
            chat_id: The Teams chat ID (from read_teams_messages results)
            message_id: The message ID to reply to (from read_teams_messages results)
            message: The reply text
            content_type: 'text' (default) or 'html' for rich formatting
            mention_emails: Optional list of email addresses to @mention
        """
        graph_client = state.graph_client
        if graph_client is None:
            return json.dumps({"error": "Graph API not configured — reply requires Graph API"})

        mentions = None
        failed_mention_emails: list[str] = []
        if mention_emails:
            content_type = "html"
            mentions = []
            mention_tags: list[str] = []
            for idx, email in enumerate(mention_emails):
                user = await graph_client.get_user_by_email(email)
                if user:
                    display_name = user["displayName"]
                    mentions.append({
                        "id": idx,
                        "mentionText": display_name,
                        "mentioned": {
                            "user": {
                                "id": user["id"],
                                "displayName": display_name,
                                "userIdentityType": "aadUser",
                            }
                        },
                    })
                    mention_tags.append(f'<at id="{idx}">{display_name}</at>')
                else:
                    failed_mention_emails.append(email)
            if mention_tags:
                message = " ".join(mention_tags) + " " + message

        try:
            result = await graph_client.reply_to_chat_message(
                chat_id, message_id, message,
                content_type=content_type,
                mentions=mentions,
            )
            reply_result: dict = {
                "status": "sent",
                "backend": "graph",
                "chat_id": chat_id,
                "parent_message_id": message_id,
                "reply_id": result.get("id"),
            }
            if failed_mention_emails:
                reply_result["unresolved_mentions"] = failed_mention_emails
            return json.dumps(reply_result)
        except Exception as exc:
            return json.dumps({"error": f"Reply failed: {exc}"})

    @mcp.tool()
    @tool_errors("Teams chat management error")
    async def manage_teams_chat(
        chat_id: str,
        action: str,
        topic: str = "",
        user_email: str = "",
        membership_id: str = "",
    ) -> str:
        """Manage a Teams group chat — rename, list/add/remove members.

        Actions:
        - ``rename``: Set the chat topic (requires ``topic`` param)
        - ``list_members``: List all members with their IDs and emails
        - ``add_member``: Add a user to the chat (requires ``user_email`` param)
        - ``remove_member``: Remove a member (requires ``membership_id`` from list_members)

        Args:
            chat_id: The Teams chat ID
            action: One of: rename, list_members, add_member, remove_member
            topic: New topic name (for rename action)
            user_email: Email of user to add (for add_member action)
            membership_id: Member ID to remove (for remove_member action)
        """
        graph_client = state.graph_client
        if graph_client is None:
            return json.dumps({"error": "Graph API not configured — chat management requires Graph API"})

        try:
            if action == "rename":
                await graph_client.update_chat_topic(chat_id, topic)
                return json.dumps({"status": "success", "action": "rename", "topic": topic})
            elif action == "list_members":
                members = await graph_client.list_chat_members(chat_id)
                return json.dumps({"status": "success", "action": "list_members", "members": members})
            elif action == "add_member":
                result = await graph_client.add_chat_member(chat_id, user_email)
                return json.dumps({"status": "success", "action": "add_member", "user_email": user_email, "result": result})
            elif action == "remove_member":
                await graph_client.remove_chat_member(chat_id, membership_id)
                return json.dumps({"status": "success", "action": "remove_member", "membership_id": membership_id})
            else:
                return json.dumps({"error": f"Unknown action '{action}'. Valid: rename, list_members, add_member, remove_member"})
        except Exception as exc:
            return json.dumps({"error": f"Chat management failed: {exc}"})

    # Expose at module level for test imports
    mod = sys.modules[__name__]
    mod.open_teams_browser = open_teams_browser
    mod.post_teams_message = post_teams_message
    mod.confirm_teams_post = confirm_teams_post
    mod.cancel_teams_post = cancel_teams_post
    mod.close_teams_browser = close_teams_browser
    mod.read_teams_messages = read_teams_messages
    mod.reply_to_teams_message = reply_to_teams_message
    mod.manage_teams_chat = manage_teams_chat
