"""Scheduler module for calendar availability and time slot analysis."""

from scheduler.availability import (
    classify_event_softness,
    find_available_slots,
    format_slots_for_sharing,
    normalize_event_for_scheduler,
)

__all__ = [
    "normalize_event_for_scheduler",
    "classify_event_softness",
    "find_available_slots",
    "format_slots_for_sharing",
]
