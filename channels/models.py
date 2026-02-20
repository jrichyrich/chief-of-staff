"""Common event model for unified channel adapter."""

from dataclasses import dataclass, field


@dataclass
class InboundEvent:
    """Normalized inbound event from any channel (iMessage, Mail, Webhook)."""

    channel: str  # "imessage", "mail", "webhook"
    source: str  # sender identifier (phone, email, webhook source)
    event_type: str  # "message", "email", "webhook_event"
    content: str  # body text
    metadata: dict = field(default_factory=dict)
    received_at: str = ""  # ISO timestamp
    raw_id: str = ""  # original ID from source system
