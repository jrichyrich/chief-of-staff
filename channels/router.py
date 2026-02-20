"""Event routing: dispatch InboundEvents to registered handler functions."""

import logging
import threading
from collections import defaultdict
from typing import Callable

from .models import InboundEvent

logger = logging.getLogger(__name__)


class EventRouter:
    """Routes InboundEvents to registered handler functions by event_type.

    Thread-safe: handler registration and routing are protected by a lock.
    """

    def __init__(self):
        self._handlers: dict[str, list[Callable[[InboundEvent], dict]]] = defaultdict(list)
        self._lock = threading.Lock()

    def register_handler(self, event_type: str, handler: Callable[[InboundEvent], dict]) -> None:
        """Register a handler for a specific event type.

        Args:
            event_type: The event type to handle (e.g. "message", "email", "webhook_event")
            handler: Callable that takes an InboundEvent and returns a dict result
        """
        with self._lock:
            self._handlers[event_type].append(handler)

    def route(self, event: InboundEvent) -> list[dict]:
        """Route an event to all registered handlers for its event_type.

        Returns a list of result dicts, one per handler. If a handler raises,
        the error is caught and included as an error dict in the results.
        """
        with self._lock:
            handlers = list(self._handlers.get(event.event_type, []))

        results = []
        for handler in handlers:
            try:
                result = handler(event)
                results.append(result)
            except Exception as exc:
                logger.warning("Handler %s failed for event %s: %s", handler.__name__, event.raw_id, exc)
                results.append({"error": str(exc), "handler": handler.__name__})
        return results
