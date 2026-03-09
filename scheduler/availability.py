"""Availability analysis for finding open calendar slots."""

import logging
from datetime import datetime, time, timedelta
from typing import Union
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_OOO_KEYWORDS = ("pto", "ooo", "out of office", "vacation", "holiday", "day off")


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
        is_all_day, attendees, location, notes, show_as, is_cancelled,
        response_status, start_tz, end_tz
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
    start_tz = ""
    if isinstance(start, dict):
        start_dict = start
        start = start_dict.get("dateTime") or ""
        start_tz = start_dict.get("timeZone") or ""
    end = event.get("end") or ""
    end_tz = ""
    if isinstance(end, dict):
        end_dict = end
        end = end_dict.get("dateTime") or ""
        end_tz = end_dict.get("timeZone") or ""

    # Calendar/provider normalization
    calendar = event.get("calendar") or ""
    provider = event.get("provider") or ""

    # All-day normalization
    is_all_day = event.get("is_all_day") or event.get("isAllDay") or False

    # showAs / cancelled normalization
    show_as = event.get("showAs") or event.get("show_as") or ""
    is_cancelled = event.get("isCancelled") or event.get("is_cancelled") or False

    # Title-based cancelled detection — Apple EventKit doesn't set isCancelled,
    # so fall back to checking title prefix (M365 prepends "Canceled:" to cancelled events)
    if not is_cancelled and title:
        title_stripped = title.strip().lower()
        if title_stripped.startswith("canceled:") or title_stripped.startswith("cancelled:"):
            is_cancelled = True

    # Response status normalization
    response_status = event.get("responseStatus") or event.get("response_status") or ""
    if isinstance(response_status, dict):
        response_status = response_status.get("response") or ""

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
        "start_tz": start_tz,
        "end_tz": end_tz,
        "calendar": calendar,
        "provider": provider,
        "is_all_day": is_all_day,
        "attendees": attendees,
        "location": location,
        "notes": notes,
        "show_as": show_as,
        "is_cancelled": is_cancelled,
        "response_status": response_status,
    }


def classify_event_softness(
    event: dict,
    soft_keywords: list[str] | None = None,
    user_email: str | None = None,
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
        user_email: If provided, only check this user's tentative status

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
    show_as = (event.get("show_as") or "").lower()

    # showAs=tentative from M365 → treat as soft block
    if show_as == "tentative":
        return {
            "is_soft": True,
            "reason": "Event marked as tentative (showAs)",
            "confidence": 0.8,
        }

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
    check_attendees = attendees
    if user_email:
        user_email_lower = user_email.lower()
        check_attendees = [
            a for a in attendees
            if (a.get("email") or "").lower() == user_email_lower
        ]

    for attendee in check_attendees:
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
    user_email: str | None = None,
    block_ooo_all_day: bool = False,
) -> list[dict]:
    """Find available time slots in a date range, excluding hard calendar blocks.

    For each day in range:
    1. Compute working window (working_hours_start to working_hours_end)
    2. Normalize all events, classify soft/hard
    3. If include_soft_blocks=True, treat soft blocks as available
    4. Skip all-day events (unless PTO/OOO with block_ooo_all_day)
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
        user_email: User email for scoping tentative checks (optional)
        block_ooo_all_day: Block entire day for PTO/OOO all-day events (default: False)

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

    # Filter out error payloads
    clean_events = []
    for event in events:
        if not isinstance(event, dict):
            logger.warning("Filtering out non-dict event: %r", event)
            continue
        if "error" in event:
            logger.warning("Filtering out error payload from events: %s", event.get("error"))
            continue
        clean_events.append(event)

    # Normalize and classify all events
    normalized_events = []
    for event in clean_events:
        normalized = normalize_event_for_scheduler(event)
        classification = classify_event_softness(normalized, soft_keywords, user_email)
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
        ooo_day_blocked = False
        for normalized in normalized_events:
            # Skip cancelled events
            if normalized.get("is_cancelled"):
                continue

            # Skip events marked as "free"
            if (normalized.get("show_as") or "").lower() == "free":
                continue

            # Skip declined events
            if (normalized.get("response_status") or "").lower() == "declined":
                continue

            # Skip events we should treat as available (soft blocks)
            if include_soft_blocks and normalized["_softness"]["is_soft"]:
                continue

            # Handle all-day events
            if normalized.get("is_all_day"):
                if block_ooo_all_day:
                    title_lower = (normalized.get("title") or "").lower()
                    show_as = (normalized.get("show_as") or "").lower()
                    if show_as == "oof" or any(kw in title_lower for kw in _OOO_KEYWORDS):
                        hard_blocks.append((day_start, day_end))
                        ooo_day_blocked = True
                continue

            if ooo_day_blocked:
                continue

            # Parse event times
            event_start_str = normalized.get("start")
            event_end_str = normalized.get("end")
            if not event_start_str or not event_end_str:
                logger.warning(
                    "Skipping event with missing start/end: %s",
                    normalized.get("title") or normalized.get("uid") or "unknown",
                )
                continue

            try:
                event_start = datetime.fromisoformat(event_start_str)
                event_end = datetime.fromisoformat(event_end_str)
            except (ValueError, TypeError):
                logger.warning(
                    "Skipping event with unparseable time: %s",
                    normalized.get("title") or "unknown",
                )
                continue

            # Handle naive datetimes — use event timezone if available
            if event_start.tzinfo is None:
                event_tz_name = normalized.get("start_tz") or ""
                if event_tz_name:
                    try:
                        event_tz = ZoneInfo(event_tz_name)
                        event_start = event_start.replace(tzinfo=event_tz)
                    except (KeyError, ValueError):
                        event_start = event_start.replace(tzinfo=tz)
                else:
                    event_start = event_start.replace(tzinfo=tz)
            if event_end.tzinfo is None:
                event_tz_name = normalized.get("end_tz") or ""
                if event_tz_name:
                    try:
                        event_tz = ZoneInfo(event_tz_name)
                        event_end = event_end.replace(tzinfo=event_tz)
                    except (KeyError, ValueError):
                        event_end = event_end.replace(tzinfo=tz)
                else:
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
