"""Slot ranking for scheduling suggestions."""

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from config import USER_TIMEZONE

# Scoring weights
W_PREFERRED = 0.30
W_BACK_TO_BACK = 0.25
W_MID_DAY = 0.20
W_PROXIMITY = 0.15
W_BUFFER = 0.10

# Named time ranges
_NAMED_RANGES: dict[str, tuple[time, time]] = {
    "morning": (time(8, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
}

# Back-to-back threshold
_B2B_THRESHOLD = timedelta(minutes=15)

# Custom range pattern: "HH:MM-HH:MM"
_CUSTOM_RANGE_RE = re.compile(r"^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})$")


def rank_slots(
    slots: list[dict],
    my_events: list[dict],
    preferred_times: str = "",
    timezone_name: str = USER_TIMEZONE,
) -> list[dict]:
    """Score and rank available time slots for meeting scheduling.

    Scoring signals (0.0-1.0 weighted sum):
    - Preferred time match (0.30): "morning" = 8-12, "afternoon" = 12-17,
      or custom "HH:MM-HH:MM" range
    - Back-to-back avoidance (0.25): Penalize slots within 15min of another event
    - Mid-morning/afternoon bonus (0.20): 9:30-11:00 and 13:30-15:00 score highest
    - Day proximity (0.15): Slight preference for sooner dates
    - Buffer room (0.10): Prefer slots with breathing room over exact-fit gaps

    Args:
        slots: List of slot dicts from find_available_slots/find_mutual_availability.
            Each has: start (ISO), end (ISO), duration_minutes, date, day_of_week
        my_events: Your calendar events for context (back-to-back detection).
            Each has at minimum: start (ISO), end (ISO)
        preferred_times: "morning", "afternoon", or "HH:MM-HH:MM" (optional)
        timezone_name: IANA timezone (default: America/Denver)

    Returns:
        Input list sorted by score descending, each with added 'score' field (0.0-1.0).
    """
    if not slots:
        return []

    tz = ZoneInfo(timezone_name)

    # Parse preferred time range
    pref_range = _parse_preferred_range(preferred_times)

    # Parse event datetimes once for back-to-back checks
    event_times = _parse_event_times(my_events, tz)

    # Compute day span for proximity scoring
    slot_dates = []
    for s in slots:
        dt = _parse_iso(s["start"], tz)
        slot_dates.append(dt.date())
    min_date = min(slot_dates)
    max_date = max(slot_dates)
    day_span = (max_date - min_date).days

    scored = []
    for slot, slot_date in zip(slots, slot_dates):
        start_dt = _parse_iso(slot["start"], tz)
        end_dt = _parse_iso(slot["end"], tz)
        start_time = start_dt.time()
        duration = slot.get("duration_minutes", 0)

        # 1. Preferred time match
        pref_score = _score_preferred(start_time, pref_range)

        # 2. Back-to-back avoidance
        b2b_score = _score_back_to_back(start_dt, end_dt, event_times)

        # 3. Mid-morning/afternoon bonus
        mid_score = _score_mid_day(start_time)

        # 4. Day proximity
        prox_score = _score_proximity(slot_date, min_date, day_span)

        # 5. Buffer room
        buf_score = _score_buffer(duration)

        total = (
            W_PREFERRED * pref_score
            + W_BACK_TO_BACK * b2b_score
            + W_MID_DAY * mid_score
            + W_PROXIMITY * prox_score
            + W_BUFFER * buf_score
        )

        slot_copy = dict(slot)
        slot_copy["score"] = round(total, 4)
        scored.append(slot_copy)

    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored


def _parse_preferred_range(
    preferred_times: str,
) -> tuple[time, time] | None:
    """Parse preferred_times string into a (start, end) time tuple or None."""
    if not preferred_times:
        return None

    cleaned = preferred_times.strip().lower()
    if cleaned in _NAMED_RANGES:
        return _NAMED_RANGES[cleaned]

    m = _CUSTOM_RANGE_RE.match(cleaned)
    if m:
        parts_start = m.group(1).split(":")
        parts_end = m.group(2).split(":")
        return (
            time(int(parts_start[0]), int(parts_start[1])),
            time(int(parts_end[0]), int(parts_end[1])),
        )

    return None


def _parse_iso(iso_str: str, tz: ZoneInfo) -> datetime:
    """Parse an ISO datetime string, applying tz if naive."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def _parse_event_times(
    events: list[dict], tz: ZoneInfo
) -> list[tuple[datetime, datetime]]:
    """Parse event start/end times into datetime pairs."""
    result = []
    for ev in events:
        start_str = ev.get("start", "")
        end_str = ev.get("end", "")
        if not start_str or not end_str:
            continue
        result.append((_parse_iso(start_str, tz), _parse_iso(end_str, tz)))
    return result


def _score_preferred(
    start_time: time, pref_range: tuple[time, time] | None
) -> float:
    """Score preferred time match. Returns 0.5 if no preference set."""
    if pref_range is None:
        return 0.5
    lo, hi = pref_range
    if lo <= start_time < hi:
        return 1.0
    return 0.0


def _score_back_to_back(
    slot_start: datetime,
    slot_end: datetime,
    event_times: list[tuple[datetime, datetime]],
) -> float:
    """Score back-to-back avoidance. 1.0 = no adjacent events, 0.2 = adjacent."""
    for ev_start, ev_end in event_times:
        # Check if any event boundary is within threshold of slot boundary
        if (
            abs(slot_start - ev_end) < _B2B_THRESHOLD
            or abs(ev_start - slot_end) < _B2B_THRESHOLD
            or abs(slot_start - ev_start) < _B2B_THRESHOLD
            or abs(slot_end - ev_end) < _B2B_THRESHOLD
        ):
            return 0.2
    return 1.0


def _score_mid_day(start_time: time) -> float:
    """Score mid-morning/afternoon preference."""
    # Prime windows
    if time(9, 30) <= start_time < time(11, 0):
        return 1.0
    if time(13, 30) <= start_time < time(15, 0):
        return 1.0
    # Decent windows
    if time(8, 0) <= start_time < time(9, 30):
        return 0.5
    if time(11, 0) <= start_time < time(12, 0):
        return 0.5
    if time(15, 0) <= start_time < time(17, 0):
        return 0.5
    # Outside business hours
    return 0.0


def _score_proximity(
    slot_date, min_date, day_span: int
) -> float:
    """Score day proximity. Earlier dates score higher."""
    if day_span == 0:
        return 1.0
    days_from_first = (slot_date - min_date).days
    return 1.0 - (days_from_first / day_span)


def _score_buffer(duration_minutes: int | float) -> float:
    """Score buffer room based on slot duration.

    Assumes the 'minimum needed' is whatever the slot duration is minus extra room.
    Since we don't know the requested meeting length, we use heuristics:
    - <=30 min slots are tight (0.3)
    - 30-60 min slots are moderate (linear 0.3-1.0)
    - 60+ min slots have plenty of buffer (1.0)
    """
    if duration_minutes <= 30:
        return 0.3
    if duration_minutes >= 60:
        return 1.0
    # Linear interpolation between 30 and 60
    return 0.3 + 0.7 * ((duration_minutes - 30) / 30)
