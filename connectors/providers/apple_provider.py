from __future__ import annotations

from datetime import datetime
from typing import Optional

from apple_calendar.eventkit import CalendarStore
from connectors.provider_base import CalendarProvider


class AppleCalendarProvider(CalendarProvider):
    """Adapter that normalizes EventKit CalendarStore output."""

    provider_name = "apple"

    def __init__(self, store: CalendarStore):
        self.store = store
        self._calendar_source_map: dict[str, str] = {}

    def is_connected(self) -> bool:
        return True

    def list_calendars(self) -> list[dict]:
        rows = self.store.list_calendars()
        if self._contains_error(rows):
            return rows
        self._calendar_source_map = {
            str(row.get("name", "")): str(row.get("source", "") or "")
            for row in rows
            if isinstance(row, dict)
        }
        return [self._tag_calendar(dict(row)) for row in rows if isinstance(row, dict)]

    def get_events(
        self,
        start_dt: datetime,
        end_dt: datetime,
        calendar_names: Optional[list[str]] = None,
    ) -> list[dict]:
        rows = self.store.get_events(start_dt, end_dt, calendar_names=calendar_names)
        if self._contains_error(rows):
            return rows
        return [self._tag_event(dict(row)) for row in rows if isinstance(row, dict)]

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
        result = self.store.create_event(
            title=title,
            start_dt=start_dt,
            end_dt=end_dt,
            calendar_name=calendar_name,
            location=location,
            notes=notes,
            is_all_day=is_all_day,
        )
        if result.get("error"):
            return result
        return self._tag_event(dict(result))

    def update_event(
        self,
        event_uid: str,
        calendar_name: Optional[str] = None,
        **kwargs,
    ) -> dict:
        result = self.store.update_event(event_uid, calendar_name=calendar_name, **kwargs)
        if result.get("error"):
            return result
        return self._tag_event(dict(result))

    def delete_event(self, event_uid: str, calendar_name: Optional[str] = None) -> dict:
        result = self.store.delete_event(event_uid, calendar_name=calendar_name)
        if result.get("error"):
            return result
        tagged = dict(result)
        tagged["provider"] = self.provider_name
        tagged["native_id"] = event_uid
        tagged["unified_uid"] = f"{self.provider_name}:{event_uid}"
        return tagged

    def search_events(
        self,
        query: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[dict]:
        rows = self.store.search_events(query, start_dt, end_dt)
        if self._contains_error(rows):
            return rows
        return [self._tag_event(dict(row)) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _contains_error(rows: list[dict]) -> bool:
        return bool(rows) and isinstance(rows[0], dict) and rows[0].get("error")

    def _tag_calendar(self, row: dict) -> dict:
        tagged = dict(row)
        tagged["provider"] = self.provider_name
        tagged["source_account"] = str(row.get("source", "") or "")
        tagged["calendar_id"] = str(row.get("name", "") or "")
        return tagged

    def _tag_event(self, row: dict) -> dict:
        tagged = dict(row)
        calendar_name = str(tagged.get("calendar", "") or "")
        source_account = self._calendar_source_map.get(calendar_name, "")
        if not source_account:
            # Lazy refresh in case events are fetched before list_calendars.
            self.list_calendars()
            source_account = self._calendar_source_map.get(calendar_name, "")

        native_id = str(tagged.get("uid", "") or "")
        tagged["provider"] = self.provider_name
        tagged["source_account"] = source_account
        tagged["calendar_id"] = calendar_name
        tagged["native_id"] = native_id
        tagged["unified_uid"] = f"{self.provider_name}:{native_id}" if native_id else ""
        return tagged
