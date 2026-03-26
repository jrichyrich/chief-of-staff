"""Calendar tools for MCP server."""

import json
import logging
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from scheduler.availability import (
    find_available_slots,
    find_mutual_availability,
    format_slots_for_sharing,
)
from scheduler.slot_ranker import rank_slots

from .decorators import tool_errors
from .state import _retry_on_transient

logger = logging.getLogger(__name__)

_EXPECTED = (OSError, subprocess.SubprocessError, TimeoutError, ValueError)


def register(mcp, state):
    """Register calendar tools with the MCP server."""

    def _parse_date(date_str: str) -> datetime:
        """Parse ISO date string to datetime."""
        try:
            return datetime.fromisoformat(date_str)
        except ValueError:
            # Handle date-only format
            return datetime.strptime(date_str, "%Y-%m-%d")

    def _parse_alerts(alerts_json: str) -> list[int] | str:
        """Parse and validate alerts JSON string.

        Returns list[int] of minutes on success, or a JSON error string on failure.
        """
        if not alerts_json:
            return []
        alarms = json.loads(alerts_json)
        if not isinstance(alarms, list):
            return json.dumps({"error": "alerts must be a JSON list of integers"})
        if len(alarms) > 10:
            return json.dumps({"error": "Maximum 10 alerts allowed"})
        for v in alarms:
            if not isinstance(v, (int, float)) or v < 0 or v > 40320:
                return json.dumps({"error": "Each alert must be 0-40320 minutes (up to 4 weeks)"})
        return [int(v) for v in alarms]

    _VALID_RECURRENCE_TYPES = {
        "daily", "weekly", "absoluteMonthly", "relativeMonthly",
        "absoluteYearly", "relativeYearly",
    }

    def _parse_attendees(attendees_json: str) -> list[dict] | str | None:
        """Parse and validate attendees JSON string.

        Returns list[dict] on success, None if empty, or JSON error string on failure.
        """
        if not attendees_json:
            return None
        try:
            attendees = json.loads(attendees_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid attendees JSON: {e}"})
        if not isinstance(attendees, list):
            return json.dumps({"error": "attendees must be a JSON array"})
        for att in attendees:
            if not isinstance(att, dict) or "email" not in att:
                return json.dumps({"error": "Each attendee must have an 'email' field"})
            att.setdefault("name", att["email"].split("@")[0])
            att.setdefault("type", "required")
        return attendees

    def _parse_recurrence(recurrence_json: str) -> dict | str | None:
        """Parse and validate recurrence JSON string.

        Returns dict on success, None if empty, or JSON error string on failure.
        """
        if not recurrence_json:
            return None
        try:
            recurrence = json.loads(recurrence_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid recurrence JSON: {e}"})
        if not isinstance(recurrence, dict):
            return json.dumps({"error": "recurrence must be a JSON object"})
        rec_type = recurrence.get("type")
        if not rec_type or rec_type not in _VALID_RECURRENCE_TYPES:
            return json.dumps({"error": f"recurrence type must be one of: {sorted(_VALID_RECURRENCE_TYPES)}"})
        if "end_date" in recurrence and "occurrences" in recurrence:
            return json.dumps({"error": "Specify end_date or occurrences, not both"})
        return recurrence

    def _looks_work_calendar(name: str) -> bool:
        """Check if a calendar name looks like a work calendar."""
        if not name:
            return False
        lower = name.lower()
        return any(kw in lower for kw in ("work", "office", "outlook", "exchange", "corp", "company", "team", "chg"))

    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def list_calendars(provider_preference: str = "auto", source_filter: str = "") -> str:
        """List calendars from available providers (Apple and optionally Microsoft 365).

        Args:
            provider_preference: auto | apple | microsoft_365 | both (default: auto)
            source_filter: Optional source/provider text filter (e.g. iCloud, Google, Exchange)
        """
        calendar_store = state.calendar_store
        kwargs = {}
        if provider_preference and provider_preference != "auto":
            kwargs["provider_preference"] = provider_preference
        if source_filter:
            kwargs["source_filter"] = source_filter
        calendars = _retry_on_transient(calendar_store.list_calendars, **kwargs)
        return json.dumps({"results": calendars})

    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def get_calendar_events(
        start_date: str,
        end_date: str,
        calendar_name: str = "",
        provider_preference: str = "auto",
        source_filter: str = "",
    ) -> str:
        """Get events in a date range across configured providers.

        Args:
            start_date: Start date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            end_date: End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            calendar_name: Optional calendar name to filter by
            provider_preference: auto | apple | microsoft_365 | both (default: auto)
            source_filter: Optional source/provider text filter (e.g. iCloud, Google, Exchange)
        """
        calendar_store = state.calendar_store
        start_dt = _parse_date(start_date)
        end_dt = _parse_date(end_date)
        calendar_names = [calendar_name] if calendar_name else None
        kwargs = {"calendar_names": calendar_names}
        if provider_preference and provider_preference != "auto":
            kwargs["provider_preference"] = provider_preference
        if source_filter:
            kwargs["source_filter"] = source_filter
        events = _retry_on_transient(calendar_store.get_events, start_dt, end_dt, **kwargs)
        return json.dumps({"results": events})

    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def create_calendar_event(
        title: str,
        start_date: str,
        end_date: str,
        calendar_name: str = "",
        location: str = "",
        notes: str = "",
        is_all_day: bool = False,
        alerts: str = "",
        attendees: str = "",
        recurrence: str = "",
        target_provider: str = "",
        provider_preference: str = "auto",
    ) -> str:
        """Create a new calendar event using routing policy.

        Args:
            title: Event title (required)
            start_date: Start date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            end_date: End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            calendar_name: Calendar to create the event in (uses default if empty)
            location: Event location
            notes: Event notes/description
            is_all_day: Whether this is an all-day event (default: False)
            alerts: JSON list of alert times in minutes before event (e.g. "[15, 30]")
            attendees: JSON array of attendees (e.g. '[{"email": "user@chg.com", "name": "User"}]'). Sends Exchange meeting invites. Only works with Microsoft 365 provider.
            recurrence: JSON object for recurring events (e.g. '{"type": "weekly", "interval": 1, "days_of_week": ["tuesday"], "end_date": "2026-12-31"}'). Valid types: daily, weekly, absoluteMonthly, relativeMonthly, absoluteYearly, relativeYearly.
            target_provider: Optional explicit provider override (apple or microsoft_365)
            provider_preference: Optional provider hint (default: auto)
        """
        calendar_store = state.calendar_store
        start_dt = _parse_date(start_date)
        end_dt = _parse_date(end_date)

        # Parse alerts
        alarms = None
        if alerts:
            parsed = _parse_alerts(alerts)
            if isinstance(parsed, str):
                return parsed
            alarms = parsed or None

        # Parse attendees
        attendees_list = None
        if attendees:
            parsed_att = _parse_attendees(attendees)
            if isinstance(parsed_att, str):
                return parsed_att
            attendees_list = parsed_att

        # Parse recurrence
        recurrence_dict = None
        if recurrence:
            parsed_rec = _parse_recurrence(recurrence)
            if isinstance(parsed_rec, str):
                return parsed_rec
            recurrence_dict = parsed_rec

        # Dual path: Graph direct (async) vs provider chain (sync)
        use_graph = (
            state.graph_client
            and (
                attendees_list
                or recurrence_dict
                or target_provider == "microsoft_365"
                or _looks_work_calendar(calendar_name)
            )
        )

        if use_graph:
            calendar_id = None
            if calendar_name:
                calendar_id = await state.graph_client.resolve_calendar_id(calendar_name)

            result = await state.graph_client.create_calendar_event(
                subject=title,
                start=start_date,
                end=end_date,
                attendees=attendees_list,
                recurrence=recurrence_dict,
                calendar_id=calendar_id,
                location=location or None,
                body=notes or None,
                is_all_day=is_all_day,
                reminder_minutes=alarms[0] if alarms else 15,
            )

            # Track ownership
            if calendar_store and not result.get("error"):
                try:
                    calendar_store._upsert_ownership({
                        "unified_uid": f"microsoft_365:{result.get('uid', '')}",
                        "provider": "microsoft_365",
                        "native_id": result.get("uid", ""),
                        "calendar": calendar_name or "",
                    })
                except Exception:
                    logger.debug("Ownership tracking failed", exc_info=True)

            result["provider_used"] = "microsoft_365"
            return json.dumps({"status": "created", "event": result})

        # Sync fallback path
        kwargs = {}
        if target_provider:
            kwargs["target_provider"] = target_provider
        if provider_preference and provider_preference != "auto":
            kwargs["provider_preference"] = provider_preference
        result = _retry_on_transient(
            calendar_store.create_event,
            title=title,
            start_dt=start_dt,
            end_dt=end_dt,
            calendar_name=calendar_name or None,
            location=location or None,
            notes=notes or None,
            is_all_day=is_all_day,
            alarms=alarms,
            attendees=attendees_list,
            recurrence=recurrence_dict,
            **kwargs,
        )
        return json.dumps({"status": "created", "event": result})

    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def update_calendar_event(
        event_uid: str,
        calendar_name: str = "",
        title: str = "",
        start_date: str = "",
        end_date: str = "",
        location: str = "",
        notes: str = "",
        alerts: str = "",
        attendees: str = "",
        recurrence: str = "",
        target_provider: str = "",
        provider_preference: str = "auto",
    ) -> str:
        """Update an existing calendar event by UID.

        Note: attendees is a FULL REPLACEMENT — omitted attendees are removed
        and receive cancellation notices from Exchange.

        Args:
            event_uid: The unique identifier of the event (required)
            calendar_name: Calendar the event belongs to (optional when ownership is known)
            title: New event title
            start_date: New start date in ISO format
            end_date: New end date in ISO format
            location: New event location
            notes: New event notes
            alerts: JSON list of alert times in minutes before event (e.g. "[15, 30]")
            attendees: JSON array of attendees — FULL REPLACEMENT (e.g. '[{"email": "user@chg.com"}]'). Only works with Microsoft 365 provider.
            recurrence: JSON object for recurring events. Only works with Microsoft 365 provider.
            target_provider: Optional explicit provider override (apple or microsoft_365)
            provider_preference: Optional provider hint (default: auto)
        """
        calendar_store = state.calendar_store

        # Parse attendees
        attendees_list = None
        if attendees:
            parsed_att = _parse_attendees(attendees)
            if isinstance(parsed_att, str):
                return parsed_att
            attendees_list = parsed_att

        # Parse recurrence
        recurrence_dict = None
        if recurrence:
            parsed_rec = _parse_recurrence(recurrence)
            if isinstance(parsed_rec, str):
                return parsed_rec
            recurrence_dict = parsed_rec

        # Dual path: Graph direct for attendees/recurrence updates
        use_graph = (
            state.graph_client
            and (attendees_list or recurrence_dict or target_provider == "microsoft_365")
        )

        if use_graph:
            graph_kwargs = {}
            if title:
                graph_kwargs["subject"] = title
            if start_date:
                graph_kwargs["start"] = start_date
            if end_date:
                graph_kwargs["end"] = end_date
            if location:
                graph_kwargs["location"] = location
            if notes:
                graph_kwargs["body"] = notes
            if attendees_list is not None:
                graph_kwargs["attendees"] = attendees_list
            if recurrence_dict is not None:
                graph_kwargs["recurrence"] = recurrence_dict

            # Resolve native event ID from unified UID
            native_id = event_uid
            if ":" in event_uid:
                native_id = event_uid.split(":", 1)[1]

            result = await state.graph_client.update_calendar_event(native_id, **graph_kwargs)
            result["provider_used"] = "microsoft_365"
            return json.dumps({"status": "updated", "event": result})

        # Sync fallback path
        kwargs = {}
        if title:
            kwargs["title"] = title
        if start_date:
            kwargs["start_dt"] = _parse_date(start_date)
        if end_date:
            kwargs["end_dt"] = _parse_date(end_date)
        if location:
            kwargs["location"] = location
        if notes:
            kwargs["notes"] = notes
        if alerts:
            parsed = _parse_alerts(alerts)
            if isinstance(parsed, str):
                return parsed
            if parsed:
                kwargs["alarms"] = parsed
        if target_provider:
            kwargs["target_provider"] = target_provider
        if provider_preference and provider_preference != "auto":
            kwargs["provider_preference"] = provider_preference
        result = _retry_on_transient(
            calendar_store.update_event,
            event_uid,
            calendar_name=calendar_name or None,
            attendees=attendees_list,
            recurrence=recurrence_dict,
            **kwargs,
        )
        return json.dumps({"status": "updated", "event": result})

    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def delete_calendar_event(
        event_uid: str,
        calendar_name: str = "",
        target_provider: str = "",
        provider_preference: str = "auto",
    ) -> str:
        """Delete a calendar event by UID.

        Args:
            event_uid: The unique identifier of the event (required)
            calendar_name: Calendar the event belongs to (optional when ownership is known)
            target_provider: Optional explicit provider override (apple or microsoft_365)
            provider_preference: Optional provider hint (default: auto)
        """
        calendar_store = state.calendar_store
        kwargs = {"calendar_name": calendar_name or None}
        if target_provider:
            kwargs["target_provider"] = target_provider
        if provider_preference and provider_preference != "auto":
            kwargs["provider_preference"] = provider_preference
        result = _retry_on_transient(calendar_store.delete_event, event_uid, **kwargs)
        return json.dumps(result)

    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def search_calendar_events(
        query: str,
        start_date: str = "",
        end_date: str = "",
        provider_preference: str = "auto",
        source_filter: str = "",
    ) -> str:
        """Search events by title text. Defaults to +/- 30 days if no dates provided.

        Args:
            query: Text to search for in event titles (required)
            start_date: Start date in ISO format (defaults to 30 days ago)
            end_date: End date in ISO format (defaults to 30 days from now)
            provider_preference: auto | apple | microsoft_365 | both (default: auto)
            source_filter: Optional source/provider text filter (e.g. iCloud, Google, Exchange)
        """
        from datetime import timedelta

        calendar_store = state.calendar_store
        now = datetime.now(tz=ZoneInfo(config.USER_TIMEZONE))
        start_dt = _parse_date(start_date) if start_date else now - timedelta(days=30)
        end_dt = _parse_date(end_date) if end_date else now + timedelta(days=30)
        kwargs = {}
        if provider_preference and provider_preference != "auto":
            kwargs["provider_preference"] = provider_preference
        if source_filter:
            kwargs["source_filter"] = source_filter
        events = _retry_on_transient(calendar_store.search_events, query, start_dt, end_dt, **kwargs)
        return json.dumps({"results": events})

    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def find_my_open_slots(
        start_date: str,
        end_date: str,
        duration_minutes: int = 30,
        include_soft_blocks: bool = True,
        soft_keywords: str = "",
        calendar_name: str = "",
        working_hours_start: str = "08:00",
        working_hours_end: str = "18:00",
        provider_preference: str = "both",
        user_email: str = "",
    ) -> str:
        """Find available time slots in your calendar within a date range.

        Analyzes calendar events to find open slots, treating soft blocks (Focus Time,
        Lunch, etc.) as available by default. Uses Mountain Time (America/Denver).

        Pulls from ALL configured calendar providers by default (Apple + Microsoft 365)
        to ensure accurate availability.

        Args:
            start_date: Start date (YYYY-MM-DD or ISO datetime)
            end_date: End date (YYYY-MM-DD or ISO datetime)
            duration_minutes: Minimum slot duration in minutes (default: 30)
            include_soft_blocks: Treat soft blocks as available (default: True)
            soft_keywords: Comma-separated soft keywords (default: "focus,lunch,prep,hold,tentative")
            calendar_name: Optional calendar filter
            working_hours_start: Working hours start time HH:MM (default: 08:00)
            working_hours_end: Working hours end time HH:MM (default: 18:00)
            provider_preference: auto | apple | microsoft_365 | both (default: both)
            user_email: User's email for tentative classification (default: config.USER_EMAIL)

        Returns:
            JSON with raw slots and formatted text for sharing
        """
        from datetime import time

        # Validate duration_minutes
        if duration_minutes < 1:
            return json.dumps({
                "error": "duration_minutes must be >= 1",
                "slots": [],
                "count": 0,
            })

        calendar_store = state.calendar_store

        # Resolve user_email: explicit param > config > empty
        resolved_email = user_email or config.USER_EMAIL

        # Parse working hours
        start_hour, start_min = map(int, working_hours_start.split(":"))
        end_hour, end_min = map(int, working_hours_end.split(":"))
        working_start = time(start_hour, start_min)
        working_end = time(end_hour, end_min)

        # Parse soft keywords
        keywords = None
        if soft_keywords:
            keywords = [kw.strip() for kw in soft_keywords.split(",") if kw.strip()]

        # Fetch events from ALL configured calendar providers (with routing metadata)
        start_dt = _parse_date(start_date)
        end_dt = _parse_date(end_date)
        calendar_names = [calendar_name] if calendar_name else None
        kwargs = {"calendar_names": calendar_names}
        if provider_preference and provider_preference != "auto":
            kwargs["provider_preference"] = provider_preference
        events, routing_info = _retry_on_transient(
            calendar_store.get_events_with_routing,
            start_dt, end_dt,
            require_all_success=False,  # Availability uses best-effort — partial data better than no data
            **kwargs,
        )

        # Log routing fallback warnings
        if routing_info.get("is_fallback"):
            logger.warning(
                "find_my_open_slots: provider routing fallback — requested=%r, "
                "routed_to=%s, reason=%s",
                provider_preference,
                routing_info.get("providers_requested"),
                routing_info.get("routing_reason"),
            )

        # Check for error payloads from provider failures
        if events and isinstance(events[0], dict) and events[0].get("error"):
            error_payload = events[0]
            # Try to use partial results if available (degraded accuracy)
            partial = error_payload.get("partial_results") or []
            if partial:
                logger.warning(
                    "Calendar provider partial failure: %s. Using %d partial events.",
                    error_payload.get("error", "unknown"), len(partial),
                )
                events = partial
            else:
                return json.dumps({
                    "error": error_payload.get("error", "Calendar provider failure"),
                    "slots": [],
                    "formatted_text": "Unable to determine availability — calendar provider error.",
                    "count": 0,
                    "provider_details": {
                        "providers_failed": error_payload.get("providers_failed", []),
                        "providers_succeeded": error_payload.get("providers_succeeded", []),
                    },
                    "routing": routing_info,
                })

        # Find available slots
        slots = find_available_slots(
            events=events,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=duration_minutes,
            working_hours_start=working_start,
            working_hours_end=working_end,
            timezone_name=config.USER_TIMEZONE,
            include_soft_blocks=include_soft_blocks,
            soft_keywords=keywords,
            user_email=resolved_email,
        )

        # Format for sharing
        formatted_text = format_slots_for_sharing(slots, timezone_name=config.USER_TIMEZONE)

        return json.dumps({
            "slots": slots,
            "formatted_text": formatted_text,
            "count": len(slots),
            "provider_preference": provider_preference,
            "routing": routing_info,
        })

    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def get_people_availability(
        emails: str,
        start_date: str,
        end_date: str,
        timezone: str = config.USER_TIMEZONE,
    ) -> str:
        """Get raw free/busy availability for one or more people via Graph API.

        Low-level tool that returns per-person schedule data. Uses Graph getSchedule
        endpoint — only works for users in the same organization.

        Args:
            emails: Comma-separated email addresses (required)
            start_date: Start datetime in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            end_date: End datetime in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            timezone: IANA timezone name (default: America/Denver)

        Returns:
            JSON with per-person availability data
        """
        if not state.graph_client:
            return json.dumps({"error": "Graph API client not available. Microsoft 365 integration required."})

        email_list = [e.strip() for e in emails.split(",") if e.strip()]
        if not email_list:
            return json.dumps({"error": "No email addresses provided"})

        schedules = await state.graph_client.get_schedule(
            schedules=email_list,
            start=start_date,
            end=end_date,
            timezone=timezone,
        )
        return json.dumps({"results": schedules, "count": len(schedules)})

    async def _resolve_participant_emails(participants: str) -> tuple[list[dict], list[str]]:
        """Resolve participant names/emails to email addresses.

        Returns:
            (resolved, errors) — resolved is list of {"email": ..., "name": ...},
            errors is list of unresolvable names.
        """
        resolved = []
        errors = []
        for part in participants.split(","):
            part = part.strip()
            if not part:
                continue
            if "@" in part:
                resolved.append({"email": part, "name": part.split("@")[0]})
            else:
                # Try identity store first
                found = False
                if state.memory_store:
                    try:
                        identities = state.memory_store.search_identity(part)
                        if identities:
                            email = identities[0].get("email", "")
                            name = identities[0].get("display_name") or identities[0].get("canonical_name") or part
                            if email:
                                resolved.append({"email": email, "name": name})
                                found = True
                    except Exception:
                        pass
                # Try Graph user resolution
                if not found and state.graph_client:
                    try:
                        email = await state.graph_client.resolve_user_email(part)
                        if email:
                            resolved.append({"email": email, "name": part})
                            found = True
                    except Exception:
                        pass
                if not found:
                    errors.append(part)
        return resolved, errors

    def _compute_default_end_date(start_date_str: str, business_days: int = 10) -> str:
        """Compute end date as N business days from start."""
        from datetime import date as date_cls

        if start_date_str:
            start = datetime.fromisoformat(start_date_str).date()
        else:
            start = datetime.now(tz=ZoneInfo(config.USER_TIMEZONE)).date()

        current = start
        added = 0
        while added < business_days:
            current += timedelta(days=1)
            if current.weekday() < 5:  # Mon-Fri
                added += 1
        return current.isoformat()

    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def find_group_availability(
        participants: str,
        start_date: str,
        end_date: str,
        duration_minutes: int = 30,
        include_my_soft_blocks: bool = True,
        max_suggestions: int = 5,
        working_hours_start: str = "08:00",
        working_hours_end: str = "18:00",
        preferred_times: str = "",
    ) -> str:
        """Find mutually available meeting times for a group of people.

        Fetches your calendar (both providers) and others' free/busy via Graph API,
        then computes mutual availability windows. Returns ranked suggestions.

        Args:
            participants: Comma-separated email addresses (required)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            duration_minutes: Meeting duration in minutes (default: 30)
            include_my_soft_blocks: Treat your soft blocks as available (default: True)
            max_suggestions: Maximum number of suggestions to return (default: 5)
            working_hours_start: Working hours start time HH:MM (default: 08:00)
            working_hours_end: Working hours end time HH:MM (default: 18:00)
            preferred_times: "morning", "afternoon", or "HH:MM-HH:MM" for ranking (optional)

        Returns:
            JSON with ranked mutual availability slots
        """
        import asyncio
        from datetime import time as time_cls

        if not state.graph_client:
            return json.dumps({"error": "Graph API client not available. Microsoft 365 integration required."})

        email_list = [e.strip() for e in participants.split(",") if e.strip()]
        if not email_list:
            return json.dumps({"error": "No participants provided"})

        resolved_email = config.USER_EMAIL

        # Parse working hours
        start_hour, start_min = map(int, working_hours_start.split(":"))
        end_hour, end_min = map(int, working_hours_end.split(":"))
        working_start = time_cls(start_hour, start_min)
        working_end = time_cls(end_hour, end_min)

        calendar_store = state.calendar_store

        # Fetch my events and others' schedules in parallel
        async def fetch_my_events():
            start_dt = _parse_date(start_date)
            end_dt = _parse_date(end_date)
            events, routing_info = _retry_on_transient(
                calendar_store.get_events_with_routing,
                start_dt, end_dt,
                require_all_success=False,
                provider_preference="both",
            )
            return events, routing_info

        async def fetch_others_schedules():
            return await state.graph_client.get_schedule(
                schedules=email_list,
                start=start_date,
                end=end_date,
                timezone=config.USER_TIMEZONE,
            )

        (my_events, routing_info), others_schedules = await asyncio.gather(
            fetch_my_events(),
            fetch_others_schedules(),
        )

        # Handle error payloads from calendar
        if my_events and isinstance(my_events[0], dict) and my_events[0].get("error"):
            partial = my_events[0].get("partial_results") or []
            my_events = partial if partial else []

        # Compute mutual availability
        mutual_slots = find_mutual_availability(
            my_events=my_events,
            others_schedules=others_schedules,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=duration_minutes,
            working_hours_start=working_start,
            working_hours_end=working_end,
            timezone_name=config.USER_TIMEZONE,
            include_soft_blocks=include_my_soft_blocks,
            user_email=resolved_email,
        )

        # Rank slots
        ranked = rank_slots(
            slots=mutual_slots,
            my_events=my_events,
            preferred_times=preferred_times,
            timezone_name=config.USER_TIMEZONE,
        )

        # Limit suggestions
        suggestions = ranked[:max_suggestions]

        if not suggestions:
            return json.dumps({
                "status": "no_slots",
                "message": f"No mutually available {duration_minutes}-minute slots found between {start_date} and {end_date}. Try expanding the date range or adjusting working hours.",
                "participants": email_list,
                "date_range": {"start": start_date, "end": end_date},
            })

        return json.dumps({
            "status": "suggestions",
            "suggestions": suggestions,
            "count": len(suggestions),
            "total_mutual_slots": len(mutual_slots),
            "participants": email_list,
            "date_range": {"start": start_date, "end": end_date},
            "duration_minutes": duration_minutes,
        })

    @mcp.tool()
    @tool_errors("Calendar error", expected=_EXPECTED)
    async def schedule_meeting(
        title: str,
        participants: str,
        duration_minutes: int = 30,
        start_date: str = "",
        end_date: str = "",
        working_hours_start: str = "08:00",
        working_hours_end: str = "18:00",
        location: str = "",
        notes: str = "",
        include_soft_blocks: bool = True,
        max_suggestions: int = 5,
        preferred_times: str = "",
    ) -> str:
        """Smart scheduling assistant: resolve names, find mutual availability, suggest times.

        End-to-end meeting scheduling workflow:
        1. Resolves participant names to emails (via identity store + Graph)
        2. Fetches your calendar and others' free/busy in parallel
        3. Computes mutual availability windows
        4. Ranks and returns top suggestions

        Does NOT create the event — returns suggestions for confirmation.
        After user picks a slot, call create_calendar_event with attendees.

        Args:
            title: Meeting title (required)
            participants: Comma-separated names or email addresses (required)
            duration_minutes: Meeting duration in minutes (default: 30)
            start_date: Start of search window (YYYY-MM-DD, default: today)
            end_date: End of search window (YYYY-MM-DD, default: +10 business days)
            working_hours_start: Working hours start time HH:MM (default: 08:00)
            working_hours_end: Working hours end time HH:MM (default: 18:00)
            location: Meeting location (optional, saved for event creation)
            notes: Meeting notes/agenda (optional, saved for event creation)
            include_soft_blocks: Treat your soft blocks as available (default: True)
            max_suggestions: Maximum number of suggestions (default: 5)
            preferred_times: "morning", "afternoon", or "HH:MM-HH:MM" (optional)

        Returns:
            JSON with status, suggestions, resolved participants, and meeting details
        """
        import asyncio
        from datetime import time as time_cls, timedelta

        if not state.graph_client:
            return json.dumps({"error": "Graph API client not available. Microsoft 365 integration required."})

        # Step 1: Resolve participants
        resolved, errors = await _resolve_participant_emails(participants)

        if errors and not resolved:
            return json.dumps({
                "status": "error",
                "message": f"Could not resolve any participants: {', '.join(errors)}",
                "unresolved": errors,
            })

        # Step 2: Compute date range defaults
        now = datetime.now(tz=ZoneInfo(config.USER_TIMEZONE))
        if not start_date:
            start_date = now.strftime("%Y-%m-%d")
        if not end_date:
            end_date = _compute_default_end_date(start_date, business_days=10)

        resolved_email = config.USER_EMAIL
        participant_emails = [p["email"] for p in resolved]

        # Parse working hours
        start_hour, start_min = map(int, working_hours_start.split(":"))
        end_hour, end_min = map(int, working_hours_end.split(":"))
        working_start = time_cls(start_hour, start_min)
        working_end = time_cls(end_hour, end_min)

        calendar_store = state.calendar_store

        # Step 3: Fetch availability in parallel
        async def fetch_my_events():
            start_dt = _parse_date(start_date)
            end_dt = _parse_date(end_date)
            events, routing_info = _retry_on_transient(
                calendar_store.get_events_with_routing,
                start_dt, end_dt,
                require_all_success=False,
                provider_preference="both",
            )
            return events, routing_info

        async def fetch_others_schedules():
            return await state.graph_client.get_schedule(
                schedules=participant_emails,
                start=start_date,
                end=end_date,
                timezone=config.USER_TIMEZONE,
            )

        (my_events, routing_info), others_schedules = await asyncio.gather(
            fetch_my_events(),
            fetch_others_schedules(),
        )

        # Handle error payloads
        if my_events and isinstance(my_events[0], dict) and my_events[0].get("error"):
            partial = my_events[0].get("partial_results") or []
            my_events = partial if partial else []

        # Step 4: Compute mutual slots
        mutual_slots = find_mutual_availability(
            my_events=my_events,
            others_schedules=others_schedules,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=duration_minutes,
            working_hours_start=working_start,
            working_hours_end=working_end,
            timezone_name=config.USER_TIMEZONE,
            include_soft_blocks=include_soft_blocks,
            user_email=resolved_email,
        )

        # Step 5: Rank slots
        ranked = rank_slots(
            slots=mutual_slots,
            my_events=my_events,
            preferred_times=preferred_times,
            timezone_name=config.USER_TIMEZONE,
        )

        suggestions = ranked[:max_suggestions]

        if not suggestions:
            result = {
                "status": "no_slots",
                "message": f"No mutually available {duration_minutes}-minute slots found between {start_date} and {end_date}. Try expanding the date range, adjusting working hours, or reducing duration.",
                "participants": resolved,
                "date_range": {"start": start_date, "end": end_date},
                "meeting_details": {"title": title, "duration": duration_minutes, "location": location, "notes": notes},
            }
            if errors:
                result["unresolved_participants"] = errors
            return json.dumps(result)

        result = {
            "status": "suggestions",
            "suggestions": suggestions,
            "participants": resolved,
            "meeting_details": {
                "title": title,
                "duration": duration_minutes,
                "location": location,
                "notes": notes,
            },
            "confirmation_required": True,
            "date_range": {"start": start_date, "end": end_date},
            "total_mutual_slots": len(mutual_slots),
        }
        if errors:
            result["unresolved_participants"] = errors
        return json.dumps(result)

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.list_calendars = list_calendars
    module.get_calendar_events = get_calendar_events
    module.create_calendar_event = create_calendar_event
    module.update_calendar_event = update_calendar_event
    module.delete_calendar_event = delete_calendar_event
    module.search_calendar_events = search_calendar_events
    module.find_my_open_slots = find_my_open_slots
    module.find_group_availability = find_group_availability
    module.get_people_availability = get_people_availability
    module.schedule_meeting = schedule_meeting
    module._parse_attendees = _parse_attendees
    module._parse_recurrence = _parse_recurrence
    module._resolve_participant_emails = _resolve_participant_emails
