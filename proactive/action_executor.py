"""Proactive action executor — acts on high-confidence suggestions autonomously."""

from __future__ import annotations

import logging
from typing import Any, Optional

import config as app_config
from proactive.models import Suggestion

logger = logging.getLogger("jarvis-proactive-action")

# Map of category -> action -> handler function name
# Only safe, reversible operations belong here
_ACTION_HANDLERS = {
    "checkpoint": {
        "checkpoint_session": "_handle_checkpoint",
    },
    "delegation": {
        "check_overdue_delegations": "_handle_overdue_delegations",
    },
    "decision": {
        "list_pending_decisions": "_handle_stale_decisions",
    },
    "webhook": {
        "list_webhook_events": "_handle_pending_webhooks",
    },
}


def execute_suggestion_action(
    suggestion: Suggestion,
    memory_store: Any = None,
    session_manager: Any = None,
    session_health: Any = None,
) -> dict:
    """Execute a suggestion's recommended action if allowed.

    Returns:
        Dict with executed (bool), action, and result or reason.
    """
    if not getattr(app_config, "PROACTIVE_ACTION_ENABLED", False):
        return {"executed": False, "action": suggestion.action, "reason": "Proactive actions disabled"}

    allowed = getattr(app_config, "PROACTIVE_ACTION_CATEGORIES", frozenset())
    if suggestion.category not in allowed:
        return {
            "executed": False,
            "action": suggestion.action,
            "reason": f"Category '{suggestion.category}' not in allowed categories: {sorted(allowed)}",
        }

    handlers = _ACTION_HANDLERS.get(suggestion.category, {})
    handler_name = handlers.get(suggestion.action)
    if handler_name is None:
        return {"executed": False, "action": suggestion.action, "reason": f"No handler for action '{suggestion.action}'"}

    handler = globals().get(handler_name)
    if handler is None:
        return {"executed": False, "action": suggestion.action, "reason": f"Handler '{handler_name}' not found"}

    try:
        result = handler(
            suggestion=suggestion,
            memory_store=memory_store,
            session_manager=session_manager,
            session_health=session_health,
        )
        return {"executed": True, "action": suggestion.action, "result": result}
    except Exception as e:
        logger.error("Proactive action failed for %s: %s", suggestion.action, e)
        return {"executed": False, "action": suggestion.action, "reason": f"Handler error: {e}"}


def _handle_checkpoint(suggestion, memory_store=None, session_manager=None, **kwargs):
    """Flush session memory to preserve context."""
    if session_manager is None:
        return {"status": "skipped", "reason": "No session manager available"}
    result = session_manager.flush_to_memory()
    if session_health := kwargs.get("session_health"):
        session_health.record_checkpoint()
    logger.info("Proactive checkpoint executed: %s", result)
    return {"status": "checkpointed", "details": result}


def _handle_overdue_delegations(suggestion, memory_store=None, **kwargs):
    """Log overdue delegations for awareness (notification-only action)."""
    if memory_store is None:
        return {"status": "skipped", "reason": "No memory store"}
    overdue = memory_store.list_overdue_delegations()
    logger.info("Proactive: %d overdue delegations flagged", len(overdue))
    return {"status": "flagged", "count": len(overdue)}


def _handle_stale_decisions(suggestion, memory_store=None, **kwargs):
    """Log stale decisions for awareness."""
    if memory_store is None:
        return {"status": "skipped", "reason": "No memory store"}
    from memory.models import DecisionStatus
    pending = memory_store.list_decisions_by_status(DecisionStatus.pending_execution)
    logger.info("Proactive: %d stale pending decisions", len(pending))
    return {"status": "flagged", "count": len(pending)}


def _handle_pending_webhooks(suggestion, memory_store=None, **kwargs):
    """Log pending webhook events for awareness."""
    if memory_store is None:
        return {"status": "skipped", "reason": "No memory store"}
    from memory.models import WebhookStatus
    pending = memory_store.list_webhook_events(status=WebhookStatus.pending)
    logger.info("Proactive: %d pending webhook events", len(pending))
    return {"status": "flagged", "count": len(pending)}
