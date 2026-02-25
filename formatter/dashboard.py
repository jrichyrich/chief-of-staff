"""Multi-panel dashboard layouts using Rich."""

from __future__ import annotations

from typing import Sequence

from rich.align import Align
from rich.panel import Panel

from formatter.console import get_console, render_to_string
from formatter.styles import BOX, TITLE_STYLE


def render(
    title: str,
    panels: Sequence[dict],
    mode: str = "terminal",
    columns: int = 1,
    width: int = 80,
) -> str:
    """Render a multi-panel dashboard as a string.

    Args:
        title: Dashboard header title.
        panels: Sequence of dicts, each with ``"title"`` and ``"content"`` keys.
        mode: ``"terminal"`` for ANSI colour output, ``"plain"`` for no ANSI.
        columns: Number of columns in the grid layout (reserved for future use).
        width: Fixed output width.

    Returns:
        Rendered dashboard string, or empty string if *panels* is empty.
    """
    if not panels:
        return ""

    console = get_console(mode=mode, width=width)

    # Header panel with title centered, using BOX style
    header = Panel(
        Align.center(title),
        box=BOX,
        style=TITLE_STYLE,
        width=width,
    )
    console.print(header)

    # Render each section panel
    for panel_spec in panels:
        section = Panel(
            panel_spec["content"],
            title=panel_spec["title"],
            title_align="left",
            width=width,
        )
        console.print(section)

    return render_to_string(console)
