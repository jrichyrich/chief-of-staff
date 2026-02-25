"""Generic table rendering with dual-mode output (terminal ANSI / plain Unicode)."""

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
    """Render a table as a string.

    Args:
        columns: Column header labels.
        rows: Row data.  Rows shorter than *columns* are padded with empty
            strings so that Rich never raises on a column-count mismatch.
        mode: "terminal" for ANSI colour output, "plain" for no escape codes.
        title: Optional table title shown above the header row.
        width: Fixed output width in columns.

    Returns:
        The rendered table string, or an empty string when *rows* is empty.
    """
    if not rows:
        return ""

    num_cols = len(columns)

    table = Table(title=title, box=BOX, header_style=HEADER_STYLE, width=width)

    for col in columns:
        table.add_column(col)

    for row in rows:
        # Pad short rows with empty strings so Rich does not crash.
        padded = list(row) + [""] * (num_cols - len(row))
        table.add_row(*padded[:num_cols])

    console = get_console(mode=mode, width=width)
    console.print(table)
    return render_to_string(console)
