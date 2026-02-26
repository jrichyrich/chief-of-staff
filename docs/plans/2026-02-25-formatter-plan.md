# Formatter Module Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `formatter/` module using `rich` that renders structured data as polished terminal dashboards and plain-text output for emails, with MCP tool wrappers for Claude to invoke directly.

**Architecture:** Internal `formatter/` library with dual-mode rendering (terminal ANSI / plain Unicode). Each formatter function takes dicts/lists in and returns strings out. New `mcp_tools/formatter_tools.py` exposes formatters as MCP tools. Existing tools and agents are untouched.

**Tech Stack:** Python 3.11+, `rich>=13.0`, existing FastMCP patterns

**Design Doc:** `docs/plans/2026-02-25-formatter-design.md`

---

### Task 1: Add `rich` dependency and create package skeleton

**Files:**
- Modify: `pyproject.toml:10-20` (add `rich` to dependencies)
- Modify: `pyproject.toml:32` (add `formatter*` to setuptools packages)
- Create: `formatter/__init__.py`
- Create: `formatter/styles.py`
- Create: `formatter/console.py`
- Create: `formatter/types.py`

**Step 1: Add `rich` to pyproject.toml dependencies**

In `pyproject.toml`, add `"rich>=13.0"` to the `dependencies` list:

```python
dependencies = [
    "anthropic>=0.42.0",
    "chromadb>=0.5.0",
    "openpyxl>=3.1.0",
    "pyyaml>=6.0",
    "mcp[cli]>=1.26,<2",
    "pyobjc-framework-EventKit>=10.0; sys_platform == 'darwin'",
    "pypdf>=5.0.0",
    "python-docx>=1.1.0",
    "playwright>=1.40.0",
    "rich>=13.0",
]
```

Also add `"formatter*"` to the `setuptools.packages.find` include list.

**Step 2: Install the updated package**

Run: `pip install -e ".[dev]"`
Expected: Successfully installs `rich` and its dependencies.

**Step 3: Create `formatter/styles.py`**

```python
"""Shared design language: colors, icons, box styles, constants."""

import rich.box

# Box style for all panels/tables
BOX = rich.box.DOUBLE
INNER_BOX = rich.box.SIMPLE_HEAVY

# Status colors (used in StatusBadge, cards, tables)
STATUS_COLORS = {
    "green": "bold green",
    "yellow": "bold yellow",
    "red": "bold red",
    "on_track": "bold green",
    "at_risk": "bold yellow",
    "blocked": "bold red",
    "completed": "bold green",
    "active": "bold cyan",
    "pending": "dim",
}

# Priority indicators
PRIORITY_ICONS = {
    "urgent": "⚠",
    "high": "★",
    "medium": "●",
    "low": "○",
    "fyi": "·",
}

# Section header style
HEADER_STYLE = "bold white"
TITLE_STYLE = "bold white on blue"
SUBTITLE_STYLE = "bold cyan"
DIM_STYLE = "dim"
```

**Step 4: Create `formatter/console.py`**

```python
"""Console factory for dual-mode rendering (terminal ANSI / plain text)."""

from io import StringIO
from rich.console import Console


def get_console(mode: str = "terminal", width: int = 80) -> Console:
    """Create a Console configured for the given render mode.

    Args:
        mode: "terminal" for ANSI color output, "plain" for no-ANSI text.
        width: Console width in characters.

    Returns:
        A rich Console instance.
    """
    if mode == "plain":
        return Console(
            file=StringIO(),
            force_terminal=False,
            no_color=True,
            width=width,
        )
    return Console(
        file=StringIO(),
        force_terminal=True,
        width=width,
    )


def render_to_string(console: Console) -> str:
    """Extract the rendered string from a Console that writes to StringIO."""
    console.file.seek(0)
    return console.file.read()
```

**Step 5: Create `formatter/types.py`**

```python
"""TypedDicts for structured input data to formatter functions."""

from typing import TypedDict, Optional


class CalendarEntry(TypedDict, total=False):
    time: str
    event: str
    location: str
    status: str
    key: bool


class ActionItem(TypedDict, total=False):
    priority: str  # urgent, high, medium, low, fyi
    text: str


class Conflict(TypedDict, total=False):
    time: str
    a: str
    b: str


class EmailHighlight(TypedDict, total=False):
    sender: str
    subject: str
    tag: str


class StatusField(TypedDict, total=False):
    label: str
    value: str
    status: str  # green, yellow, red


class PanelData(TypedDict, total=False):
    title: str
    content: str
```

**Step 6: Create `formatter/__init__.py`**

```python
"""Jarvis formatter: rich-powered terminal dashboards and plain-text output.

Usage:
    from formatter import tables, cards, brief, dashboard

    # Render a table
    output = tables.render(
        title="Calendar",
        columns=["Time", "Event"],
        rows=[("8:30 AM", "ePMLT")],
        mode="terminal",
    )

    # Render a status card
    output = cards.render(
        title="RBAC Status",
        status="yellow",
        fields={"Owner": "Shawn", "Progress": "5%"},
        mode="terminal",
    )
"""

from formatter import tables, cards, brief, dashboard

__all__ = ["tables", "cards", "brief", "dashboard"]
```

**Step 7: Commit**

```bash
git add formatter/ pyproject.toml
git commit -m "feat: add formatter package skeleton with styles, console, and types"
```

---

### Task 2: Implement `formatter/tables.py` with TDD

**Files:**
- Create: `formatter/tables.py`
- Create: `tests/test_formatter_tables.py`

**Step 1: Write the failing tests**

Create `tests/test_formatter_tables.py`:

```python
"""Tests for formatter.tables — generic table rendering."""

import pytest
from formatter.tables import render


class TestTableRender:
    def test_basic_table_contains_all_data(self):
        result = render(
            title="Calendar",
            columns=["Time", "Event", "Status"],
            rows=[
                ("8:30 AM", "ePMLT", "Zoom"),
                ("10:30 AM", "PwC Readout", "⚠ KEY"),
            ],
            mode="plain",
        )
        assert "Calendar" in result
        assert "8:30 AM" in result
        assert "ePMLT" in result
        assert "PwC Readout" in result
        assert "⚠ KEY" in result

    def test_plain_mode_has_no_ansi(self):
        result = render(
            title="Test",
            columns=["A", "B"],
            rows=[("1", "2")],
            mode="plain",
        )
        assert "\x1b[" not in result

    def test_terminal_mode_has_ansi(self):
        result = render(
            title="Test",
            columns=["A", "B"],
            rows=[("1", "2")],
            mode="terminal",
        )
        assert "\x1b[" in result

    def test_empty_rows_returns_empty_string(self):
        result = render(
            title="Empty",
            columns=["A", "B"],
            rows=[],
            mode="plain",
        )
        assert result == ""

    def test_no_title(self):
        result = render(
            columns=["A", "B"],
            rows=[("1", "2")],
            mode="plain",
        )
        assert "1" in result
        assert "A" in result

    def test_unicode_content(self):
        result = render(
            title="People",
            columns=["Name", "Role"],
            rows=[("José García", "Analyst"), ("Müller", "Engineer")],
            mode="plain",
        )
        assert "José García" in result
        assert "Müller" in result

    def test_column_count_matches_row_length(self):
        """Extra columns or missing data should not crash."""
        result = render(
            title="Ragged",
            columns=["A", "B", "C"],
            rows=[("1", "2")],  # missing column C
            mode="plain",
        )
        assert "1" in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatter_tables.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'formatter.tables'`

**Step 3: Implement `formatter/tables.py`**

```python
"""Generic table rendering using rich.table.Table."""

from typing import Optional, Sequence
from rich.table import Table

from formatter.console import get_console, render_to_string
from formatter.styles import BOX, HEADER_STYLE


def render(
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
    mode: str = "terminal",
    title: Optional[str] = None,
    width: int = 80,
) -> str:
    """Render a table from structured data.

    Args:
        columns: Column header names.
        rows: List of row tuples/lists. Missing values padded with "".
        mode: "terminal" for ANSI output, "plain" for no-color text.
        title: Optional table title.
        width: Console width in characters.

    Returns:
        Rendered table as a string. Empty string if no rows.
    """
    if not rows:
        return ""

    table = Table(
        title=title,
        box=BOX,
        title_style=HEADER_STYLE,
        header_style="bold",
        show_lines=False,
        expand=True,
    )

    for col in columns:
        table.add_column(col)

    num_cols = len(columns)
    for row in rows:
        # Pad short rows with empty strings
        padded = list(row) + [""] * (num_cols - len(row))
        table.add_row(*[str(cell) for cell in padded[:num_cols]])

    console = get_console(mode=mode, width=width)
    console.print(table)
    return render_to_string(console)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_formatter_tables.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add formatter/tables.py tests/test_formatter_tables.py
git commit -m "feat: add formatter.tables with dual-mode table rendering"
```

---

### Task 3: Implement `formatter/cards.py` with TDD

**Files:**
- Create: `formatter/cards.py`
- Create: `tests/test_formatter_cards.py`

**Step 1: Write the failing tests**

Create `tests/test_formatter_cards.py`:

```python
"""Tests for formatter.cards — status cards and key-value panels."""

import pytest
from formatter.cards import render, render_kv


class TestCardRender:
    def test_basic_card(self):
        result = render(
            title="RBAC Project Status",
            status="yellow",
            fields={"Owner": "Sam Wilson", "Progress": "5%"},
            mode="plain",
        )
        assert "RBAC Project Status" in result
        assert "YELLOW" in result or "yellow" in result.lower()
        assert "Sam Wilson" in result
        assert "5%" in result

    def test_card_plain_no_ansi(self):
        result = render(
            title="Test",
            status="green",
            fields={"A": "B"},
            mode="plain",
        )
        assert "\x1b[" not in result

    def test_card_terminal_has_ansi(self):
        result = render(
            title="Test",
            status="green",
            fields={"A": "B"},
            mode="terminal",
        )
        assert "\x1b[" in result

    def test_card_no_status(self):
        result = render(
            title="Info Card",
            fields={"Key": "Value"},
            mode="plain",
        )
        assert "Info Card" in result
        assert "Value" in result

    def test_card_with_body_text(self):
        result = render(
            title="Alert",
            status="red",
            fields={"Issue": "Alchemy contract unsigned"},
            body="Escalation needed by Friday.",
            mode="plain",
        )
        assert "Escalation needed" in result


class TestKeyValueRender:
    def test_basic_kv(self):
        result = render_kv(
            fields={"Owner": "Shawn", "Progress": "5%", "Blocker": "Contract"},
            mode="plain",
        )
        assert "Owner" in result
        assert "Shawn" in result
        assert "Contract" in result

    def test_kv_empty_fields(self):
        result = render_kv(fields={}, mode="plain")
        assert result == ""
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatter_cards.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement `formatter/cards.py`**

```python
"""Status cards and key-value panels using rich.panel.Panel."""

from typing import Optional
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from formatter.console import get_console, render_to_string
from formatter.styles import BOX, STATUS_COLORS, HEADER_STYLE, PRIORITY_ICONS


def render_kv(
    fields: dict[str, str],
    mode: str = "terminal",
    width: int = 80,
) -> str:
    """Render key-value pairs as a borderless two-column table.

    Args:
        fields: Dict of label → value pairs.
        mode: "terminal" or "plain".
        width: Console width.

    Returns:
        Rendered key-value pairs. Empty string if no fields.
    """
    if not fields:
        return ""

    table = Table(show_header=False, box=None, expand=True, padding=(0, 1))
    table.add_column("Key", style="bold", ratio=1)
    table.add_column("Value", ratio=3)

    for key, value in fields.items():
        table.add_row(key, str(value))

    console = get_console(mode=mode, width=width)
    console.print(table)
    return render_to_string(console)


def render(
    title: str,
    fields: dict[str, str],
    mode: str = "terminal",
    status: Optional[str] = None,
    body: Optional[str] = None,
    width: int = 80,
) -> str:
    """Render a status card with optional status badge and body text.

    Args:
        title: Card title.
        fields: Key-value fields to display.
        mode: "terminal" or "plain".
        status: Optional status string (green/yellow/red/on_track/blocked).
        body: Optional body text below the fields.
        width: Console width.

    Returns:
        Rendered card as a string.
    """
    # Build subtitle with status badge
    subtitle = None
    if status:
        style = STATUS_COLORS.get(status.lower(), "bold")
        badge = status.upper()
        subtitle = Text(f" {badge} ", style=style)

    # Build inner content
    inner_table = Table(show_header=False, box=None, expand=True, padding=(0, 1))
    inner_table.add_column("Key", style="bold", ratio=1)
    inner_table.add_column("Value", ratio=3)
    for key, value in fields.items():
        inner_table.add_row(key, str(value))

    console = get_console(mode=mode, width=width)

    panel = Panel(
        inner_table,
        title=title,
        subtitle=subtitle,
        box=BOX,
        title_align="left",
    )
    console.print(panel)

    if body:
        console.print(f"\n{body}")

    return render_to_string(console)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_formatter_cards.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add formatter/cards.py tests/test_formatter_cards.py
git commit -m "feat: add formatter.cards with status cards and key-value panels"
```

---

### Task 4: Implement `formatter/dashboard.py` with TDD

**Files:**
- Create: `formatter/dashboard.py`
- Create: `tests/test_formatter_dashboard.py`

**Step 1: Write the failing tests**

Create `tests/test_formatter_dashboard.py`:

```python
"""Tests for formatter.dashboard — multi-panel grid layouts."""

import pytest
from formatter.dashboard import render
from formatter import tables


class TestDashboardRender:
    def test_basic_dashboard(self):
        panel_a = tables.render(
            title="Calendar",
            columns=["Time", "Event"],
            rows=[("8:30 AM", "ePMLT")],
            mode="plain",
        )
        result = render(
            title="Daily Status",
            panels=[
                {"title": "Schedule", "content": panel_a},
                {"title": "Notes", "content": "No notes today."},
            ],
            mode="plain",
        )
        assert "Daily Status" in result
        assert "Schedule" in result
        assert "Notes" in result

    def test_dashboard_plain_no_ansi(self):
        result = render(
            title="Test",
            panels=[{"title": "A", "content": "hello"}],
            mode="plain",
        )
        assert "\x1b[" not in result

    def test_dashboard_terminal_has_ansi(self):
        result = render(
            title="Test",
            panels=[{"title": "A", "content": "hello"}],
            mode="terminal",
        )
        assert "\x1b[" in result

    def test_empty_panels_returns_empty(self):
        result = render(title="Empty", panels=[], mode="plain")
        assert result == ""

    def test_single_panel(self):
        result = render(
            title="Solo",
            panels=[{"title": "Only", "content": "Just me"}],
            mode="plain",
        )
        assert "Solo" in result
        assert "Only" in result
        assert "Just me" in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatter_dashboard.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement `formatter/dashboard.py`**

```python
"""Multi-panel dashboard layouts using rich.panel.Panel and rich.columns.Columns."""

from typing import Sequence
from rich.panel import Panel
from rich.text import Text

from formatter.console import get_console, render_to_string
from formatter.styles import BOX, TITLE_STYLE, SUBTITLE_STYLE


def render(
    title: str,
    panels: Sequence[dict],
    mode: str = "terminal",
    columns: int = 1,
    width: int = 80,
) -> str:
    """Render a multi-panel dashboard.

    Args:
        title: Dashboard title.
        panels: List of dicts with "title" and "content" keys.
            Content can be a pre-rendered string or plain text.
        mode: "terminal" or "plain".
        columns: Number of columns for grid layout (default 1 = stacked).
        width: Console width.

    Returns:
        Rendered dashboard. Empty string if no panels.
    """
    if not panels:
        return ""

    console = get_console(mode=mode, width=width)

    # Outer dashboard header
    header = Panel(
        Text(title, justify="center"),
        box=BOX,
        style=TITLE_STYLE,
        expand=True,
    )
    console.print(header)

    # Render each panel
    for panel_data in panels:
        panel_title = panel_data.get("title", "")
        content = panel_data.get("content", "")

        section = Panel(
            content,
            title=f" {panel_title} ",
            title_align="left",
            box=BOX,
            subtitle_align="right",
            expand=True,
        )
        console.print(section)

    return render_to_string(console)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_formatter_dashboard.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add formatter/dashboard.py tests/test_formatter_dashboard.py
git commit -m "feat: add formatter.dashboard with multi-panel grid layouts"
```

---

### Task 5: Implement `formatter/brief.py` with TDD

**Files:**
- Create: `formatter/brief.py`
- Create: `tests/test_formatter_brief.py`

**Step 1: Write the failing tests**

Create `tests/test_formatter_brief.py`:

```python
"""Tests for formatter.brief — daily/weekly brief composition."""

import pytest
from formatter.brief import render_daily


class TestDailyBrief:
    def test_full_brief(self):
        result = render_daily(
            date="2026-02-25",
            calendar=[
                {"time": "8:30 AM", "event": "ePMLT", "status": "Zoom"},
                {"time": "10:30 AM", "event": "PwC Readout", "status": "⚠ KEY"},
            ],
            action_items=[
                {"priority": "urgent", "text": "Review PwC draft deck"},
                {"priority": "medium", "text": "Close Statuspage ticket"},
            ],
            conflicts=[
                {"time": "10:30-11:30", "a": "PwC Readout", "b": "SentinelOne"},
            ],
            email_highlights=[
                {"sender": "Collin Hoffman", "subject": "PwC draft", "tag": "prep"},
            ],
            personal=["BYU tour tomorrow evening"],
            mode="plain",
        )
        assert "DAILY BRIEFING" in result or "Daily Briefing" in result
        assert "2026-02-25" in result or "Feb 25" in result
        assert "ePMLT" in result
        assert "PwC Readout" in result
        assert "Review PwC draft deck" in result
        assert "Close Statuspage ticket" in result
        assert "SentinelOne" in result
        assert "Collin Hoffman" in result
        assert "BYU tour" in result

    def test_brief_plain_no_ansi(self):
        result = render_daily(
            date="2026-02-25",
            calendar=[{"time": "9 AM", "event": "Test", "status": "Zoom"}],
            mode="plain",
        )
        assert "\x1b[" not in result

    def test_brief_empty_sections_omitted(self):
        result = render_daily(
            date="2026-02-25",
            calendar=[],
            action_items=[],
            conflicts=[],
            email_highlights=[],
            personal=[],
            mode="plain",
        )
        # Should still have header but no section content
        assert "CALENDAR" not in result
        assert "ACTION" not in result

    def test_brief_only_calendar(self):
        result = render_daily(
            date="2026-02-25",
            calendar=[{"time": "9 AM", "event": "Standup", "status": "Teams"}],
            mode="plain",
        )
        assert "Standup" in result
        assert "ACTION" not in result

    def test_brief_date_formatting(self):
        result = render_daily(
            date="2026-02-25",
            calendar=[{"time": "9 AM", "event": "Test", "status": "OK"}],
            mode="plain",
        )
        # Should display a human-readable date
        assert "2026" in result or "Feb" in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatter_brief.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement `formatter/brief.py`**

```python
"""Daily and weekly brief composition using formatter components."""

from datetime import datetime
from typing import Optional, Sequence

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from formatter.console import get_console, render_to_string
from formatter.styles import BOX, INNER_BOX, PRIORITY_ICONS, TITLE_STYLE
from formatter.types import ActionItem, CalendarEntry, Conflict, EmailHighlight


def _format_date(date_str: str) -> str:
    """Convert ISO date string to human-readable format."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A, %B %-d, %Y")
    except (ValueError, TypeError):
        return date_str


def _build_calendar_table(entries: Sequence[CalendarEntry]) -> Table:
    """Build a rich Table from calendar entries."""
    table = Table(
        box=INNER_BOX,
        show_header=True,
        header_style="bold",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Time", style="bold", min_width=10)
    table.add_column("Event", ratio=3)
    table.add_column("Status", min_width=10)

    for entry in entries:
        table.add_row(
            entry.get("time", ""),
            entry.get("event", ""),
            entry.get("status", ""),
        )
    return table


def _build_action_items(items: Sequence[ActionItem]) -> str:
    """Build action items as formatted text lines."""
    lines = []
    for item in items:
        icon = PRIORITY_ICONS.get(item.get("priority", "medium"), "●")
        lines.append(f"  {icon}  {item.get('text', '')}")
    return "\n".join(lines)


def _build_conflicts(conflicts: Sequence[Conflict]) -> str:
    """Build conflict lines."""
    lines = []
    for c in conflicts:
        lines.append(f"  {c.get('time', '')}  {c.get('a', '')} ←→ {c.get('b', '')}")
    return "\n".join(lines)


def _build_email_table(highlights: Sequence[EmailHighlight]) -> Table:
    """Build email highlights table."""
    table = Table(
        box=INNER_BOX,
        show_header=True,
        header_style="bold",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Sender", ratio=1)
    table.add_column("Subject", ratio=2)
    table.add_column("Tag", min_width=8)

    for h in highlights:
        table.add_row(
            h.get("sender", ""),
            h.get("subject", ""),
            h.get("tag", ""),
        )
    return table


def render_daily(
    date: str,
    calendar: Optional[Sequence[CalendarEntry]] = None,
    action_items: Optional[Sequence[ActionItem]] = None,
    conflicts: Optional[Sequence[Conflict]] = None,
    email_highlights: Optional[Sequence[EmailHighlight]] = None,
    personal: Optional[Sequence[str]] = None,
    delegations: Optional[str] = None,
    decisions: Optional[str] = None,
    mode: str = "terminal",
    width: int = 80,
) -> str:
    """Render a daily brief from structured data.

    Args:
        date: ISO date string (YYYY-MM-DD).
        calendar: List of calendar entries.
        action_items: List of action items with priority.
        conflicts: List of scheduling conflicts.
        email_highlights: List of notable emails.
        personal: List of personal notes.
        delegations: Pre-formatted delegations text.
        decisions: Pre-formatted decisions text.
        mode: "terminal" or "plain".
        width: Console width.

    Returns:
        Rendered daily brief. Sections with no data are omitted.
    """
    calendar = calendar or []
    action_items = action_items or []
    conflicts = conflicts or []
    email_highlights = email_highlights or []
    personal = personal or []

    # Check if there's anything to render at all
    has_content = any([calendar, action_items, conflicts, email_highlights, personal, delegations, decisions])
    if not has_content:
        return ""

    console = get_console(mode=mode, width=width)
    human_date = _format_date(date)

    # Header
    header = Panel(
        Text(f"DAILY BRIEFING — {human_date}", justify="center", style="bold"),
        box=BOX,
        expand=True,
    )
    console.print(header)

    # Calendar section
    if calendar:
        cal_table = _build_calendar_table(calendar)
        console.print(Panel(cal_table, title=" CALENDAR ", title_align="left", box=BOX, expand=True))

    # Action items
    if action_items:
        items_text = _build_action_items(action_items)
        console.print(Panel(items_text, title=" ACTION ITEMS ", title_align="left", box=BOX, expand=True))

    # Conflicts
    if conflicts:
        conflict_text = _build_conflicts(conflicts)
        console.print(Panel(conflict_text, title=" CONFLICTS ", title_align="left", box=BOX, expand=True))

    # Email highlights
    if email_highlights:
        email_table = _build_email_table(email_highlights)
        console.print(Panel(email_table, title=" EMAIL HIGHLIGHTS ", title_align="left", box=BOX, expand=True))

    # Personal
    if personal:
        personal_text = "\n".join(f"  · {item}" for item in personal)
        console.print(Panel(personal_text, title=" PERSONAL ", title_align="left", box=BOX, expand=True))

    # Delegations
    if delegations:
        console.print(Panel(delegations, title=" DELEGATIONS ", title_align="left", box=BOX, expand=True))

    # Decisions
    if decisions:
        console.print(Panel(decisions, title=" DECISIONS ", title_align="left", box=BOX, expand=True))

    return render_to_string(console)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_formatter_brief.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add formatter/brief.py tests/test_formatter_brief.py
git commit -m "feat: add formatter.brief with daily brief composition"
```

---

### Task 6: Implement `formatter/text.py` (plain-text helpers)

**Files:**
- Create: `formatter/text.py`

**Step 1: Create the module**

This is a small utility module for the plain-text render path — used by email and notification delivery.

```python
"""Plain-text rendering helpers for non-terminal output (email, iMessage, notifications)."""

from formatter.styles import PRIORITY_ICONS


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from a string."""
    import re
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_escape.sub("", text)


def status_text(status: str) -> str:
    """Convert a status string to a plain-text badge.

    Args:
        status: Status string like "green", "yellow", "red".

    Returns:
        Plain-text badge like "[GREEN]", "[YELLOW]", "[RED]".
    """
    return f"[{status.upper()}]"


def priority_icon(priority: str) -> str:
    """Get the Unicode icon for a priority level."""
    return PRIORITY_ICONS.get(priority.lower(), "●")
```

**Step 2: Commit**

```bash
git add formatter/text.py
git commit -m "feat: add formatter.text plain-text rendering helpers"
```

---

### Task 7: Add MCP tool wrappers (`mcp_tools/formatter_tools.py`) with TDD

**Files:**
- Create: `mcp_tools/formatter_tools.py`
- Modify: `mcp_server.py` (add import and register call)
- Create: `tests/test_formatter_tools.py`

**Step 1: Write the failing tests**

Create `tests/test_formatter_tools.py`:

```python
"""Tests for MCP formatter tool wrappers."""

import json
import pytest

import mcp_server  # Trigger register() calls
from mcp_tools.formatter_tools import format_table, format_brief, format_dashboard


class TestFormatTable:
    @pytest.mark.asyncio
    async def test_format_table_returns_string(self):
        result = await format_table(
            title="Test",
            columns=json.dumps(["A", "B"]),
            rows=json.dumps([["1", "2"], ["3", "4"]]),
            mode="plain",
        )
        assert isinstance(result, str)
        assert "1" in result
        assert "A" in result

    @pytest.mark.asyncio
    async def test_format_table_empty_rows(self):
        result = await format_table(
            title="Empty",
            columns=json.dumps(["A"]),
            rows=json.dumps([]),
            mode="plain",
        )
        parsed = json.loads(result)
        assert parsed["result"] == ""


class TestFormatBrief:
    @pytest.mark.asyncio
    async def test_format_brief_returns_rendered(self):
        data = json.dumps({
            "date": "2026-02-25",
            "calendar": [{"time": "9 AM", "event": "Standup", "status": "Teams"}],
        })
        result = await format_brief(data=data, mode="plain")
        assert "Standup" in result

    @pytest.mark.asyncio
    async def test_format_brief_invalid_json(self):
        result = await format_brief(data="not json", mode="plain")
        parsed = json.loads(result)
        assert "error" in parsed


class TestFormatDashboard:
    @pytest.mark.asyncio
    async def test_format_dashboard_returns_rendered(self):
        panels = json.dumps([
            {"title": "Section A", "content": "Hello"},
            {"title": "Section B", "content": "World"},
        ])
        result = await format_dashboard(
            title="Test Dashboard",
            panels=panels,
            mode="plain",
        )
        assert "Test Dashboard" in result
        assert "Section A" in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatter_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_tools.formatter_tools'`

**Step 3: Create `mcp_tools/formatter_tools.py`**

```python
"""MCP tool wrappers for the formatter module."""

import json
import logging

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register formatter tools with the FastMCP server."""

    @mcp.tool()
    async def format_table(title: str, columns: str, rows: str, mode: str = "terminal") -> str:
        """Render a formatted table from structured data.

        Args:
            title: Table title
            columns: JSON array of column header names (e.g. '["Time", "Event", "Status"]')
            rows: JSON array of row arrays (e.g. '[["8:30 AM", "ePMLT", "Zoom"]]')
            mode: Render mode — "terminal" for ANSI color, "plain" for no-color text (default: terminal)
        """
        try:
            from formatter.tables import render
            parsed_columns = json.loads(columns)
            parsed_rows = json.loads(rows)
            result = render(
                title=title,
                columns=parsed_columns,
                rows=parsed_rows,
                mode=mode,
            )
            if not result:
                return json.dumps({"result": ""})
            return result
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            logger.exception("Error in format_table")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def format_brief(data: str, mode: str = "terminal") -> str:
        """Render a daily brief from structured JSON data.

        Args:
            data: JSON object with keys: date, calendar, action_items, conflicts, email_highlights, personal
            mode: Render mode — "terminal" for ANSI color, "plain" for no-color text (default: terminal)
        """
        try:
            from formatter.brief import render_daily
            parsed = json.loads(data)
            result = render_daily(**parsed, mode=mode)
            if not result:
                return json.dumps({"result": ""})
            return result
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            logger.exception("Error in format_brief")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def format_dashboard(title: str, panels: str, columns: int = 1, mode: str = "terminal") -> str:
        """Render a multi-panel dashboard.

        Args:
            title: Dashboard title
            panels: JSON array of panel objects with "title" and "content" keys
            columns: Number of columns for grid layout (default: 1)
            mode: Render mode — "terminal" for ANSI color, "plain" for no-color text (default: terminal)
        """
        try:
            from formatter.dashboard import render
            parsed_panels = json.loads(panels)
            result = render(
                title=title,
                panels=parsed_panels,
                columns=columns,
                mode=mode,
            )
            if not result:
                return json.dumps({"result": ""})
            return result
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            logger.exception("Error in format_dashboard")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def format_card(title: str, fields: str, status: str = "", body: str = "", mode: str = "terminal") -> str:
        """Render a status card with key-value fields and optional status badge.

        Args:
            title: Card title
            fields: JSON object of key-value pairs (e.g. '{"Owner": "Shawn", "Progress": "5%"}')
            status: Optional status string (green/yellow/red/on_track/blocked)
            body: Optional body text below the fields
            mode: Render mode — "terminal" for ANSI color, "plain" for no-color text (default: terminal)
        """
        try:
            from formatter.cards import render
            parsed_fields = json.loads(fields)
            result = render(
                title=title,
                fields=parsed_fields,
                status=status or None,
                body=body or None,
                mode=mode,
            )
            return result
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            logger.exception("Error in format_card")
            return json.dumps({"error": str(e)})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.format_table = format_table
    module.format_brief = format_brief
    module.format_dashboard = format_dashboard
    module.format_card = format_card
```

**Step 4: Register in `mcp_server.py`**

Add to the imports block (around line 200, with the other `from mcp_tools import ...`):

```python
from mcp_tools import formatter_tools
```

Add to the registration block (with the other `*.register(mcp, _state)` calls):

```python
formatter_tools.register(mcp, _state)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_formatter_tools.py -v`
Expected: All 5 tests PASS

**Step 6: Run the full test suite**

Run: `pytest --tb=short -q`
Expected: All existing tests still pass, plus the new formatter tests.

**Step 7: Commit**

```bash
git add mcp_tools/formatter_tools.py mcp_server.py tests/test_formatter_tools.py
git commit -m "feat: add MCP formatter tools and register in mcp_server"
```

---

### Task 8: Update `formatter/__init__.py` and verify end-to-end

**Files:**
- Modify: `formatter/__init__.py` (ensure all modules export correctly)

**Step 1: Verify the `__init__.py` imports work**

Run: `python -c "from formatter import tables, cards, brief, dashboard; print('OK')"`
Expected: `OK`

**Step 2: Run a quick smoke test in Python**

```bash
python -c "
from formatter.tables import render
print(render(title='Test', columns=['A','B'], rows=[('1','2')], mode='plain'))
"
```

Expected: A plain-text table with columns A, B and values 1, 2 inside double-line box borders.

**Step 3: Run the full test suite one more time**

Run: `pytest --tb=short -q`
Expected: All tests pass.

**Step 4: Commit**

```bash
git add formatter/__init__.py
git commit -m "feat: finalize formatter package with public API exports"
```

---

### Task 9 (Optional): Integrate with delivery adapters

**Files:**
- Modify: `scheduler/delivery.py` (use formatter for email delivery)

This task is optional and can be done after the core formatter is working. The idea is to update the `EmailDeliveryAdapter` to use `brief.render_daily(..., mode="plain")` when delivering scheduled task results that contain structured brief data.

**Step 1: Read `scheduler/delivery.py` to understand current pattern**

Check the current `EmailDeliveryAdapter.deliver()` method.

**Step 2: Add formatter import and conditional formatting**

If the result data looks like a brief (has `calendar`, `action_items` keys), render it through the formatter. Otherwise, pass through as-is.

**Step 3: Test manually by triggering a scheduled brief delivery**

**Step 4: Commit**

```bash
git add scheduler/delivery.py
git commit -m "feat: integrate formatter with email delivery adapter"
```
