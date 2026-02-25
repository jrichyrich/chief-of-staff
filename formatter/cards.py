"""Status cards and key-value panels for formatted CLI output."""

from __future__ import annotations

from typing import Optional

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from formatter.console import get_console, render_to_string
from formatter.styles import BOX, HEADER_STYLE, STATUS_COLORS


def render_kv(fields: dict[str, str], mode: str = "terminal", width: int = 80) -> str:
    """Render key-value pairs as a borderless two-column table.

    Args:
        fields: Dictionary of key-value pairs to display.
        mode: "terminal" for ANSI colour output, "plain" for no markup.
        width: Console width in characters.

    Returns:
        Rendered string, or empty string if fields is empty.
    """
    if not fields:
        return ""

    console = get_console(mode=mode, width=width)

    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 1))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    for key, value in fields.items():
        table.add_row(key, value)

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
        title: Card title displayed at the top of the panel.
        fields: Key-value pairs to display inside the card.
        mode: "terminal" for ANSI colour output, "plain" for no markup.
        status: Optional status string (e.g. "ok", "fail") for a coloured badge.
        body: Optional body text displayed below the key-value fields.
        width: Console width in characters.

    Returns:
        Rendered card string.
    """
    console = get_console(mode=mode, width=width)

    # Build the inner content: key-value table
    inner_parts: list = []

    if fields:
        table = Table(show_header=False, show_edge=False, box=None, padding=(0, 1))
        table.add_column("Key", style="bold")
        table.add_column("Value")
        for key, value in fields.items():
            table.add_row(key, value)
        inner_parts.append(table)

    if body:
        inner_parts.append(Text(body))

    # Build subtitle with status badge
    subtitle: Optional[str] = None
    if status:
        color = STATUS_COLORS.get(status.lower(), "white")
        subtitle = f"[{color}]{status.upper()}[/{color}]"

    # Combine inner content into a renderables group
    from rich.console import Group

    content = Group(*inner_parts) if inner_parts else Text("")

    panel = Panel(
        content,
        title=title,
        title_align="left",
        subtitle=subtitle,
        subtitle_align="right",
        box=BOX,
        style=HEADER_STYLE,
        width=width,
    )

    console.print(panel)
    return render_to_string(console)
