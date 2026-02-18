# tests/test_apple_reminders.py
"""Unit tests for ReminderStore (apple_reminders/eventkit.py).

Since EventKit is macOS-only via PyObjC, all tests mock the EventKit framework
objects and the module-level _EVENTKIT_AVAILABLE flag.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build mock EventKit objects
# ---------------------------------------------------------------------------


def _make_mock_reminder_list(name="Reminders", source_name="iCloud", color_hex="#0000ff"):
    """Build a mock EKCalendar (reminder list)."""
    cal = MagicMock()
    cal.title.return_value = name

    source = MagicMock()
    source.title.return_value = source_name
    cal.source.return_value = source

    color = MagicMock()
    r, g, b = int(color_hex[1:3], 16), int(color_hex[3:5], 16), int(color_hex[5:7], 16)
    color.redComponent.return_value = r / 255
    color.greenComponent.return_value = g / 255
    color.blueComponent.return_value = b / 255
    cal.color.return_value = color

    return cal


def _make_mock_reminder(
    uid="REM-123",
    title="Buy groceries",
    notes=None,
    completed=False,
    priority=0,
    list_name="Reminders",
    due_ts=None,
    completion_ts=None,
    creation_ts=1700000000.0,
):
    """Build a mock EKReminder."""
    rem = MagicMock()
    rem.calendarItemExternalIdentifier.return_value = uid
    rem.title.return_value = title
    rem.notes.return_value = notes
    rem.isCompleted.return_value = completed
    rem.priority.return_value = priority

    # Due date components
    if due_ts:
        due_components = MagicMock()
        ns_cal = MagicMock()
        ns_date = MagicMock()
        ns_date.timeIntervalSince1970.return_value = due_ts
        ns_cal.dateFromComponents_.return_value = ns_date
        rem.dueDateComponents.return_value = due_components
    else:
        rem.dueDateComponents.return_value = None

    # Completion date
    if completion_ts:
        comp_date = MagicMock()
        comp_date.timeIntervalSince1970.return_value = completion_ts
        rem.completionDate.return_value = comp_date
    else:
        rem.completionDate.return_value = None

    # Creation date
    if creation_ts:
        create_date = MagicMock()
        create_date.timeIntervalSince1970.return_value = creation_ts
        rem.creationDate.return_value = create_date
    else:
        rem.creationDate.return_value = None

    # Calendar (reminder list)
    cal = MagicMock()
    cal.title.return_value = list_name
    rem.calendar.return_value = cal

    return rem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reminder_store():
    """Create a ReminderStore with mocked internals so it never touches real EventKit."""
    with patch("apple_reminders.eventkit._EVENTKIT_AVAILABLE", True):
        from apple_reminders.eventkit import ReminderStore

        store = ReminderStore()
        store._store = MagicMock()
        store._access_granted = True
        yield store


@pytest.fixture
def unavailable_store():
    """Create a ReminderStore where EventKit is unavailable."""
    with patch("apple_reminders.eventkit._EVENTKIT_AVAILABLE", False):
        from apple_reminders.eventkit import ReminderStore

        store = ReminderStore()
        yield store


# ---------------------------------------------------------------------------
# Tests: list_reminder_lists
# ---------------------------------------------------------------------------


class TestListReminderLists:
    def test_list_all(self, reminder_store):
        mock_list = _make_mock_reminder_list(name="Reminders", source_name="iCloud", color_hex="#ff0000")
        reminder_store._store.calendarsForEntityType_.return_value = [mock_list]

        result = reminder_store.list_reminder_lists()

        assert len(result) == 1
        assert result[0]["name"] == "Reminders"
        assert result[0]["source"] == "iCloud"
        assert result[0]["color"] == "#ff0000"

    def test_list_empty(self, reminder_store):
        reminder_store._store.calendarsForEntityType_.return_value = []

        result = reminder_store.list_reminder_lists()

        assert result == []

    def test_list_multiple(self, reminder_store):
        list_a = _make_mock_reminder_list(name="Reminders")
        list_b = _make_mock_reminder_list(name="Shopping")
        list_c = _make_mock_reminder_list(name="Work")
        reminder_store._store.calendarsForEntityType_.return_value = [list_a, list_b, list_c]

        result = reminder_store.list_reminder_lists()

        assert len(result) == 3
        names = [r["name"] for r in result]
        assert "Reminders" in names
        assert "Shopping" in names
        assert "Work" in names


# ---------------------------------------------------------------------------
# Tests: get_reminders
# ---------------------------------------------------------------------------


class TestGetReminders:
    def test_get_all(self, reminder_store):
        mock_rem = _make_mock_reminder(uid="R1", title="Buy milk")
        reminder_store._store.predicateForRemindersInCalendars_.return_value = "pred"
        reminder_store._fetch_reminders = MagicMock(return_value=[mock_rem])

        with patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
            mock_ns_cal.currentCalendar.return_value = MagicMock()
            result = reminder_store.list_reminders()

        assert len(result) == 1
        assert result[0]["id"] == "R1"
        assert result[0]["title"] == "Buy milk"

    def test_get_filtered_by_list(self, reminder_store):
        mock_cal = _make_mock_reminder_list(name="Shopping")
        reminder_store._get_reminder_list_by_name = MagicMock(return_value=mock_cal)
        mock_rem = _make_mock_reminder(uid="R2", title="Buy bread", list_name="Shopping")
        reminder_store._store.predicateForRemindersInCalendars_.return_value = "pred"
        reminder_store._fetch_reminders = MagicMock(return_value=[mock_rem])

        with patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
            mock_ns_cal.currentCalendar.return_value = MagicMock()
            result = reminder_store.list_reminders(list_name="Shopping")

        assert len(result) == 1
        assert result[0]["list_name"] == "Shopping"

    def test_get_completed_only(self, reminder_store):
        mock_rem = _make_mock_reminder(uid="R3", title="Done task", completed=True)
        reminder_store._store.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_.return_value = "pred"
        reminder_store._fetch_reminders = MagicMock(return_value=[mock_rem])

        with patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
            mock_ns_cal.currentCalendar.return_value = MagicMock()
            result = reminder_store.list_reminders(completed=True)

        assert len(result) == 1
        assert result[0]["completed"] is True

    def test_get_incomplete_only(self, reminder_store):
        mock_rem = _make_mock_reminder(uid="R4", title="Pending task", completed=False)
        reminder_store._store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_.return_value = "pred"
        reminder_store._fetch_reminders = MagicMock(return_value=[mock_rem])

        with patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
            mock_ns_cal.currentCalendar.return_value = MagicMock()
            result = reminder_store.list_reminders(completed=False)

        assert len(result) == 1
        assert result[0]["completed"] is False

    def test_get_list_not_found(self, reminder_store):
        reminder_store._get_reminder_list_by_name = MagicMock(return_value=None)

        result = reminder_store.list_reminders(list_name="NonExistent")

        assert len(result) == 1
        assert "error" in result[0]
        assert "not found" in result[0]["error"]


# ---------------------------------------------------------------------------
# Tests: create_reminder
# ---------------------------------------------------------------------------


class TestCreateReminder:
    def test_create_basic(self, reminder_store):
        mock_rem = _make_mock_reminder(uid="NEW-1", title="New reminder")

        with patch("apple_reminders.eventkit.EventKit") as mock_ek:
            mock_ek.EKReminder.reminderWithEventStore_.return_value = mock_rem
            reminder_store._store.defaultCalendarForNewReminders.return_value = MagicMock()
            reminder_store._store.saveReminder_commit_error_.return_value = (True, None)

            with patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
                mock_ns_cal.currentCalendar.return_value = MagicMock()
                result = reminder_store.create_reminder(title="New reminder")

        assert result["id"] == "NEW-1"
        assert result["title"] == "New reminder"

    def test_create_with_all_fields(self, reminder_store):
        mock_rem = _make_mock_reminder(
            uid="NEW-2", title="Full reminder", notes="Some notes",
            priority=1, list_name="Work",
        )

        with patch("apple_reminders.eventkit.EventKit") as mock_ek, \
             patch("apple_reminders.eventkit.NSDateComponents") as mock_components, \
             patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
            mock_ek.EKReminder.reminderWithEventStore_.return_value = mock_rem
            mock_cal = _make_mock_reminder_list(name="Work")
            reminder_store._get_reminder_list_by_name = MagicMock(return_value=mock_cal)
            reminder_store._store.saveReminder_commit_error_.return_value = (True, None)
            mock_components.alloc.return_value.init.return_value = MagicMock()
            mock_ns_cal.currentCalendar.return_value = MagicMock()

            result = reminder_store.create_reminder(
                title="Full reminder",
                list_name="Work",
                due_date="2025-03-15T14:00:00",
                priority=1,
                notes="Some notes",
            )

        assert result["id"] == "NEW-2"
        assert result["title"] == "Full reminder"

    def test_create_list_not_found(self, reminder_store):
        with patch("apple_reminders.eventkit.EventKit") as mock_ek:
            mock_ek.EKReminder.reminderWithEventStore_.return_value = MagicMock()
            reminder_store._get_reminder_list_by_name = MagicMock(return_value=None)

            result = reminder_store.create_reminder(
                title="Reminder",
                list_name="NonExistent",
            )

        assert "error" in result
        assert "not found" in result["error"]

    def test_create_save_failure(self, reminder_store):
        mock_rem = _make_mock_reminder(uid="FAIL-1", title="Fail")

        with patch("apple_reminders.eventkit.EventKit") as mock_ek:
            mock_ek.EKReminder.reminderWithEventStore_.return_value = mock_rem
            reminder_store._store.defaultCalendarForNewReminders.return_value = MagicMock()
            reminder_store._store.saveReminder_commit_error_.return_value = (False, "Write error")

            result = reminder_store.create_reminder(title="Fail")

        assert "error" in result
        assert "Failed to save" in result["error"]


# ---------------------------------------------------------------------------
# Tests: complete_reminder
# ---------------------------------------------------------------------------


class TestCompleteReminder:
    def test_mark_complete(self, reminder_store):
        mock_rem = _make_mock_reminder(uid="COMP-1", title="Done", completed=True)
        reminder_store._find_reminder_by_id = MagicMock(return_value=mock_rem)
        reminder_store._store.saveReminder_commit_error_.return_value = (True, None)

        with patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
            mock_ns_cal.currentCalendar.return_value = MagicMock()
            result = reminder_store.complete_reminder("COMP-1")

        assert result["id"] == "COMP-1"
        assert result["completed"] is True

    def test_complete_not_found(self, reminder_store):
        reminder_store._find_reminder_by_id = MagicMock(return_value=None)

        result = reminder_store.complete_reminder("MISSING-1")

        assert "error" in result
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Tests: delete_reminder
# ---------------------------------------------------------------------------


class TestDeleteReminder:
    def test_delete(self, reminder_store):
        mock_rem = _make_mock_reminder(uid="DEL-1")
        reminder_store._find_reminder_by_id = MagicMock(return_value=mock_rem)
        reminder_store._store.removeReminder_commit_error_.return_value = (True, None)

        result = reminder_store.delete_reminder("DEL-1")

        assert result["status"] == "deleted"
        assert result["reminder_id"] == "DEL-1"

    def test_delete_not_found(self, reminder_store):
        reminder_store._find_reminder_by_id = MagicMock(return_value=None)

        result = reminder_store.delete_reminder("MISSING-1")

        assert isinstance(result, dict)
        assert "error" in result
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Tests: search_reminders
# ---------------------------------------------------------------------------


class TestSearchReminders:
    def test_search_match(self, reminder_store):
        rem_match = _make_mock_reminder(uid="S1", title="Buy groceries")
        rem_no_match = _make_mock_reminder(uid="S2", title="Call dentist")
        reminder_store._store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_.return_value = "pred"
        reminder_store._fetch_reminders = MagicMock(return_value=[rem_match, rem_no_match])

        with patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
            mock_ns_cal.currentCalendar.return_value = MagicMock()
            result = reminder_store.search_reminders("groceries")

        assert len(result) == 1
        assert result[0]["id"] == "S1"
        assert result[0]["title"] == "Buy groceries"

    def test_search_no_results(self, reminder_store):
        reminder_store._store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_.return_value = "pred"
        reminder_store._fetch_reminders = MagicMock(return_value=[])

        with patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
            mock_ns_cal.currentCalendar.return_value = MagicMock()
            result = reminder_store.search_reminders("nonexistent")

        assert result == []

    def test_search_case_insensitive(self, reminder_store):
        rem = _make_mock_reminder(uid="S3", title="IMPORTANT Task")
        reminder_store._store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_.return_value = "pred"
        reminder_store._fetch_reminders = MagicMock(return_value=[rem])

        with patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
            mock_ns_cal.currentCalendar.return_value = MagicMock()
            result = reminder_store.search_reminders("important")

        assert len(result) == 1

    def test_search_include_completed(self, reminder_store):
        rem = _make_mock_reminder(uid="S4", title="Done task", completed=True)
        reminder_store._store.predicateForRemindersInCalendars_.return_value = "pred"
        reminder_store._fetch_reminders = MagicMock(return_value=[rem])

        with patch("apple_reminders.eventkit.NSCalendar") as mock_ns_cal:
            mock_ns_cal.currentCalendar.return_value = MagicMock()
            result = reminder_store.search_reminders("done", include_completed=True)

        assert len(result) == 1
        # Verify it used predicateForRemindersInCalendars_ (all) not incomplete-only
        reminder_store._store.predicateForRemindersInCalendars_.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# Tests: EventKit unavailable / permission denied
# ---------------------------------------------------------------------------


class TestEventKitUnavailable:
    def test_list_reminder_lists(self, unavailable_store):
        result = unavailable_store.list_reminder_lists()
        assert len(result) == 1
        assert "error" in result[0]
        assert "only available on macOS" in result[0]["error"]

    def test_get_reminders(self, unavailable_store):
        result = unavailable_store.list_reminders()
        assert len(result) == 1
        assert "error" in result[0]

    def test_create_reminder(self, unavailable_store):
        result = unavailable_store.create_reminder("Test")
        assert "error" in result

    def test_complete_reminder(self, unavailable_store):
        result = unavailable_store.complete_reminder("uid-123")
        assert "error" in result

    def test_delete_reminder(self, unavailable_store):
        result = unavailable_store.delete_reminder("uid-123")
        assert isinstance(result, dict)
        assert "error" in result

    def test_search_reminders(self, unavailable_store):
        result = unavailable_store.search_reminders("query")
        assert len(result) == 1
        assert "error" in result[0]


class TestPermissionDenied:
    def test_permission_denied_list(self):
        with patch("apple_reminders.eventkit._EVENTKIT_AVAILABLE", True):
            from apple_reminders.eventkit import ReminderStore

            store = ReminderStore()
            store._store = MagicMock()
            store._access_granted = False

            result = store.list_reminder_lists()
            assert len(result) == 1
            assert "error" in result[0]
            assert "Reminders access denied" in result[0]["error"]

    def test_permission_denied_create(self):
        with patch("apple_reminders.eventkit._EVENTKIT_AVAILABLE", True):
            from apple_reminders.eventkit import ReminderStore

            store = ReminderStore()
            store._store = MagicMock()
            store._access_granted = False

            result = store.create_reminder("Test")
            assert "error" in result
            assert "Reminders access denied" in result["error"]

    def test_permission_denied_complete(self):
        with patch("apple_reminders.eventkit._EVENTKIT_AVAILABLE", True):
            from apple_reminders.eventkit import ReminderStore

            store = ReminderStore()
            store._store = MagicMock()
            store._access_granted = False

            result = store.complete_reminder("uid-123")
            assert "error" in result
            assert "Reminders access denied" in result["error"]

    def test_permission_denied_delete(self):
        with patch("apple_reminders.eventkit._EVENTKIT_AVAILABLE", True):
            from apple_reminders.eventkit import ReminderStore

            store = ReminderStore()
            store._store = MagicMock()
            store._access_granted = False

            result = store.delete_reminder("uid-123")
            assert isinstance(result, dict)
            assert "error" in result
            assert "Reminders access denied" in result["error"]

    def test_permission_denied_search(self):
        with patch("apple_reminders.eventkit._EVENTKIT_AVAILABLE", True):
            from apple_reminders.eventkit import ReminderStore

            store = ReminderStore()
            store._store = MagicMock()
            store._access_granted = False

            result = store.search_reminders("query")
            assert len(result) == 1
            assert "error" in result[0]
            assert "Reminders access denied" in result[0]["error"]
