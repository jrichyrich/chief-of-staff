"""Built-in event handlers (consumers) for the channel router."""

from .models import InboundEvent

_URGENT_KEYWORDS = {"urgent", "asap", "critical", "emergency", "blocking"}


def log_event_handler(event: InboundEvent) -> dict:
    """Return a summary dict suitable for logging/audit trail."""
    return {
        "action": "logged",
        "channel": event.channel,
        "source": event.source,
        "event_type": event.event_type,
        "received_at": event.received_at,
        "raw_id": event.raw_id,
        "content_preview": event.content[:120] if event.content else "",
    }


def priority_filter(event: InboundEvent) -> dict:
    """Flag events whose content contains urgent keywords.

    Returns a dict with 'is_priority' bool and 'matched_keywords' list.
    """
    content_lower = event.content.lower() if event.content else ""
    matched = [kw for kw in _URGENT_KEYWORDS if kw in content_lower]
    return {
        "action": "priority_check",
        "is_priority": bool(matched),
        "matched_keywords": sorted(matched),
        "channel": event.channel,
        "raw_id": event.raw_id,
    }
