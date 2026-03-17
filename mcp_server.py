# mcp_server.py
"""Chief of Staff MCP Server -- Claude Desktop & Claude Code plugin.

Exposes granular tools for memory, document search, and agent management.
No internal LLM calls — the host Claude handles all reasoning.
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import config as app_config
from agents.registry import AgentRegistry
from apple_calendar.eventkit import CalendarStore
from apple_mail.mail import MailStore
from apple_messages.messages import MessageStore
from apple_reminders.eventkit import ReminderStore
from connectors.calendar_unified import UnifiedCalendarService
from connectors.claude_m365_bridge import ClaudeM365Bridge
from connectors.providers import AppleCalendarProvider, Microsoft365CalendarProvider
from connectors.router import ProviderRouter
from documents.store import DocumentStore
from memory.models import ScheduledTask
from memory.store import MemoryStore
from okr.store import OKRStore
from hooks.registry import HookRegistry
from mcp_tools.state import ServerState

# All logging to stderr (stdout is the JSON-RPC channel for stdio transport)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("jarvis-mcp")

# Module-level state populated by lifespan manager
_state = ServerState()


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize shared resources on startup, clean up on shutdown."""
    app_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    app_config.AGENT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    routing_db_candidate = getattr(app_config, "CALENDAR_ROUTING_DB_PATH", None)
    routing_db_path = Path(routing_db_candidate) if isinstance(routing_db_candidate, (str, Path)) else (app_config.DATA_DIR / "calendar-routing.db")
    dual_read_candidate = getattr(app_config, "CALENDAR_REQUIRE_DUAL_READ", True)
    require_dual_read = bool(dual_read_candidate) if isinstance(dual_read_candidate, bool) else True
    claude_bin_candidate = getattr(app_config, "CLAUDE_BIN", "claude")
    claude_bin = claude_bin_candidate if isinstance(claude_bin_candidate, str) and claude_bin_candidate else "claude"
    claude_mcp_candidate = getattr(app_config, "CLAUDE_MCP_CONFIG", "")
    claude_mcp_config = claude_mcp_candidate if isinstance(claude_mcp_candidate, str) else ""
    m365_model_candidate = getattr(app_config, "M365_BRIDGE_MODEL", "sonnet")
    m365_model = m365_model_candidate if isinstance(m365_model_candidate, str) and m365_model_candidate else "sonnet"
    timeout_candidate = getattr(app_config, "M365_BRIDGE_TIMEOUT_SECONDS", 90)
    m365_timeout = timeout_candidate if isinstance(timeout_candidate, int) and timeout_candidate > 0 else 90
    detect_timeout_candidate = getattr(app_config, "M365_BRIDGE_DETECT_TIMEOUT_SECONDS", 5)
    m365_detect_timeout = detect_timeout_candidate if isinstance(detect_timeout_candidate, int) and detect_timeout_candidate > 0 else 5

    document_store = DocumentStore(persist_dir=app_config.CHROMA_PERSIST_DIR)
    memory_store = MemoryStore(
        app_config.MEMORY_DB_PATH,
        chroma_client=document_store.client,
    )
    agent_registry = AgentRegistry(app_config.AGENT_CONFIGS_DIR)
    apple_calendar_store = CalendarStore()
    m365_bridge = ClaudeM365Bridge(
        claude_bin=claude_bin,
        mcp_config=claude_mcp_config,
        model=m365_model,
        timeout_seconds=m365_timeout,
        detect_timeout_seconds=m365_detect_timeout,
    )
    m365_initial_connected = m365_bridge.is_connector_connected()
    if not m365_initial_connected:
        logger.warning(
            "M365 bridge not connected at startup — will re-check periodically. "
            "Calendar reads may fall back to Apple until M365 reconnects."
        )
    m365_provider = Microsoft365CalendarProvider(
        connected=m365_initial_connected,
        list_calendars_fn=m365_bridge.list_calendars,
        get_events_fn=m365_bridge.get_events,
        create_event_fn=m365_bridge.create_event,
        update_event_fn=m365_bridge.update_event,
        delete_event_fn=m365_bridge.delete_event,
        search_events_fn=m365_bridge.search_events,
        connectivity_checker=m365_bridge.is_connector_connected,
    )
    calendar_router = ProviderRouter({
        "apple": AppleCalendarProvider(apple_calendar_store),
        "microsoft_365": m365_provider,
    })
    calendar_store = UnifiedCalendarService(
        router=calendar_router,
        ownership_db_path=routing_db_path,
        require_all_read_providers_success=require_dual_read,
    )
    reminder_store = ReminderStore()
    mail_store = MailStore()
    messages_store = MessageStore()
    okr_store = OKRStore(app_config.OKR_DATA_DIR)

    # Initialize hook registry and load YAML configs
    hook_registry = HookRegistry()
    hook_configs_dir = app_config.BASE_DIR / "hooks" / "hook_configs"
    loaded = hook_registry.load_configs(hook_configs_dir)
    logger.info("Loaded %d hook(s) from %s", loaded, hook_configs_dir)

    _state.memory_store = memory_store
    _state.document_store = document_store
    _state.agent_registry = agent_registry
    _state.apple_calendar_store = apple_calendar_store
    _state.m365_bridge = m365_bridge
    _state.calendar_store = calendar_store
    _state.reminder_store = reminder_store
    _state.mail_store = mail_store
    _state.messages_store = messages_store
    _state.okr_store = okr_store
    _state.hook_registry = hook_registry

    # Initialize session brain
    from session.brain import SessionBrain
    _state.session_brain = SessionBrain(app_config.SESSION_BRAIN_PATH)
    _state.session_brain.load()

    # Initialize session manager (with brain for cross-session persistence)
    from session.manager import SessionManager
    _state.session_manager = SessionManager(memory_store, session_brain=_state.session_brain)

    # Seed default scheduled tasks if they don't already exist
    _default_tasks = [
        ScheduledTask(
            name="alert_eval",
            handler_type="alert_eval",
            schedule_type="interval",
            schedule_config='{"hours": 2}',
            description="Evaluate alert rules every 2 hours",
        ),
        ScheduledTask(
            name="webhook_poll",
            handler_type="webhook_poll",
            schedule_type="interval",
            schedule_config='{"minutes": 5}',
            description="Poll for new webhook events every 5 minutes",
        ),
        ScheduledTask(
            name="webhook_dispatch",
            handler_type="webhook_dispatch",
            schedule_type="interval",
            schedule_config='{"minutes": 5}',
            description="Dispatch pending webhook events to matched agents every 5 minutes",
        ),
        ScheduledTask(
            name="skill_analysis",
            handler_type="skill_analysis",
            schedule_type="interval",
            schedule_config='{"hours": 24}',
            description="Analyze skill usage patterns daily",
        ),
    ]
    for default_task in _default_tasks:
        if memory_store.get_scheduled_task_by_name(default_task.name) is None:
            from scheduler.engine import calculate_next_run
            default_task.next_run_at = calculate_next_run(
                default_task.schedule_type, default_task.schedule_config
            )
            memory_store.store_scheduled_task(default_task)
            logger.info("Seeded default scheduled task: %s", default_task.name)

    # Load proactive session context
    from session.context_loader import load_session_context
    from session.context_config import ContextLoaderConfig

    context_config = ContextLoaderConfig(
        enabled=app_config.SESSION_CONTEXT_ENABLED,
        per_source_timeout_seconds=app_config.SESSION_CONTEXT_TIMEOUT,
        ttl_minutes=app_config.SESSION_CONTEXT_TTL,
        sources={s: True for s in app_config.SESSION_CONTEXT_SOURCES},
    )
    if context_config.enabled:
        try:
            _state.session_context = load_session_context(_state, context_config)
            logger.info(
                "Session context loaded: %d events, %d unread, %d overdue, %d pending, %d reminders, errors: %s",
                len(_state.session_context.calendar_events),
                _state.session_context.unread_mail_count,
                len(_state.session_context.overdue_delegations),
                len(_state.session_context.pending_decisions),
                len(_state.session_context.due_reminders),
                list(_state.session_context.errors.keys()) or "none",
            )
        except Exception:
            logger.exception("Failed to load session context (non-fatal)")

    # Initialize Graph API client if credentials are available
    if app_config.M365_GRAPH_ENABLED:
        try:
            from connectors.graph_client import GraphClient
            _state.graph_client = GraphClient(
                client_id=app_config.M365_CLIENT_ID,
                tenant_id=app_config.M365_TENANT_ID,
                scopes=app_config.M365_GRAPH_SCOPES,
                interactive=False,  # MCP server runs headless over stdio
            )
            logger.info("Graph API client initialized")
            # Proactively validate the delegated token on startup
            try:
                refresh_result = await _state.graph_client.proactive_token_refresh()
                status = refresh_result["status"]
                if status == "expired":
                    logger.warning("Graph delegated token EXPIRED: %s", refresh_result["message"])
                elif status == "warning":
                    logger.warning("Graph token nearing expiry: %s", refresh_result["message"])
                else:
                    logger.info("Graph token OK: %s", refresh_result["message"])
                # Send macOS notification for warning/expired
                if status in ("warning", "expired"):
                    try:
                        from apple_notifications.notifier import Notifier

                        if status == "warning":
                            days = refresh_result.get("days_until_expiry", "?")
                            Notifier.send(
                                title="Jarvis: Graph Token Expiring",
                                message=f"Token expires in ~{days} days. Run: python scripts/bootstrap_secrets.py --reauth",
                            )
                        else:
                            Notifier.send(
                                title="Jarvis: Graph Token Expired",
                                message="Run: python scripts/bootstrap_secrets.py --reauth",
                                sound="Basso",
                            )
                    except Exception:
                        logger.warning("Failed to send token notification", exc_info=True)
            except Exception:
                logger.warning("Graph token refresh check failed", exc_info=True)
        except ImportError:
            logger.warning("msal/httpx not installed — Graph API disabled")
        except Exception:
            logger.warning("Graph API client initialization failed", exc_info=True)

    logger.info("Jarvis MCP server initialized")

    # Fire session_start hooks
    hook_registry.fire_hooks("session_start", {"event": "session_start"})

    try:
        yield
    finally:
        # Fire session_end hooks
        hook_registry.fire_hooks("session_end", {"event": "session_end"})

        # Close Graph API client
        if _state.graph_client:
            try:
                await _state.graph_client.close()
            except Exception:
                logger.warning("Failed to close Graph API client", exc_info=True)

        # Reset all state attributes
        _state.graph_client = None
        _state.hook_registry = None
        _state.memory_store = None
        _state.document_store = None
        _state.agent_registry = None
        _state.apple_calendar_store = None
        _state.m365_bridge = None
        _state.calendar_store = None
        _state.reminder_store = None
        _state.mail_store = None
        _state.messages_store = None
        _state.okr_store = None
        _state.allowed_ingest_roots = None
        _state.session_manager = None
        _state.session_brain = None
        _state.session_context = None
        memory_store.close()
        logger.info("Jarvis MCP server shut down")


# Create FastMCP server instance
mcp = FastMCP(
    "jarvis",
    lifespan=app_lifespan,
)

# Import and register all tool modules
from mcp_tools import (
    memory_tools,
    document_tools,
    agent_tools,
    lifecycle_tools,
    calendar_tools,
    reminder_tools,
    mail_tools,
    imessage_tools,
    okr_tools,
    webhook_tools,
    skill_tools,
    scheduler_tools,
    proactive_tools,
    channel_tools,
    identity_tools,
    event_rule_tools,
    session_tools,
    resources,
    enrichment,
    teams_browser_tools,
    web_browser_tools,
    brain_tools,
    routing_tools,
    playbook_tools,
    formatter_tools,
    dispatch_tools,
    sharepoint_tools,
    api_usage_tools,
)

# Register all tool groups
memory_tools.register(mcp, _state)
document_tools.register(mcp, _state)
agent_tools.register(mcp, _state)
lifecycle_tools.register(mcp, _state)
calendar_tools.register(mcp, _state)
reminder_tools.register(mcp, _state)
mail_tools.register(mcp, _state)
imessage_tools.register(mcp, _state)
okr_tools.register(mcp, _state)
webhook_tools.register(mcp, _state)
skill_tools.register(mcp, _state)
scheduler_tools.register(mcp, _state)
proactive_tools.register(mcp, _state)
channel_tools.register(mcp, _state)
identity_tools.register(mcp, _state)
event_rule_tools.register(mcp, _state)
session_tools.register(mcp, _state)
resources.register(mcp, _state)
enrichment.register(mcp, _state)
teams_browser_tools.register(mcp, _state)
web_browser_tools.register(mcp, _state)
brain_tools.register(mcp, _state)
routing_tools.register(mcp, _state)
playbook_tools.register(mcp, _state)
formatter_tools.register(mcp, _state)
dispatch_tools.register(mcp, _state)
sharepoint_tools.register(mcp, _state)
api_usage_tools.register(mcp, _state)

# Install automatic tool usage tracking (must come after all tools are registered)
from mcp_tools.usage_tracker import install_usage_tracker
install_usage_tracker(mcp, _state)


# --- Entry point ---


def main():
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
