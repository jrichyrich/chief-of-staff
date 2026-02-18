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
