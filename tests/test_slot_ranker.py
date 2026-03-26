"""Tests for scheduler.slot_ranker — pure slot scoring function."""

import pytest

from scheduler.slot_ranker import rank_slots


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slot(start: str, end: str, duration: int, date: str, dow: str) -> dict:
    """Build a slot dict with Denver offset."""
    return {
        "start": start,
        "end": end,
        "duration_minutes": duration,
        "date": date,
        "day_of_week": dow,
    }


def _event(start: str, end: str, title: str = "Meeting") -> dict:
    return {"start": start, "end": end, "title": title}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSlotRanker:

    def test_rank_empty_slots(self):
        """Empty input returns empty list."""
        result = rank_slots([], [], preferred_times="morning")
        assert result == []

    def test_rank_preferred_morning(self):
        """Morning slots score higher with preferred_times='morning'."""
        morning_slot = _slot(
            "2026-03-23T09:00:00-06:00", "2026-03-23T10:00:00-06:00",
            60, "2026-03-23", "Monday",
        )
        afternoon_slot = _slot(
            "2026-03-23T14:00:00-06:00", "2026-03-23T15:00:00-06:00",
            60, "2026-03-23", "Monday",
        )
        result = rank_slots(
            [afternoon_slot, morning_slot], [], preferred_times="morning"
        )
        # Morning slot should be ranked first
        assert result[0]["start"] == morning_slot["start"]
        assert result[0]["score"] > result[1]["score"]

    def test_rank_preferred_afternoon(self):
        """Afternoon slots score higher with preferred_times='afternoon'."""
        morning_slot = _slot(
            "2026-03-23T09:00:00-06:00", "2026-03-23T10:00:00-06:00",
            60, "2026-03-23", "Monday",
        )
        afternoon_slot = _slot(
            "2026-03-23T14:00:00-06:00", "2026-03-23T15:00:00-06:00",
            60, "2026-03-23", "Monday",
        )
        result = rank_slots(
            [morning_slot, afternoon_slot], [], preferred_times="afternoon"
        )
        assert result[0]["start"] == afternoon_slot["start"]
        assert result[0]["score"] > result[1]["score"]

    def test_rank_preferred_custom_range(self):
        """Custom '10:00-12:00' boosts 10am slot over 8am slot."""
        early_slot = _slot(
            "2026-03-23T08:00:00-06:00", "2026-03-23T09:00:00-06:00",
            60, "2026-03-23", "Monday",
        )
        target_slot = _slot(
            "2026-03-23T10:00:00-06:00", "2026-03-23T11:00:00-06:00",
            60, "2026-03-23", "Monday",
        )
        result = rank_slots(
            [early_slot, target_slot], [], preferred_times="10:00-12:00"
        )
        assert result[0]["start"] == target_slot["start"]

    def test_rank_back_to_back_penalty(self):
        """Slot adjacent to existing event scores lower than isolated slot."""
        # This event ends right when slot_a starts → back-to-back
        existing_event = _event(
            "2026-03-23T08:00:00-06:00", "2026-03-23T09:00:00-06:00",
            "Standup",
        )
        # Slot A starts at 9:00 — immediately after existing event
        slot_a = _slot(
            "2026-03-23T09:00:00-06:00", "2026-03-23T10:00:00-06:00",
            60, "2026-03-23", "Monday",
        )
        # Slot B at 14:00 — far from any event
        slot_b = _slot(
            "2026-03-23T14:00:00-06:00", "2026-03-23T15:00:00-06:00",
            60, "2026-03-23", "Monday",
        )
        result = rank_slots([slot_a, slot_b], [existing_event])
        # slot_b should score higher due to no back-to-back penalty
        scores = {r["start"]: r["score"] for r in result}
        assert scores[slot_b["start"]] > scores[slot_a["start"]]

    def test_rank_mid_morning_bonus(self):
        """9:30am slot scores higher than 8:00am on mid-morning signal."""
        early_slot = _slot(
            "2026-03-23T08:00:00-06:00", "2026-03-23T09:00:00-06:00",
            60, "2026-03-23", "Monday",
        )
        mid_morning_slot = _slot(
            "2026-03-23T09:30:00-06:00", "2026-03-23T10:30:00-06:00",
            60, "2026-03-23", "Monday",
        )
        # No preferred_times so that signal is neutral for both
        result = rank_slots([early_slot, mid_morning_slot], [])
        scores = {r["start"]: r["score"] for r in result}
        assert scores[mid_morning_slot["start"]] > scores[early_slot["start"]]

    def test_rank_day_proximity(self):
        """Earlier day scores higher than later day (all else equal)."""
        monday_slot = _slot(
            "2026-03-23T10:00:00-06:00", "2026-03-23T11:00:00-06:00",
            60, "2026-03-23", "Monday",
        )
        wednesday_slot = _slot(
            "2026-03-25T10:00:00-06:00", "2026-03-25T11:00:00-06:00",
            60, "2026-03-25", "Wednesday",
        )
        friday_slot = _slot(
            "2026-03-27T10:00:00-06:00", "2026-03-27T11:00:00-06:00",
            60, "2026-03-27", "Friday",
        )
        result = rank_slots(
            [friday_slot, monday_slot, wednesday_slot], []
        )
        # Monday should rank first, then Wednesday, then Friday
        assert result[0]["start"] == monday_slot["start"]
        assert result[1]["start"] == wednesday_slot["start"]
        assert result[2]["start"] == friday_slot["start"]

    def test_rank_buffer_room(self):
        """Wider slot (90 min) scores higher than narrow slot (30 min)."""
        narrow_slot = _slot(
            "2026-03-23T10:00:00-06:00", "2026-03-23T10:30:00-06:00",
            30, "2026-03-23", "Monday",
        )
        wide_slot = _slot(
            "2026-03-23T10:00:00-06:00", "2026-03-23T11:30:00-06:00",
            90, "2026-03-23", "Monday",
        )
        result = rank_slots([narrow_slot, wide_slot], [])
        scores = {r["duration_minutes"]: r["score"] for r in result}
        assert scores[90] > scores[30]

    def test_rank_overall_ordering(self):
        """Composite score produces expected ranking across mixed signals."""
        # Best: mid-morning, wide buffer, morning preferred, earliest day
        best_slot = _slot(
            "2026-03-23T09:30:00-06:00", "2026-03-23T11:00:00-06:00",
            90, "2026-03-23", "Monday",
        )
        # Medium: afternoon, moderate buffer, later day
        mid_slot = _slot(
            "2026-03-24T14:00:00-06:00", "2026-03-24T15:00:00-06:00",
            60, "2026-03-24", "Tuesday",
        )
        # Worst: early morning, narrow, latest day, back-to-back
        worst_slot = _slot(
            "2026-03-25T07:30:00-06:00", "2026-03-25T08:00:00-06:00",
            30, "2026-03-25", "Wednesday",
        )
        existing = _event(
            "2026-03-25T08:00:00-06:00", "2026-03-25T09:00:00-06:00",
            "Standup",
        )
        result = rank_slots(
            [worst_slot, mid_slot, best_slot],
            [existing],
            preferred_times="morning",
        )
        assert result[0]["start"] == best_slot["start"]
        assert result[-1]["start"] == worst_slot["start"]

    def test_rank_score_range(self):
        """All scores are between 0.0 and 1.0."""
        slots = [
            _slot(
                "2026-03-23T06:00:00-06:00", "2026-03-23T06:30:00-06:00",
                30, "2026-03-23", "Monday",
            ),
            _slot(
                "2026-03-23T10:00:00-06:00", "2026-03-23T11:30:00-06:00",
                90, "2026-03-23", "Monday",
            ),
            _slot(
                "2026-03-27T19:00:00-06:00", "2026-03-27T20:00:00-06:00",
                60, "2026-03-27", "Friday",
            ),
        ]
        events = [
            _event("2026-03-23T06:30:00-06:00", "2026-03-23T07:00:00-06:00"),
        ]
        result = rank_slots(slots, events, preferred_times="morning")
        for s in result:
            assert 0.0 <= s["score"] <= 1.0, f"Score {s['score']} out of range"
