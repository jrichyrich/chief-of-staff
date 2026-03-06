"""Shared AppleScript utilities."""


def escape_osascript(text: str) -> str:
    """Escape text for safe use in AppleScript strings."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
