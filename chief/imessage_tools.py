"""Build tool schemas and handlers for async iMessage command execution.

Provides a subset of Jarvis MCP tools that are safe and useful for
unattended async execution from iMessage instructions.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Tools available for async iMessage execution (read-heavy, low-risk).
# Deliberately excludes destructive operations like send_email, delete_*,
# create_calendar_event, post_teams_message, etc.
ASYNC_SAFE_TOOLS = [
    # Calendar (read)
    "get_calendar_events",
    "search_calendar_events",
    "find_my_open_slots",
    # Memory (read/write — store_fact is low-risk)
    "query_memory",
    "store_fact",
    "list_facts",
    # Reminders (read/write — create and complete are low-risk)
    "list_reminders",
    "create_reminder",
    "complete_reminder",
    "search_reminders",
    # Mail (read only)
    "search_mail",
    "get_mail_messages",
    # Decisions/Delegations (read only)
    "list_pending_decisions",
    "list_delegations",
    "check_overdue_delegations",
    # Session
    "get_session_brain",
]

# Map tool names to the (module_path, function_name) where they live
_TOOL_MODULE_MAP: dict[str, str] = {
    "get_calendar_events": "mcp_tools.calendar_tools",
    "search_calendar_events": "mcp_tools.calendar_tools",
    "find_my_open_slots": "mcp_tools.calendar_tools",
    "query_memory": "mcp_tools.memory_tools",
    "store_fact": "mcp_tools.memory_tools",
    "list_facts": "mcp_tools.memory_tools",
    "list_reminders": "mcp_tools.reminder_tools",
    "create_reminder": "mcp_tools.reminder_tools",
    "complete_reminder": "mcp_tools.reminder_tools",
    "search_reminders": "mcp_tools.reminder_tools",
    "search_mail": "mcp_tools.mail_tools",
    "get_mail_messages": "mcp_tools.mail_tools",
    "list_pending_decisions": "mcp_tools.lifecycle_tools",
    "list_delegations": "mcp_tools.lifecycle_tools",
    "check_overdue_delegations": "mcp_tools.lifecycle_tools",
    "get_session_brain": "mcp_tools.brain_tools",
}

# Schemas for tools not in capabilities/registry.py TOOL_SCHEMAS.
# These are defined here to avoid modifying the capabilities registry.
_EXTRA_SCHEMAS: dict[str, dict] = {
    "list_facts": {
        "name": "list_facts",
        "description": "List facts by key prefix and/or category — deterministic, no ranking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "Key prefix filter (e.g. 'isp_team_'). Empty = all keys.",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category (personal, preference, work, relationship). Empty = all.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max facts to return (default 100).",
                },
            },
        },
    },
}


def build_tool_registry(
    state: Any,
) -> tuple[list[dict], dict[str, Callable]]:
    """Build tool schemas and async handler map for iMessage command execution.

    Registers only the tools listed in ASYNC_SAFE_TOOLS. Schemas come from
    the capabilities registry (TOOL_SCHEMAS) where available, with fallbacks
    in _EXTRA_SCHEMAS for tools not in the registry.

    Args:
        state: ServerState instance with store references (used to trigger
               mcp_server registration which exposes functions at module level).

    Returns:
        (tool_schemas, tool_handlers) — schemas for Claude API tool param,
        handlers keyed by tool name.
    """
    # Import mcp_server to trigger register() calls which expose functions
    # at module level via sys.modules
    import mcp_server  # noqa: F401

    from capabilities.registry import TOOL_SCHEMAS

    tool_schemas: list[dict] = []
    tool_handlers: dict[str, Callable] = {}

    for tool_name in ASYNC_SAFE_TOOLS:
        # Get schema from capabilities registry or extra schemas
        schema = TOOL_SCHEMAS.get(tool_name) or _EXTRA_SCHEMAS.get(tool_name)
        if schema is None:
            logger.warning("No schema found for async tool: %s", tool_name)
            continue

        # Get handler function from the module
        module_path = _TOOL_MODULE_MAP.get(tool_name)
        if module_path is None:
            logger.warning("No module mapping for async tool: %s", tool_name)
            continue

        try:
            import importlib
            module = importlib.import_module(module_path)
            handler = getattr(module, tool_name, None)
            if handler is None or not callable(handler):
                logger.warning("Handler not found at %s.%s", module_path, tool_name)
                continue
        except (ImportError, AttributeError) as e:
            logger.warning("Failed to import handler for %s: %s", tool_name, e)
            continue

        tool_schemas.append(deepcopy(schema))
        tool_handlers[tool_name] = handler

    return tool_schemas, tool_handlers
