"""Hook function for integrating the humanizer with the Jarvis hook system."""

from typing import Any

from humanizer.rules import humanize

# Tools whose text fields should be humanized
OUTBOUND_TOOLS = frozenset({
    "send_email",
    "reply_to_email",
    "send_imessage_reply",
})

# Fields to humanize on outbound tools
TEXT_FIELDS = ("body", "subject")


def humanize_hook(context: dict) -> dict[str, Any] | None:
    """before_tool_call hook that humanizes outbound text fields.

    Returns modified tool_args dict if the tool is an outbound communication
    tool and has text fields to transform. Returns None otherwise.
    """
    tool_name = context.get("tool_name", "")
    if tool_name not in OUTBOUND_TOOLS:
        return None

    tool_args = context.get("tool_args", {})
    if not tool_args:
        return None

    modified = dict(tool_args)
    changed = False

    for field in TEXT_FIELDS:
        value = modified.get(field)
        if value and isinstance(value, str):
            cleaned = humanize(value)
            if cleaned != value:
                modified[field] = cleaned
                changed = True

    if not changed:
        return None

    return {"tool_args": modified}
