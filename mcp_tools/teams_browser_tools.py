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
    from connectors.graph_client import GraphAuthError, GraphTransientError
except ImportError:
    GraphAuthError = None  # type: ignore[assignment,misc]
    GraphTransientError = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Pre-compute Graph exception tuple once at import time (avoids per-call rebuild)
_GRAPH_FALLBACK_EXCEPTIONS: tuple = tuple(
    exc for exc in (GraphTransientError, GraphAuthError) if exc is not None
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


async def _graph_send_message(graph_client, target: str, message: str) -> dict:
    """Send a Teams message via Graph API, resolving target to a chat.

    Tries to find an existing chat by member email, then falls back to
    searching chats by display name, and finally creates a new chat if needed.

    Returns a dict with status and details.
    """
    # If target looks like an email, try direct member lookup
    target_emails = []
    if "@" in target:
        target_emails = [target.strip()]
    else:
        # Try comma-separated names as emails (group chat)
        parts = [t.strip() for t in target.split(",") if t.strip()]
        target_emails = [p for p in parts if "@" in p]

    chat_id = None

    # Strategy 1: Find chat by member email(s)
    if target_emails:
        chat_id = await graph_client.find_chat_by_members(target_emails)

    # Strategy 2: Search through chats by display name match
    # Prefer exact match, then substring; error on ambiguous substring matches
    if chat_id is None:
        target_lower = target.lower().strip()
        chats = await graph_client.list_chats(limit=50)
        substring_matches: list[tuple[str, str]] = []  # (chat_id, matched_name)

        # Pass 1: exact match on topic or displayName
        for chat in chats:
            topic = (chat.get("topic") or "").lower()
            if topic and target_lower == topic:
                chat_id = chat.get("id")
                break
            members = chat.get("members", [])
            for m in members:
                display = (m.get("displayName") or "").lower()
                if target_lower == display:
                    chat_id = chat.get("id")
                    break
            if chat_id:
                break

        # Pass 2: substring match (only if no exact match found)
        if chat_id is None:
            for chat in chats:
                topic = (chat.get("topic") or "").lower()
                if topic and target_lower in topic:
                    substring_matches.append((chat.get("id", ""), chat.get("topic") or ""))
                    continue
                members = chat.get("members", [])
                for m in members:
                    display = (m.get("displayName") or "").lower()
                    if target_lower in display:
                        substring_matches.append((chat.get("id", ""), m.get("displayName") or ""))
                        break

            if len(substring_matches) == 1:
                chat_id = substring_matches[0][0]
            elif len(substring_matches) > 1:
                match_names = [name for _, name in substring_matches]
                return {
                    "status": "error",
                    "backend": "graph",
                    "error": f"Ambiguous target '{target}' matched multiple chats: {match_names}. "
                             "Please use a more specific name or an email address.",
                }

    # Strategy 3: If target is email(s), create a new chat
    if chat_id is None and target_emails:
        result = await graph_client.create_chat(target_emails, message=message)
        return {
            "status": "sent",
            "backend": "graph",
            "chat_id": result.get("id"),
            "detail": f"Created new chat and sent message to {', '.join(target_emails)}",
        }

    if chat_id is None:
        return {
            "status": "error",
            "backend": "graph",
            "error": f"Could not resolve target '{target}' to a Teams chat. "
                     "Try using an email address instead of a display name.",
        }

    # Send to the resolved chat
    result = await graph_client.send_chat_message(chat_id, message)
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
    async def post_teams_message(target: str, message: str, auto_send: bool = False) -> str:
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

        Args:
            target: Channel name, person name, email, or comma-separated names for group chat
            message: The message text to post
            auto_send: If True, send immediately without confirmation step
        """
        send_backend = _get_send_backend()

        # --- Graph API path ---
        if send_backend == "graph":
            graph_client = state.graph_client
            if graph_client is not None:
                _graph_exceptions = _GRAPH_FALLBACK_EXCEPTIONS
                try:
                    result = await _graph_send_message(graph_client, target, message)
                    return json.dumps(result)
                except Exception as exc:
                    if _graph_exceptions and isinstance(exc, _graph_exceptions):
                        logger.warning(
                            "Graph API send failed (%s: %s), falling back to browser",
                            type(exc).__name__,
                            exc,
                        )
                    else:
                        raise  # Don't mask programming bugs
            else:
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

                    # Fetch messages from all chats in parallel
                    tasks = []
                    chat_index = []
                    for chat in chats[:limit]:
                        cid = chat.get("id")
                        if cid:
                            tasks.append(graph_client.get_chat_messages(cid, limit=25))
                            chat_index.append(chat)

                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for chat, chat_result in zip(chat_index, results):
                        if len(messages) >= limit:
                            break
                        if isinstance(chat_result, BaseException):
                            logger.warning("Failed to fetch messages for chat %s: %s", chat.get("id"), chat_result)
                            continue
                        chat_id = chat.get("id")
                        chat_name = chat.get("topic") or ", ".join(
                            m.get("displayName", "") for m in chat.get("members", [])
                        )
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

    # Expose at module level for test imports
    mod = sys.modules[__name__]
    mod.open_teams_browser = open_teams_browser
    mod.post_teams_message = post_teams_message
    mod.confirm_teams_post = confirm_teams_post
    mod.cancel_teams_post = cancel_teams_post
    mod.close_teams_browser = close_teams_browser
    mod.read_teams_messages = read_teams_messages
