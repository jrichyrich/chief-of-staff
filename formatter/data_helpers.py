"""Transform raw API data into formatter-compatible structures.

Converts raw calendar events, delegations, decisions, and OKR data from
MCP tool responses into the TypedDict structures expected by formatter
modules (brief, tables, cards).
"""

from datetime import datetime
from typing import Sequence

from formatter.types import CalendarEntry


def _format_time(iso_str: str) -> str:
    """Convert ISO datetime string to human-readable time like '8:30 AM'."""
    try:
        dt = datetime.fromisoformat(iso_str)
        try:
            return dt.strftime("%-I:%M %p")
        except ValueError:
            # Windows does not support %-I; fall back to %I and strip leading zero
            return dt.strftime("%I:%M %p").lstrip("0")
    except (ValueError, TypeError):
        return iso_str


def calendar_events_to_entries(events: Sequence[dict]) -> list[CalendarEntry]:
    """Convert raw calendar event dicts to CalendarEntry format.

    Args:
        events: Raw event dicts from calendar tools (keys: title, start, end, status, location).

    Returns:
        List of CalendarEntry dicts with time, event, status keys.
    """
    entries: list[CalendarEntry] = []
    for ev in events:
        entry: CalendarEntry = {
            "time": _format_time(ev.get("start", "")),
            "event": ev.get("title", ev.get("summary", "")),
            "status": ev.get("status", ""),
        }
        entries.append(entry)
    return entries


def delegations_to_table_data(
    delegations: Sequence[dict],
) -> tuple[list[str], list[tuple[str, ...]]]:
    """Convert raw delegation dicts to table columns and rows.

    Returns:
        (columns, rows) tuple for formatter.tables.render().
    """
    columns = ["Task", "Assigned To", "Priority", "Status", "Due"]
    rows = []
    for d in delegations:
        rows.append((
            d.get("task", ""),
            d.get("delegated_to", ""),
            d.get("priority", ""),
            d.get("status", ""),
            d.get("due_date", ""),
        ))
    return columns, rows


def decisions_to_table_data(
    decisions: Sequence[dict],
) -> tuple[list[str], list[tuple[str, ...]]]:
    """Convert raw decision dicts to table columns and rows.

    Returns:
        (columns, rows) tuple for formatter.tables.render().
    """
    columns = ["Decision", "Status", "Owner", "Follow-up"]
    rows = []
    for d in decisions:
        rows.append((
            d.get("title", ""),
            d.get("status", ""),
            d.get("owner", ""),
            d.get("follow_up_date", ""),
        ))
    return columns, rows


def delegations_to_summary(delegations: Sequence[dict]) -> str:
    """Produce a one-line summary of delegations for the daily brief.

    Returns:
        Summary string like '2 active, 1 high priority' or empty string.
    """
    if not delegations:
        return ""

    active = [d for d in delegations if d.get("status") == "active"]
    high = [d for d in active if d.get("priority") in ("high", "critical")]

    parts = [f"{len(active)} active"]
    if high:
        parts.append(f"{len(high)} high priority")
    return ", ".join(parts)


def decisions_to_summary(decisions: Sequence[dict]) -> str:
    """Produce a one-line summary of decisions for the daily brief.

    Returns:
        Summary string like '2 pending' or empty string.
    """
    if not decisions:
        return ""

    pending = [d for d in decisions if d.get("status") == "pending_execution"]
    parts = [f"{len(pending)} pending"]
    return ", ".join(parts)
