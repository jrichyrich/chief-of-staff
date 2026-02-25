"""Automatic tool usage tracking middleware for the MCP server.

Wraps FastMCP.call_tool to record every tool invocation in the
skill_usage table. Tracking failures are swallowed so they never
break actual tool execution.
"""

import functools
import logging

logger = logging.getLogger("jarvis-mcp")

# Tools that should not track themselves
_EXCLUDED_TOOLS = frozenset({
    "record_tool_usage",
    "analyze_skill_patterns",
    "list_skill_suggestions",
    "auto_create_skill",
    "auto_execute_skills",
})

_QUERY_PATTERN = "auto"


def install_usage_tracker(mcp, state):
    """Wrap mcp.call_tool to automatically record tool usage.

    Idempotent — calling multiple times does not double-wrap.

    Args:
        mcp: The FastMCP server instance.
        state: ServerState with memory_store for recording.
    """
    if getattr(mcp.call_tool, "_usage_tracked", False):
        return

    original_call_tool = mcp.call_tool

    @functools.wraps(original_call_tool)
    async def tracked_call_tool(name, arguments):
        # Record usage before calling the tool
        if name not in _EXCLUDED_TOOLS:
            try:
                memory_store = state.memory_store
                if memory_store is not None:
                    memory_store.record_skill_usage(name, _QUERY_PATTERN)
            except Exception:
                logger.debug("Failed to record usage for %s", name, exc_info=True)

        return await original_call_tool(name, arguments)

    tracked_call_tool._usage_tracked = True
    mcp.call_tool = tracked_call_tool
