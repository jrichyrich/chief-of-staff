"""Tests for scheduler handler timeout (Fix 6)."""

import asyncio
import json
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from memory.models import ScheduledTask
from scheduler.engine import SchedulerEngine


def _make_task(**overrides) -> ScheduledTask:
    defaults = dict(
        id=1,
        name="test-task",
        handler_type="webhook_poll",
        handler_config="{}",
        schedule_type="interval",
        schedule_config='{"minutes": 5}',
        enabled=True,
        next_run_at=datetime(2026, 1, 1, 0, 0).isoformat(),
        last_run_at=None,
        last_result=None,
        created_at=datetime(2026, 1, 1).isoformat(),
        delivery_channel=None,
        delivery_config=None,
    )
    defaults.update(overrides)
    return ScheduledTask(**defaults)


@pytest.fixture
def memory_store(tmp_path):
    from memory.store import MemoryStore
    return MemoryStore(tmp_path / "test.db")


class TestSchedulerHandlerTimeout:
    @pytest.mark.asyncio
    async def test_handler_timeout_produces_timeout_status(self, memory_store):
        """A handler that exceeds the timeout should produce status='timeout'."""
        task = _make_task()
        engine = SchedulerEngine(memory_store)

        def slow_handler(*args, **kwargs):
            time.sleep(10)  # Will be killed by timeout
            return "should not reach"

        with patch("scheduler.engine.execute_handler", side_effect=slow_handler):
            with patch("config.SCHEDULER_HANDLER_TIMEOUT_SECONDS", 0.1):
                result = await engine._execute_task_async(task, datetime(2026, 1, 1, 0, 5))

        assert result["status"] == "timeout"
        assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_handler_timeout_updates_last_run(self, memory_store):
        """After timeout, last_run_at should be updated to prevent immediate retry."""
        task_model = memory_store.store_scheduled_task(ScheduledTask(
            name="timeout-test",
            handler_type="webhook_poll",
            handler_config="{}",
            schedule_type="interval",
            schedule_config='{"minutes": 5}',
            next_run_at=datetime(2026, 1, 1, 0, 0).isoformat(),
        ))
        task = _make_task(id=task_model.id, name="timeout-test")
        engine = SchedulerEngine(memory_store)

        def slow_handler(*args, **kwargs):
            time.sleep(10)
            return "nope"

        now = datetime(2026, 1, 1, 0, 5)
        with patch("scheduler.engine.execute_handler", side_effect=slow_handler):
            with patch("config.SCHEDULER_HANDLER_TIMEOUT_SECONDS", 0.1):
                result = await engine._execute_task_async(task, now)

        assert result["status"] == "timeout"

        # Verify the DB was updated
        tasks = memory_store.list_scheduled_tasks()
        updated = [t for t in tasks if t.name == "timeout-test"][0]
        assert updated.last_run_at == now.isoformat()
        last_result = json.loads(updated.last_result)
        assert last_result["status"] == "timeout"

    @pytest.mark.asyncio
    async def test_successful_handler_still_works_async(self, memory_store):
        """Normal handler execution should work fine through the async path."""
        task_model = memory_store.store_scheduled_task(ScheduledTask(
            name="fast-task",
            handler_type="webhook_poll",
            handler_config="{}",
            schedule_type="interval",
            schedule_config='{"minutes": 5}',
            next_run_at=datetime(2026, 1, 1, 0, 0).isoformat(),
        ))
        task = _make_task(id=task_model.id, name="fast-task")
        engine = SchedulerEngine(memory_store)

        with patch("scheduler.engine.execute_handler", return_value='{"ok": true}'):
            result = await engine._execute_task_async(task, datetime(2026, 1, 1, 0, 5))

        assert result["status"] == "executed"
        assert result["result"] == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_evaluate_due_tasks_async(self, memory_store):
        """evaluate_due_tasks_async should find and execute due tasks."""
        now = datetime(2026, 1, 1, 0, 10)
        memory_store.store_scheduled_task(ScheduledTask(
            name="due-task",
            handler_type="webhook_poll",
            handler_config="{}",
            schedule_type="interval",
            schedule_config='{"minutes": 5}',
            next_run_at=datetime(2026, 1, 1, 0, 5).isoformat(),
        ))
        engine = SchedulerEngine(memory_store)

        with patch("scheduler.engine.execute_handler", return_value="done"):
            results = await engine.evaluate_due_tasks_async(now=now)

        assert len(results) == 1
        assert results[0]["status"] == "executed"
