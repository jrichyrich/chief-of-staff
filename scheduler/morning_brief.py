"""Morning brief handler — spawns a Claude CLI session to produce a daily brief.

Claude Code has access to all MCP connectors (Jarvis, M365, Atlassian) so it can
query every data source in parallel, synthesize conflicts and priorities, and
return a polished markdown brief.  The handler captures the output and returns it
as the task result, which the delivery system then routes to email/iMessage/etc.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Defaults — overridable via handler_config
_DEFAULT_CLAUDE_BIN = "/opt/homebrew/bin/claude"
_DEFAULT_MODEL = "sonnet"
_DEFAULT_TIMEOUT = 180  # 3 minutes — brief needs many MCP calls
_DEFAULT_PROJECT_DIR = str(Path(__file__).parent.parent)

_BRIEF_PROMPT = """\
Generate my morning brief for today.  Follow these rules exactly:

1. Query ALL of these sources IN PARALLEL:
   - M365 Calendar (outlook_calendar_search) — today's meetings, start/end/attendees
   - Apple Calendar (get_calendar_events) — today, provider_preference="both"
   - M365 Email (outlook_email_search) — last 24h, unread/flagged
   - M365 Teams (chat_message_search) — last 24h, mentions and DMs
   - iMessages (get_imessages) — last 24h
   - Delegations (list_delegations, status="active")
   - Pending decisions (list_pending_decisions)
   - Reminders (list_reminders)
   - Overdue delegations (check_overdue_delegations)

2. Synthesize into a clear markdown brief with these sections:
   ## Schedule
   Chronological list of today's meetings with times, attendees, and prep notes.
   Flag any conflicts or back-to-back meetings.

   ## Action Items
   Overdue delegations, pending decisions, and due reminders.
   Prioritize by urgency.

   ## Communications
   Important unread emails, Teams messages, and iMessages that need attention.
   Group by urgency, not by source.

   ## Heads Up
   Anything noteworthy: upcoming deadlines this week, stale decisions, patterns.

3. Be concise.  No filler.  Use bullet points.  Bold key names/times.
4. If a source returns empty or errors, skip it silently — do not mention it.
5. Do NOT call format_brief or any formatter tools — output raw markdown.
"""


def run_morning_brief(handler_config: str = "") -> str:
    """Spawn a Claude CLI session to produce the morning brief.

    Args:
        handler_config: JSON string with optional overrides:
            - claude_bin: path to claude binary
            - model: Claude model to use (default: sonnet)
            - timeout: max seconds to wait (default: 180)
            - project_dir: project directory for MCP config
            - prompt_extra: additional instructions appended to the prompt

    Returns:
        JSON string with status and the brief text (or error).
    """
    config = _parse_config(handler_config)

    claude_bin = config.get("claude_bin", _DEFAULT_CLAUDE_BIN)
    model = config.get("model", _DEFAULT_MODEL)
    timeout = int(config.get("timeout", _DEFAULT_TIMEOUT))
    project_dir = config.get("project_dir", _DEFAULT_PROJECT_DIR)
    prompt_extra = config.get("prompt_extra", "")

    prompt = _BRIEF_PROMPT
    if prompt_extra:
        prompt += f"\n\nAdditional instructions:\n{prompt_extra}"

    mcp_config = str(Path(project_dir) / ".mcp.json")

    args = [
        claude_bin,
        "-p", prompt,
        "--output-format", "text",
        "--no-session-persistence",
        "--model", model,
        "--mcp-config", mcp_config,
        "--dangerously-skip-permissions",
    ]

    # Build a clean env — strip CLAUDECODE to allow spawning from inside
    # a Claude Code session (MCP server runs as a Claude Code child process).
    import os
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env.setdefault("HOME", os.path.expanduser("~"))
    env.setdefault("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin")

    logger.info("Spawning Claude CLI for morning brief (model=%s, timeout=%ds)", model, timeout)

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        logger.error("Morning brief timed out after %ds", timeout)
        return json.dumps({
            "status": "error",
            "handler": "morning_brief",
            "error": f"Claude CLI timed out after {timeout}s",
        })
    except FileNotFoundError:
        logger.error("Claude CLI not found at %s", claude_bin)
        return json.dumps({
            "status": "error",
            "handler": "morning_brief",
            "error": f"Claude binary not found: {claude_bin}",
        })
    except Exception as e:
        logger.error("Morning brief failed: %s", e)
        return json.dumps({
            "status": "error",
            "handler": "morning_brief",
            "error": str(e),
        })

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:500]
        logger.error("Claude CLI exited %d: %s", proc.returncode, err)
        return json.dumps({
            "status": "error",
            "handler": "morning_brief",
            "error": f"Claude CLI exit code {proc.returncode}: {err}",
        })

    brief_text = (proc.stdout or "").strip()
    if not brief_text:
        return json.dumps({
            "status": "error",
            "handler": "morning_brief",
            "error": "Claude CLI returned empty output",
        })

    logger.info("Morning brief generated (%d chars)", len(brief_text))
    return json.dumps({
        "status": "ok",
        "handler": "morning_brief",
        "brief": brief_text,
    })


def _parse_config(config_str: str) -> dict:
    """Safely parse handler_config JSON."""
    if not config_str or not config_str.strip():
        return {}
    try:
        value = json.loads(config_str)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
