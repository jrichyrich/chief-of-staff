"""EventKit wrapper for macOS calendar access via PyObjC."""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import EventKit  # noqa: N811
    from Foundation import NSDate

    _EVENTKIT_AVAILABLE = True
except ImportError:
    _EVENTKIT_AVAILABLE = False

_PLATFORM_ERROR = {
    "error": "EventKit is only available on macOS with PyObjC installed."
}

_PERMISSION_ERROR = {
    "error": (
        "Calendar access denied. Grant permission in "
        "System Settings > Privacy & Security > Calendars."
    )
}


def _ns_date(dt: datetime) -> "NSDate":
    """Convert a Python datetime to an NSDate."""
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _event_to_dict(event, calendar_name: str) -> dict:
    """Convert an EKEvent to a plain dict."""
    attendees = []
    if event.attendees():
        for a in event.attendees():
            attendees.append({
                "name": str(a.name()) if a.name() else None,
                "email": str(a.URL().resourceSpecifier()) if a.URL() else None,
                "status": int(a.participantStatus()),
            })

    start = event.startDate()
    end = event.endDate()

    return {
        "uid": str(event.calendarItemExternalIdentifier()),
        "title": str(event.title()) if event.title() else "",
        "start": datetime.fromtimestamp(start.timeIntervalSince1970()).isoformat() if start else None,
        "end": datetime.fromtimestamp(end.timeIntervalSince1970()).isoformat() if end else None,
        "location": str(event.location()) if event.location() else None,
        "notes": str(event.notes()) if event.notes() else None,
        "attendees": attendees,
        "calendar": calendar_name,
        "is_all_day": bool(event.isAllDay()),
    }


class CalendarStore:
    """Wraps Apple EventKit for calendar read/write operations.

    Lazily initializes the EKEventStore on first use. All public methods
    return plain dicts so callers never need to touch PyObjC objects.
    """

    def __init__(self):
        self._store = None
        self._access_granted: Optional[bool] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_store(self) -> Optional[dict]:
        """Lazily create EKEventStore and request access.

        Returns None on success, or an error dict if unavailable.
        """
        if not _EVENTKIT_AVAILABLE:
            return _PLATFORM_ERROR

        if self._store is None:
            self._store = EventKit.EKEventStore.alloc().init()

        if self._access_granted is None:
            self._access_granted = self._request_access()

        if not self._access_granted:
            return _PERMISSION_ERROR

        return None

    def _request_access(self) -> bool:
        """Request calendar access synchronously.

        Uses the completion-handler API and waits on a simple flag.
        """
        import threading

        granted_flag = threading.Event()
        result = {"granted": False}

        def handler(granted, error):
            result["granted"] = granted
            granted_flag.set()

        self._store.requestFullAccessToEventsWithCompletion_(handler)
        granted_flag.wait(timeout=30)
        return result["granted"]

    def _get_calendar_by_name(self, name: str):
        """Find an EKCalendar by display title, or None."""
        for cal in self._store.calendarsForEntityType_(0):  # 0 = Event
            if cal.title() == name:
                return cal
        return None

    def _find_event_by_uid(self, uid: str, calendar_name: Optional[str] = None):
        """Find a single EKEvent by its external identifier."""
        event = self._store.calendarItemWithIdentifier_(uid)
        if event is not None:
            return event
        # Fallback: search recent range for the UID
        from datetime import timedelta
        now = datetime.now()
        start = _ns_date(now - timedelta(days=365 * 2))
        end = _ns_date(now + timedelta(days=365 * 2))
        calendars = None
        if calendar_name:
            cal = self._get_calendar_by_name(calendar_name)
            if cal:
                calendars = [cal]
        predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(
            start, end, calendars
        )
        for ev in self._store.eventsMatchingPredicate_(predicate):
            if str(ev.calendarItemExternalIdentifier()) == uid:
                return ev
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_calendars(self) -> list[dict]:
        """Return all calendars with name, type, source, and color."""
        err = self._ensure_store()
        if err:
            return [err]

        try:
            calendars = self._store.calendarsForEntityType_(0)  # 0 = Event
            result = []
            for cal in calendars:
                color = cal.color()
                color_hex = None
                if color:
                    r = int(color.redComponent() * 255)
                    g = int(color.greenComponent() * 255)
                    b = int(color.blueComponent() * 255)
                    color_hex = f"#{r:02x}{g:02x}{b:02x}"

                cal_type_int = cal.type()
                cal_type_map = {0: "local", 1: "calDAV", 2: "exchange", 3: "subscription", 4: "birthday"}
                cal_type = cal_type_map.get(cal_type_int, f"unknown({cal_type_int})")

                result.append({
                    "name": str(cal.title()),
                    "type": cal_type,
                    "source": str(cal.source().title()) if cal.source() else None,
                    "color": color_hex,
                })
            return result
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error listing calendars: %s", e)
            return [{"error": f"Failed to list calendars: {e}"}]

    def get_events(
        self,
        start_dt: datetime,
        end_dt: datetime,
        calendar_names: Optional[list[str]] = None,
    ) -> list[dict]:
        """Return events in the given date range."""
        err = self._ensure_store()
        if err:
            return [err]

        try:
            calendars = None
            if calendar_names:
                calendars = []
                for name in calendar_names:
                    cal = self._get_calendar_by_name(name)
                    if cal:
                        calendars.append(cal)
                if not calendars:
                    return [{"error": f"No matching calendars found for: {calendar_names}"}]

            predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(
                _ns_date(start_dt), _ns_date(end_dt), calendars
            )
            events = self._store.eventsMatchingPredicate_(predicate)
            if events is None:
                return []
            return [
                _event_to_dict(ev, str(ev.calendar().title()))
                for ev in events
            ]
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error getting events: %s", e)
            return [{"error": f"Failed to get events: {e}"}]

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
        """Create a calendar event and return its dict representation."""
        err = self._ensure_store()
        if err:
            return err

        try:
            event = EventKit.EKEvent.eventWithEventStore_(self._store)
            event.setTitle_(title)
            event.setStartDate_(_ns_date(start_dt))
            event.setEndDate_(_ns_date(end_dt))
            event.setAllDay_(is_all_day)

            if location:
                event.setLocation_(location)
            if notes:
                event.setNotes_(notes)

            if calendar_name:
                cal = self._get_calendar_by_name(calendar_name)
                if cal:
                    event.setCalendar_(cal)
                else:
                    return {"error": f"Calendar not found: {calendar_name}"}
            else:
                event.setCalendar_(self._store.defaultCalendarForNewEvents())

            success, error = self._store.saveEvent_span_error_(event, 0, None)
            if not success:
                return {"error": f"Failed to save event: {error}"}

            return _event_to_dict(event, str(event.calendar().title()))
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error creating event: %s", e)
            return {"error": f"Failed to create event: {e}"}

    def update_event(self, event_uid: str, calendar_name: Optional[str] = None, **kwargs) -> dict:
        """Update an existing event by UID. Supported kwargs: title, start_dt,
        end_dt, location, notes, is_all_day."""
        err = self._ensure_store()
        if err:
            return err

        try:
            event = self._find_event_by_uid(event_uid, calendar_name)
            if event is None:
                return {"error": f"Event not found: {event_uid}"}

            if "title" in kwargs:
                event.setTitle_(kwargs["title"])
            if "start_dt" in kwargs:
                event.setStartDate_(_ns_date(kwargs["start_dt"]))
            if "end_dt" in kwargs:
                event.setEndDate_(_ns_date(kwargs["end_dt"]))
            if "location" in kwargs:
                event.setLocation_(kwargs["location"])
            if "notes" in kwargs:
                event.setNotes_(kwargs["notes"])
            if "is_all_day" in kwargs:
                event.setAllDay_(kwargs["is_all_day"])

            success, error = self._store.saveEvent_span_error_(event, 0, None)
            if not success:
                return {"error": f"Failed to update event: {error}"}

            return _event_to_dict(event, str(event.calendar().title()))
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error updating event: %s", e)
            return {"error": f"Failed to update event: {e}"}

    def delete_event(self, event_uid: str, calendar_name: Optional[str] = None) -> dict:
        """Delete an event by UID. Returns status dict on success, or an error dict."""
        err = self._ensure_store()
        if err:
            return err

        try:
            event = self._find_event_by_uid(event_uid, calendar_name)
            if event is None:
                return {"error": f"Event not found: {event_uid}"}

            success, error = self._store.removeEvent_span_error_(event, 0, None)
            if not success:
                return {"error": f"Failed to delete event: {error}"}
            return {"status": "deleted", "event_uid": event_uid}
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error deleting event: %s", e)
            return {"error": f"Failed to delete event: {e}"}

    def search_events(
        self,
        query: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[dict]:
        """Search events by title text within a date range."""
        err = self._ensure_store()
        if err:
            return [err]

        try:
            predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(
                _ns_date(start_dt), _ns_date(end_dt), None
            )
            events = self._store.eventsMatchingPredicate_(predicate)
            if events is None:
                return []

            query_lower = query.lower()
            results = []
            for ev in events:
                title = str(ev.title()) if ev.title() else ""
                if query_lower in title.lower():
                    results.append(_event_to_dict(ev, str(ev.calendar().title())))
            return results
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error searching events: %s", e)
            return [{"error": f"Failed to search events: {e}"}]
