"""Daily brief composition -- renders a structured daily briefing dashboard."""

from datetime import datetime
from typing import Optional, Sequence

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from formatter.console import get_console, render_to_string
from formatter.styles import BOX, INNER_BOX, PRIORITY_ICONS, TITLE_STYLE
from formatter.types import ActionItem, CalendarEntry, Conflict, EmailHighlight


def _format_date(date_str: str) -> str:
    """Convert ISO date string to human-readable format.

    Args:
        date_str: Date in YYYY-MM-DD format.

    Returns:
        Human-readable date like 'Wednesday, February 25, 2026'.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    try:
        return dt.strftime("%A, %B %-d, %Y")
    except ValueError:
        # Windows does not support %-d; fall back to %d and strip leading zero
        return dt.strftime("%A, %B %d, %Y").replace(" 0", " ")


def _build_calendar_table(entries: Sequence[CalendarEntry]) -> Table:
    """Build a rich Table for calendar entries.

    Args:
        entries: Sequence of CalendarEntry dicts.

    Returns:
        A rich Table with Time, Event, and Status columns.
    """
    table = Table(box=INNER_BOX, expand=True, show_edge=False)
    table.add_column("Time", style="cyan", no_wrap=True)
    table.add_column("Event", style="white")
    table.add_column("Status", style="dim")
    for entry in entries:
        table.add_row(
            entry.get("time", ""),
            entry.get("event", ""),
            entry.get("status", ""),
        )
    return table


def _build_action_items(items: Sequence[ActionItem]) -> Text:
    """Build formatted text for action items with priority icons.

    Args:
        items: Sequence of ActionItem dicts.

    Returns:
        A rich Text object with one line per action item.
    """
    text = Text()
    for i, item in enumerate(items):
        priority = item.get("priority", "medium")
        icon = PRIORITY_ICONS.get(priority, PRIORITY_ICONS["medium"])
        line = f"  {icon} {item.get('text', '')}"
        if i < len(items) - 1:
            line += "\n"
        text.append(line)
    return text


def _build_conflicts(conflicts: Sequence[Conflict]) -> Text:
    """Build formatted text for scheduling conflicts.

    Args:
        conflicts: Sequence of Conflict dicts.

    Returns:
        A rich Text object with one line per conflict.
    """
    text = Text()
    for i, conflict in enumerate(conflicts):
        time = conflict.get("time", "")
        a = conflict.get("a", "")
        b = conflict.get("b", "")
        line = f"  {time}: {a} \u2190\u2192 {b}"
        if i < len(conflicts) - 1:
            line += "\n"
        text.append(line)
    return text


def _build_email_table(highlights: Sequence[EmailHighlight]) -> Table:
    """Build a rich Table for email highlights.

    Args:
        highlights: Sequence of EmailHighlight dicts.

    Returns:
        A rich Table with Sender, Subject, and Tag columns.
    """
    table = Table(box=INNER_BOX, expand=True, show_edge=False)
    table.add_column("Sender", style="cyan", no_wrap=True)
    table.add_column("Subject", style="white")
    table.add_column("Tag", style="dim")
    for highlight in highlights:
        table.add_row(
            highlight.get("sender", ""),
            highlight.get("subject", ""),
            highlight.get("tag", ""),
        )
    return table


def _build_delegation_table(items: Sequence[dict]) -> Table:
    """Build a rich Table for structured delegation data."""
    table = Table(box=INNER_BOX, expand=True, show_edge=False)
    table.add_column("Task", style="white")
    table.add_column("Assigned To", style="cyan", no_wrap=True)
    table.add_column("Priority", style="dim")
    table.add_column("Status", style="dim")
    for item in items:
        table.add_row(
            item.get("task", ""),
            item.get("delegated_to", ""),
            item.get("priority", ""),
            item.get("status", ""),
        )
    return table


def _build_decision_table(items: Sequence[dict]) -> Table:
    """Build a rich Table for structured decision data."""
    table = Table(box=INNER_BOX, expand=True, show_edge=False)
    table.add_column("Decision", style="white")
    table.add_column("Status", style="dim")
    table.add_column("Owner", style="cyan", no_wrap=True)
    for item in items:
        table.add_row(
            item.get("title", ""),
            item.get("status", ""),
            item.get("owner", ""),
        )
    return table


def _build_okr_table(items: Sequence[dict]) -> Table:
    """Build a rich Table for OKR highlights."""
    table = Table(box=INNER_BOX, expand=True, show_edge=False)
    table.add_column("Initiative", style="white")
    table.add_column("Team", style="cyan", no_wrap=True)
    table.add_column("Status", style="dim")
    table.add_column("Progress", style="dim")
    for item in items:
        table.add_row(
            item.get("initiative", item.get("name", "")),
            item.get("team", ""),
            item.get("status", ""),
            item.get("progress", ""),
        )
    return table


def _build_personal(items: Sequence[str]) -> Text:
    """Build a bulleted list for personal items.

    Args:
        items: Sequence of string items.

    Returns:
        A rich Text object with bullet-prefixed lines.
    """
    text = Text()
    for i, item in enumerate(items):
        line = f"  \u00b7 {item}"
        if i < len(items) - 1:
            line += "\n"
        text.append(line)
    return text


def render_daily(
    date: str,
    calendar: Optional[Sequence[CalendarEntry]] = None,
    action_items: Optional[Sequence[ActionItem]] = None,
    conflicts: Optional[Sequence[Conflict]] = None,
    email_highlights: Optional[Sequence[EmailHighlight]] = None,
    personal: Optional[Sequence[str]] = None,
    delegations: Optional[str] = None,
    decisions: Optional[str] = None,
    delegation_items: Optional[Sequence[dict]] = None,
    decision_items: Optional[Sequence[dict]] = None,
    okr_highlights: Optional[Sequence[dict]] = None,
    mode: str = "terminal",
    width: int = 80,
) -> str:
    """Render a complete daily briefing dashboard.

    Sections with no data are omitted entirely. Returns empty string
    if all sections are empty.

    Args:
        date: ISO format date string (YYYY-MM-DD).
        calendar: Calendar entries for the day.
        action_items: Prioritized action items.
        conflicts: Scheduling conflicts.
        email_highlights: Notable emails.
        personal: Personal reminders/notes.
        delegations: Summary text for active delegations.
        decisions: Summary text for pending decisions.
        delegation_items: Structured delegation dicts (takes priority over string form).
        decision_items: Structured decision dicts (takes priority over string form).
        okr_highlights: Structured OKR highlight dicts.
        mode: "terminal" for ANSI output, "plain" for plain text.
        width: Console width in characters.

    Returns:
        Rendered string, or empty string if no sections have data.
    """
    sections = []

    # Calendar section
    if calendar:
        table = _build_calendar_table(calendar)
        sections.append(
            Panel(table, title="[bold]CALENDAR[/bold]", title_align="left", box=BOX)
        )

    # Action items section
    if action_items:
        text = _build_action_items(action_items)
        sections.append(
            Panel(text, title="[bold]ACTION ITEMS[/bold]", title_align="left", box=BOX)
        )

    # Conflicts section
    if conflicts:
        text = _build_conflicts(conflicts)
        sections.append(
            Panel(text, title="[bold]CONFLICTS[/bold]", title_align="left", box=BOX)
        )

    # Email highlights section
    if email_highlights:
        table = _build_email_table(email_highlights)
        sections.append(
            Panel(table, title="[bold]EMAIL HIGHLIGHTS[/bold]", title_align="left", box=BOX)
        )

    # Personal section
    if personal:
        text = _build_personal(personal)
        sections.append(
            Panel(text, title="[bold]PERSONAL[/bold]", title_align="left", box=BOX)
        )

    # Delegations section — structured table takes priority over string summary
    if delegation_items:
        table = _build_delegation_table(delegation_items)
        sections.append(
            Panel(table, title="[bold]DELEGATIONS[/bold]", title_align="left", box=BOX)
        )
    elif delegations:
        sections.append(
            Panel(
                Text(f"  {delegations}"),
                title="[bold]DELEGATIONS[/bold]",
                title_align="left",
                box=BOX,
            )
        )

    # Decisions section — structured table takes priority over string summary
    if decision_items:
        table = _build_decision_table(decision_items)
        sections.append(
            Panel(table, title="[bold]DECISIONS[/bold]", title_align="left", box=BOX)
        )
    elif decisions:
        sections.append(
            Panel(
                Text(f"  {decisions}"),
                title="[bold]DECISIONS[/bold]",
                title_align="left",
                box=BOX,
            )
        )

    # OKR highlights section
    if okr_highlights:
        table = _build_okr_table(okr_highlights)
        sections.append(
            Panel(table, title="[bold]OKR HIGHLIGHTS[/bold]", title_align="left", box=BOX)
        )

    # Return empty string if no sections
    if not sections:
        return ""

    # Compose output
    console = get_console(mode=mode, width=width)

    # Header panel
    human_date = _format_date(date)
    header_text = Text(f"DAILY BRIEFING \u2014 {human_date}", justify="center")
    console.print(
        Panel(header_text, style=TITLE_STYLE, box=BOX)
    )

    # Print each section
    for section in sections:
        console.print(section)

    return render_to_string(console)
