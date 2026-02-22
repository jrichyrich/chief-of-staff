"""Built-in hook implementations: audit logging and timing."""

import json
import logging
import time
from pathlib import Path
from typing import Any

import config as app_config

logger = logging.getLogger("jarvis-mcp.hooks")

# Default audit log path
AUDIT_LOG_PATH = app_config.DATA_DIR / "audit.jsonl"

# Module-level timing store (maps tool call timestamp -> start time)
_timing_store: dict[str, float] = {}


def audit_log_hook(context: dict) -> dict[str, Any]:
    """Append a JSON line to the audit log for every tool call.

    Works as both a before_tool_call and after_tool_call hook.
    """
    log_path = Path(AUDIT_LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": context.get("timestamp", ""),
        "tool_name": context.get("tool_name", ""),
        "agent_name": context.get("agent_name", ""),
        "event": "after_tool_call" if "result" in context else "before_tool_call",
    }

    # Include args only for before_tool_call (to avoid double-logging)
    if "result" not in context:
        entry["tool_args"] = context.get("tool_args", {})
    else:
        # Truncate large results to keep the log manageable
        result = context.get("result")
        result_str = str(result)
        if len(result_str) > 500:
            result_str = result_str[:500] + "...[truncated]"
        entry["result_preview"] = result_str

    with open(log_path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    return entry


def timing_before_hook(context: dict) -> None:
    """Record the start time for a tool call (before_tool_call)."""
    key = context.get("timestamp", "")
    _timing_store[key] = time.monotonic()


def timing_after_hook(context: dict) -> dict[str, Any] | None:
    """Calculate and return elapsed time for a tool call (after_tool_call).

    Expects the same timestamp key that was passed to timing_before_hook.
    """
    key = context.get("timestamp", "")
    start = _timing_store.pop(key, None)
    if start is None:
        return None
    elapsed = time.monotonic() - start
    return {
        "tool_name": context.get("tool_name", ""),
        "elapsed_seconds": round(elapsed, 4),
    }
