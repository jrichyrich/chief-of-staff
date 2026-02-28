"""Backward-compatibility shim. Import from delivery.service instead."""
from delivery.service import *  # noqa: F401,F403
from delivery.service import (  # explicit re-exports for type checkers
    DeliveryAdapter,
    EmailDeliveryAdapter,
    IMessageDeliveryAdapter,
    NotificationDeliveryAdapter,
    TeamsDeliveryAdapter,
    VALID_CHANNELS,
    _ADAPTERS,
    _BRIEF_KEYS,
    _build_template_vars,
    _maybe_format_brief,
    deliver_result,
    get_delivery_adapter,
)
