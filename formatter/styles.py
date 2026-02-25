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
    "urgent": "\u26a0",
    "high": "\u2605",
    "medium": "\u25cf",
    "low": "\u25cb",
    "fyi": "\u00b7",
}

# Section header style
HEADER_STYLE = "bold white"
TITLE_STYLE = "bold white on blue"
SUBTITLE_STYLE = "bold cyan"
DIM_STYLE = "dim"
