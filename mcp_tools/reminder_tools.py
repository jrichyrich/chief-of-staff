"""Reminder tools for MCP server."""

import json


def register(mcp, state):
    """Register reminder tools with the MCP server."""

    @mcp.tool()
    async def list_reminder_lists() -> str:
        """List all reminder lists available on this Mac."""
        reminder_store = state.reminder_store
        try:
            lists = reminder_store.list_reminder_lists()
            return json.dumps({"results": lists})
        except Exception as e:
            return json.dumps({"error": f"Failed to list reminder lists: {e}"})

    @mcp.tool()
    async def list_reminders(list_name: str = "", completed: str = "") -> str:
        """Get reminders, optionally filtered by list and completion status.

        Args:
            list_name: Optional reminder list name to filter by
            completed: Filter by completion status: 'true' for completed only, 'false' for incomplete only, empty for all
        """
        reminder_store = state.reminder_store
        try:
            completed_flag = None
            if completed.lower() == "true":
                completed_flag = True
            elif completed.lower() == "false":
                completed_flag = False

            reminders = reminder_store.get_reminders(
                list_name=list_name or None,
                completed=completed_flag,
            )
            return json.dumps({"results": reminders})
        except Exception as e:
            return json.dumps({"error": f"Failed to get reminders: {e}"})

    @mcp.tool()
    async def create_reminder(
        title: str,
        list_name: str = "",
        due_date: str = "",
        priority: int = 0,
        notes: str = "",
    ) -> str:
        """Create a new reminder.

        Args:
            title: Reminder title (required)
            list_name: Reminder list to add to (uses default if empty)
            due_date: Due date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            priority: Priority level: 0=none, 1=high, 4=medium, 9=low (default: 0)
            notes: Additional notes
        """
        reminder_store = state.reminder_store
        try:
            result = reminder_store.create_reminder(
                title=title,
                list_name=list_name or None,
                due_date=due_date or None,
                priority=priority if priority != 0 else None,
                notes=notes or None,
            )
            return json.dumps({"status": "created", "reminder": result})
        except Exception as e:
            return json.dumps({"error": f"Failed to create reminder: {e}"})

    @mcp.tool()
    async def complete_reminder(reminder_id: str) -> str:
        """Mark a reminder as completed.

        Args:
            reminder_id: The unique identifier of the reminder (required)
        """
        reminder_store = state.reminder_store
        try:
            result = reminder_store.complete_reminder(reminder_id)
            return json.dumps({"status": "completed", "reminder": result})
        except Exception as e:
            return json.dumps({"error": f"Failed to complete reminder: {e}"})

    @mcp.tool()
    async def delete_reminder(reminder_id: str) -> str:
        """Delete a reminder.

        Args:
            reminder_id: The unique identifier of the reminder (required)
        """
        reminder_store = state.reminder_store
        try:
            result = reminder_store.delete_reminder(reminder_id)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": f"Failed to delete reminder: {e}"})

    @mcp.tool()
    async def search_reminders(query: str, include_completed: bool = False) -> str:
        """Search reminders by title text.

        Args:
            query: Text to search for in reminder titles (required)
            include_completed: Whether to include completed reminders (default: False)
        """
        reminder_store = state.reminder_store
        try:
            reminders = reminder_store.search_reminders(query, include_completed=include_completed)
            return json.dumps({"results": reminders})
        except Exception as e:
            return json.dumps({"error": f"Failed to search reminders: {e}"})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.list_reminder_lists = list_reminder_lists
    module.list_reminders = list_reminders
    module.create_reminder = create_reminder
    module.complete_reminder = complete_reminder
    module.delete_reminder = delete_reminder
    module.search_reminders = search_reminders
