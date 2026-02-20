"""Scheduler management tools for the Chief of Staff MCP server."""

import json
from datetime import datetime

from memory.models import ScheduledTask
from scheduler.engine import SchedulerEngine, calculate_next_run


def register(mcp, state):
    """Register scheduler tools with the FastMCP server."""

    @mcp.tool()
    async def create_scheduled_task(
        name: str,
        schedule_type: str,
        schedule_config: str,
        handler_type: str,
        handler_config: str = "",
        description: str = "",
        enabled: bool = True,
    ) -> str:
        """Create a new scheduled task.

        Args:
            name: Unique name for the task (required)
            schedule_type: Type of schedule: interval, cron, or once (required)
            schedule_config: JSON config for the schedule (required). Examples:
                - interval: {"minutes": 30} or {"hours": 2}
                - cron: {"expression": "0 8 * * 1-5"} (minute hour day month weekday, 0=Monday)
                - once: {"run_at": "2026-03-01T09:00:00"}
            handler_type: Type of handler: alert_eval, backup, webhook_poll, or custom (required)
            handler_config: JSON config for the handler. For custom: {"command": "echo hello"}
            description: Human-readable description of the task
            enabled: Whether the task is active (default: True)
        """
        memory_store = state.memory_store

        # Validate schedule_type
        if schedule_type not in ("interval", "cron", "once"):
            return json.dumps({"status": "error", "error": f"Invalid schedule_type: {schedule_type}. Must be interval, cron, or once."})

        # Calculate initial next_run_at
        try:
            next_run = calculate_next_run(schedule_type, schedule_config)
        except ValueError as e:
            return json.dumps({"status": "error", "error": str(e)})

        task = ScheduledTask(
            name=name,
            description=description,
            schedule_type=schedule_type,
            schedule_config=schedule_config,
            handler_type=handler_type,
            handler_config=handler_config,
            enabled=enabled,
            next_run_at=next_run,
        )

        try:
            stored = memory_store.store_scheduled_task(task)
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

        return json.dumps({
            "status": "created",
            "task": {
                "id": stored.id,
                "name": stored.name,
                "schedule_type": stored.schedule_type,
                "handler_type": stored.handler_type,
                "enabled": stored.enabled,
                "next_run_at": stored.next_run_at,
            },
        })

    @mcp.tool()
    async def list_scheduled_tasks(enabled_only: bool = False) -> str:
        """List all scheduled tasks.

        Args:
            enabled_only: If True, only return enabled tasks
        """
        memory_store = state.memory_store
        tasks = memory_store.list_scheduled_tasks(enabled_only=enabled_only)
        return json.dumps({
            "count": len(tasks),
            "tasks": [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "schedule_type": t.schedule_type,
                    "handler_type": t.handler_type,
                    "enabled": t.enabled,
                    "last_run_at": t.last_run_at,
                    "next_run_at": t.next_run_at,
                }
                for t in tasks
            ],
        })

    @mcp.tool()
    async def update_scheduled_task(
        task_id: int,
        enabled: bool = None,
        schedule_config: str = "",
        handler_config: str = "",
    ) -> str:
        """Update a scheduled task's configuration.

        Args:
            task_id: The ID of the task to update (required)
            enabled: Enable or disable the task
            schedule_config: New schedule config (JSON string)
            handler_config: New handler config (JSON string)
        """
        memory_store = state.memory_store

        task = memory_store.get_scheduled_task(task_id)
        if task is None:
            return json.dumps({"status": "error", "error": f"Task {task_id} not found"})

        kwargs = {}
        if enabled is not None:
            kwargs["enabled"] = enabled
        if schedule_config:
            kwargs["schedule_config"] = schedule_config
            # Recalculate next_run_at with new config
            try:
                next_run = calculate_next_run(task.schedule_type, schedule_config)
                kwargs["next_run_at"] = next_run
            except ValueError as e:
                return json.dumps({"status": "error", "error": str(e)})
        if handler_config:
            kwargs["handler_config"] = handler_config

        if not kwargs:
            return json.dumps({"status": "error", "error": "No fields to update"})

        updated = memory_store.update_scheduled_task(task_id, **kwargs)
        if updated is None:
            return json.dumps({"status": "error", "error": f"Task {task_id} not found"})

        return json.dumps({
            "status": "updated",
            "task": {
                "id": updated.id,
                "name": updated.name,
                "enabled": updated.enabled,
                "schedule_config": updated.schedule_config,
                "handler_config": updated.handler_config,
                "next_run_at": updated.next_run_at,
            },
        })

    @mcp.tool()
    async def delete_scheduled_task(task_id: int) -> str:
        """Delete a scheduled task by ID.

        Args:
            task_id: The ID of the task to delete (required)
        """
        memory_store = state.memory_store
        deleted = memory_store.delete_scheduled_task(task_id)
        return json.dumps({
            "status": "deleted" if deleted else "not_found",
            "task_id": task_id,
        })

    @mcp.tool()
    async def run_scheduled_task(task_id: int) -> str:
        """Manually trigger a scheduled task to run now.

        Args:
            task_id: The ID of the task to run (required)
        """
        memory_store = state.memory_store
        task = memory_store.get_scheduled_task(task_id)
        if task is None:
            return json.dumps({"status": "error", "error": f"Task {task_id} not found"})

        engine = SchedulerEngine(memory_store)
        now = datetime.now()
        result = engine._execute_task(task, now)
        return json.dumps(result)

    @mcp.tool()
    async def get_scheduler_status() -> str:
        """Get a summary of all scheduled tasks with their last and next run times."""
        memory_store = state.memory_store
        tasks = memory_store.list_scheduled_tasks()
        now = datetime.now().isoformat()

        summary = []
        for t in tasks:
            overdue = False
            if t.enabled and t.next_run_at and t.next_run_at <= now:
                overdue = True
            summary.append({
                "id": t.id,
                "name": t.name,
                "enabled": t.enabled,
                "schedule_type": t.schedule_type,
                "handler_type": t.handler_type,
                "last_run_at": t.last_run_at,
                "next_run_at": t.next_run_at,
                "last_result": t.last_result,
                "overdue": overdue,
            })

        enabled_count = sum(1 for t in tasks if t.enabled)
        overdue_count = sum(1 for s in summary if s["overdue"])

        return json.dumps({
            "total_tasks": len(tasks),
            "enabled_tasks": enabled_count,
            "overdue_tasks": overdue_count,
            "tasks": summary,
        })

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.create_scheduled_task = create_scheduled_task
    module.list_scheduled_tasks = list_scheduled_tasks
    module.update_scheduled_task = update_scheduled_task
    module.delete_scheduled_task = delete_scheduled_task
    module.run_scheduled_task = run_scheduled_task
    module.get_scheduler_status = get_scheduler_status
