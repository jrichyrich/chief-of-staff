"""Teams browser automation tools for MCP server.

Five tools:
1. ``open_teams_browser`` — launch persistent browser, navigate to Teams
2. ``post_teams_message`` — search for target by name, return confirmation
3. ``confirm_teams_post`` — send the prepared message
4. ``cancel_teams_post`` — cancel without sending
5. ``close_teams_browser`` — close the browser

Supports two backends controlled by ``TEAMS_POSTER_BACKEND`` in config:
- ``"agent-browser"`` (default): Uses accessibility-tree snapshots via agent-browser CLI
- ``"playwright"``: Uses CSS selectors via Playwright CDP
"""

import json
import logging
import sys

logger = logging.getLogger(__name__)

_manager = None
_poster = None
_ab = None


def _get_backend() -> str:
    from config import TEAMS_POSTER_BACKEND
    return TEAMS_POSTER_BACKEND


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
        backend = _get_backend()
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
    try:
        pw, browser = await manager.connect()
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # If already on Teams, nothing to do
        if any(p in page.url.lower() for p in ("teams.microsoft.com", "teams.cloud.microsoft")):
            await pw.stop()
            return {"ok": True}

        # Go through Okta auth -> tile click -> Teams
        from browser.okta_auth import ensure_okta_and_open_teams
        await ensure_okta_and_open_teams(page, ctx)

        await pw.stop()
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


def register(mcp, state):
    """Register Teams browser tools with the MCP server."""

    @mcp.tool()
    async def open_teams_browser() -> str:
        """Launch a persistent browser and navigate to Teams.

        The browser stays open in the background. If the Teams session
        has expired, authenticate manually in the browser window — the
        session is cached in the browser profile for future calls.

        Call this before using post_teams_message. Idempotent — returns
        current status if the browser is already running.
        """
        backend = _get_backend()

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
    async def post_teams_message(target: str, message: str, auto_send: bool = False) -> str:
        """Prepare a message for posting to a Teams channel, person, or group.

        Connects to the running browser, uses the Teams search bar to
        find the target by name, navigates there, and returns
        confirmation info. Does NOT send the message yet (unless auto_send=True).

        After this returns ``"confirm_required"``, call
        ``confirm_teams_post`` to send or ``cancel_teams_post`` to abort.

        For group chats, pass multiple names separated by commas
        (e.g. "Alice, Bob, Charlie"). This creates a new group chat
        with all recipients.

        Args:
            target: Channel name, person name, or comma-separated names for group chat
            message: The message text to post
            auto_send: If True, send immediately without confirmation step
        """
        poster = _get_poster()

        # Detect group chat: comma-separated names → list
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
    async def confirm_teams_post() -> str:
        """Send the previously prepared Teams message.

        Must be called after ``post_teams_message`` returned
        ``"confirm_required"``.
        """
        poster = _get_poster()
        result = await poster.send_prepared_message()
        return json.dumps(result)

    @mcp.tool()
    async def cancel_teams_post() -> str:
        """Cancel the previously prepared Teams message.

        Disconnects from the browser without sending.
        """
        poster = _get_poster()
        result = await poster.cancel_prepared_message()
        return json.dumps(result)

    @mcp.tool()
    async def close_teams_browser() -> str:
        """Close the persistent Teams browser.

        Call ``open_teams_browser`` to restart.
        """
        backend = _get_backend()

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

    # Expose at module level for test imports
    mod = sys.modules[__name__]
    mod.open_teams_browser = open_teams_browser
    mod.post_teams_message = post_teams_message
    mod.confirm_teams_post = confirm_teams_post
    mod.cancel_teams_post = cancel_teams_post
    mod.close_teams_browser = close_teams_browser
