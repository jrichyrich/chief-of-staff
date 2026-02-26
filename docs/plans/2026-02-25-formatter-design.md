# Formatter Module Design

## Overview

A `formatter/` module internal to Jarvis that uses `rich` to render structured data as visually polished terminal output and plain-text output. Every Jarvis output surface — conversation responses, email bodies, MCP tool returns, scheduled task deliveries — gets consistent, dashboard-style formatting.

## Problem

All MCP tool responses return raw `json.dumps()` strings. Daily briefs and reports rely on Claude writing ad-hoc markdown. Email bodies are flat plain text. There is no shared formatting layer, no tables, no dashboards, no visual hierarchy.

## Decision

- Use `rich` (single new dependency, v13.0+)
- Internal library (`formatter/` package), not a standalone published package
- Dual-mode rendering: `"terminal"` (ANSI colors) and `"plain"` (Unicode box-drawing, no ANSI)
- Boxed structured style with double-line borders (╔═╗)
- Expose via new MCP tools so Claude can call formatters directly

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Data Sources                       │
│  (MCP tools, agents, memory, calendar, email)        │
│  All return dicts/lists/JSON as they do today        │
└──────────────────────┬──────────────────────────────┘
                       │ structured data (dicts/lists)
                       ▼
┌─────────────────────────────────────────────────────┐
│              formatter/ module                        │
│                                                       │
│  formatter/console.py   ← shared Console singleton   │
│  formatter/brief.py     ← daily/weekly brief layout  │
│  formatter/tables.py    ← generic table rendering    │
│  formatter/dashboard.py ← multi-panel dashboards     │
│  formatter/cards.py     ← status cards, summaries    │
│  formatter/text.py      ← plain-text render target   │
│  formatter/styles.py    ← colors, icons, constants   │
│  formatter/types.py     ← TypedDicts for input data  │
│                                                       │
│  Each module: takes structured data → returns string  │
│  Two render modes: "terminal" (ANSI) / "plain" (text)│
└──────────┬──────────────────────┬───────────────────┘
           │                      │
     terminal (ANSI)        plain text
           │                      │
           ▼                      ▼
    Claude Code CLI         Email bodies
    Direct terminal         iMessages
                            Notifications
```

## Components

### Core Building Blocks

| Component | Purpose | Rich Feature |
|-----------|---------|--------------|
| `Table` | Any tabular data (calendar, emails, OKRs) | `rich.table.Table` |
| `Panel` | Boxed section with title (brief sections, status cards) | `rich.panel.Panel` |
| `Dashboard` | Multi-panel grid layout (daily brief, project status) | `rich.layout.Layout` + `rich.columns.Columns` |
| `StatusBadge` | Inline indicators: `[GREEN]`, `[YELLOW]`, `⚠ URGENT` | `rich.text.Text` with styles |
| `KeyValue` | Labeled data pairs (initiative details, person info) | `rich.table.Table` (borderless, 2-col) |

### Composed Output Types

| Output Type | Components Used | Surfaces |
|-------------|----------------|----------|
| Daily Brief | Dashboard → Panels (Calendar, Actions, Email, Personal) with Tables | Terminal + Email |
| Weekly Brief | Dashboard → day-by-day Panels with summary Tables | Terminal + Email |
| Calendar View | Table with time, event, attendees, status columns | Terminal + Email |
| Project Status | Panel with StatusBadge header → KeyValue pairs → Table | Terminal + Email |
| Email Inbox | Table with sender, subject, date, read/flagged indicators | Terminal |
| Person Enrichment | Panel → KeyValue for identity + Tables for messages | Terminal |
| Memory Query | Table with category, key, value, confidence columns | Terminal |

## API Design

### Public API

```python
from formatter import brief, tables, dashboard, cards

# Tables
tables.render(
    title="Calendar",
    columns=["Time", "Event", "Status"],
    rows=[("8:30 AM", "ePMLT", "Zoom"), ("10:30 AM", "PwC Readout", "⚠ KEY")],
    mode="terminal"  # or "plain"
) → str

# Status Cards
cards.render(
    title="RBAC Project Status",
    status="yellow",
    fields={"Owner": "Sam Wilson", "Progress": "5%", "Blocker": "Alchemy contract"},
    mode="terminal"
) → str

# Daily Brief (composed)
brief.render_daily(
    date="2026-02-25",
    calendar=[{"time": "8:30 AM", "event": "ePMLT", "status": "Zoom"}, ...],
    action_items=[{"priority": "high", "text": "Review PwC deck"}, ...],
    conflicts=[{"time": "10:30-11:30", "a": "PwC Readout", "b": "SentinelOne"}],
    email_highlights=[{"sender": "Collin Hoffman", "subject": "PwC draft", "tag": "prep"}],
    personal=["BYU tour tomorrow evening"],
    mode="terminal"
) → str

# Dashboard (arbitrary grid)
dashboard.render(
    title="ISP Weekly Status",
    panels=[
        {"title": "OKR Progress", "content": tables.render(...)},
        {"title": "Blockers", "content": cards.render(...)},
    ],
    columns=2,
    mode="terminal"
) → str
```

### Design Principles

1. Everything returns `str` — caller decides what to do with it
2. `mode` parameter everywhere — `"terminal"` for ANSI, `"plain"` for emails/iMessages
3. Data in, string out — no side effects, purely functional
4. Composable — dashboard accepts output from tables and cards as panel content
5. Sensible defaults — auto column widths, default colors per status, double-line box style

### Console Singleton

```python
from rich.console import Console
from io import StringIO

def get_console(mode="terminal", width=80):
    if mode == "plain":
        return Console(file=StringIO(), force_terminal=False, width=width)
    return Console(force_terminal=True, width=width)
```

## Shared Design Language (styles.py)

```python
STATUS_COLORS = {
    "green": "bold green",
    "yellow": "bold yellow",
    "red": "bold red",
    "on_track": "bold green",
    "at_risk": "bold yellow",
    "blocked": "bold red",
}

PRIORITY_ICONS = {
    "urgent": "⚠",
    "high": "★",
    "medium": "●",
    "low": "○",
    "fyi": "·",
}

BOX = rich.box.DOUBLE
```

## Integration Points

### 1. MCP Tools (new)

```python
# mcp_tools/formatter_tools.py
@mcp.tool()
async def format_brief(data: str, mode: str = "terminal") -> str:
    """Render a daily/weekly brief from structured JSON data."""

@mcp.tool()
async def format_table(title: str, columns: str, rows: str, mode: str = "terminal") -> str:
    """Render a table from structured data."""

@mcp.tool()
async def format_dashboard(title: str, panels: str, columns: int = 2, mode: str = "terminal") -> str:
    """Render a multi-panel dashboard."""
```

### 2. Email Bodies

Same formatter with `mode="plain"` — Unicode box-drawing without ANSI colors.

### 3. Delivery Adapters

`scheduler/delivery.py` calls formatters with `mode="plain"` before passing to email/iMessage/notification adapters.

### 4. What Does NOT Change

- Existing MCP tools keep returning JSON
- Agent system (`agents/base.py`) untouched
- Hook system untouched
- Memory/document stores untouched

## File Structure

```
formatter/
├── __init__.py          # Public API re-exports
├── console.py           # Console singleton, mode switching
├── tables.py            # Table rendering (generic)
├── cards.py             # Status cards, key-value panels
├── brief.py             # Daily/weekly brief composers
├── dashboard.py         # Multi-panel grid layouts
├── text.py              # Plain-text render helpers
├── styles.py            # Color palette, status badges, constants
└── types.py             # TypedDicts for structured input data

mcp_tools/
└── formatter_tools.py   # MCP tool wrappers

tests/
├── test_formatter_tables.py
├── test_formatter_cards.py
├── test_formatter_brief.py
├── test_formatter_dashboard.py
└── test_formatter_tools.py
```

## Dependencies

Single addition to `pyproject.toml`:

```toml
dependencies = [
    "rich>=13.0",
]
```

## Testing Strategy

- Unit tests per component: data in, assert content presence in output string
- Plain mode: assert no ANSI escape codes (`\x1b[` not in result)
- Terminal mode: assert ANSI escape codes present
- Composed outputs: assert all sections present in briefs/dashboards
- Edge cases: empty data, long text wrapping, Unicode in data
- MCP tool wrappers: async tests verifying string returns
- Do NOT test `rich` internals — test content presence, not exact spacing

## Visual Example

```
╔══════════════════════════════════════════════════════════════╗
║  DAILY BRIEFING                          Wed Feb 25, 2026   ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  ┌─ CALENDAR ──────────────────────────────────────────────┐ ║
║  │ TIME       │ EVENT                        │ STATUS      │ ║
║  │────────────│──────────────────────────────│─────────────│ ║
║  │  8:30 AM   │ ePMLT (90 min)               │ Zoom        │ ║
║  │ 10:30 AM   │ PwC Threat Assessment         │ ⚠ KEY      │ ║
║  │ 11:30 AM   │ Privacy Training              │ Zoom        │ ║
║  │ 12:00 PM   │ Interview: Meera Rao          │ ⚠ KEY      │ ║
║  │  4:00 PM   │ Performance Review            │ ⚠ KEY      │ ║
║  └─────────────────────────────────────────────────────────┘ ║
║                                                              ║
║  ┌─ ACTION ITEMS ──────────────────────────────────────────┐ ║
║  │ ⚠  Review PwC draft deck before 10:30 AM               │ ║
║  │ ⚠  Prepare performance review talking points            │ ║
║  │ ●  Close Statuspage test ticket (12+ hours)             │ ║
║  └─────────────────────────────────────────────────────────┘ ║
║                                                              ║
║  ┌─ CONFLICTS ─────────────────────────────────────────────┐ ║
║  │ 10:30-11:30  PwC Readout ←→ SentinelOne Sync           │ ║
║  │ 12:00-1:00   Meera Rao Interview ←→ Lunch              │ ║
║  └─────────────────────────────────────────────────────────┘ ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```
