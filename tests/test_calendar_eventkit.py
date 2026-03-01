# tests/test_calendar_eventkit.py
"""Unit tests for CalendarStore (calendar/eventkit.py).

Since EventKit is macOS-only via PyObjC, all tests mock the EventKit framework
objects and the module-level _EVENTKIT_AVAILABLE flag.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build mock EventKit objects
# ---------------------------------------------------------------------------


def _make_mock_calendar(name="Work", cal_type=1, source_name="iCloud", color_hex="#0000ff"):
    """Build a mock EKCalendar."""
    cal = MagicMock()
    cal.title.return_value = name
    cal.type.return_value = cal_type

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


def _make_mock_alarm(offset_minutes):
    """Build a mock EKAlarm with a relative offset in minutes (stored as negative seconds)."""
    alarm = MagicMock()
    alarm.relativeOffset.return_value = -offset_minutes * 60
    return alarm


def _make_mock_event(
    uid="ABC-123",
    title="Team Standup",
    start_ts=1700000000.0,
    end_ts=1700003600.0,
    location=None,
    notes=None,
    all_day=False,
    attendees=None,
    calendar_title="Work",
    alarms=None,
):
    """Build a mock EKEvent."""
    ev = MagicMock()
    ev.calendarItemExternalIdentifier.return_value = uid
    ev.title.return_value = title
    ev.location.return_value = location
    ev.notes.return_value = notes
    ev.isAllDay.return_value = all_day

    start_ns = MagicMock()
    start_ns.timeIntervalSince1970.return_value = start_ts
    ev.startDate.return_value = start_ns

    end_ns = MagicMock()
    end_ns.timeIntervalSince1970.return_value = end_ts
    ev.endDate.return_value = end_ns

    if attendees:
        mock_attendees = []
        for att in attendees:
            a = MagicMock()
            a.name.return_value = att.get("name")
            if att.get("email"):
                url = MagicMock()
                url.resourceSpecifier.return_value = att["email"]
                a.URL.return_value = url
            else:
                a.URL.return_value = None
            a.participantStatus.return_value = att.get("status", 0)
            mock_attendees.append(a)
        ev.attendees.return_value = mock_attendees
    else:
        ev.attendees.return_value = None

    if alarms is not None:
        ev.alarms.return_value = [_make_mock_alarm(m) for m in alarms]
    else:
        ev.alarms.return_value = None

    cal = MagicMock()
    cal.title.return_value = calendar_title
    ev.calendar.return_value = cal

    return ev


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def calendar_store():
    """Create a CalendarStore with mocked internals so it never touches real EventKit."""
    with patch("apple_calendar.eventkit._EVENTKIT_AVAILABLE", True):
        from apple_calendar.eventkit import CalendarStore

        store = CalendarStore()
        # Pre-populate with a mock EKEventStore so _ensure_store succeeds
        store._store = MagicMock()
        store._access_granted = True
        store._check_access = lambda: None  # Bypass permission re-check in tests
        yield store


@pytest.fixture
def unavailable_store():
    """Create a CalendarStore where EventKit is unavailable."""
    with patch("apple_calendar.eventkit._EVENTKIT_AVAILABLE", False):
        from apple_calendar.eventkit import CalendarStore

        store = CalendarStore()
        yield store


# ---------------------------------------------------------------------------
# Tests: list_calendars
# ---------------------------------------------------------------------------


class TestListCalendars:
    def test_list_calendars(self, calendar_store):
        mock_cal = _make_mock_calendar(name="Work", cal_type=1, source_name="iCloud", color_hex="#ff0000")
        calendar_store._store.calendarsForEntityType_.return_value = [mock_cal]

        result = calendar_store.list_calendars()

        assert len(result) == 1
        assert result[0]["name"] == "Work"
        assert result[0]["type"] == "calDAV"
        assert result[0]["source"] == "iCloud"
        assert result[0]["color"] == "#ff0000"

    def test_list_calendars_multiple(self, calendar_store):
        cal_a = _make_mock_calendar(name="Work", cal_type=1)
        cal_b = _make_mock_calendar(name="Personal", cal_type=0)
        calendar_store._store.calendarsForEntityType_.return_value = [cal_a, cal_b]

        result = calendar_store.list_calendars()

        assert len(result) == 2
        names = [c["name"] for c in result]
        assert "Work" in names
        assert "Personal" in names

    def test_list_calendars_empty(self, calendar_store):
        calendar_store._store.calendarsForEntityType_.return_value = []

        result = calendar_store.list_calendars()

        assert result == []


# ---------------------------------------------------------------------------
# Tests: get_events
# ---------------------------------------------------------------------------


class TestGetEvents:
    def test_get_events_in_range(self, calendar_store):
        mock_ev = _make_mock_event(uid="E1", title="Meeting")
        calendar_store._store.predicateForEventsWithStartDate_endDate_calendars_.return_value = "pred"
        calendar_store._store.eventsMatchingPredicate_.return_value = [mock_ev]

        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 31)
        result = calendar_store.get_events(start, end)

        assert len(result) == 1
        assert result[0]["uid"] == "E1"
        assert result[0]["title"] == "Meeting"
        assert result[0]["calendar"] == "Work"

    def test_get_events_with_calendar_filter(self, calendar_store):
        mock_cal = _make_mock_calendar(name="Personal")
        calendar_store._store.calendarsForEntityType_.return_value = [mock_cal]

        mock_ev = _make_mock_event(uid="E2", title="Lunch", calendar_title="Personal")
        calendar_store._store.predicateForEventsWithStartDate_endDate_calendars_.return_value = "pred"
        calendar_store._store.eventsMatchingPredicate_.return_value = [mock_ev]

        # Patch _get_calendar_by_name to return our mock
        calendar_store._get_calendar_by_name = MagicMock(return_value=mock_cal)

        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 31)
        result = calendar_store.get_events(start, end, calendar_names=["Personal"])

        assert len(result) == 1
        assert result[0]["calendar"] == "Personal"

    def test_get_events_no_results(self, calendar_store):
        calendar_store._store.predicateForEventsWithStartDate_endDate_calendars_.return_value = "pred"
        calendar_store._store.eventsMatchingPredicate_.return_value = None

        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 31)
        result = calendar_store.get_events(start, end)

        assert result == []

    def test_get_events_calendar_not_found(self, calendar_store):
        calendar_store._get_calendar_by_name = MagicMock(return_value=None)

        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 31)
        result = calendar_store.get_events(start, end, calendar_names=["NonExistent"])

        assert len(result) == 1
        assert "error" in result[0]


# ---------------------------------------------------------------------------
# Tests: create_event
# ---------------------------------------------------------------------------


class TestCreateEvent:
    def test_create_event(self, calendar_store):
        mock_ev = _make_mock_event(uid="NEW-1", title="New Event")

        with patch("apple_calendar.eventkit.EventKit") as mock_ek:
            mock_ek.EKEvent.eventWithEventStore_.return_value = mock_ev
            calendar_store._store.defaultCalendarForNewEvents.return_value = MagicMock()
            calendar_store._store.saveEvent_span_error_.return_value = (True, None)

            result = calendar_store.create_event(
                title="New Event",
                start_dt=datetime(2024, 3, 1, 9, 0),
                end_dt=datetime(2024, 3, 1, 10, 0),
            )

        assert result["uid"] == "NEW-1"
        assert result["title"] == "New Event"

    def test_create_event_with_all_fields(self, calendar_store):
        mock_ev = _make_mock_event(
            uid="NEW-2", title="Offsite", location="Conference Room A",
            notes="Bring laptop", all_day=True,
        )
        mock_cal = _make_mock_calendar(name="Work")

        with patch("apple_calendar.eventkit.EventKit") as mock_ek:
            mock_ek.EKEvent.eventWithEventStore_.return_value = mock_ev
            calendar_store._get_calendar_by_name = MagicMock(return_value=mock_cal)
            calendar_store._store.saveEvent_span_error_.return_value = (True, None)

            result = calendar_store.create_event(
                title="Offsite",
                start_dt=datetime(2024, 3, 1),
                end_dt=datetime(2024, 3, 2),
                calendar_name="Work",
                location="Conference Room A",
                notes="Bring laptop",
                is_all_day=True,
            )

        assert result["uid"] == "NEW-2"
        assert result["title"] == "Offsite"
        assert result["location"] == "Conference Room A"
        assert result["notes"] == "Bring laptop"
        assert result["is_all_day"] is True

    def test_create_event_calendar_not_found(self, calendar_store):
        with patch("apple_calendar.eventkit.EventKit") as mock_ek:
            mock_ek.EKEvent.eventWithEventStore_.return_value = MagicMock()
            calendar_store._get_calendar_by_name = MagicMock(return_value=None)

            result = calendar_store.create_event(
                title="Event",
                start_dt=datetime(2024, 3, 1, 9, 0),
                end_dt=datetime(2024, 3, 1, 10, 0),
                calendar_name="NonExistent",
            )

        assert "error" in result
        assert "Calendar not found" in result["error"]

    def test_create_event_save_fails(self, calendar_store):
        mock_ev = _make_mock_event(uid="FAIL-1", title="Fail Event")

        with patch("apple_calendar.eventkit.EventKit") as mock_ek:
            mock_ek.EKEvent.eventWithEventStore_.return_value = mock_ev
            calendar_store._store.defaultCalendarForNewEvents.return_value = MagicMock()
            calendar_store._store.saveEvent_span_error_.return_value = (False, "Write error")

            result = calendar_store.create_event(
                title="Fail Event",
                start_dt=datetime(2024, 3, 1, 9, 0),
                end_dt=datetime(2024, 3, 1, 10, 0),
            )

        assert "error" in result


# ---------------------------------------------------------------------------
# Tests: update_event
# ---------------------------------------------------------------------------


class TestUpdateEvent:
    def test_update_event(self, calendar_store):
        mock_ev = _make_mock_event(uid="UPD-1", title="Updated Title")
        calendar_store._find_event_by_uid = MagicMock(return_value=mock_ev)
        calendar_store._store.saveEvent_span_error_.return_value = (True, None)

        result = calendar_store.update_event("UPD-1", title="Updated Title")

        assert result["uid"] == "UPD-1"
        assert result["title"] == "Updated Title"

    def test_update_event_not_found(self, calendar_store):
        calendar_store._find_event_by_uid = MagicMock(return_value=None)

        result = calendar_store.update_event("MISSING-1", title="No such event")

        assert "error" in result
        assert "Event not found" in result["error"]


# ---------------------------------------------------------------------------
# Tests: delete_event
# ---------------------------------------------------------------------------


class TestDeleteEvent:
    def test_delete_event(self, calendar_store):
        mock_ev = _make_mock_event(uid="DEL-1")
        calendar_store._find_event_by_uid = MagicMock(return_value=mock_ev)
        calendar_store._store.removeEvent_span_error_.return_value = (True, None)

        result = calendar_store.delete_event("DEL-1")

        assert result["status"] == "deleted"
        assert result["event_uid"] == "DEL-1"

    def test_delete_event_not_found(self, calendar_store):
        calendar_store._find_event_by_uid = MagicMock(return_value=None)

        result = calendar_store.delete_event("MISSING-1")

        assert isinstance(result, dict)
        assert "error" in result
        assert "Event not found" in result["error"]


# ---------------------------------------------------------------------------
# Tests: search_events
# ---------------------------------------------------------------------------


class TestSearchEvents:
    def test_search_events(self, calendar_store):
        ev_match = _make_mock_event(uid="S1", title="Team Standup")
        ev_no_match = _make_mock_event(uid="S2", title="Lunch break")
        calendar_store._store.predicateForEventsWithStartDate_endDate_calendars_.return_value = "pred"
        calendar_store._store.eventsMatchingPredicate_.return_value = [ev_match, ev_no_match]

        start = datetime(2024, 1, 1)
        end = datetime(2024, 12, 31)
        result = calendar_store.search_events("standup", start, end)

        assert len(result) == 1
        assert result[0]["uid"] == "S1"
        assert result[0]["title"] == "Team Standup"

    def test_search_events_no_results(self, calendar_store):
        calendar_store._store.predicateForEventsWithStartDate_endDate_calendars_.return_value = "pred"
        calendar_store._store.eventsMatchingPredicate_.return_value = None

        start = datetime(2024, 1, 1)
        end = datetime(2024, 12, 31)
        result = calendar_store.search_events("nothing", start, end)

        assert result == []

    def test_search_events_case_insensitive(self, calendar_store):
        ev = _make_mock_event(uid="S3", title="IMPORTANT Meeting")
        calendar_store._store.predicateForEventsWithStartDate_endDate_calendars_.return_value = "pred"
        calendar_store._store.eventsMatchingPredicate_.return_value = [ev]

        start = datetime(2024, 1, 1)
        end = datetime(2024, 12, 31)
        result = calendar_store.search_events("important", start, end)

        assert len(result) == 1


# ---------------------------------------------------------------------------
# Tests: EventKit unavailable / permission denied
# ---------------------------------------------------------------------------


class TestEventKitUnavailable:
    def test_eventkit_unavailable(self, unavailable_store):
        result = unavailable_store.list_calendars()
        assert len(result) == 1
        assert "error" in result[0]
        assert "only available on macOS" in result[0]["error"]

    def test_eventkit_unavailable_get_events(self, unavailable_store):
        result = unavailable_store.get_events(datetime(2024, 1, 1), datetime(2024, 1, 31))
        assert len(result) == 1
        assert "error" in result[0]

    def test_eventkit_unavailable_create_event(self, unavailable_store):
        result = unavailable_store.create_event("Test", datetime(2024, 1, 1), datetime(2024, 1, 2))
        assert "error" in result

    def test_eventkit_unavailable_update_event(self, unavailable_store):
        result = unavailable_store.update_event("uid-123", title="Nope")
        assert "error" in result

    def test_eventkit_unavailable_delete_event(self, unavailable_store):
        result = unavailable_store.delete_event("uid-123")
        assert isinstance(result, dict)
        assert "error" in result

    def test_eventkit_unavailable_search_events(self, unavailable_store):
        result = unavailable_store.search_events("query", datetime(2024, 1, 1), datetime(2024, 12, 31))
        assert len(result) == 1
        assert "error" in result[0]


class TestPermissionDenied:
    def test_permission_denied(self):
        with patch("apple_calendar.eventkit._EVENTKIT_AVAILABLE", True):
            from apple_calendar.eventkit import CalendarStore

            store = CalendarStore()
            store._store = MagicMock()
            store._access_granted = False

            result = store.list_calendars()
            assert len(result) == 1
            assert "error" in result[0]
            assert "Calendar access denied" in result[0]["error"]

    def test_permission_denied_create(self):
        with patch("apple_calendar.eventkit._EVENTKIT_AVAILABLE", True):
            from apple_calendar.eventkit import CalendarStore

            store = CalendarStore()
            store._store = MagicMock()
            store._access_granted = False

            result = store.create_event("Test", datetime(2024, 1, 1), datetime(2024, 1, 2))
            assert "error" in result
            assert "Calendar access denied" in result["error"]


# ---------------------------------------------------------------------------
# Tests: Calendar alias resolution
# ---------------------------------------------------------------------------


class TestCalendarAliases:
    """Test that _get_calendar_by_name resolves CALENDAR_ALIASES."""

    def test_alias_resolves_to_exchange(self, calendar_store):
        """'work' alias picks Exchange calendar, not iCloud."""
        icloud_cal = _make_mock_calendar(name="Calendar", source_name="iCloud")
        exchange_cal = _make_mock_calendar(name="CHG", source_name="Exchange")
        calendar_store._store.calendarsForEntityType_.return_value = [icloud_cal, exchange_cal]

        result = calendar_store._get_calendar_by_name("work")

        assert result is exchange_cal

    def test_alias_case_insensitive(self, calendar_store):
        """Alias lookup is case-insensitive: 'Work', 'WORK', 'work' all resolve."""
        icloud_cal = _make_mock_calendar(name="Calendar", source_name="iCloud")
        exchange_cal = _make_mock_calendar(name="CHG", source_name="Exchange")
        calendar_store._store.calendarsForEntityType_.return_value = [icloud_cal, exchange_cal]

        for variant in ["work", "Work", "WORK", "Work Calendar", "EXCHANGE"]:
            result = calendar_store._get_calendar_by_name(variant)
            assert result is exchange_cal, f"Failed for alias variant: {variant!r}"

    def test_alias_personal_resolves_to_icloud(self, calendar_store):
        """'personal' alias picks iCloud calendar."""
        icloud_cal = _make_mock_calendar(name="Calendar", source_name="iCloud")
        exchange_cal = _make_mock_calendar(name="Calendar", source_name="Exchange")
        calendar_store._store.calendarsForEntityType_.return_value = [icloud_cal, exchange_cal]

        result = calendar_store._get_calendar_by_name("personal")

        assert result is icloud_cal

    def test_non_alias_name_uses_first_match(self, calendar_store):
        """A non-alias calendar name falls back to first-match behavior."""
        cal_a = _make_mock_calendar(name="Meetings", source_name="iCloud")
        cal_b = _make_mock_calendar(name="Meetings", source_name="Exchange")
        calendar_store._store.calendarsForEntityType_.return_value = [cal_a, cal_b]

        result = calendar_store._get_calendar_by_name("Meetings")

        assert result is cal_a  # first match, backward compatible

    def test_alias_chg_resolves_to_exchange(self, calendar_store):
        """'chg' alias picks Exchange calendar."""
        icloud_cal = _make_mock_calendar(name="Calendar", source_name="iCloud")
        exchange_cal = _make_mock_calendar(name="CHG", source_name="Exchange")
        calendar_store._store.calendarsForEntityType_.return_value = [icloud_cal, exchange_cal]

        result = calendar_store._get_calendar_by_name("chg")

        assert result is exchange_cal

    def test_create_event_with_alias(self, calendar_store):
        """create_event with alias 'work' targets the Exchange calendar."""
        icloud_cal = _make_mock_calendar(name="Calendar", source_name="iCloud")
        exchange_cal = _make_mock_calendar(name="CHG", source_name="Exchange")
        calendar_store._store.calendarsForEntityType_.return_value = [icloud_cal, exchange_cal]
        calendar_store._store.saveEvent_span_error_.return_value = (True, None)

        # Patch EventKit.EKEvent to return a mock event
        mock_event = _make_mock_event(uid="ALIAS-1", title="Work Meeting", calendar_title="CHG")
        with patch("apple_calendar.eventkit.EventKit") as mock_ek:
            mock_ek.EKEvent.eventWithEventStore_.return_value = mock_event

            result = calendar_store.create_event(
                title="Work Meeting",
                start_dt=datetime(2026, 4, 23, 9, 0),
                end_dt=datetime(2026, 4, 23, 12, 0),
                calendar_name="work",
            )

        assert "error" not in result
        # Verify setCalendar_ was called with the Exchange calendar, not iCloud
        mock_event.setCalendar_.assert_called_once_with(exchange_cal)


# ---------------------------------------------------------------------------
# Tests: alarms / alerts
# ---------------------------------------------------------------------------


class TestEventToDict_Alarms:
    """Tests for alarm extraction in _event_to_dict."""

    def test_event_with_alarms(self, calendar_store):
        """Events with alarms return alarm minutes in the dict."""
        ev = _make_mock_event(uid="AL-1", title="Reminder Event", alarms=[15, 30])

        from apple_calendar.eventkit import _event_to_dict

        result = _event_to_dict(ev, "Work")

        assert "alarms" in result
        assert result["alarms"] == [15, 30]

    def test_event_without_alarms(self, calendar_store):
        """Events with no alarms return an empty list."""
        ev = _make_mock_event(uid="AL-2", title="No Alarms")

        from apple_calendar.eventkit import _event_to_dict

        result = _event_to_dict(ev, "Work")

        assert "alarms" in result
        assert result["alarms"] == []

    def test_event_single_alarm(self, calendar_store):
        """Single alarm is correctly extracted."""
        ev = _make_mock_event(uid="AL-3", title="One Alarm", alarms=[5])

        from apple_calendar.eventkit import _event_to_dict

        result = _event_to_dict(ev, "Work")

        assert result["alarms"] == [5]


class TestCreateEventAlarms:
    """Tests for alarm creation in CalendarStore.create_event."""

    def test_create_event_with_alarms(self, calendar_store):
        mock_ev = _make_mock_event(uid="CA-1", title="With Alarms", alarms=[15, 30])

        with patch("apple_calendar.eventkit.EventKit") as mock_ek:
            mock_alarm_15 = MagicMock()
            mock_alarm_30 = MagicMock()
            mock_ek.EKAlarm.alarmWithRelativeOffset_.side_effect = [mock_alarm_15, mock_alarm_30]
            mock_ek.EKEvent.eventWithEventStore_.return_value = mock_ev
            calendar_store._store.defaultCalendarForNewEvents.return_value = MagicMock()
            calendar_store._store.saveEvent_span_error_.return_value = (True, None)

            result = calendar_store.create_event(
                title="With Alarms",
                start_dt=datetime(2024, 3, 1, 9, 0),
                end_dt=datetime(2024, 3, 1, 10, 0),
                alarms=[15, 30],
            )

        assert result["uid"] == "CA-1"
        # Verify alarmWithRelativeOffset_ called with negative seconds
        calls = mock_ek.EKAlarm.alarmWithRelativeOffset_.call_args_list
        assert calls[0][0][0] == -900   # -15 * 60
        assert calls[1][0][0] == -1800  # -30 * 60
        # Verify addAlarm_ called twice
        assert mock_ev.addAlarm_.call_count == 2

    def test_create_event_without_alarms(self, calendar_store):
        """When alarms is None (default), no alarms are added."""
        mock_ev = _make_mock_event(uid="CA-2", title="No Alarms")

        with patch("apple_calendar.eventkit.EventKit") as mock_ek:
            mock_ek.EKEvent.eventWithEventStore_.return_value = mock_ev
            calendar_store._store.defaultCalendarForNewEvents.return_value = MagicMock()
            calendar_store._store.saveEvent_span_error_.return_value = (True, None)

            result = calendar_store.create_event(
                title="No Alarms",
                start_dt=datetime(2024, 3, 1, 9, 0),
                end_dt=datetime(2024, 3, 1, 10, 0),
            )

        assert result["uid"] == "CA-2"
        mock_ev.addAlarm_.assert_not_called()

    def test_create_event_empty_alarms_list(self, calendar_store):
        """Empty alarms list adds no alarms but is a valid input."""
        mock_ev = _make_mock_event(uid="CA-3", title="Empty Alarms")

        with patch("apple_calendar.eventkit.EventKit") as mock_ek:
            mock_ek.EKEvent.eventWithEventStore_.return_value = mock_ev
            calendar_store._store.defaultCalendarForNewEvents.return_value = MagicMock()
            calendar_store._store.saveEvent_span_error_.return_value = (True, None)

            result = calendar_store.create_event(
                title="Empty Alarms",
                start_dt=datetime(2024, 3, 1, 9, 0),
                end_dt=datetime(2024, 3, 1, 10, 0),
                alarms=[],
            )

        assert result["uid"] == "CA-3"
        mock_ev.addAlarm_.assert_not_called()


class TestUpdateEventAlarms:
    """Tests for alarm updates in CalendarStore.update_event."""

    def test_update_event_replaces_alarms(self, calendar_store):
        """Updating alarms removes existing and adds new ones."""
        existing_alarm = MagicMock()
        mock_ev = _make_mock_event(uid="UA-1", title="Event")
        mock_ev.alarms.return_value = [existing_alarm]
        calendar_store._find_event_by_uid = MagicMock(return_value=mock_ev)
        calendar_store._store.saveEvent_span_error_.return_value = (True, None)

        with patch("apple_calendar.eventkit.EventKit") as mock_ek:
            new_alarm = MagicMock()
            mock_ek.EKAlarm.alarmWithRelativeOffset_.return_value = new_alarm

            result = calendar_store.update_event("UA-1", alarms=[10])

        assert result["uid"] == "UA-1"
        mock_ev.removeAlarm_.assert_called_once_with(existing_alarm)
        mock_ev.addAlarm_.assert_called_once_with(new_alarm)
        mock_ek.EKAlarm.alarmWithRelativeOffset_.assert_called_once_with(-600)  # -10 * 60

    def test_update_event_removes_all_alarms(self, calendar_store):
        """Setting alarms=None removes all existing alarms without adding new ones."""
        existing_alarm = MagicMock()
        mock_ev = _make_mock_event(uid="UA-2", title="Event")
        mock_ev.alarms.return_value = [existing_alarm]
        calendar_store._find_event_by_uid = MagicMock(return_value=mock_ev)
        calendar_store._store.saveEvent_span_error_.return_value = (True, None)

        result = calendar_store.update_event("UA-2", alarms=None)

        assert result["uid"] == "UA-2"
        mock_ev.removeAlarm_.assert_called_once_with(existing_alarm)
        mock_ev.addAlarm_.assert_not_called()

    def test_update_event_adds_alarms_when_none_existed(self, calendar_store):
        """Adding alarms to an event that had none."""
        mock_ev = _make_mock_event(uid="UA-3", title="Event")
        mock_ev.alarms.return_value = None
        calendar_store._find_event_by_uid = MagicMock(return_value=mock_ev)
        calendar_store._store.saveEvent_span_error_.return_value = (True, None)

        with patch("apple_calendar.eventkit.EventKit") as mock_ek:
            new_alarm = MagicMock()
            mock_ek.EKAlarm.alarmWithRelativeOffset_.return_value = new_alarm

            result = calendar_store.update_event("UA-3", alarms=[5, 60])

        assert result["uid"] == "UA-3"
        mock_ev.removeAlarm_.assert_not_called()
        assert mock_ev.addAlarm_.call_count == 2

    def test_update_event_alarms_empty_list(self, calendar_store):
        """Setting alarms=[] removes all existing alarms without adding new ones."""
        existing_a = MagicMock()
        existing_b = MagicMock()
        mock_ev = _make_mock_event(uid="UA-4", title="Event")
        mock_ev.alarms.return_value = [existing_a, existing_b]
        calendar_store._find_event_by_uid = MagicMock(return_value=mock_ev)
        calendar_store._store.saveEvent_span_error_.return_value = (True, None)

        with patch("apple_calendar.eventkit.EventKit"):
            result = calendar_store.update_event("UA-4", alarms=[])

        assert result["uid"] == "UA-4"
        # Both existing alarms should have been removed
        assert mock_ev.removeAlarm_.call_count == 2
        mock_ev.removeAlarm_.assert_any_call(existing_a)
        mock_ev.removeAlarm_.assert_any_call(existing_b)
        # No new alarms added
        mock_ev.addAlarm_.assert_not_called()

    def test_update_event_without_alarms_kwarg(self, calendar_store):
        """When alarms is not passed at all, existing alarms are not touched."""
        mock_ev = _make_mock_event(uid="UA-5", title="Event", alarms=[15])
        calendar_store._find_event_by_uid = MagicMock(return_value=mock_ev)
        calendar_store._store.saveEvent_span_error_.return_value = (True, None)

        result = calendar_store.update_event("UA-5", title="New Title")

        assert result["uid"] == "UA-5"
        # Alarms should not be touched at all
        mock_ev.removeAlarm_.assert_not_called()
        mock_ev.addAlarm_.assert_not_called()
