# tests/test_scheduler.py
import pytest
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from scheduler.availability import (
    normalize_event_for_scheduler,
    classify_event_softness,
    find_available_slots,
    format_slots_for_sharing,
)


# Test data fixtures
@pytest.fixture
def apple_event():
    """Sample Apple Calendar event dict."""
    return {
        "uid": "apple-event-123",
        "title": "Team Standup",
        "start": "2026-02-18T09:00:00-07:00",
        "end": "2026-02-18T09:30:00-07:00",
        "calendar": "Work",
        "location": "Zoom",
        "notes": "Daily standup meeting",
        "attendees": [
            {"name": "Jason", "email": "jason@example.com", "status": 2},
            {"name": "Matt", "email": "matt@example.com", "status": 2},
        ],
        "is_all_day": False,
    }


@pytest.fixture
def m365_event():
    """Sample Microsoft 365 event dict."""
    return {
        "id": "m365-event-456",
        "subject": "Client Review",
        "start": {"dateTime": "2026-02-18T14:00:00", "timeZone": "America/Denver"},
        "end": {"dateTime": "2026-02-18T15:00:00", "timeZone": "America/Denver"},
        "location": {"displayName": "Conference Room A"},
        "body": {"content": "Q1 review with client"},
        "attendees": [
            {
                "emailAddress": {"name": "Jason", "address": "jason@example.com"},
                "status": {"response": "accepted"},
            }
        ],
        "isAllDay": False,
    }


@pytest.fixture
def focus_event():
    """Sample focus time event."""
    return {
        "uid": "focus-123",
        "title": "Focus Time",
        "start": "2026-02-18T10:00:00-07:00",
        "end": "2026-02-18T12:00:00-07:00",
        "calendar": "Work",
        "notes": "",
        "attendees": [],
        "is_all_day": False,
    }


@pytest.fixture
def lunch_event():
    """Sample lunch event."""
    return {
        "uid": "lunch-123",
        "title": "Lunch",
        "start": "2026-02-18T12:00:00-07:00",
        "end": "2026-02-18T13:00:00-07:00",
        "calendar": "Personal",
        "notes": "",
        "attendees": [],
        "is_all_day": False,
    }


# normalize_event_for_scheduler tests
class TestNormalizeEvent:
    def test_normalize_apple_event(self, apple_event):
        """Apple Calendar event dict normalized correctly."""
        result = normalize_event_for_scheduler(apple_event)

        assert result["uid"] == "apple-event-123"
        assert result["title"] == "Team Standup"
        assert result["start"] == "2026-02-18T09:00:00-07:00"
        assert result["end"] == "2026-02-18T09:30:00-07:00"
        assert result["calendar"] == "Work"
        assert result["is_all_day"] is False
        assert result["location"] == "Zoom"
        assert result["notes"] == "Daily standup meeting"
        assert len(result["attendees"]) == 2

    def test_normalize_m365_event(self, m365_event):
        """M365 event dict (subject instead of title, etc.) normalized correctly."""
        result = normalize_event_for_scheduler(m365_event)

        assert result["uid"] == "m365-event-456"
        assert result["title"] == "Client Review"
        assert "2026-02-18T14:00:00" in result["start"]
        assert "2026-02-18T15:00:00" in result["end"]
        assert result["is_all_day"] is False
        assert result["location"] == "Conference Room A"
        assert result["notes"] == "Q1 review with client"
        assert len(result["attendees"]) == 1

    def test_normalize_minimal_event(self):
        """Event with missing fields gets safe defaults."""
        minimal_event = {
            "uid": "minimal-123",
            "title": "Simple Event",
            "start": "2026-02-18T10:00:00-07:00",
            "end": "2026-02-18T11:00:00-07:00",
        }

        result = normalize_event_for_scheduler(minimal_event)

        assert result["uid"] == "minimal-123"
        assert result["title"] == "Simple Event"
        assert result["calendar"] == ""
        assert result["provider"] == ""
        assert result["is_all_day"] is False
        assert result["attendees"] == []
        assert result["location"] == ""
        assert result["notes"] == ""

    def test_normalize_preserves_attendees(self, apple_event):
        """Attendee list preserved."""
        result = normalize_event_for_scheduler(apple_event)

        assert len(result["attendees"]) == 2
        assert result["attendees"][0]["name"] == "Jason"
        assert result["attendees"][0]["email"] == "jason@example.com"
        assert result["attendees"][0]["status"] == 2


# classify_event_softness tests
class TestClassifyEventSoftness:
    def test_classify_focus_time_soft(self, focus_event):
        """'Focus time' title → is_soft=True."""
        result = classify_event_softness(focus_event)

        assert result["is_soft"] is True
        assert "focus" in result["reason"].lower()
        assert result["confidence"] > 0.8

    def test_classify_lunch_soft(self, lunch_event):
        """'Lunch' title → is_soft=True."""
        result = classify_event_softness(lunch_event)

        assert result["is_soft"] is True
        assert "lunch" in result["reason"].lower()
        assert result["confidence"] > 0.8

    def test_classify_real_meeting_hard(self, apple_event):
        """'1:1 with Matt' → is_soft=False."""
        result = classify_event_softness(apple_event)

        assert result["is_soft"] is False
        assert result["confidence"] > 0.8

    def test_classify_tentative_attendee_soft(self):
        """Attendee status=3 → is_soft=True."""
        tentative_event = {
            "uid": "tentative-123",
            "title": "Maybe Meeting",
            "start": "2026-02-18T10:00:00-07:00",
            "end": "2026-02-18T11:00:00-07:00",
            "calendar": "Work",
            "notes": "",
            "attendees": [
                {"name": "Jason", "email": "jason@example.com", "status": 3}  # tentative
            ],
            "is_all_day": False,
        }

        result = classify_event_softness(tentative_event)

        assert result["is_soft"] is True
        assert "tentative" in result["reason"].lower()

    def test_classify_custom_keywords(self):
        """Custom soft_keywords list works."""
        event = {
            "uid": "custom-123",
            "title": "Deep Work",
            "start": "2026-02-18T10:00:00-07:00",
            "end": "2026-02-18T12:00:00-07:00",
            "calendar": "Work",
            "notes": "",
            "attendees": [],
            "is_all_day": False,
        }

        result = classify_event_softness(event, soft_keywords=["deep work", "buffer"])

        assert result["is_soft"] is True
        assert "keyword" in result["reason"].lower()

    def test_classify_keyword_in_notes(self):
        """Keyword in notes (not title) still detected."""
        event = {
            "uid": "notes-123",
            "title": "Block",
            "start": "2026-02-18T10:00:00-07:00",
            "end": "2026-02-18T11:00:00-07:00",
            "calendar": "Work",
            "notes": "This is placeholder time for prep work",
            "attendees": [],
            "is_all_day": False,
        }

        result = classify_event_softness(event)

        assert result["is_soft"] is True
        assert "placeholder" in result["reason"].lower() or "prep" in result["reason"].lower()


# find_available_slots tests
class TestFindAvailableSlots:
    def test_find_slots_no_events(self):
        """Empty calendar returns full working day."""
        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=[],
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600  # 8 AM to 6 PM = 10 hours
        assert slots[0]["date"] == "2026-02-18"
        assert "Wednesday" in slots[0]["day_of_week"]

    def test_find_slots_with_gaps(self):
        """Events with gaps returns correct windows."""
        events = [
            {
                "uid": "event-1",
                "title": "Morning Meeting",
                "start": "2026-02-18T09:00:00-07:00",
                "end": "2026-02-18T10:00:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],  # accepted = hard
            },
            {
                "uid": "event-2",
                "title": "Afternoon Meeting",
                "start": "2026-02-18T14:00:00-07:00",
                "end": "2026-02-18T15:00:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],  # accepted = hard
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        # Should have 3 slots: 8-9 AM, 10 AM-2 PM, 3-6 PM
        assert len(slots) == 3
        assert slots[0]["duration_minutes"] == 60  # 8-9 AM
        assert slots[1]["duration_minutes"] == 240  # 10 AM-2 PM
        assert slots[2]["duration_minutes"] == 180  # 3-6 PM

    def test_find_slots_soft_blocks_included(self, focus_event):
        """Focus time treated as available when include_soft_blocks=True."""
        events = [focus_event]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
            include_soft_blocks=True,
        )

        # Focus time 10-12 should be AVAILABLE, so we get a continuous 8 AM-6 PM slot
        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600

    def test_find_slots_soft_blocks_excluded(self, focus_event):
        """Focus time blocks time when include_soft_blocks=False."""
        events = [focus_event]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
            include_soft_blocks=False,
        )

        # Focus time 10-12 blocks, so we get 8-10 AM and 12-6 PM
        assert len(slots) == 2
        assert slots[0]["duration_minutes"] == 120  # 8-10 AM
        assert slots[1]["duration_minutes"] == 360  # 12-6 PM

    def test_find_slots_duration_filter(self):
        """Slots shorter than duration_minutes excluded."""
        events = [
            {
                "uid": "event-1",
                "title": "Meeting 1",
                "start": "2026-02-18T09:00:00-07:00",
                "end": "2026-02-18T09:45:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=60,  # need at least 60 minutes
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        # 8-9 AM slot is only 60 minutes, should be included
        # 9:45 AM-6 PM is much longer
        slot_durations = [s["duration_minutes"] for s in slots]
        assert all(d >= 60 for d in slot_durations)
        # The 8-9 AM slot should be included
        assert 60 in slot_durations

    def test_find_slots_multiple_days(self):
        """Multi-day range returns slots for each day."""
        events = []

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 20, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        # Should have one full-day slot for Feb 18, 19, and 20
        dates = [s["date"] for s in slots]
        assert "2026-02-18" in dates
        assert "2026-02-19" in dates
        assert "2026-02-20" in dates

    def test_find_slots_fully_booked(self):
        """Back-to-back hard meetings returns empty."""
        events = [
            {
                "uid": "event-1",
                "title": "All Day Meetings",
                "start": "2026-02-18T08:00:00-07:00",
                "end": "2026-02-18T18:00:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        assert len(slots) == 0

    def test_find_slots_all_day_event_ignored(self):
        """All-day events don't block slots."""
        events = [
            {
                "uid": "event-1",
                "title": "Holiday",
                "start": "2026-02-18T00:00:00-07:00",
                "end": "2026-02-18T23:59:59-07:00",
                "is_all_day": True,
                "attendees": [],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        # Should still get full working day since all-day events are ignored
        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600

    def test_find_slots_working_hours(self):
        """Only returns slots within working hours."""
        events = [
            {
                "uid": "event-1",
                "title": "Early Meeting",
                "start": "2026-02-18T07:00:00-07:00",
                "end": "2026-02-18T07:30:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],
            },
            {
                "uid": "event-2",
                "title": "Late Meeting",
                "start": "2026-02-18T19:00:00-07:00",
                "end": "2026-02-18T20:00:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        # Should only get 8 AM-6 PM slot, ignoring 7 AM and 7 PM events
        assert len(slots) == 1
        assert "08:00" in slots[0]["start"]
        assert "18:00" in slots[0]["end"]

    def test_find_slots_overlapping_events(self):
        """Overlapping events handled correctly."""
        events = [
            {
                "uid": "event-1",
                "title": "Meeting 1",
                "start": "2026-02-18T09:00:00-07:00",
                "end": "2026-02-18T10:30:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],
            },
            {
                "uid": "event-2",
                "title": "Meeting 2",
                "start": "2026-02-18T10:00:00-07:00",
                "end": "2026-02-18T11:00:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        # Overlapping events should be merged, blocking 9-11 AM
        # Should get 8-9 AM and 11 AM-6 PM
        assert len(slots) == 2
        assert slots[0]["duration_minutes"] == 60  # 8-9 AM
        assert slots[1]["duration_minutes"] == 420  # 11 AM-6 PM


# format_slots_for_sharing tests
class TestFormatSlotsForSharing:
    def test_format_single_day(self):
        """Single day formatted correctly."""
        slots = [
            {
                "start": "2026-02-18T08:00:00-07:00",
                "end": "2026-02-18T10:00:00-07:00",
                "duration_minutes": 120,
                "date": "2026-02-18",
                "day_of_week": "Tuesday",
            },
            {
                "start": "2026-02-18T14:00:00-07:00",
                "end": "2026-02-18T16:00:00-07:00",
                "duration_minutes": 120,
                "date": "2026-02-18",
                "day_of_week": "Tuesday",
            },
        ]

        result = format_slots_for_sharing(slots, timezone_name="America/Denver")

        assert "Tuesday" in result
        assert "Feb 18" in result or "February 18" in result
        assert "8:00" in result or "08:00" in result
        assert "10:00" in result
        assert "2:00" in result or "14:00" in result
        assert "4:00" in result or "16:00" in result
        assert "MST" in result or "MDT" in result or "MT" in result  # Mountain Time

    def test_format_multiple_days(self):
        """Multiple days grouped and formatted."""
        slots = [
            {
                "start": "2026-02-18T08:00:00-07:00",
                "end": "2026-02-18T10:00:00-07:00",
                "duration_minutes": 120,
                "date": "2026-02-18",
                "day_of_week": "Tuesday",
            },
            {
                "start": "2026-02-19T08:00:00-07:00",
                "end": "2026-02-19T10:00:00-07:00",
                "duration_minutes": 120,
                "date": "2026-02-19",
                "day_of_week": "Wednesday",
            },
        ]

        result = format_slots_for_sharing(slots, timezone_name="America/Denver")

        assert "Tuesday" in result
        assert "Wednesday" in result
        assert "Feb 18" in result or "February 18" in result
        assert "Feb 19" in result or "February 19" in result
        # Should be separate lines or sections for each day
        assert result.count("8:00") == 2 or result.count("08:00") == 2


# ---------------------------------------------------------------------------
# Error payload filtering tests
# ---------------------------------------------------------------------------


class TestFindSlotsErrorPayloadFiltering:
    def test_find_slots_error_payload_filtered(self):
        """Error payload dicts in events list are filtered out — returns full-day availability."""
        events = [{"error": "provider failed"}]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        # Error dict filtered out → full working day available
        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600

    def test_find_slots_error_payload_mixed_with_events(self):
        """Error dict mixed with valid events: error filtered, valid event still blocks."""
        events = [
            {"error": "Dual-read policy failed"},
            {
                "uid": "real-1",
                "title": "Real Meeting",
                "start": "2026-02-18T09:00:00-07:00",
                "end": "2026-02-18T10:00:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        # Real meeting 9-10 blocks time; error dict is filtered
        assert len(slots) == 2
        assert slots[0]["duration_minutes"] == 60   # 8-9 AM
        assert slots[1]["duration_minutes"] == 480   # 10 AM-6 PM


# ---------------------------------------------------------------------------
# Cancelled / declined / showAs filtering tests
# ---------------------------------------------------------------------------


class TestFindSlotsCancelledDeclinedShowAs:
    def test_find_slots_cancelled_event_skipped(self):
        """Event with is_cancelled=True should not block time."""
        events = [
            {
                "uid": "cancel-1",
                "title": "Cancelled Meeting",
                "start": "2026-02-18T09:00:00-07:00",
                "end": "2026-02-18T10:00:00-07:00",
                "is_all_day": False,
                "isCancelled": True,
                "attendees": [{"status": 2}],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600

    def test_find_slots_declined_event_skipped(self):
        """Event with responseStatus='declined' should not block time."""
        events = [
            {
                "uid": "decline-1",
                "title": "Declined Meeting",
                "start": "2026-02-18T09:00:00-07:00",
                "end": "2026-02-18T10:00:00-07:00",
                "is_all_day": False,
                "responseStatus": "declined",
                "attendees": [{"status": 2}],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600

    def test_find_slots_show_as_free_skipped(self):
        """Event with showAs='free' should not block time."""
        events = [
            {
                "uid": "free-1",
                "title": "Free Event",
                "start": "2026-02-18T09:00:00-07:00",
                "end": "2026-02-18T10:00:00-07:00",
                "is_all_day": False,
                "showAs": "free",
                "attendees": [{"status": 2}],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600

    def test_find_slots_show_as_busy_blocks(self):
        """Event with showAs='busy' blocks time normally."""
        events = [
            {
                "uid": "busy-1",
                "title": "Busy Event",
                "start": "2026-02-18T09:00:00-07:00",
                "end": "2026-02-18T10:00:00-07:00",
                "is_all_day": False,
                "showAs": "busy",
                "attendees": [{"status": 2}],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        # 9-10 blocked → 8-9 AM and 10 AM-6 PM
        assert len(slots) == 2
        assert slots[0]["duration_minutes"] == 60
        assert slots[1]["duration_minutes"] == 480


# ---------------------------------------------------------------------------
# User-scoped tentative classification tests
# ---------------------------------------------------------------------------


class TestClassifySoftnessUserScoped:
    def test_classify_softness_user_tentative(self):
        """User email matches a tentative attendee → soft."""
        event = {
            "uid": "tent-1",
            "title": "Team Sync",
            "start": "2026-02-18T10:00:00-07:00",
            "end": "2026-02-18T11:00:00-07:00",
            "attendees": [
                {"name": "Jason", "email": "jason@example.com", "status": 3},
                {"name": "Matt", "email": "matt@example.com", "status": 2},
            ],
            "is_all_day": False,
        }

        result = classify_event_softness(event, user_email="jason@example.com")

        assert result["is_soft"] is True
        assert "tentative" in result["reason"].lower()

    def test_classify_softness_other_tentative_not_user(self):
        """Another attendee is tentative but user accepted → NOT soft."""
        event = {
            "uid": "tent-2",
            "title": "Team Sync",
            "start": "2026-02-18T10:00:00-07:00",
            "end": "2026-02-18T11:00:00-07:00",
            "attendees": [
                {"name": "Jason", "email": "jason@example.com", "status": 2},  # accepted
                {"name": "Matt", "email": "matt@example.com", "status": 3},    # tentative
            ],
            "is_all_day": False,
        }

        result = classify_event_softness(event, user_email="jason@example.com")

        assert result["is_soft"] is False


# ---------------------------------------------------------------------------
# PTO/OOO all-day blocking tests
# ---------------------------------------------------------------------------


class TestFindSlotsOOOBlocking:
    def test_find_slots_ooo_all_day_blocks(self):
        """All-day PTO event with block_ooo_all_day=True blocks the entire day."""
        events = [
            {
                "uid": "pto-1",
                "title": "PTO",
                "start": "2026-02-18T00:00:00-07:00",
                "end": "2026-02-18T23:59:59-07:00",
                "is_all_day": True,
                "attendees": [],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
            block_ooo_all_day=True,
        )

        assert len(slots) == 0

    def test_find_slots_ooo_all_day_default_skipped(self):
        """All-day PTO event with default params should NOT block (backward compat)."""
        events = [
            {
                "uid": "pto-2",
                "title": "PTO",
                "start": "2026-02-18T00:00:00-07:00",
                "end": "2026-02-18T23:59:59-07:00",
                "is_all_day": True,
                "attendees": [],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
            # block_ooo_all_day defaults to False
        )

        # PTO all-day ignored by default → full working day
        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600


# ---------------------------------------------------------------------------
# Timezone and normalization tests
# ---------------------------------------------------------------------------


class TestNormalizeTimezoneAndFields:
    def test_normalize_m365_timezone_preserved(self):
        """M365 event with nested dateTime/timeZone has start_tz in normalized output."""
        event = {
            "id": "m365-tz-1",
            "subject": "UTC Meeting",
            "start": {"dateTime": "2026-02-18T16:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-02-18T17:00:00", "timeZone": "UTC"},
            "isAllDay": False,
        }

        result = normalize_event_for_scheduler(event)

        assert result["start_tz"] == "UTC"
        assert result["end_tz"] == "UTC"
        assert result["start"] == "2026-02-18T16:00:00"
        assert result["end"] == "2026-02-18T17:00:00"

    def test_find_slots_m365_utc_event_converted(self):
        """Event with naive datetime and start_tz=UTC placed at correct Mountain Time position."""
        # 4 PM UTC = 9 AM Mountain (MST = UTC-7)
        events = [
            {
                "id": "utc-1",
                "subject": "UTC Meeting",
                "start": {"dateTime": "2026-02-18T16:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-02-18T17:00:00", "timeZone": "UTC"},
                "isAllDay": False,
                "attendees": [
                    {
                        "emailAddress": {"name": "Jason", "address": "jason@example.com"},
                        "status": {"response": "accepted"},
                    }
                ],
            },
        ]

        start_date = datetime(2026, 2, 18, tzinfo=ZoneInfo("America/Denver"))
        end_date = datetime(2026, 2, 18, 23, 59, 59, tzinfo=ZoneInfo("America/Denver"))

        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name="America/Denver",
        )

        # 4-5 PM UTC = 9-10 AM Mountain → blocks 9-10 AM
        assert len(slots) == 2
        assert slots[0]["duration_minutes"] == 60   # 8-9 AM
        assert slots[1]["duration_minutes"] == 480   # 10 AM-6 PM

    def test_normalize_preserves_show_as(self):
        """showAs from input appears as show_as in normalized output."""
        event = {
            "uid": "show-1",
            "title": "Test",
            "start": "2026-02-18T09:00:00-07:00",
            "end": "2026-02-18T10:00:00-07:00",
            "showAs": "tentative",
        }

        result = normalize_event_for_scheduler(event)
        assert result["show_as"] == "tentative"

    def test_normalize_preserves_is_cancelled(self):
        """isCancelled from input appears as is_cancelled in normalized output."""
        event = {
            "uid": "cancel-n1",
            "title": "Cancelled",
            "start": "2026-02-18T09:00:00-07:00",
            "end": "2026-02-18T10:00:00-07:00",
            "isCancelled": True,
        }

        result = normalize_event_for_scheduler(event)
        assert result["is_cancelled"] is True

    def test_normalize_response_status_string(self):
        """responseStatus string mapped to response_status."""
        event = {
            "uid": "resp-1",
            "title": "Declined",
            "start": "2026-02-18T09:00:00-07:00",
            "end": "2026-02-18T10:00:00-07:00",
            "responseStatus": "declined",
        }

        result = normalize_event_for_scheduler(event)
        assert result["response_status"] == "declined"

    def test_normalize_response_status_dict(self):
        """responseStatus dict (M365 format) mapped to response_status string."""
        event = {
            "uid": "resp-2",
            "title": "Declined M365",
            "start": "2026-02-18T09:00:00-07:00",
            "end": "2026-02-18T10:00:00-07:00",
            "responseStatus": {"response": "declined"},
        }

        result = normalize_event_for_scheduler(event)
        assert result["response_status"] == "declined"


class TestOofShowAsBlocking:
    """Tests for showAs='oof' all-day event blocking."""

    def test_find_slots_ooo_show_as_oof_blocks(self):
        """showAs='oof' all-day event with block_ooo_all_day=True blocks the day."""
        events = [
            {
                "title": "PTO",
                "start": "2026-02-18",
                "end": "2026-02-19",
                "is_all_day": True,
                "showAs": "oof",
            }
        ]
        result = find_available_slots(
            events, "2026-02-18", "2026-02-18", 30, block_ooo_all_day=True
        )
        assert len(result) == 0

    def test_find_slots_ooo_show_as_oof_no_keyword_blocks(self):
        """showAs='oof' blocks even when title has no OOO keyword."""
        events = [
            {
                "title": "Personal Day",
                "start": "2026-02-18",
                "end": "2026-02-19",
                "is_all_day": True,
                "showAs": "oof",
            }
        ]
        result = find_available_slots(
            events, "2026-02-18", "2026-02-18", 30, block_ooo_all_day=True
        )
        assert len(result) == 0

    def test_find_slots_non_dict_event_filtered(self):
        """Non-dict events (strings, ints, None) are filtered without crashing."""
        events = [
            "not a dict", 42, None,
            {"title": "Real Meeting", "start": "2026-02-18T09:00:00-07:00", "end": "2026-02-18T10:00:00-07:00"},
        ]
        result = find_available_slots(events, "2026-02-18", "2026-02-18", 30)
        # Should not crash, and the real meeting should block 9-10
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Title-based cancelled detection tests
# ---------------------------------------------------------------------------


class TestTitleBasedCancelledDetection:
    def test_normalize_canceled_prefix_sets_is_cancelled(self):
        """Title starting with 'Canceled:' sets is_cancelled=True in normalized output."""
        event = {
            "uid": "cancel-title-1",
            "title": "Canceled: Security Touchpoint",
            "start": "2026-02-18T09:00:00-07:00",
            "end": "2026-02-18T10:00:00-07:00",
        }
        result = normalize_event_for_scheduler(event)
        assert result["is_cancelled"] is True

    def test_normalize_cancelled_prefix_british_spelling(self):
        """Title starting with 'Cancelled:' (British spelling) sets is_cancelled=True."""
        event = {
            "uid": "cancel-title-2",
            "title": "Cancelled: 1 on 1 with Shawn",
            "start": "2026-02-18T09:00:00-07:00",
            "end": "2026-02-18T10:00:00-07:00",
        }
        result = normalize_event_for_scheduler(event)
        assert result["is_cancelled"] is True

    def test_normalize_canceled_prefix_case_insensitive(self):
        """Title prefix detection is case-insensitive."""
        event = {
            "uid": "cancel-title-3",
            "title": "CANCELED: Team Meeting",
            "start": "2026-02-18T09:00:00-07:00",
            "end": "2026-02-18T10:00:00-07:00",
        }
        result = normalize_event_for_scheduler(event)
        assert result["is_cancelled"] is True

    def test_normalize_canceled_no_false_positive(self):
        """Title containing 'canceled' but not as prefix does NOT set is_cancelled."""
        event = {
            "uid": "cancel-title-4",
            "title": "Meeting about canceled projects",
            "start": "2026-02-18T09:00:00-07:00",
            "end": "2026-02-18T10:00:00-07:00",
        }
        result = normalize_event_for_scheduler(event)
        assert result["is_cancelled"] is False

    def test_normalize_is_cancelled_field_takes_precedence(self):
        """If isCancelled is already True, title check doesn't override."""
        event = {
            "uid": "cancel-title-5",
            "title": "Canceled: Meeting",
            "start": "2026-02-18T09:00:00-07:00",
            "end": "2026-02-18T10:00:00-07:00",
            "isCancelled": True,
        }
        result = normalize_event_for_scheduler(event)
        assert result["is_cancelled"] is True

    def test_find_slots_title_canceled_event_skipped(self):
        """Apple event with 'Canceled:' title prefix does not block time."""
        events = [
            {
                "uid": "apple-cancel-1",
                "title": "Canceled: Security Touchpoint",
                "start": "2026-02-18T09:00:00-07:00",
                "end": "2026-02-18T10:00:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],
                # No isCancelled field — simulates Apple EventKit behavior
            },
        ]

        slots = find_available_slots(
            events=events,
            start_date="2026-02-18",
            end_date="2026-02-18",
            duration_minutes=30,
        )

        # Cancelled event should NOT block time
        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600

    def test_find_slots_title_cancelled_british_skipped(self):
        """Apple event with 'Cancelled:' (British) title prefix does not block time."""
        events = [
            {
                "uid": "apple-cancel-2",
                "title": "Cancelled: 1 on 1 with Shawn",
                "start": "2026-02-18T09:00:00-07:00",
                "end": "2026-02-18T11:30:00-07:00",
                "is_all_day": False,
                "attendees": [{"status": 2}],
            },
        ]

        slots = find_available_slots(
            events=events,
            start_date="2026-02-18",
            end_date="2026-02-18",
            duration_minutes=30,
        )

        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600


# ---------------------------------------------------------------------------
# showAs=free exclusion tests (real-world scenarios)
# ---------------------------------------------------------------------------


class TestShowAsFreeRealWorld:
    def test_find_slots_personal_appointment_free_not_blocking(self):
        """M365 event with showAs=free (e.g., 'Phil - Personal Appointment') does not block."""
        events = [
            {
                "id": "m365-free-1",
                "subject": "Phil - Personal Appointment",
                "start": {"dateTime": "2026-02-18T10:00:00", "timeZone": "America/Denver"},
                "end": {"dateTime": "2026-02-18T12:30:00", "timeZone": "America/Denver"},
                "isAllDay": False,
                "showAs": "free",
                "attendees": [],
            },
        ]

        slots = find_available_slots(
            events=events,
            start_date="2026-02-18",
            end_date="2026-02-18",
            duration_minutes=30,
        )

        # showAs=free → should not block any time
        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600

    def test_find_slots_canceled_with_show_as_free_not_blocking(self):
        """Cancelled M365 event (isCancelled=True + showAs=free) doesn't block time."""
        events = [
            {
                "id": "m365-cancel-free-1",
                "subject": "Canceled: Security Touchpoint",
                "start": {"dateTime": "2026-02-18T14:00:00", "timeZone": "America/Denver"},
                "end": {"dateTime": "2026-02-18T14:30:00", "timeZone": "America/Denver"},
                "isAllDay": False,
                "showAs": "free",
                "isCancelled": True,
                "attendees": [
                    {"emailAddress": {"name": "Jason", "address": "jason@example.com"}, "status": {"response": "accepted"}},
                ],
            },
        ]

        slots = find_available_slots(
            events=events,
            start_date="2026-02-18",
            end_date="2026-02-18",
            duration_minutes=30,
        )

        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600


# ---------------------------------------------------------------------------
# showAs=tentative as soft block tests
# ---------------------------------------------------------------------------


class TestShowAsTentativeSoftBlock:
    def test_classify_show_as_tentative_is_soft(self):
        """Event with show_as='tentative' classified as soft block."""
        event = {
            "uid": "tent-show-1",
            "title": "Security Touchpoint",
            "start": "2026-02-18T14:00:00-07:00",
            "end": "2026-02-18T14:30:00-07:00",
            "show_as": "tentative",
            "attendees": [
                {"name": "Jason", "email": "jason@example.com", "status": 2},
            ],
            "is_all_day": False,
            "notes": "",
        }

        result = classify_event_softness(event)
        assert result["is_soft"] is True
        assert "tentative" in result["reason"].lower()
        assert result["confidence"] >= 0.7

    def test_classify_show_as_busy_not_soft(self):
        """Event with show_as='busy' is NOT classified as soft (no other indicators)."""
        event = {
            "uid": "busy-show-1",
            "title": "Security Touchpoint",
            "start": "2026-02-18T14:00:00-07:00",
            "end": "2026-02-18T14:30:00-07:00",
            "show_as": "busy",
            "attendees": [
                {"name": "Jason", "email": "jason@example.com", "status": 2},
            ],
            "is_all_day": False,
            "notes": "",
        }

        result = classify_event_softness(event)
        assert result["is_soft"] is False

    def test_find_slots_tentative_available_with_soft_blocks(self):
        """showAs=tentative event available when include_soft_blocks=True."""
        events = [
            {
                "uid": "tent-slot-1",
                "title": "SentinelOne | CHG Weekly Sync",
                "start": "2026-02-18T10:00:00-07:00",
                "end": "2026-02-18T11:00:00-07:00",
                "is_all_day": False,
                "showAs": "tentative",
                "attendees": [
                    {"name": "Jason", "email": "jason@example.com", "status": 2},
                ],
            },
        ]

        slots = find_available_slots(
            events=events,
            start_date="2026-02-18",
            end_date="2026-02-18",
            duration_minutes=30,
            include_soft_blocks=True,  # default
        )

        # Tentative event treated as soft → entire day available
        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 600

    def test_find_slots_tentative_blocks_without_soft_blocks(self):
        """showAs=tentative event blocks time when include_soft_blocks=False."""
        events = [
            {
                "uid": "tent-slot-2",
                "title": "IR Lesson's Learned",
                "start": "2026-02-18T10:00:00-07:00",
                "end": "2026-02-18T11:00:00-07:00",
                "is_all_day": False,
                "showAs": "tentative",
                "attendees": [
                    {"name": "Jason", "email": "jason@example.com", "status": 2},
                ],
            },
        ]

        slots = find_available_slots(
            events=events,
            start_date="2026-02-18",
            end_date="2026-02-18",
            duration_minutes=30,
            include_soft_blocks=False,
        )

        # Tentative is soft but soft blocks are excluded → blocks 10-11 AM
        assert len(slots) == 2
        assert slots[0]["duration_minutes"] == 120  # 8-10 AM
        assert slots[1]["duration_minutes"] == 420  # 11 AM-6 PM

    def test_find_slots_mixed_cancelled_free_tentative_busy(self):
        """Real-world mix: cancelled, free, tentative, and busy events."""
        events = [
            # Cancelled — should NOT block
            {
                "uid": "e1",
                "title": "Canceled: Security Touchpoint",
                "start": "2026-02-18T08:00:00-07:00",
                "end": "2026-02-18T08:30:00-07:00",
                "is_all_day": False,
                "showAs": "free",
                "isCancelled": True,
                "attendees": [],
            },
            # Free (informational) — should NOT block
            {
                "uid": "e2",
                "title": "Phil - Personal Appointment",
                "start": "2026-02-18T10:00:00-07:00",
                "end": "2026-02-18T12:30:00-07:00",
                "is_all_day": False,
                "showAs": "free",
                "attendees": [],
            },
            # Tentative — soft block (available with include_soft_blocks=True)
            {
                "uid": "e3",
                "title": "AI rollout steering committee",
                "start": "2026-02-18T13:00:00-07:00",
                "end": "2026-02-18T14:00:00-07:00",
                "is_all_day": False,
                "showAs": "tentative",
                "attendees": [{"name": "Jason", "email": "jason@example.com", "status": 2}],
            },
            # Busy — SHOULD block
            {
                "uid": "e4",
                "title": "1:1 with Manager",
                "start": "2026-02-18T15:00:00-07:00",
                "end": "2026-02-18T16:00:00-07:00",
                "is_all_day": False,
                "showAs": "busy",
                "attendees": [{"name": "Manager", "email": "manager@example.com", "status": 2}],
            },
        ]

        slots = find_available_slots(
            events=events,
            start_date="2026-02-18",
            end_date="2026-02-18",
            duration_minutes=30,
            include_soft_blocks=True,
        )

        # Only the busy 1:1 (15:00-16:00) blocks time
        # Expected: 8:00-15:00 (420 min) and 16:00-18:00 (120 min)
        assert len(slots) == 2
        assert slots[0]["duration_minutes"] == 420  # 8 AM - 3 PM
        assert slots[1]["duration_minutes"] == 120  # 4 PM - 6 PM

    def test_classify_show_as_tentative_takes_precedence_over_keywords(self):
        """showAs=tentative is checked before keyword scan — returns tentative reason."""
        event = {
            "uid": "tent-kw-1",
            "title": "Focus Time",
            "start": "2026-02-18T10:00:00-07:00",
            "end": "2026-02-18T11:00:00-07:00",
            "show_as": "tentative",
            "attendees": [],
            "is_all_day": False,
            "notes": "",
        }

        result = classify_event_softness(event)
        assert result["is_soft"] is True
        # Should match on tentative showAs, not keyword
        assert "tentative" in result["reason"].lower()
        assert "showas" in result["reason"].lower() or "showAs" in result["reason"]
