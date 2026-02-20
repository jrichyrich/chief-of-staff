"""Channel adapter MCP tools for unified inbound event access."""

import json
import logging

from channels.adapter import adapt_event

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register channel tools with the FastMCP server."""

    @mcp.tool()
    async def list_inbound_events(
        channel: str = "",
        event_type: str = "",
        limit: int = 25,
    ) -> str:
        """List recent inbound events normalized across channels (iMessage, Mail, Webhook).

        Args:
            channel: Filter by channel ("imessage", "mail", "webhook"). Leave empty for all.
            event_type: Filter by event type ("message", "email", "webhook_event"). Leave empty for all.
            limit: Maximum events per channel (default 25, max 100)
        """
        limit = max(1, min(limit, 100))
        channels_to_query = (
            [channel] if channel else ["imessage", "mail", "webhook"]
        )
        all_events = []

        for ch in channels_to_query:
            raw_events = _fetch_raw_events(state, ch, limit)
            for raw in raw_events:
                if "error" in raw:
                    continue
                try:
                    event = adapt_event(ch, raw)
                except (ValueError, KeyError):
                    continue
                if event_type and event.event_type != event_type:
                    continue
                all_events.append({
                    "channel": event.channel,
                    "source": event.source,
                    "event_type": event.event_type,
                    "content_preview": event.content[:200] if event.content else "",
                    "received_at": event.received_at,
                    "raw_id": event.raw_id,
                    "metadata": event.metadata,
                })

        # Sort by received_at descending (best effort — mixed date formats)
        all_events.sort(key=lambda e: e.get("received_at", ""), reverse=True)
        return json.dumps({"results": all_events[:limit], "count": len(all_events)})

    @mcp.tool()
    async def get_event_summary() -> str:
        """Get a count of recent inbound events by channel."""
        summary = {}
        for ch in ("imessage", "mail", "webhook"):
            raw_events = _fetch_raw_events(state, ch, limit=100)
            summary[ch] = len([e for e in raw_events if "error" not in e])
        return json.dumps({"summary": summary, "total": sum(summary.values())})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.list_inbound_events = list_inbound_events
    module.get_event_summary = get_event_summary


def _fetch_raw_events(state, channel: str, limit: int) -> list[dict]:
    """Fetch raw events from the appropriate store for a channel."""
    try:
        if channel == "imessage":
            messages_store = state.messages_store
            if messages_store is None:
                return []
            return messages_store.get_messages(minutes=24 * 60, limit=limit)
        elif channel == "mail":
            mail_store = state.mail_store
            if mail_store is None:
                return []
            return mail_store.get_messages(limit=limit)
        elif channel == "webhook":
            memory_store = state.memory_store
            if memory_store is None:
                return []
            events = memory_store.list_webhook_events(limit=limit)
            return [
                {
                    "id": e.id,
                    "source": e.source,
                    "event_type": e.event_type,
                    "payload": e.payload,
                    "status": e.status,
                    "received_at": e.received_at,
                }
                for e in events
            ]
        else:
            return []
    except Exception as exc:
        logger.warning("Failed to fetch %s events: %s", channel, exc)
        return [{"error": str(exc)}]
