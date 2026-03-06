"""Automatic tool usage tracking middleware for the MCP server.

Wraps FastMCP.call_tool to record every tool invocation in the
skill_usage table. Tracking failures are swallowed so they never
break actual tool execution.
"""

import functools
import logging
import time

logger = logging.getLogger("jarvis-mcp")

# Tools that should not track themselves
_EXCLUDED_TOOLS = frozenset({
    "record_tool_usage",
    "analyze_skill_patterns",
    "list_skill_suggestions",
    "auto_create_skill",
    "auto_execute_skills",
    "get_tool_statistics",
})

# Ordered priority of argument keys to extract as query_pattern
_PATTERN_KEYS = (
    "query",
    "query_pattern",
    "tool_name",
    "name",
    "title",
    "canonical_name",
    "to",
    "task",
    "organization_name",
    "start_date",
    "mailbox",
    "calendar_name",
    "agent_name",
    "event_id",
    "message_id",
    "suggestion_id",
    "chat_identifier",
    "recipient_type",
)

_MAX_PATTERN_LEN = 100


def _extract_query_pattern(tool_name: str, arguments: dict | None) -> str:
    """Extract a meaningful query pattern from tool arguments.

    Walks _PATTERN_KEYS in priority order and returns the first
    non-empty string value found, truncated to _MAX_PATTERN_LEN.
    Falls back to "auto" if no meaningful string argument is found.
    """
    if not arguments:
        return "auto"
    for key in _PATTERN_KEYS:
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:_MAX_PATTERN_LEN]
    return "auto"


def install_usage_tracker(mcp, state):
    """Wrap the ToolManager's call_tool to automatically record tool usage.

    Wraps ``mcp._tool_manager.call_tool`` rather than ``mcp.call_tool``
    because FastMCP registers its ``call_tool`` bound method with the
    low-level MCP server during ``__init__``.  That reference is captured
    in a closure and never updated, so replacing the instance attribute on
    the FastMCP object is invisible to the stdio transport.  By wrapping
    one level deeper (the ToolManager), every code path — including the
    low-level handler — flows through the tracker.

    Idempotent — calling multiple times does not double-wrap.

    Args:
        mcp: The FastMCP server instance.
        state: ServerState with memory_store for recording.
    """
    tool_mgr = mcp._tool_manager
    if getattr(tool_mgr.call_tool, "_usage_tracked", False):
        return

    original_call_tool = tool_mgr.call_tool  # bound method

    @functools.wraps(original_call_tool)
    async def tracked_call_tool(name, arguments, **kwargs):
        if name not in _EXCLUDED_TOOLS:
            pattern = _extract_query_pattern(name, arguments)

            # Record aggregated usage (existing behavior)
            try:
                memory_store = state.memory_store
                if memory_store is not None:
                    memory_store.record_skill_usage(name, pattern)
            except Exception:
                logger.debug("Failed to record usage for %s", name, exc_info=True)

            # Fire before_tool_call hooks
            hook_registry = getattr(state, "hook_registry", None)
            if hook_registry is not None:
                try:
                    from hooks.registry import build_tool_context, extract_transformed_args
                    before_ctx = build_tool_context(name, arguments or {})
                    hook_results = hook_registry.fire_hooks("before_tool_call", before_ctx)
                    transformed = extract_transformed_args(hook_results)
                    if transformed is not None:
                        arguments = transformed
                except Exception:
                    logger.debug("before_tool_call hooks failed for %s", name, exc_info=True)

            # Execute tool and log individual invocation
            start = time.monotonic()
            success = True
            result = None
            response_size_bytes = None
            try:
                result = await original_call_tool(name, arguments, **kwargs)
                try:
                    response_size_bytes = len(str(result).encode("utf-8"))
                except Exception:
                    pass
                return result
            except Exception:
                success = False
                raise
            finally:
                duration_ms = int((time.monotonic() - start) * 1000)
                try:
                    memory_store = state.memory_store
                    if memory_store is not None:
                        memory_store.log_tool_invocation(
                            tool_name=name,
                            query_pattern=pattern,
                            success=success,
                            duration_ms=duration_ms,
                            response_size_bytes=response_size_bytes,
                        )
                except Exception:
                    logger.debug("Failed to log invocation for %s", name, exc_info=True)

                # Fire after_tool_call hooks
                if hook_registry is not None:
                    try:
                        from hooks.registry import build_tool_context
                        after_ctx = build_tool_context(
                            name, arguments or {},
                            result=result if success else None,
                        )
                        after_ctx["success"] = success
                        after_ctx["duration_ms"] = duration_ms
                        hook_registry.fire_hooks("after_tool_call", after_ctx)
                    except Exception:
                        logger.debug("after_tool_call hooks failed for %s", name, exc_info=True)

                # Record tool call in session health
                try:
                    session_health = getattr(state, "session_health", None)
                    if session_health is not None:
                        session_health.record_tool_call()
                except Exception:
                    logger.debug("Failed to record tool call in session health", exc_info=True)
        else:
            return await original_call_tool(name, arguments, **kwargs)

    tracked_call_tool._usage_tracked = True
    tool_mgr.call_tool = tracked_call_tool
