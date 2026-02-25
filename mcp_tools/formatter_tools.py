"""MCP tool wrappers for the formatter module.

These tools are intended for **delivery channels** (scheduled tasks, email,
iMessage, macOS notifications) where the consumer is a human reading rendered
output.  In interactive Claude Code sessions the formatter adds ~2x token
overhead for no visual benefit — ANSI codes are not interpreted and box-drawing
art must be re-parsed by the model.  For Claude Code, skip these tools and
present raw structured data with markdown commentary instead.
"""

import json
import logging
import sys

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register formatter tools with the FastMCP server."""

    @mcp.tool()
    async def format_table(title: str, columns: str, rows: str, mode: str = "terminal") -> str:
        """Render a formatted table from structured data.

        Args:
            title: Table title
            columns: JSON array of column header names (e.g. '["Time", "Event", "Status"]')
            rows: JSON array of row arrays (e.g. '[["8:30 AM", "ePMLT", "Zoom"]]')
            mode: Render mode — "terminal" for ANSI color, "plain" for no-color text (default: terminal)
        """
        try:
            from formatter.tables import render
            parsed_columns = json.loads(columns)
            parsed_rows = json.loads(rows)
            result = render(
                title=title,
                columns=parsed_columns,
                rows=parsed_rows,
                mode=mode,
            )
            if not result:
                return json.dumps({"result": ""})
            return result
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            logger.exception("Error in format_table")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def format_brief(data: str, mode: str = "terminal") -> str:
        """Render a daily brief from structured JSON data.

        **Intended for delivery channels** (email, iMessage, notification).
        In interactive Claude Code sessions, skip this tool — present the raw
        data as markdown instead to save ~50% tokens.

        Plain strings are accepted wherever dicts are expected — they will be
        coerced automatically (e.g. "Fix bug" becomes {"text": "Fix bug", "priority": "medium"}).

        Args:
            data: JSON object with these keys (all optional except date):
                date        — "YYYY-MM-DD" or human-readable like "Wednesday, February 25, 2026"
                calendar    — [{"time": "9 AM", "event": "Standup", "status": "Teams"}] or ["9 AM - Standup"]
                action_items — [{"text": "Review RBAC", "priority": "high|medium|low"}] or ["Review RBAC"]
                conflicts   — [{"time": "2 PM", "a": "Meeting A", "b": "Meeting B"}] or ["2 PM: A vs B"]
                email_highlights — [{"sender": "Mike", "subject": "Budget", "tag": "action"}] or ["Check Outlook"]
                personal    — ["Pick up dry cleaning"]
                delegations — "2 active delegations" (summary string)
                decisions   — "1 pending decision" (summary string)
                delegation_items — [{"task": "X", "delegated_to": "Y", "priority": "high", "status": "active"}]
                decision_items   — [{"title": "X", "status": "pending_execution", "owner": "Y"}]
                okr_highlights   — [{"initiative": "X", "team": "IAM", "status": "On Track", "progress": "80%"}]
            mode: Render mode — "terminal" for ANSI color, "plain" for no-color text (default: terminal)
        """
        try:
            from formatter.brief import render_daily
            parsed = json.loads(data)
            result = render_daily(**parsed, mode=mode)
            if not result:
                return json.dumps({"result": ""})
            return result
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            logger.exception("Error in format_brief")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def format_dashboard(title: str, panels: str, columns: int = 1, mode: str = "terminal") -> str:
        """Render a multi-panel dashboard.

        Args:
            title: Dashboard title
            panels: JSON array of panel objects with "title" and "content" keys
            columns: Number of columns for grid layout (default: 1)
            mode: Render mode — "terminal" for ANSI color, "plain" for no-color text (default: terminal)
        """
        try:
            from formatter.dashboard import render
            parsed_panels = json.loads(panels)
            result = render(
                title=title,
                panels=parsed_panels,
                columns=columns,
                mode=mode,
            )
            if not result:
                return json.dumps({"result": ""})
            return result
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            logger.exception("Error in format_dashboard")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def format_card(title: str, fields: str, status: str = "", body: str = "", mode: str = "terminal") -> str:
        """Render a status card with key-value fields and optional status badge.

        Args:
            title: Card title
            fields: JSON object of key-value pairs (e.g. '{"Owner": "Shawn", "Progress": "5%"}')
            status: Optional status string (green/yellow/red/on_track/blocked)
            body: Optional body text below the fields
            mode: Render mode — "terminal" for ANSI color, "plain" for no-color text (default: terminal)
        """
        try:
            from formatter.cards import render
            parsed_fields = json.loads(fields)
            result = render(
                title=title,
                fields=parsed_fields,
                status=status or None,
                body=body or None,
                mode=mode,
            )
            return result
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            logger.exception("Error in format_card")
            return json.dumps({"error": str(e)})

    # Expose tool functions at module level for testing
    module = sys.modules[__name__]
    module.format_table = format_table
    module.format_brief = format_brief
    module.format_dashboard = format_dashboard
    module.format_card = format_card
