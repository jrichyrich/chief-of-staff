"""Availability analysis for finding open calendar slots."""

from datetime import datetime, time, timedelta
from typing import Union
from zoneinfo import ZoneInfo


def normalize_event_for_scheduler(event: dict) -> dict:
    """Normalize events from Apple Calendar or M365 to a consistent format.

    Handles field name differences defensively:
    - uid/native_id/unified_uid
    - title/subject
    - Apple attendees vs M365 attendees
    - Apple status==3 (tentative) vs M365 responseStatus

    Args:
        event: Raw event dict from CalendarStore or M365 bridge

    Returns:
        Normalized dict with: uid, title, start, end, calendar, provider,
        is_all_day, attendees, location, notes
    """
    # UID normalization
    uid = (
        event.get("uid")
        or event.get("native_id")
        or event.get("unified_uid")
        or event.get("id")
        or ""
    )

    # Title normalization
    title = event.get("title") or event.get("subject") or ""

    # Time normalization — handle M365 nested {"dateTime": ..., "timeZone": ...}
    start = event.get("start") or ""
    if isinstance(start, dict):
        start = start.get("dateTime") or ""
    end = event.get("end") or ""
    if isinstance(end, dict):
        end = end.get("dateTime") or ""

    # Calendar/provider normalization
    calendar = event.get("calendar") or ""
    provider = event.get("provider") or ""

    # All-day normalization
    is_all_day = event.get("is_all_day") or event.get("isAllDay") or False

    # Attendees normalization - Apple vs M365 format
    raw_attendees = event.get("attendees") or []
    attendees = []
    if raw_attendees:
        for a in raw_attendees:
            if isinstance(a, dict):
                if "emailAddress" in a:
                    # M365 nested format: {emailAddress: {name, address}, status: {response}}
                    email_info = a["emailAddress"]
                    status_info = a.get("status") or {}
                    attendees.append({
                        "name": email_info.get("name"),
                        "email": email_info.get("address"),
                        "status": None,
                        "responseStatus": status_info.get("response"),
                    })
                else:
                    # Apple format: {name, email, status}
                    attendees.append(a)
            elif isinstance(a, str):
                # M365 simple format: list of email strings
                attendees.append({"email": a, "name": None, "status": None})

    # Location normalization — handle M365 nested {"displayName": ...}
    location = event.get("location") or ""
    if isinstance(location, dict):
        location = location.get("displayName") or ""

    # Notes normalization — handle M365 nested {"content": ...}
    notes = event.get("notes") or event.get("description") or ""
    if isinstance(notes, dict):
        notes = notes.get("content") or ""
    if not notes:
        body = event.get("body")
        if isinstance(body, dict):
            notes = body.get("content") or ""

    return {
        "uid": uid,
        "title": title,
        "start": start,
        "end": end,
        "calendar": calendar,
        "provider": provider,
        "is_all_day": is_all_day,
        "attendees": attendees,
        "location": location,
        "notes": notes,
    }


def classify_event_softness(
    event: dict, soft_keywords: list[str] | None = None
) -> dict:
    """Classify whether an event is 'soft' (movable) or 'hard' (fixed).

    Default soft keywords: focus, focus time, lunch, heads down, prep, hold,
    tentative, placeholder.

    Soft block criteria:
    - Title or notes contain soft keywords
    - Attendee status is tentative (Apple: status==3, M365: responseStatus)
    - Solo event with no attendees + focus/hold/prep keywords

    Args:
        event: Normalized event dict from normalize_event_for_scheduler
        soft_keywords: Custom keyword list (optional)

    Returns:
        {is_soft: bool, reason: str, confidence: float}
    """
    if soft_keywords is None:
        soft_keywords = [
            "focus",
            "focus time",
            "lunch",
            "heads down",
            "prep",
            "hold",
            "tentative",
            "placeholder",
        ]

    title = (event.get("title") or "").lower()
    notes = (event.get("notes") or "").lower()
    attendees = event.get("attendees") or []

    # Check title and notes for keywords
    for keyword in soft_keywords:
        if keyword.lower() in title or keyword.lower() in notes:
            # Solo event + soft keyword = high confidence soft block
            if not attendees:
                return {
                    "is_soft": True,
                    "reason": f"Solo event with '{keyword}' keyword",
                    "confidence": 0.9,
                }
            # Multi-attendee with soft keyword = medium confidence
            return {
                "is_soft": True,
                "reason": f"Contains '{keyword}' keyword",
                "confidence": 0.7,
            }

    # Check attendee status for tentative responses
    for attendee in attendees:
        status = attendee.get("status")
        # Apple: status==3 is tentative
        if status == 3:
            return {
                "is_soft": True,
                "reason": "Attendee marked tentative",
                "confidence": 0.8,
            }
        # M365: responseStatus field
        response_status = attendee.get("responseStatus")
        if response_status and "tentative" in str(response_status).lower():
            return {
                "is_soft": True,
                "reason": "Attendee marked tentative",
                "confidence": 0.8,
            }

    # Default: hard block
    return {
        "is_soft": False,
        "reason": "No soft indicators found",
        "confidence": 1.0,
    }


def find_available_slots(
    events: list[dict],
    start_date: Union[str, datetime],
    end_date: Union[str, datetime],
    duration_minutes: int,
    working_hours_start: time = time(8, 0),
    working_hours_end: time = time(18, 0),
    timezone_name: str = "America/Denver",
    include_soft_blocks: bool = True,
    soft_keywords: list[str] | None = None,
) -> list[dict]:
    """Find available time slots in a date range, excluding hard calendar blocks.

    For each day in range:
    1. Compute working window (working_hours_start to working_hours_end)
    2. Normalize all events, classify soft/hard
    3. If include_soft_blocks=True, treat soft blocks as available
    4. Skip all-day events and zero-duration events
    5. Compute gaps between hard blocks within working hours
    6. Filter gaps by minimum duration_minutes

    Args:
        events: List of event dicts (from CalendarStore or M365)
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)
        duration_minutes: Minimum slot duration to return
        working_hours_start: Daily start time (default: 8:00 AM)
        working_hours_end: Daily end time (default: 6:00 PM)
        timezone_name: Timezone name (default: America/Denver)
        include_soft_blocks: Treat soft blocks as available (default: True)
        soft_keywords: Custom soft keyword list (optional)

    Returns:
        List of dicts: [{start: ISO str, end: ISO str, duration_minutes: int,
                         date: YYYY-MM-DD, day_of_week: str}, ...]
    """
    tz = ZoneInfo(timezone_name)

    # Parse date range — accept both str and datetime
    if isinstance(start_date, datetime):
        start_dt = start_date
    else:
        start_dt = datetime.fromisoformat(start_date)
    if isinstance(end_date, datetime):
        end_dt = end_date
    else:
        end_dt = datetime.fromisoformat(end_date)

    # Ensure dates are timezone-aware
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tz)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=tz)

    # Normalize and classify all events
    normalized_events = []
    for event in events:
        normalized = normalize_event_for_scheduler(event)
        classification = classify_event_softness(normalized, soft_keywords)
        normalized["_softness"] = classification
        normalized_events.append(normalized)

    # Iterate over each day in range
    available_slots = []
    current_date = start_dt.date()
    end_only_date = end_dt.date()

    while current_date <= end_only_date:
        # Define working window for this day
        day_start = datetime.combine(current_date, working_hours_start, tzinfo=tz)
        day_end = datetime.combine(current_date, working_hours_end, tzinfo=tz)

        # Collect hard blocks for this day
        hard_blocks = []
        for event in normalized_events:
            # Skip events we should treat as available
            if include_soft_blocks and event["_softness"]["is_soft"]:
                continue

            # Skip all-day events
            if event.get("is_all_day"):
                continue

            # Parse event times
            event_start_str = event.get("start")
            event_end_str = event.get("end")
            if not event_start_str or not event_end_str:
                continue

            try:
                event_start = datetime.fromisoformat(event_start_str)
                event_end = datetime.fromisoformat(event_end_str)
            except (ValueError, TypeError):
                continue

            # Handle naive datetimes
            if event_start.tzinfo is None:
                event_start = event_start.replace(tzinfo=tz)
            if event_end.tzinfo is None:
                event_end = event_end.replace(tzinfo=tz)

            # Convert to user timezone
            event_start = event_start.astimezone(tz)
            event_end = event_end.astimezone(tz)

            # Skip zero-duration events
            if event_start >= event_end:
                continue

            # Check if event overlaps this day's working window
            if event_end <= day_start or event_start >= day_end:
                continue

            # Clip event to working window
            block_start = max(event_start, day_start)
            block_end = min(event_end, day_end)

            hard_blocks.append((block_start, block_end))

        # Sort hard blocks by start time
        hard_blocks.sort(key=lambda x: x[0])

        # Merge overlapping blocks
        merged_blocks = []
        for block_start, block_end in hard_blocks:
            if merged_blocks and block_start <= merged_blocks[-1][1]:
                # Overlapping or adjacent - merge
                merged_blocks[-1] = (
                    merged_blocks[-1][0],
                    max(merged_blocks[-1][1], block_end),
                )
            else:
                merged_blocks.append((block_start, block_end))

        # Compute gaps between hard blocks
        gaps = []
        current_gap_start = day_start
        for block_start, block_end in merged_blocks:
            if current_gap_start < block_start:
                gaps.append((current_gap_start, block_start))
            current_gap_start = max(current_gap_start, block_end)

        # Final gap from last block to day_end
        if current_gap_start < day_end:
            gaps.append((current_gap_start, day_end))

        # Filter gaps by minimum duration
        for gap_start, gap_end in gaps:
            gap_duration = int((gap_end - gap_start).total_seconds() / 60)
            if gap_duration >= duration_minutes:
                available_slots.append(
                    {
                        "start": gap_start.isoformat(),
                        "end": gap_end.isoformat(),
                        "duration_minutes": gap_duration,
                        "date": current_date.isoformat(),
                        "day_of_week": current_date.strftime("%A"),
                    }
                )

        # Move to next day
        current_date += timedelta(days=1)

    return available_slots


def format_slots_for_sharing(
    slots: list[dict], timezone_name: str = "America/Denver"
) -> str:
    """Format available slots as human-readable text for sharing.

    Groups by date and formats as:
    "Wednesday, Feb 18: 8:00-10:00 AM, 11:00 AM-12:00 PM MT"

    Args:
        slots: List of slot dicts from find_available_slots
        timezone_name: Timezone name (default: America/Denver)

    Returns:
        Formatted string with slots grouped by date
    """
    if not slots:
        return "No available slots found."

    tz = ZoneInfo(timezone_name)

    # Group slots by date
    slots_by_date = {}
    for slot in slots:
        date_key = slot["date"]
        if date_key not in slots_by_date:
            slots_by_date[date_key] = []
        slots_by_date[date_key].append(slot)

    # Format each date group
    lines = []
    for date_key in sorted(slots_by_date.keys()):
        date_slots = slots_by_date[date_key]
        # Parse first slot to get day name
        first_slot = date_slots[0]
        day_of_week = first_slot["day_of_week"]

        # Format date: "Wednesday, Feb 18"
        date_obj = datetime.fromisoformat(date_key).date()
        date_formatted = date_obj.strftime("%B %d")  # e.g., "February 18"

        # Format time ranges
        time_ranges = []
        for slot in date_slots:
            start_dt = datetime.fromisoformat(slot["start"]).astimezone(tz)
            end_dt = datetime.fromisoformat(slot["end"]).astimezone(tz)

            # Format times (e.g., "8:00 AM", "11:00 AM")
            start_time = start_dt.strftime("%-I:%M %p")
            end_time = end_dt.strftime("%-I:%M %p")

            time_ranges.append(f"{start_time}-{end_time}")

        # Get timezone abbreviation
        tz_abbr = start_dt.strftime("%Z")

        # Combine into line
        times_str = ", ".join(time_ranges)
        lines.append(f"{day_of_week}, {date_formatted}: {times_str} {tz_abbr}")

    return "\n".join(lines)
