from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class CalendarProvider(ABC):
    """Abstract provider interface for calendar backends."""

    provider_name: str

    @abstractmethod
    def is_connected(self) -> bool:
        """Return whether this provider is available for use."""

    @abstractmethod
    def list_calendars(self) -> list[dict]:
        """List calendars exposed by this provider."""

    @abstractmethod
    def get_events(
        self,
        start_dt: datetime,
        end_dt: datetime,
        calendar_names: Optional[list[str]] = None,
    ) -> list[dict]:
        """Get events within a date range."""

    @abstractmethod
    def create_event(
        self,
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        calendar_name: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        is_all_day: bool = False,
    ) -> dict:
        """Create an event."""

    @abstractmethod
    def update_event(
        self,
        event_uid: str,
        calendar_name: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Update an existing event."""

    @abstractmethod
    def delete_event(self, event_uid: str, calendar_name: Optional[str] = None) -> dict:
        """Delete an existing event."""

    @abstractmethod
    def search_events(
        self,
        query: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[dict]:
        """Search events in a date range."""
