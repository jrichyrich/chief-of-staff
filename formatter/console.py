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
