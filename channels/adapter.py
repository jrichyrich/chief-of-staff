"""Channel adapters that normalize raw events into InboundEvent."""

from abc import ABC, abstractmethod

from .models import InboundEvent


class ChannelAdapter(ABC):
    """Abstract base class for channel adapters."""

    @abstractmethod
    def normalize(self, raw_event: dict) -> InboundEvent:
        """Convert a raw channel-specific event dict into an InboundEvent."""
        ...


class IMessageAdapter(ChannelAdapter):
    """Normalize iMessage dicts (from MessageStore) to InboundEvent."""

    def normalize(self, raw_event: dict) -> InboundEvent:
        return InboundEvent(
            channel="imessage",
            source=raw_event.get("sender", ""),
            event_type="message",
            content=raw_event.get("text", ""),
            metadata={
                "is_from_me": raw_event.get("is_from_me", False),
                "chat_identifier": raw_event.get("chat_identifier", ""),
            },
            received_at=raw_event.get("date_local", ""),
            raw_id=raw_event.get("guid", ""),
        )


class MailAdapter(ChannelAdapter):
    """Normalize mail message dicts (from MailStore) to InboundEvent."""

    def normalize(self, raw_event: dict) -> InboundEvent:
        # Full message (has 'body') vs header-only (has 'subject' only)
        content = raw_event.get("body", raw_event.get("subject", ""))
        return InboundEvent(
            channel="mail",
            source=raw_event.get("sender", ""),
            event_type="email",
            content=content,
            metadata={
                "subject": raw_event.get("subject", ""),
                "read": raw_event.get("read", False),
                "flagged": raw_event.get("flagged", False),
                "mailbox": raw_event.get("mailbox", ""),
                "account": raw_event.get("account", ""),
                "to": raw_event.get("to", []),
                "cc": raw_event.get("cc", []),
            },
            received_at=raw_event.get("date", ""),
            raw_id=raw_event.get("message_id", ""),
        )


class WebhookAdapter(ChannelAdapter):
    """Normalize WebhookEvent dicts (from MemoryStore) to InboundEvent."""

    def normalize(self, raw_event: dict) -> InboundEvent:
        return InboundEvent(
            channel="webhook",
            source=raw_event.get("source", ""),
            event_type="webhook_event",
            content=raw_event.get("payload", ""),
            metadata={
                "status": raw_event.get("status", ""),
                "event_type": raw_event.get("event_type", ""),
            },
            received_at=raw_event.get("received_at", ""),
            raw_id=str(raw_event.get("id", "")),
        )


_ADAPTERS: dict[str, ChannelAdapter] = {
    "imessage": IMessageAdapter(),
    "mail": MailAdapter(),
    "webhook": WebhookAdapter(),
}


def adapt_event(channel: str, raw_event: dict) -> InboundEvent:
    """Factory function: normalize a raw event dict using the appropriate adapter.

    Args:
        channel: One of "imessage", "mail", "webhook"
        raw_event: Channel-specific event dict

    Raises:
        ValueError: If channel is not recognized
    """
    adapter = _ADAPTERS.get(channel)
    if adapter is None:
        raise ValueError(f"Unknown channel: {channel!r}. Must be one of: {sorted(_ADAPTERS)}")
    return adapter.normalize(raw_event)
