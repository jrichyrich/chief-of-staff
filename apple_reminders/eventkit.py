"""EventKit wrapper for macOS Reminders access via PyObjC."""

import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import EventKit  # noqa: N811
    from Foundation import NSDate, NSDateComponents, NSCalendar

    _EVENTKIT_AVAILABLE = True
except ImportError:
    _EVENTKIT_AVAILABLE = False

_PLATFORM_ERROR = {
    "error": "EventKit is only available on macOS with PyObjC installed."
}

_PERMISSION_ERROR = {
    "error": (
        "Reminders access denied. Grant permission in "
        "System Settings > Privacy & Security > Reminders."
    )
}

# EKEntityType constants
_EK_ENTITY_TYPE_REMINDER = 1

# Priority map for human-readable output
_PRIORITY_MAP = {0: "none", 1: "high", 4: "medium", 9: "low"}


def _reminder_to_dict(reminder) -> dict:
    """Convert an EKReminder to a plain dict."""
    due_date = None
    due_components = reminder.dueDateComponents()
    if due_components:
        cal = NSCalendar.currentCalendar()
        ns_date = cal.dateFromComponents_(due_components)
        if ns_date:
            due_date = datetime.fromtimestamp(
                ns_date.timeIntervalSince1970()
            ).isoformat()

    completion_date = None
    comp_ns = reminder.completionDate()
    if comp_ns:
        completion_date = datetime.fromtimestamp(
            comp_ns.timeIntervalSince1970()
        ).isoformat()

    creation_date = None
    create_ns = reminder.creationDate()
    if create_ns:
        creation_date = datetime.fromtimestamp(
            create_ns.timeIntervalSince1970()
        ).isoformat()

    return {
        "id": str(reminder.calendarItemExternalIdentifier()),
        "title": str(reminder.title()) if reminder.title() else "",
        "notes": str(reminder.notes()) if reminder.notes() else None,
        "completed": bool(reminder.isCompleted()),
        "completion_date": completion_date,
        "due_date": due_date,
        "priority": int(reminder.priority()),
        "list_name": str(reminder.calendar().title()) if reminder.calendar() else None,
        "creation_date": creation_date,
    }


class ReminderStore:
    """Wraps Apple EventKit for Reminders read/write operations.

    Lazily initializes the EKEventStore on first use. All public methods
    return plain dicts so callers never need to touch PyObjC objects.
    """

    def __init__(self):
        self._store = None
        self._access_granted: Optional[bool] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_store(self):
        """Lazily create EKEventStore and request access.

        Returns the EKEventStore on success, or an error dict if unavailable.
        """
        if not _EVENTKIT_AVAILABLE:
            return _PLATFORM_ERROR

        if self._store is None:
            self._store = EventKit.EKEventStore.alloc().init()

        if self._access_granted is None:
            self._access_granted = self._request_access()

        if not self._access_granted:
            return _PERMISSION_ERROR

        return self._store

    def _request_access(self) -> bool:
        """Request Reminders access synchronously."""
        granted_flag = threading.Event()
        result = {"granted": False}

        def handler(granted, error):
            result["granted"] = granted
            granted_flag.set()

        self._store.requestFullAccessToRemindersWithCompletion_(handler)
        granted_flag.wait(timeout=30)
        return result["granted"]

    def _get_reminder_list_by_name(self, name: str):
        """Find an EKCalendar (reminder list) by display title, or None."""
        for cal in self._store.calendarsForEntityType_(_EK_ENTITY_TYPE_REMINDER):
            if cal.title() == name:
                return cal
        return None

    def _fetch_reminders(self, predicate) -> list:
        """Execute a reminder fetch with predicate, blocking until complete."""
        results = []
        done = threading.Event()

        def handler(reminders):
            if reminders:
                for r in reminders:
                    results.append(r)
            done.set()

        self._store.fetchRemindersMatchingPredicate_completion_(predicate, handler)
        done.wait(timeout=10)
        return results

    def _find_reminder_by_id(self, reminder_id: str):
        """Find a single EKReminder by its external identifier."""
        item = self._store.calendarItemWithIdentifier_(reminder_id)
        if item is not None:
            return item
        # Fallback: fetch all reminders and filter
        predicate = self._store.predicateForRemindersInCalendars_(None)
        for r in self._fetch_reminders(predicate):
            if str(r.calendarItemExternalIdentifier()) == reminder_id:
                return r
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_reminder_lists(self) -> list[dict]:
        """Return all reminder lists (calendars with entityType Reminder)."""
        store = self._ensure_store()
        if isinstance(store, dict):
            return [store]

        try:
            calendars = store.calendarsForEntityType_(_EK_ENTITY_TYPE_REMINDER)
            result = []
            for cal in calendars:
                color = cal.color()
                color_hex = None
                if color:
                    r = int(color.redComponent() * 255)
                    g = int(color.greenComponent() * 255)
                    b = int(color.blueComponent() * 255)
                    color_hex = f"#{r:02x}{g:02x}{b:02x}"

                result.append({
                    "name": str(cal.title()),
                    "source": str(cal.source().title()) if cal.source() else None,
                    "color": color_hex,
                })
            return result
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error listing reminder lists: %s", e)
            return [{"error": f"Failed to list reminder lists: {e}"}]

    def list_reminders(
        self,
        list_name: Optional[str] = None,
        completed: Optional[bool] = None,
    ) -> list[dict]:
        """Fetch reminders, optionally filtered by list and completion status.

        completed=None returns all, True returns completed only,
        False returns incomplete only.
        """
        store = self._ensure_store()
        if isinstance(store, dict):
            return [store]

        try:
            calendars = None
            if list_name:
                cal = self._get_reminder_list_by_name(list_name)
                if not cal:
                    return [{"error": f"Reminder list '{list_name}' not found"}]
                calendars = [cal]

            if completed is True:
                predicate = store.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_(
                    None, None, calendars
                )
            elif completed is False:
                predicate = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
                    None, None, calendars
                )
            else:
                predicate = store.predicateForRemindersInCalendars_(calendars)

            raw_reminders = self._fetch_reminders(predicate)
            return [_reminder_to_dict(r) for r in raw_reminders]
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error getting reminders: %s", e)
            return [{"error": f"Failed to get reminders: {e}"}]

    def create_reminder(
        self,
        title: str,
        list_name: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Create a new reminder and return its dict representation.

        Args:
            title: Reminder title.
            list_name: Target reminder list name, or default list if None.
            due_date: ISO format date string (e.g. "2025-03-15" or "2025-03-15T14:00:00").
            priority: 0=none, 1=high, 4=medium, 9=low.
            notes: Optional notes text.
        """
        store = self._ensure_store()
        if isinstance(store, dict):
            return store

        try:
            reminder = EventKit.EKReminder.reminderWithEventStore_(store)
            reminder.setTitle_(title)

            if list_name:
                cal = self._get_reminder_list_by_name(list_name)
                if not cal:
                    return {"error": f"Reminder list '{list_name}' not found"}
                reminder.setCalendar_(cal)
            else:
                reminder.setCalendar_(store.defaultCalendarForNewReminders())

            if notes:
                reminder.setNotes_(notes)

            if priority is not None:
                reminder.setPriority_(priority)

            if due_date:
                dt = datetime.fromisoformat(due_date)
                components = NSDateComponents.alloc().init()
                components.setYear_(dt.year)
                components.setMonth_(dt.month)
                components.setDay_(dt.day)
                components.setHour_(dt.hour)
                components.setMinute_(dt.minute)
                reminder.setDueDateComponents_(components)

            success, error = store.saveReminder_commit_error_(reminder, True, None)
            if not success:
                return {"error": f"Failed to save reminder: {error}"}

            return _reminder_to_dict(reminder)
        except (AttributeError, TypeError, RuntimeError, ValueError) as e:
            logger.error("Error creating reminder: %s", e)
            return {"error": f"Failed to create reminder: {e}"}

    def complete_reminder(self, reminder_id: str) -> dict:
        """Mark a reminder as completed by its ID."""
        store = self._ensure_store()
        if isinstance(store, dict):
            return store

        try:
            reminder = self._find_reminder_by_id(reminder_id)
            if reminder is None:
                return {"error": f"Reminder not found: {reminder_id}"}

            reminder.setCompleted_(True)
            success, error = store.saveReminder_commit_error_(reminder, True, None)
            if not success:
                return {"error": f"Failed to complete reminder: {error}"}

            return _reminder_to_dict(reminder)
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error completing reminder: %s", e)
            return {"error": f"Failed to complete reminder: {e}"}

    def delete_reminder(self, reminder_id: str) -> dict:
        """Delete a reminder by its ID. Returns status dict on success, or an error dict."""
        store = self._ensure_store()
        if isinstance(store, dict):
            return store

        try:
            reminder = self._find_reminder_by_id(reminder_id)
            if reminder is None:
                return {"error": f"Reminder not found: {reminder_id}"}

            success, error = store.removeReminder_commit_error_(reminder, True, None)
            if not success:
                return {"error": f"Failed to delete reminder: {error}"}
            return {"status": "deleted", "reminder_id": reminder_id}
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error deleting reminder: %s", e)
            return {"error": f"Failed to delete reminder: {e}"}

    def search_reminders(
        self,
        query: str,
        include_completed: bool = False,
    ) -> list[dict]:
        """Search reminders by title text.

        Args:
            query: Text to search for in reminder titles (case-insensitive).
            include_completed: If False (default), only search incomplete reminders.
        """
        store = self._ensure_store()
        if isinstance(store, dict):
            return [store]

        try:
            if include_completed:
                predicate = store.predicateForRemindersInCalendars_(None)
            else:
                predicate = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
                    None, None, None
                )

            raw_reminders = self._fetch_reminders(predicate)
            query_lower = query.lower()
            results = []
            for r in raw_reminders:
                title = str(r.title()) if r.title() else ""
                if query_lower in title.lower():
                    results.append(_reminder_to_dict(r))
            return results
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.error("PyObjC error searching reminders: %s", e)
            return [{"error": f"Failed to search reminders: {e}"}]
