"""Session management tools for the Chief of Staff MCP server."""

import asyncio
import json
import logging
from datetime import datetime

logger = logging.getLogger("jarvis-mcp")

# Minimum seconds between refresh_session_context calls
_REFRESH_COOLDOWN_SECONDS = 30


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

        # Include cached session context if available
        context_bundle = None
        if state.session_context is not None:
            ctx = state.session_context
            context_bundle = {
                "loaded_at": ctx.loaded_at,
                "is_stale": ctx.is_stale,
                "calendar_event_count": len(ctx.calendar_events),
                "calendar_events": ctx.calendar_events[:10],
                "unread_mail_count": ctx.unread_mail_count,
                "overdue_delegation_count": len(ctx.overdue_delegations),
                "overdue_delegations": ctx.overdue_delegations,
                "pending_decision_count": len(ctx.pending_decisions),
                "pending_decisions": ctx.pending_decisions,
                "due_reminder_count": len(ctx.due_reminders),
                "due_reminders": ctx.due_reminders,
                "brain_summary": ctx.session_brain_summary,
                "errors": ctx.errors,
            }

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
            "context_bundle": context_bundle,
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

    @mcp.tool()
    async def refresh_session_context() -> str:
        """Re-fetch and cache the session context bundle.

        Useful when cached data is stale or after making changes
        (e.g., completing a delegation, creating a reminder).
        Returns the refreshed context summary.  Rate-limited to one
        call per 30 seconds to avoid hammering backends.
        """
        from session.context_loader import load_session_context
        from session.context_config import ContextLoaderConfig
        import config as app_config

        # Rate limiting — reject if last load was too recent
        if state.session_context is not None and state.session_context.loaded_at:
            try:
                loaded = datetime.fromisoformat(state.session_context.loaded_at)
                elapsed = (datetime.now() - loaded).total_seconds()
                if elapsed < _REFRESH_COOLDOWN_SECONDS:
                    return json.dumps({
                        "status": "rate_limited",
                        "message": f"Last refresh was {elapsed:.0f}s ago. Wait {_REFRESH_COOLDOWN_SECONDS - elapsed:.0f}s.",
                        "loaded_at": state.session_context.loaded_at,
                    })
            except (ValueError, TypeError):
                pass

        loader_config = ContextLoaderConfig(
            enabled=True,
            per_source_timeout_seconds=app_config.SESSION_CONTEXT_TIMEOUT,
            ttl_minutes=app_config.SESSION_CONTEXT_TTL,
            sources={s: True for s in app_config.SESSION_CONTEXT_SOURCES},
        )
        try:
            state.session_context = await asyncio.to_thread(
                load_session_context, state, loader_config
            )
            ctx = state.session_context
            return json.dumps({
                "status": "refreshed",
                "loaded_at": ctx.loaded_at,
                "calendar_event_count": len(ctx.calendar_events),
                "unread_mail_count": ctx.unread_mail_count,
                "overdue_delegation_count": len(ctx.overdue_delegations),
                "pending_decision_count": len(ctx.pending_decisions),
                "due_reminder_count": len(ctx.due_reminders),
                "errors": ctx.errors,
            })
        except Exception as e:
            logger.exception("Error refreshing session context")
            return json.dumps({"error": f"Refresh failed: {e}"})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.get_session_status = get_session_status
    module.flush_session_memory = flush_session_memory
    module.restore_session = restore_session
    module.refresh_session_context = refresh_session_context
