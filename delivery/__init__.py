"""Delivery adapters for scheduled task results."""

from delivery.service import (
    DeliveryAdapter,
    EmailDeliveryAdapter,
    IMessageDeliveryAdapter,
    NotificationDeliveryAdapter,
    TeamsDeliveryAdapter,
    VALID_CHANNELS,
    deliver_result,
    get_delivery_adapter,
    _build_template_vars,
)

__all__ = [
    "DeliveryAdapter",
    "EmailDeliveryAdapter",
    "IMessageDeliveryAdapter",
    "NotificationDeliveryAdapter",
    "TeamsDeliveryAdapter",
    "VALID_CHANNELS",
    "deliver_result",
    "get_delivery_adapter",
]
