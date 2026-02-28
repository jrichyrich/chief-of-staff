"""Shared decorators for MCP tool handlers."""

import functools
import json
import logging

logger = logging.getLogger("jarvis-mcp")


def tool_errors(context: str, expected: tuple = ()):
    """Standardize error handling for MCP tool handlers.

    Catches *expected* exception types and returns a JSON error with the given
    context prefix.  Any other exception is logged via ``logger.exception``
    and returned as an "Unexpected error".

    Usage::

        @mcp.tool()
        @tool_errors("Calendar error", expected=(OSError, TimeoutError))
        async def list_calendars(...) -> str:
            ...  # only the happy path — no try/except needed
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except expected as e:
                return json.dumps({"error": f"{context}: {e}"})
            except Exception as e:
                logger.exception("Unexpected error in %s", func.__name__)
                return json.dumps({"error": f"Unexpected error ({type(e).__name__}). Check server logs."})

        return wrapper

    return decorator
