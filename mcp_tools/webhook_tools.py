"""Webhook event tools for the Chief of Staff MCP server."""

import json
import logging

from .state import _retry_on_transient

logger = logging.getLogger("jarvis-mcp")

_VALID_WEBHOOK_STATUSES = {"pending", "processed", "failed"}
_MAX_WEBHOOK_LIMIT = 500


def register(mcp, state):
    """Register webhook tools with the FastMCP server."""

    @mcp.tool()
    async def list_webhook_events(
        status: str = "", source: str = "", limit: int = 50
    ) -> str:
        """List webhook events with optional filters.

        Args:
            status: Filter by status (pending, processed, failed). Leave empty for all.
            source: Filter by event source. Leave empty for all.
            limit: Maximum number of events to return (default 50, max 500)
        """
        if status and status not in _VALID_WEBHOOK_STATUSES:
            return json.dumps({
                "error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(_VALID_WEBHOOK_STATUSES))}"
            })
        limit = max(1, min(limit, _MAX_WEBHOOK_LIMIT))
        memory_store = state.memory_store
        events = _retry_on_transient(
            memory_store.list_webhook_events,
            status=status or None,
            source=source or None,
            limit=limit,
        )
        if not events:
            return json.dumps({"message": "No webhook events found.", "results": []})
        results = [
            {
                "id": e.id,
                "source": e.source,
                "event_type": e.event_type,
                "status": e.status,
                "received_at": e.received_at,
                "processed_at": e.processed_at,
            }
            for e in events
        ]
        return json.dumps({"results": results, "count": len(results)})

    @mcp.tool()
    async def get_webhook_event(event_id: int) -> str:
        """Get full details of a webhook event including its payload.

        Args:
            event_id: The ID of the webhook event to retrieve
        """
        memory_store = state.memory_store
        event = _retry_on_transient(memory_store.get_webhook_event, event_id)
        if event is None:
            return json.dumps({"error": f"Webhook event {event_id} not found"})

        # Parse payload back to dict if it's valid JSON
        payload = event.payload
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            pass

        return json.dumps({
            "id": event.id,
            "source": event.source,
            "event_type": event.event_type,
            "payload": payload,
            "status": event.status,
            "received_at": event.received_at,
            "processed_at": event.processed_at,
        })

    @mcp.tool()
    async def process_webhook_event(event_id: int) -> str:
        """Mark a webhook event as processed.

        Args:
            event_id: The ID of the webhook event to mark as processed
        """
        memory_store = state.memory_store
        event = _retry_on_transient(memory_store.get_webhook_event, event_id)
        if event is None:
            return json.dumps({"error": f"Webhook event {event_id} not found"})
        if event.status == "processed":
            return json.dumps({"status": "already_processed", "id": event_id})

        updated = _retry_on_transient(memory_store.update_webhook_event_status, event_id, "processed")
        return json.dumps({
            "status": "processed",
            "id": updated.id,
            "processed_at": updated.processed_at,
        })

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.list_webhook_events = list_webhook_events
    module.get_webhook_event = get_webhook_event
    module.process_webhook_event = process_webhook_event
