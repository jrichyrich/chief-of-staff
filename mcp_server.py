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
from apple_notifications.notifier import Notifier
from apple_reminders.eventkit import ReminderStore
from connectors.calendar_unified import UnifiedCalendarService
from connectors.claude_m365_bridge import ClaudeM365Bridge
from connectors.providers import AppleCalendarProvider, Microsoft365CalendarProvider
from connectors.router import ProviderRouter
from documents.store import DocumentStore
from memory.store import MemoryStore
from okr.store import OKRStore
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
    m365_provider = Microsoft365CalendarProvider(
        connected=m365_bridge.is_connector_connected(),
        list_calendars_fn=m365_bridge.list_calendars,
        get_events_fn=m365_bridge.get_events,
        create_event_fn=m365_bridge.create_event,
        update_event_fn=m365_bridge.update_event,
        delete_event_fn=m365_bridge.delete_event,
        search_events_fn=m365_bridge.search_events,
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

    logger.info("Jarvis MCP server initialized")

    try:
        yield
    finally:
        # Reset all state attributes
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
    resources,
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
resources.register(mcp, _state)


# --- Entry point ---


def main():
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
