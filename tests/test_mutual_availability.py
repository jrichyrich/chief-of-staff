"""Tests for find_mutual_availability() in scheduler/availability.py."""

import pytest
from datetime import time

from scheduler.availability import find_mutual_availability


TZ = "America/Denver"
# Week of 2026-03-23 (Mon) to 2026-03-27 (Fri)
MON = "2026-03-23"
TUE = "2026-03-24"
WED = "2026-03-25"
THU = "2026-03-26"
FRI = "2026-03-27"
SAT = "2026-03-28"
SUN = "2026-03-29"


def _event(title: str, start: str, end: str, **kwargs) -> dict:
    """Helper to build a calendar event dict."""
    ev = {"title": title, "start": start, "end": end}
    ev.update(kwargs)
    return ev


def _schedule(email: str, items: list[dict]) -> dict:
    """Helper to build a Graph getSchedule response for one person."""
    return {"email": email, "availability_view": "", "schedule_items": items}


def _busy(start: str, end: str, status: str = "busy") -> dict:
    return {"status": status, "start": start, "end": end}


class TestMutualAvailability:
    """Tests for find_mutual_availability."""

    def test_mutual_no_overlap(self):
        """You have a slot 9-12, other person is busy 9-12 -> zero mutual slots."""
        # You are free all morning (no events blocks 9-12)
        my_events = []
        others = [
            _schedule("alice@example.com", [
                _busy(f"{MON}T09:00:00", f"{MON}T12:00:00"),
            ]),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=MON,
            end_date=MON,
            duration_minutes=30,
            working_hours_start=time(9, 0),
            working_hours_end=time(12, 0),
            timezone_name=TZ,
        )
        assert len(result) == 0

    def test_mutual_partial_overlap(self):
        """You have 8-18 free, other busy 10-11 -> slots before and after."""
        my_events = []
        others = [
            _schedule("bob@example.com", [
                _busy(f"{MON}T10:00:00", f"{MON}T11:00:00"),
            ]),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=MON,
            end_date=MON,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
        )
        # Should have slot before (8-10) and after (11-18) the busy block
        assert len(result) == 2
        # First slot: 8:00 - 10:00
        assert "08:00:00" in result[0]["start"]
        assert "10:00:00" in result[0]["end"]
        # Second slot: 11:00 - 18:00
        assert "11:00:00" in result[1]["start"]
        assert "18:00:00" in result[1]["end"]

    def test_mutual_full_day_free(self):
        """Both you and other person have no events -> full working day available."""
        my_events = []
        others = [
            _schedule("carol@example.com", []),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=MON,
            end_date=MON,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
            user_email="me@example.com",
        )
        assert len(result) == 1
        assert result[0]["duration_minutes"] == 600  # 10 hours
        assert "me@example.com" in result[0]["available_for"]
        assert "carol@example.com" in result[0]["available_for"]

    def test_mutual_weekend_skipping(self):
        """Saturday slot is removed when skip_weekends=True."""
        my_events = []
        others = [
            _schedule("dan@example.com", []),
        ]
        # Range includes Saturday (2026-03-28)
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=FRI,
            end_date=SAT,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
            skip_weekends=True,
        )
        # Should only have Friday, not Saturday
        dates = [s["date"] for s in result]
        assert FRI in dates
        assert SAT not in dates

    def test_mutual_weekend_not_skipped(self):
        """Saturday slot is kept when skip_weekends=False."""
        my_events = []
        others = [
            _schedule("dan@example.com", []),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=FRI,
            end_date=SAT,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
            skip_weekends=False,
        )
        dates = [s["date"] for s in result]
        assert FRI in dates
        assert SAT in dates

    def test_mutual_one_person_fully_booked(self):
        """One person busy all day -> zero slots for that day."""
        my_events = []
        others = [
            _schedule("eve@example.com", [
                _busy(f"{MON}T08:00:00", f"{MON}T18:00:00"),
            ]),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=MON,
            end_date=MON,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
        )
        assert len(result) == 0

    def test_mutual_soft_blocks_your_side(self):
        """Your Focus Time (soft block) still shows as available."""
        my_events = [
            _event("Focus Time", f"{MON}T09:00:00-06:00", f"{MON}T11:00:00-06:00"),
        ]
        others = [
            _schedule("frank@example.com", []),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=MON,
            end_date=MON,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
            include_soft_blocks=True,
        )
        # Focus Time is soft -> treated as available -> full day slot
        assert len(result) == 1
        assert result[0]["duration_minutes"] == 600

    def test_mutual_others_tentative_is_busy(self):
        """Other person's tentative status is treated as busy."""
        my_events = []
        others = [
            _schedule("grace@example.com", [
                _busy(f"{MON}T14:00:00", f"{MON}T15:00:00", status="tentative"),
            ]),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=MON,
            end_date=MON,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
        )
        # Tentative blocks 14-15, so we get 8-14 and 15-18
        assert len(result) == 2
        assert "14:00:00" in result[0]["end"]
        assert "15:00:00" in result[1]["start"]

    def test_mutual_multiple_others(self):
        """3 other people, only slots where ALL are free are returned."""
        my_events = []
        others = [
            _schedule("p1@example.com", [
                _busy(f"{MON}T09:00:00", f"{MON}T10:00:00"),
            ]),
            _schedule("p2@example.com", [
                _busy(f"{MON}T11:00:00", f"{MON}T12:00:00"),
            ]),
            _schedule("p3@example.com", [
                _busy(f"{MON}T14:00:00", f"{MON}T15:00:00"),
            ]),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=MON,
            end_date=MON,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
            user_email="me@example.com",
        )
        # Your free: 8-18 (full day)
        # p1 busy 9-10, p2 busy 11-12, p3 busy 14-15
        # Mutual free windows: 8-9, 10-11, 12-14, 15-18
        assert len(result) == 4
        # Verify all participants in available_for for each slot
        for slot in result:
            assert "me@example.com" in slot["available_for"]
            assert "p1@example.com" in slot["available_for"]
            assert "p2@example.com" in slot["available_for"]
            assert "p3@example.com" in slot["available_for"]

    def test_mutual_others_oof_is_busy(self):
        """Other person OOF blocks the slot."""
        my_events = []
        others = [
            _schedule("henry@example.com", [
                _busy(f"{MON}T08:00:00", f"{MON}T18:00:00", status="oof"),
            ]),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=MON,
            end_date=MON,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
        )
        assert len(result) == 0

    def test_soft_blocks_blocked_when_disabled(self):
        """Your Focus Time blocks the slot when include_soft_blocks=False."""
        my_events = [
            _event("Focus Time", f"{MON}T09:00:00-06:00", f"{MON}T11:00:00-06:00"),
        ]
        others = [
            _schedule("frank@example.com", []),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=MON,
            end_date=MON,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
            include_soft_blocks=False,
        )
        # Focus Time is now hard-blocked -> two windows around it
        assert len(result) == 2
        assert "08:00:00" in result[0]["start"]
        assert "09:00:00" in result[0]["end"]
        assert "11:00:00" in result[1]["start"]
        assert "18:00:00" in result[1]["end"]

    def test_all_soft_keyword_variants(self):
        """All common soft-block keywords are recognized and treated as available."""
        keywords_to_test = [
            "Focus Time",
            "Focus",
            "Heads Down",
            "Prep",
            "Hold",
            "Placeholder",
            "Lunch",
            "Tentative meeting",
        ]
        for keyword in keywords_to_test:
            my_events = [
                _event(keyword, f"{MON}T10:00:00-06:00", f"{MON}T11:00:00-06:00"),
            ]
            others = [_schedule("test@example.com", [])]
            result = find_mutual_availability(
                my_events=my_events,
                others_schedules=others,
                start_date=MON,
                end_date=MON,
                duration_minutes=30,
                working_hours_start=time(8, 0),
                working_hours_end=time(18, 0),
                timezone_name=TZ,
                include_soft_blocks=True,
            )
            # Every soft keyword should yield full day (event treated as available)
            assert len(result) == 1, f"Keyword '{keyword}' was not treated as soft block"
            assert result[0]["duration_minutes"] == 600, f"Keyword '{keyword}' blocked time"

    def test_mutual_working_elsewhere_is_free(self):
        """Other person 'workingElsewhere' is treated as free."""
        my_events = []
        others = [
            _schedule("irene@example.com", [
                # workingElsewhere should NOT block the slot
                {"status": "workingElsewhere", "start": f"{MON}T09:00:00", "end": f"{MON}T17:00:00"},
            ]),
        ]
        result = find_mutual_availability(
            my_events=my_events,
            others_schedules=others,
            start_date=MON,
            end_date=MON,
            duration_minutes=30,
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            timezone_name=TZ,
        )
        # workingElsewhere is free -> full day available
        assert len(result) == 1
        assert result[0]["duration_minutes"] == 600
