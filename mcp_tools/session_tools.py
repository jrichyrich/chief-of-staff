"""Session management tools for the Chief of Staff MCP server."""

import json
import logging
from datetime import datetime

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register session management tools with the FastMCP server."""

    @mcp.tool()
    async def get_session_status() -> str:
        """Return current session status: token estimate, interaction count,
        time since last checkpoint, and a preview of extracted items.

        Use this to decide whether a flush_session_memory call is needed.
        """
        session_manager = state.session_manager
        if session_manager is None:
            return json.dumps({"error": "Session manager not initialized."})

        extracted = session_manager.extract_structured_data()
        tokens = session_manager.estimate_tokens()

        # Calculate time since last checkpoint
        health = state.session_health
        mins = health.minutes_since_checkpoint()
        minutes_since_checkpoint = None if mins == float('inf') else round(mins, 1)

        return json.dumps({
            "session_id": session_manager.session_id,
            "token_estimate": tokens,
            "interaction_count": session_manager.interaction_count,
            "time_since_last_checkpoint": minutes_since_checkpoint,
            "extracted_items_preview": {
                "decisions": len(extracted["decisions"]),
                "action_items": len(extracted["action_items"]),
                "key_facts": len(extracted["key_facts"]),
                "general": len(extracted["general"]),
            },
            "context_window_usage": round(tokens / 150000, 3) if tokens > 0 else 0.0,
        })

    @mcp.tool()
    async def flush_session_memory(priority: str = "all") -> str:
        """Persist structured session data to long-term memory.

        Extracts decisions, action items, and key facts from the current session
        and stores them as facts. Also creates a session checkpoint.

        Args:
            priority: What to flush — "all", "decisions", "action_items", or "key_facts".
                      "decisions" flushes only decisions. "all" flushes everything.
        """
        session_manager = state.session_manager
        if session_manager is None:
            return json.dumps({"error": "Session manager not initialized."})

        valid_priorities = ("all", "decisions", "action_items", "key_facts")
        if priority not in valid_priorities:
            return json.dumps({
                "error": f"Invalid priority '{priority}'. Must be one of: {', '.join(valid_priorities)}"
            })

        try:
            result = session_manager.flush(priority_threshold=priority)
            state.session_health.record_checkpoint()
            return json.dumps({
                "status": "flushed",
                "session_id": session_manager.session_id,
                **result,
            })
        except Exception as e:
            logger.exception("Error flushing session memory")
            return json.dumps({"error": f"Flush failed: {e}"})

    @mcp.tool()
    async def restore_session(session_id: str) -> str:
        """Restore context from a previous session checkpoint.

        Args:
            session_id: The session ID to restore from.
        """
        session_manager = state.session_manager
        if session_manager is None:
            return json.dumps({"error": "Session manager not initialized."})

        try:
            restored = session_manager.restore_from_checkpoint(session_id)
            return json.dumps({
                "status": "restored",
                **restored,
            })
        except Exception as e:
            logger.exception("Error restoring session")
            return json.dumps({"error": f"Restore failed: {e}"})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.get_session_status = get_session_status
    module.flush_session_memory = flush_session_memory
    module.restore_session = restore_session
