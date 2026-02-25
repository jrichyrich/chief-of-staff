"""MCP tool wrappers for the formatter module."""

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

        Args:
            data: JSON object with keys: date, calendar, action_items, conflicts, email_highlights, personal, delegations, decisions
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
