# tests/test_scheduler_tools.py
"""Tests for scheduler MCP tool handlers."""

import json

import pytest

from memory.store import MemoryStore
from memory.models import ScheduledTask


@pytest.fixture
def shared_state(tmp_path):
    memory_store = MemoryStore(tmp_path / "test.db")
    state = {"memory_store": memory_store}
    yield state
    memory_store.close()


class TestCreateScheduledTask:
    @pytest.mark.asyncio
    async def test_create_interval_task(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await create_scheduled_task(
                name="test-interval",
                schedule_type="interval",
                schedule_config='{"minutes": 30}',
                handler_type="alert_eval",
                description="Run alerts every 30 min",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["task"]["name"] == "test-interval"
        assert data["task"]["schedule_type"] == "interval"
        assert data["task"]["next_run_at"] is not None

    @pytest.mark.asyncio
    async def test_create_cron_task(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await create_scheduled_task(
                name="daily-morning",
                schedule_type="cron",
                schedule_config='{"expression": "0 8 * * *"}',
                handler_type="alert_eval",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["task"]["handler_type"] == "alert_eval"

    @pytest.mark.asyncio
    async def test_create_once_task(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await create_scheduled_task(
                name="one-time",
                schedule_type="once",
                schedule_config='{"run_at": "2030-01-01T09:00:00"}',
                handler_type="custom",
                handler_config='{"command": "echo done"}',
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["task"]["next_run_at"] == "2030-01-01T09:00:00"

    @pytest.mark.asyncio
    async def test_create_invalid_schedule_type(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await create_scheduled_task(
                name="bad-type",
                schedule_type="weekly",
                schedule_config="{}",
                handler_type="backup",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "error"
        assert "Invalid schedule_type" in data["error"]

    @pytest.mark.asyncio
    async def test_create_invalid_cron_expression(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await create_scheduled_task(
                name="bad-cron",
                schedule_type="cron",
                schedule_config='{"expression": "bad"}',
                handler_type="backup",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "error"


class TestListScheduledTasks:
    @pytest.mark.asyncio
    async def test_list_empty(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import list_scheduled_tasks

        mcp_server._state.update(shared_state)
        try:
            result = await list_scheduled_tasks()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["count"] == 0
        assert data["tasks"] == []

    @pytest.mark.asyncio
    async def test_list_with_tasks(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, list_scheduled_tasks

        mcp_server._state.update(shared_state)
        try:
            await create_scheduled_task(
                name="task-a",
                schedule_type="interval",
                schedule_config='{"minutes": 10}',
                handler_type="backup",
            )
            await create_scheduled_task(
                name="task-b",
                schedule_type="interval",
                schedule_config='{"hours": 1}',
                handler_type="alert_eval",
            )
            result = await list_scheduled_tasks()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_list_enabled_only(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, list_scheduled_tasks

        mcp_server._state.update(shared_state)
        try:
            await create_scheduled_task(
                name="enabled-task",
                schedule_type="interval",
                schedule_config='{"minutes": 10}',
                handler_type="backup",
                enabled=True,
            )
            await create_scheduled_task(
                name="disabled-task",
                schedule_type="interval",
                schedule_config='{"minutes": 10}',
                handler_type="backup",
                enabled=False,
            )
            result = await list_scheduled_tasks(enabled_only=True)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["count"] == 1
        assert data["tasks"][0]["name"] == "enabled-task"


class TestUpdateScheduledTask:
    @pytest.mark.asyncio
    async def test_update_enable_disable(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, update_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            create_result = await create_scheduled_task(
                name="toggle-me",
                schedule_type="interval",
                schedule_config='{"minutes": 15}',
                handler_type="backup",
            )
            task_id = json.loads(create_result)["task"]["id"]

            result = await update_scheduled_task(task_id=task_id, enabled=False)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "updated"
        assert data["task"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_update_schedule_config(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, update_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            create_result = await create_scheduled_task(
                name="reconfig-me",
                schedule_type="interval",
                schedule_config='{"minutes": 15}',
                handler_type="backup",
            )
            task_id = json.loads(create_result)["task"]["id"]

            result = await update_scheduled_task(
                task_id=task_id,
                schedule_config='{"minutes": 60}',
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "updated"
        assert data["task"]["schedule_config"] == '{"minutes": 60}'

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import update_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await update_scheduled_task(task_id=999)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "error"
        assert "not found" in data["error"]

    @pytest.mark.asyncio
    async def test_update_no_fields(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, update_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            create_result = await create_scheduled_task(
                name="no-update",
                schedule_type="interval",
                schedule_config='{"minutes": 15}',
                handler_type="backup",
            )
            task_id = json.loads(create_result)["task"]["id"]

            result = await update_scheduled_task(task_id=task_id)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "error"
        assert "No fields" in data["error"]


class TestDeleteScheduledTask:
    @pytest.mark.asyncio
    async def test_delete_existing(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, delete_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            create_result = await create_scheduled_task(
                name="delete-me",
                schedule_type="interval",
                schedule_config='{"minutes": 10}',
                handler_type="backup",
            )
            task_id = json.loads(create_result)["task"]["id"]

            result = await delete_scheduled_task(task_id=task_id)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import delete_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await delete_scheduled_task(task_id=999)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "not_found"


class TestRunScheduledTask:
    @pytest.mark.asyncio
    async def test_run_manually(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, run_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            create_result = await create_scheduled_task(
                name="manual-run",
                schedule_type="interval",
                schedule_config='{"minutes": 60}',
                handler_type="backup",
            )
            task_id = json.loads(create_result)["task"]["id"]

            result = await run_scheduled_task(task_id=task_id)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "executed"
        assert data["name"] == "manual-run"

    @pytest.mark.asyncio
    async def test_run_nonexistent(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import run_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await run_scheduled_task(task_id=999)
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "error"
        assert "not found" in data["error"]


class TestGetSchedulerStatus:
    @pytest.mark.asyncio
    async def test_status_empty(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import get_scheduler_status

        mcp_server._state.update(shared_state)
        try:
            result = await get_scheduler_status()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["total_tasks"] == 0
        assert data["enabled_tasks"] == 0
        assert data["overdue_tasks"] == 0

    @pytest.mark.asyncio
    async def test_status_with_tasks(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, get_scheduler_status

        mcp_server._state.update(shared_state)
        try:
            await create_scheduled_task(
                name="status-task",
                schedule_type="interval",
                schedule_config='{"minutes": 10}',
                handler_type="backup",
            )
            result = await get_scheduler_status()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["total_tasks"] == 1
        assert data["enabled_tasks"] == 1
        assert len(data["tasks"]) == 1


class TestMCPToolRegistration:
    def test_scheduler_tools_registered(self):
        import mcp_server
        tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
        assert "create_scheduled_task" in tool_names
        assert "list_scheduled_tasks" in tool_names
        assert "update_scheduled_task" in tool_names
        assert "delete_scheduled_task" in tool_names
        assert "run_scheduled_task" in tool_names
        assert "get_scheduler_status" in tool_names
