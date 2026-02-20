"""Calendar tools for MCP server."""

import json
import subprocess
from datetime import datetime

from .state import _retry_on_transient


def register(mcp, state):
    """Register calendar tools with the MCP server."""

    def _parse_date(date_str: str) -> datetime:
        """Parse ISO date string to datetime."""
        try:
            return datetime.fromisoformat(date_str)
        except ValueError:
            # Handle date-only format
            return datetime.strptime(date_str, "%Y-%m-%d")

    @mcp.tool()
    async def list_calendars(provider_preference: str = "auto", source_filter: str = "") -> str:
        """List calendars from available providers (Apple and optionally Microsoft 365).

        Args:
            provider_preference: auto | apple | microsoft_365 | both (default: auto)
            source_filter: Optional source/provider text filter (e.g. iCloud, Google, Exchange)
        """
        calendar_store = state.calendar_store
        try:
            kwargs = {}
            if provider_preference and provider_preference != "auto":
                kwargs["provider_preference"] = provider_preference
            if source_filter:
                kwargs["source_filter"] = source_filter
            calendars = _retry_on_transient(calendar_store.list_calendars, **kwargs)
            return json.dumps({"results": calendars})
        except (OSError, subprocess.SubprocessError, TimeoutError, ValueError) as e:
            return json.dumps({"error": f"Calendar error listing calendars: {e}"})
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Unexpected error in list_calendars")
            return json.dumps({"error": f"Unexpected error: {e}"})

    @mcp.tool()
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
        try:
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
        except (OSError, subprocess.SubprocessError, TimeoutError, ValueError) as e:
            return json.dumps({"error": f"Calendar error getting events: {e}"})
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Unexpected error in get_calendar_events")
            return json.dumps({"error": f"Unexpected error: {e}"})

    @mcp.tool()
    async def create_calendar_event(
        title: str,
        start_date: str,
        end_date: str,
        calendar_name: str = "",
        location: str = "",
        notes: str = "",
        is_all_day: bool = False,
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
            target_provider: Optional explicit provider override (apple or microsoft_365)
            provider_preference: Optional provider hint (default: auto)
        """
        calendar_store = state.calendar_store
        try:
            start_dt = _parse_date(start_date)
            end_dt = _parse_date(end_date)
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
                **kwargs,
            )
            return json.dumps({"status": "created", "event": result})
        except (OSError, subprocess.SubprocessError, TimeoutError, ValueError) as e:
            return json.dumps({"error": f"Calendar error creating event: {e}"})
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Unexpected error in create_calendar_event")
            return json.dumps({"error": f"Unexpected error: {e}"})

    @mcp.tool()
    async def update_calendar_event(
        event_uid: str,
        calendar_name: str = "",
        title: str = "",
        start_date: str = "",
        end_date: str = "",
        location: str = "",
        notes: str = "",
        target_provider: str = "",
        provider_preference: str = "auto",
    ) -> str:
        """Update an existing calendar event by UID.

        Args:
            event_uid: The unique identifier of the event (required)
            calendar_name: Calendar the event belongs to (optional when ownership is known)
            title: New event title
            start_date: New start date in ISO format
            end_date: New end date in ISO format
            location: New event location
            notes: New event notes
            target_provider: Optional explicit provider override (apple or microsoft_365)
            provider_preference: Optional provider hint (default: auto)
        """
        calendar_store = state.calendar_store
        try:
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
            if target_provider:
                kwargs["target_provider"] = target_provider
            if provider_preference and provider_preference != "auto":
                kwargs["provider_preference"] = provider_preference
            result = calendar_store.update_event(
                event_uid,
                calendar_name=calendar_name or None,
                **kwargs,
            )
            return json.dumps({"status": "updated", "event": result})
        except Exception as e:
            return json.dumps({"error": f"Failed to update event: {e}"})

    @mcp.tool()
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
        try:
            kwargs = {"calendar_name": calendar_name or None}
            if target_provider:
                kwargs["target_provider"] = target_provider
            if provider_preference and provider_preference != "auto":
                kwargs["provider_preference"] = provider_preference
            result = calendar_store.delete_event(event_uid, **kwargs)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": f"Failed to delete event: {e}"})

    @mcp.tool()
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
        try:
            now = datetime.now()
            start_dt = _parse_date(start_date) if start_date else now - timedelta(days=30)
            end_dt = _parse_date(end_date) if end_date else now + timedelta(days=30)
            kwargs = {}
            if provider_preference and provider_preference != "auto":
                kwargs["provider_preference"] = provider_preference
            if source_filter:
                kwargs["source_filter"] = source_filter
            events = calendar_store.search_events(query, start_dt, end_dt, **kwargs)
            try:
                state.memory_store.record_skill_usage("search_calendar_events", query)
            except Exception:
                pass
            return json.dumps({"results": events})
        except Exception as e:
            return json.dumps({"error": f"Failed to search events: {e}"})

    @mcp.tool()
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

        Returns:
            JSON with raw slots and formatted text for sharing
        """
        from datetime import time

        from scheduler.availability import find_available_slots, format_slots_for_sharing

        calendar_store = state.calendar_store

        try:
            # Parse working hours
            start_hour, start_min = map(int, working_hours_start.split(":"))
            end_hour, end_min = map(int, working_hours_end.split(":"))
            working_start = time(start_hour, start_min)
            working_end = time(end_hour, end_min)

            # Parse soft keywords
            keywords = None
            if soft_keywords:
                keywords = [kw.strip() for kw in soft_keywords.split(",") if kw.strip()]

            # Fetch events from ALL configured calendar providers
            start_dt = _parse_date(start_date)
            end_dt = _parse_date(end_date)
            calendar_names = [calendar_name] if calendar_name else None
            kwargs = {"calendar_names": calendar_names}
            if provider_preference and provider_preference != "auto":
                kwargs["provider_preference"] = provider_preference
            events = calendar_store.get_events(start_dt, end_dt, **kwargs)

            # Find available slots
            slots = find_available_slots(
                events=events,
                start_date=start_date,
                end_date=end_date,
                duration_minutes=duration_minutes,
                working_hours_start=working_start,
                working_hours_end=working_end,
                timezone_name="America/Denver",
                include_soft_blocks=include_soft_blocks,
                soft_keywords=keywords,
            )

            # Format for sharing
            formatted_text = format_slots_for_sharing(slots, timezone_name="America/Denver")

            return json.dumps({
                "slots": slots,
                "formatted_text": formatted_text,
                "count": len(slots),
            })

        except Exception as e:
            return json.dumps({"error": f"Failed to find open slots: {e}"})

    @mcp.tool()
    async def find_group_availability(
        participants: str,
        start_date: str,
        end_date: str,
        duration_minutes: int = 30,
        include_my_soft_blocks: bool = True,
        max_suggestions: int = 5,
    ) -> str:
        """GUIDANCE TOOL: Explains workflow for finding group meeting times.

        This tool provides instructions for the two-step workflow to find times that
        work for a group including yourself. We cannot directly call the M365 MCP tool
        from within our MCP server, so this returns the methodology for the agent to follow.

        Workflow:
        1. Use mcp__claude_ai_Microsoft_365__find_meeting_availability with:
           - attendees: comma-separated email list
           - isOrganizerOptional: true (to check everyone's availability including yours)
           - duration: meeting duration in minutes
           - start_date/end_date: date range
        2. Use find_my_open_slots to get your REAL availability (including soft block logic)
        3. Cross-reference to find times that work for everyone

        Args:
            participants: Comma-separated email addresses
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            duration_minutes: Meeting duration (default: 30)
            include_my_soft_blocks: Treat your soft blocks as available (default: True)
            max_suggestions: Maximum number of suggestions to return (default: 5)

        Returns:
            Instructions for the agent to follow the two-step workflow
        """
        return json.dumps({
            "status": "guidance",
            "message": "This is a guidance tool. Follow the workflow below:",
            "workflow": [
                {
                    "step": 1,
                    "description": "Check group availability via Microsoft 365 MCP",
                    "tool": "mcp__claude_ai_Microsoft_365__find_meeting_availability",
                    "parameters": {
                        "attendees": participants,
                        "isOrganizerOptional": True,
                        "duration": duration_minutes,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    "note": "This checks availability for all participants including you (via their M365 calendars)",
                },
                {
                    "step": 2,
                    "description": "Check your REAL availability with soft block logic",
                    "tool": "find_my_open_slots",
                    "parameters": {
                        "start_date": start_date,
                        "end_date": end_date,
                        "duration_minutes": duration_minutes,
                        "include_soft_blocks": include_my_soft_blocks,
                    },
                    "note": "This applies your preference to treat Focus Time/Lunch as available",
                },
                {
                    "step": 3,
                    "description": "Cross-reference the two result sets",
                    "action": "Find time slots that appear in BOTH the M365 group availability AND your open slots",
                    "suggestion": f"Return the top {max_suggestions} matching slots",
                },
            ],
            "parameters_provided": {
                "participants": participants,
                "start_date": start_date,
                "end_date": end_date,
                "duration_minutes": duration_minutes,
                "include_my_soft_blocks": include_my_soft_blocks,
                "max_suggestions": max_suggestions,
            },
        })

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
