"""Plain-text rendering helpers for non-terminal output (email, iMessage, notifications)."""

import re

from formatter.styles import PRIORITY_ICONS

_ANSI_ESCAPE = re.compile(r"\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from a string."""
    return _ANSI_ESCAPE.sub("", text)


def status_text(status: str) -> str:
    """Convert a status string to a plain-text badge."""
    return f"[{status.upper()}]"


def priority_icon(priority: str) -> str:
    """Get the Unicode icon for a priority level."""
    return PRIORITY_ICONS.get(priority.lower(), "●")
