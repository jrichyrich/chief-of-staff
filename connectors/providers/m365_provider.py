from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from connectors.provider_base import CalendarProvider


class Microsoft365CalendarProvider(CalendarProvider):
    """Pluggable Microsoft 365 calendar adapter.

    This process does not natively execute host MCP connectors, so this adapter
    uses optional call hooks. When hooks are not supplied, it returns explicit
    configuration errors and allows caller-controlled fallback.
    """

    provider_name = "microsoft_365"

    def __init__(
        self,
        connected: bool = False,
        list_calendars_fn: Callable[[], list[dict]] | None = None,
        get_events_fn: Callable[[datetime, datetime, Optional[list[str]]], list[dict]] | None = None,
        create_event_fn: Callable[..., dict] | None = None,
        update_event_fn: Callable[..., dict] | None = None,
        delete_event_fn: Callable[..., dict] | None = None,
        search_events_fn: Callable[[str, datetime, datetime], list[dict]] | None = None,
    ):
        self._connected = bool(connected)
        self._hooks = {
            "list_calendars": list_calendars_fn,
            "get_events": get_events_fn,
            "create_event": create_event_fn,
            "update_event": update_event_fn,
            "delete_event": delete_event_fn,
            "search_events": search_events_fn,
        }

    def is_connected(self) -> bool:
        return self._connected

    def set_connected(self, connected: bool) -> None:
        self._connected = bool(connected)

    def list_calendars(self) -> list[dict]:
        if not self.is_connected():
            return [self._not_connected_error()]
        hook = self._hooks["list_calendars"]
        if hook is None:
            return [self._not_configured_error("list calendars")]
        rows = hook()
        return [self._tag_calendar(dict(row)) for row in rows if isinstance(row, dict)]

    def get_events(
        self,
        start_dt: datetime,
        end_dt: datetime,
        calendar_names: Optional[list[str]] = None,
    ) -> list[dict]:
        if not self.is_connected():
            return [self._not_connected_error()]
        hook = self._hooks["get_events"]
        if hook is None:
            return [self._not_configured_error("get events")]
        rows = hook(start_dt, end_dt, calendar_names)
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
        if not self.is_connected():
            return self._not_connected_error()
        hook = self._hooks["create_event"]
        if hook is None:
            return self._not_configured_error("create events")
        row = hook(
            title=title,
            start_dt=start_dt,
            end_dt=end_dt,
            calendar_name=calendar_name,
            location=location,
            notes=notes,
            is_all_day=is_all_day,
        )
        if row.get("error"):
            return row
        return self._tag_event(dict(row))

    def update_event(
        self,
        event_uid: str,
        calendar_name: Optional[str] = None,
        **kwargs,
    ) -> dict:
        if not self.is_connected():
            return self._not_connected_error()
        hook = self._hooks["update_event"]
        if hook is None:
            return self._not_configured_error("update events")
        row = hook(event_uid=event_uid, calendar_name=calendar_name, **kwargs)
        if row.get("error"):
            return row
        return self._tag_event(dict(row))

    def delete_event(self, event_uid: str, calendar_name: Optional[str] = None) -> dict:
        if not self.is_connected():
            return self._not_connected_error()
        hook = self._hooks["delete_event"]
        if hook is None:
            return self._not_configured_error("delete events")
        row = hook(event_uid=event_uid, calendar_name=calendar_name)
        if row.get("error"):
            return row
        tagged = dict(row)
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
        if not self.is_connected():
            return [self._not_connected_error()]
        hook = self._hooks["search_events"]
        if hook is None:
            return [self._not_configured_error("search events")]
        rows = hook(query, start_dt, end_dt)
        return [self._tag_event(dict(row)) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _not_connected_error() -> dict:
        return {
            "error": (
                "Microsoft 365 connector is not connected for this runtime. "
                "Use provider_preference='auto' or target_provider='apple' to fallback."
            )
        }

    @staticmethod
    def _not_configured_error(operation: str) -> dict:
        return {
            "error": (
                f"Microsoft 365 provider is connected but no adapter hook is configured for '{operation}'. "
                "Wire a provider bridge into Microsoft365CalendarProvider hooks."
            )
        }

    def _tag_calendar(self, row: dict) -> dict:
        tagged = dict(row)
        tagged["provider"] = self.provider_name
        tagged["source_account"] = str(row.get("source_account", "") or "Microsoft 365")
        tagged["calendar_id"] = str(row.get("calendar_id", "") or row.get("name", "") or "")
        return tagged

    def _tag_event(self, row: dict) -> dict:
        tagged = dict(row)
        native_id = str(tagged.get("native_id", "") or tagged.get("uid", "") or "")
        tagged["provider"] = self.provider_name
        tagged["source_account"] = str(tagged.get("source_account", "") or "Microsoft 365")
        tagged["calendar_id"] = str(tagged.get("calendar_id", "") or tagged.get("calendar", "") or "")
        tagged["native_id"] = native_id
        tagged["unified_uid"] = f"{self.provider_name}:{native_id}" if native_id else ""
        return tagged
