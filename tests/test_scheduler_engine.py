# tests/test_scheduler_engine.py
"""Tests for the scheduler engine: cron parser, next-run calculation, and task execution."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.models import ScheduledTask
from memory.store import MemoryStore
from scheduler.daemon import JarvisDaemon
from scheduler.engine import (
    CronExpression,
    SchedulerEngine,
    _validate_custom_command,
    calculate_next_run,
    execute_handler,
)


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


# --- CronExpression Parser Tests ---


class TestCronParser:
    def test_wildcard_all_fields(self):
        cron = CronExpression("* * * * *")
        assert cron.minute == set(range(0, 60))
        assert cron.hour == set(range(0, 24))
        assert cron.day == set(range(1, 32))
        assert cron.month == set(range(1, 13))
        assert cron.weekday == set(range(0, 7))

    def test_exact_values(self):
        cron = CronExpression("30 8 15 6 3")
        assert cron.minute == {30}
        assert cron.hour == {8}
        assert cron.day == {15}
        assert cron.month == {6}
        assert cron.weekday == {3}

    def test_ranges(self):
        cron = CronExpression("0-5 9-17 1-15 * 0-4")
        assert cron.minute == {0, 1, 2, 3, 4, 5}
        assert cron.hour == set(range(9, 18))
        assert cron.day == set(range(1, 16))
        assert cron.weekday == {0, 1, 2, 3, 4}

    def test_lists(self):
        cron = CronExpression("0,15,30,45 * * * *")
        assert cron.minute == {0, 15, 30, 45}

    def test_steps(self):
        cron = CronExpression("*/15 */6 * * *")
        assert cron.minute == {0, 15, 30, 45}
        assert cron.hour == {0, 6, 12, 18}

    def test_range_with_step(self):
        cron = CronExpression("1-30/5 * * * *")
        assert cron.minute == {1, 6, 11, 16, 21, 26}

    def test_combined_list_and_range(self):
        cron = CronExpression("0,30 8-17 * * 0-4")
        assert cron.minute == {0, 30}
        assert cron.hour == set(range(8, 18))
        assert cron.weekday == {0, 1, 2, 3, 4}

    def test_invalid_field_count(self):
        with pytest.raises(ValueError, match="5 fields"):
            CronExpression("* * *")

    def test_value_out_of_range(self):
        with pytest.raises(ValueError, match="out of bounds"):
            CronExpression("60 * * * *")

    def test_range_out_of_bounds(self):
        with pytest.raises(ValueError, match="out of bounds"):
            CronExpression("* 0-25 * * *")

    def test_invalid_step(self):
        with pytest.raises(ValueError, match="Step must be >= 1"):
            CronExpression("*/0 * * * *")


class TestCronNextTime:
    def test_next_minute(self):
        cron = CronExpression("* * * * *")
        base = datetime(2026, 2, 20, 10, 30, 0)
        result = cron.next_time(base)
        assert result == datetime(2026, 2, 20, 10, 31, 0)

    def test_next_specific_minute(self):
        cron = CronExpression("45 * * * *")
        base = datetime(2026, 2, 20, 10, 30, 0)
        result = cron.next_time(base)
        assert result == datetime(2026, 2, 20, 10, 45, 0)

    def test_next_hour_rollover(self):
        cron = CronExpression("15 * * * *")
        base = datetime(2026, 2, 20, 10, 30, 0)
        result = cron.next_time(base)
        assert result == datetime(2026, 2, 20, 11, 15, 0)

    def test_weekday_filter(self):
        # 2026-02-20 is a Friday (weekday=4)
        cron = CronExpression("0 9 * * 0")  # Monday only (0=Monday)
        base = datetime(2026, 2, 20, 10, 0, 0)
        result = cron.next_time(base)
        assert result.weekday() == 0  # Monday
        assert result == datetime(2026, 2, 23, 9, 0, 0)

    def test_every_15_minutes(self):
        cron = CronExpression("*/15 * * * *")
        base = datetime(2026, 2, 20, 10, 7, 0)
        result = cron.next_time(base)
        assert result == datetime(2026, 2, 20, 10, 15, 0)

    def test_workday_morning(self):
        # "0 8 * * 0-4" means 8:00 AM, Mon-Fri (0=Monday in our system)
        cron = CronExpression("0 8 * * 0-4")
        # Start from Saturday morning
        base = datetime(2026, 2, 21, 7, 0, 0)  # Saturday
        result = cron.next_time(base)
        # Should skip to Monday
        assert result == datetime(2026, 2, 23, 8, 0, 0)
        assert result.weekday() == 0  # Monday

    def test_month_boundary(self):
        cron = CronExpression("0 0 1 * *")  # Midnight on the 1st of each month
        base = datetime(2026, 1, 15, 0, 0, 0)
        result = cron.next_time(base)
        assert result == datetime(2026, 2, 1, 0, 0, 0)


# --- calculate_next_run Tests ---


class TestCalculateNextRun:
    def test_interval_minutes(self):
        config = json.dumps({"minutes": 30})
        base = datetime(2026, 2, 20, 10, 0, 0)
        result = calculate_next_run("interval", config, from_time=base)
        expected = (base + timedelta(minutes=30)).isoformat()
        assert result == expected

    def test_interval_hours(self):
        config = json.dumps({"hours": 2})
        base = datetime(2026, 2, 20, 10, 0, 0)
        result = calculate_next_run("interval", config, from_time=base)
        expected = (base + timedelta(hours=2)).isoformat()
        assert result == expected

    def test_interval_combined(self):
        config = json.dumps({"hours": 1, "minutes": 30})
        base = datetime(2026, 2, 20, 10, 0, 0)
        result = calculate_next_run("interval", config, from_time=base)
        expected = (base + timedelta(hours=1, minutes=30)).isoformat()
        assert result == expected

    def test_interval_zero_raises(self):
        config = json.dumps({"minutes": 0})
        with pytest.raises(ValueError, match="positive"):
            calculate_next_run("interval", config)

    def test_cron_schedule(self):
        config = json.dumps({"expression": "0 8 * * *"})
        base = datetime(2026, 2, 20, 10, 0, 0)
        result = calculate_next_run("cron", config, from_time=base)
        assert result == datetime(2026, 2, 21, 8, 0, 0).isoformat()

    def test_cron_missing_expression(self):
        config = json.dumps({})
        with pytest.raises(ValueError, match="expression"):
            calculate_next_run("cron", config)

    def test_once_future(self):
        config = json.dumps({"run_at": "2026-03-01T09:00:00"})
        base = datetime(2026, 2, 20, 10, 0, 0)
        result = calculate_next_run("once", config, from_time=base)
        assert result == "2026-03-01T09:00:00"

    def test_once_past_returns_none(self):
        config = json.dumps({"run_at": "2026-01-01T09:00:00"})
        base = datetime(2026, 2, 20, 10, 0, 0)
        result = calculate_next_run("once", config, from_time=base)
        assert result is None

    def test_once_missing_run_at(self):
        config = json.dumps({})
        with pytest.raises(ValueError, match="run_at"):
            calculate_next_run("once", config)

    def test_unknown_schedule_type(self):
        with pytest.raises(ValueError, match="Unknown"):
            calculate_next_run("weekly", "{}")


# --- Custom Command Validation Tests ---


class TestCustomCommandValidation:
    def test_valid_command(self):
        result = _validate_custom_command("echo hello")
        assert result == "echo hello"

    def test_empty_command_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            _validate_custom_command("")

    def test_dangerous_rm(self):
        with pytest.raises(ValueError, match="not allowed"):
            _validate_custom_command("rm -rf /")

    def test_dangerous_sudo(self):
        with pytest.raises(ValueError, match="not allowed"):
            _validate_custom_command("sudo anything")

    def test_dangerous_kill(self):
        with pytest.raises(ValueError, match="not allowed"):
            _validate_custom_command("kill -9 1234")

    def test_shell_metacharacters_rejected(self):
        with pytest.raises(ValueError, match="metacharacters"):
            _validate_custom_command("echo hello; rm -rf /")

    def test_pipe_rejected(self):
        with pytest.raises(ValueError, match="metacharacters"):
            _validate_custom_command("cat /etc/passwd | grep root")

    def test_backtick_rejected(self):
        with pytest.raises(ValueError, match="metacharacters"):
            _validate_custom_command("echo `whoami`")

    def test_dollar_rejected(self):
        with pytest.raises(ValueError, match="metacharacters"):
            _validate_custom_command("echo $HOME")


# --- execute_handler Tests ---


class TestExecuteHandler:
    def test_alert_eval_handler(self):
        with patch("scheduler.alert_evaluator.evaluate_alerts") as mock_eval:
            result = json.loads(execute_handler("alert_eval", ""))
            assert result["status"] == "ok"
            assert result["handler"] == "alert_eval"
            mock_eval.assert_called_once()

    def test_alert_eval_handler_error(self):
        with patch("scheduler.alert_evaluator.evaluate_alerts", side_effect=RuntimeError("test fail")):
            result = json.loads(execute_handler("alert_eval", ""))
            assert result["status"] == "error"
            assert "test fail" in result["error"]

    def test_custom_handler_echo(self):
        config = json.dumps({"command": "echo hello"})
        result = json.loads(execute_handler("custom", config))
        assert result["status"] == "ok"
        assert result["handler"] == "custom"
        assert "hello" in result["stdout"]

    def test_custom_handler_bad_command(self):
        config = json.dumps({"command": "rm -rf /"})
        result = json.loads(execute_handler("custom", config))
        assert result["status"] == "error"

    def test_custom_handler_not_found(self):
        config = json.dumps({"command": "nonexistent_command_12345"})
        result = json.loads(execute_handler("custom", config))
        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_unimplemented_handler(self):
        result = json.loads(execute_handler("backup", ""))
        assert result["status"] == "skipped"
        assert "not yet implemented" in result["message"]

    def test_webhook_poll_calls_ingest(self):
        mock_store = MagicMock()
        with patch("scheduler.engine.Path") as mock_path_cls:
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path_cls.return_value = mock_path_instance
            with patch("webhook.ingest.ingest_events", return_value={"ingested": 2, "failed": 0, "skipped": 0}) as mock_ingest:
                result = json.loads(execute_handler("webhook_poll", "", memory_store=mock_store))
                assert result["status"] == "ok"
                assert result["handler"] == "webhook_poll"
                assert result["ingested"] == 2
                mock_ingest.assert_called_once()

    def test_webhook_poll_inbox_missing(self):
        mock_store = MagicMock()
        with patch("scheduler.engine.Path") as mock_path_cls:
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = False
            mock_path_cls.return_value = mock_path_instance
            result = json.loads(execute_handler("webhook_poll", "", memory_store=mock_store))
            assert result["status"] == "ok"
            assert "does not exist" in result["message"]

    def test_webhook_poll_error(self):
        mock_store = MagicMock()
        with patch("scheduler.engine.Path") as mock_path_cls:
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path_cls.return_value = mock_path_instance
            with patch("webhook.ingest.ingest_events", side_effect=RuntimeError("ingest boom")):
                result = json.loads(execute_handler("webhook_poll", "", memory_store=mock_store))
                assert result["status"] == "error"
                assert "ingest boom" in result["error"]


# --- SchedulerEngine Tests ---


class TestSchedulerEngine:
    def test_evaluate_no_due_tasks(self, memory_store):
        engine = SchedulerEngine(memory_store)
        results = engine.evaluate_due_tasks(now=datetime(2026, 2, 20, 10, 0, 0))
        assert results == []

    def test_evaluate_due_task_executes(self, memory_store):
        # Create a task that's due
        task = ScheduledTask(
            name="test-alert",
            schedule_type="interval",
            schedule_config=json.dumps({"minutes": 30}),
            handler_type="backup",  # unimplemented, but won't error
            enabled=True,
            next_run_at="2026-02-20T09:00:00",
        )
        stored = memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        now = datetime(2026, 2, 20, 10, 0, 0)
        results = engine.evaluate_due_tasks(now=now)

        assert len(results) == 1
        assert results[0]["name"] == "test-alert"
        assert results[0]["status"] == "executed"

        # Verify task was updated
        updated = memory_store.get_scheduled_task(stored.id)
        assert updated.last_run_at == now.isoformat()
        assert updated.next_run_at is not None

    def test_evaluate_skips_future_tasks(self, memory_store):
        task = ScheduledTask(
            name="future-task",
            schedule_type="interval",
            schedule_config=json.dumps({"hours": 1}),
            handler_type="backup",
            enabled=True,
            next_run_at="2026-02-20T12:00:00",
        )
        memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        results = engine.evaluate_due_tasks(now=datetime(2026, 2, 20, 10, 0, 0))
        assert results == []

    def test_evaluate_skips_disabled_tasks(self, memory_store):
        task = ScheduledTask(
            name="disabled-task",
            schedule_type="interval",
            schedule_config=json.dumps({"minutes": 5}),
            handler_type="backup",
            enabled=False,
            next_run_at="2026-02-20T09:00:00",
        )
        memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        results = engine.evaluate_due_tasks(now=datetime(2026, 2, 20, 10, 0, 0))
        assert results == []

    def test_evaluate_once_task_clears_next_run(self, memory_store):
        task = ScheduledTask(
            name="one-shot",
            schedule_type="once",
            schedule_config=json.dumps({"run_at": "2026-02-20T09:00:00"}),
            handler_type="backup",
            enabled=True,
            next_run_at="2026-02-20T09:00:00",
        )
        stored = memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        now = datetime(2026, 2, 20, 10, 0, 0)
        results = engine.evaluate_due_tasks(now=now)

        assert len(results) == 1
        updated = memory_store.get_scheduled_task(stored.id)
        assert updated.next_run_at is None  # once-type shouldn't run again

    def test_evaluate_with_alert_eval_handler(self, memory_store):
        task = ScheduledTask(
            name="alert-check",
            schedule_type="interval",
            schedule_config=json.dumps({"hours": 2}),
            handler_type="alert_eval",
            enabled=True,
            next_run_at="2026-02-20T08:00:00",
        )
        stored = memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        now = datetime(2026, 2, 20, 10, 0, 0)

        with patch("scheduler.alert_evaluator.evaluate_alerts"):
            results = engine.evaluate_due_tasks(now=now)

        assert len(results) == 1
        assert results[0]["status"] == "executed"
        result_data = json.loads(results[0]["result"])
        assert result_data["handler"] == "alert_eval"

    def test_execute_multiple_due_tasks(self, memory_store):
        for i in range(3):
            task = ScheduledTask(
                name=f"task-{i}",
                schedule_type="interval",
                schedule_config=json.dumps({"minutes": 10}),
                handler_type="backup",
                enabled=True,
                next_run_at="2026-02-20T09:00:00",
            )
            memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        results = engine.evaluate_due_tasks(now=datetime(2026, 2, 20, 10, 0, 0))
        assert len(results) == 3

    def test_handler_error_updates_last_result(self, memory_store):
        task = ScheduledTask(
            name="custom-fail",
            schedule_type="interval",
            schedule_config=json.dumps({"minutes": 5}),
            handler_type="custom",
            handler_config=json.dumps({"command": "nonexistent_cmd_xyz"}),
            enabled=True,
            next_run_at="2026-02-20T09:00:00",
        )
        stored = memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        now = datetime(2026, 2, 20, 10, 0, 0)
        results = engine.evaluate_due_tasks(now=now)

        assert len(results) == 1
        # The custom handler returns an error result but doesn't raise
        updated = memory_store.get_scheduled_task(stored.id)
        assert updated.last_run_at == now.isoformat()
        assert updated.last_result is not None


# --- Skill Analysis Handler Tests ---


class TestSkillAnalysisHandler:
    def test_skill_analysis_no_patterns(self, memory_store):
        result = json.loads(execute_handler("skill_analysis", "", memory_store=memory_store))
        assert result["status"] == "ok"
        assert result["handler"] == "skill_analysis"
        assert result["patterns_found"] == 0

    def test_skill_analysis_with_patterns(self, memory_store):
        # Seed enough usage data to trigger pattern detection
        for i in range(10):
            memory_store.record_skill_usage("query_memory", "weekly meeting notes")
        result = json.loads(execute_handler("skill_analysis", "", memory_store=memory_store))
        assert result["status"] == "ok"
        assert result["handler"] == "skill_analysis"
        assert result["patterns_found"] >= 1

        # Verify suggestions were stored
        suggestions = memory_store.list_skill_suggestions(status="pending")
        assert len(suggestions) >= 1

    def test_skill_analysis_stores_suggestions(self, memory_store):
        for i in range(10):
            memory_store.record_skill_usage("search_calendar_events", "team standup")
        execute_handler("skill_analysis", "", memory_store=memory_store)

        suggestions = memory_store.list_skill_suggestions(status="pending")
        assert len(suggestions) >= 1
        assert any("search_calendar_events" in s.description for s in suggestions)

    def test_skill_analysis_handler_error(self):
        # Pass None as memory_store to trigger an error
        result = json.loads(execute_handler("skill_analysis", "", memory_store=None))
        assert result["status"] == "error"
        assert result["handler"] == "skill_analysis"

    def test_skill_analysis_via_scheduler(self, memory_store):
        task = ScheduledTask(
            name="daily-skill-analysis",
            schedule_type="interval",
            schedule_config=json.dumps({"hours": 24}),
            handler_type="skill_analysis",
            enabled=True,
            next_run_at="2026-02-20T09:00:00",
        )
        stored = memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        now = datetime(2026, 2, 20, 10, 0, 0)
        results = engine.evaluate_due_tasks(now=now)

        assert len(results) == 1
        assert results[0]["status"] == "executed"
        result_data = json.loads(results[0]["result"])
        assert result_data["handler"] == "skill_analysis"
        assert "patterns_found" in result_data


# --- SchedulerEngine Stores Tests ---


class TestSchedulerEngineStores:
    def test_engine_accepts_agent_registry(self, memory_store):
        mock_registry = MagicMock()
        engine = SchedulerEngine(memory_store, agent_registry=mock_registry)
        assert engine.agent_registry is mock_registry

    def test_engine_accepts_document_store(self, memory_store):
        mock_doc_store = MagicMock()
        engine = SchedulerEngine(memory_store, document_store=mock_doc_store)
        assert engine.document_store is mock_doc_store

    def test_engine_defaults_stores_to_none(self, memory_store):
        engine = SchedulerEngine(memory_store)
        assert engine.agent_registry is None
        assert engine.document_store is None

    def test_skill_auto_exec_receives_agent_registry(self, memory_store):
        """Verify agent_registry is passed to skill_auto_exec handler (fixes existing bug)."""
        mock_registry = MagicMock()
        task = ScheduledTask(
            name="skill-auto",
            schedule_type="interval",
            schedule_config=json.dumps({"minutes": 60}),
            handler_type="skill_auto_exec",
            enabled=True,
            next_run_at="2026-02-20T09:00:00",
        )
        memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store, agent_registry=mock_registry)
        now = datetime(2026, 2, 20, 10, 0, 0)

        with patch("scheduler.engine._run_skill_auto_exec_handler", return_value='{"status":"skipped"}') as mock_handler:
            engine.evaluate_due_tasks(now=now)
            mock_handler.assert_called_once_with(memory_store, mock_registry)


# --- Webhook Dispatch Handler Tests ---


class TestWebhookDispatchHandler:
    def test_webhook_dispatch_disabled_returns_skipped(self):
        mock_store = MagicMock()
        with patch("config.WEBHOOK_AUTO_DISPATCH_ENABLED", False):
            result = json.loads(execute_handler("webhook_dispatch", "", memory_store=mock_store))
        assert result["status"] == "skipped"
        assert result["handler"] == "webhook_dispatch"

    def test_webhook_dispatch_enabled_returns_counts(self):
        mock_store = MagicMock()
        mock_registry = MagicMock()
        mock_docs = MagicMock()
        expected = {"dispatched": 2, "failed": 0, "skipped": 1}
        with patch("config.WEBHOOK_AUTO_DISPATCH_ENABLED", True):
            with patch("webhook.ingest.dispatch_pending_events", new_callable=AsyncMock, return_value=expected):
                result = json.loads(execute_handler(
                    "webhook_dispatch", "",
                    memory_store=mock_store,
                    agent_registry=mock_registry,
                    document_store=mock_docs,
                ))
        assert result["status"] == "ok"
        assert result["handler"] == "webhook_dispatch"
        assert result["dispatched"] == 2
        assert result["skipped"] == 1

    def test_webhook_dispatch_error_caught(self):
        mock_store = MagicMock()
        with patch("config.WEBHOOK_AUTO_DISPATCH_ENABLED", True):
            with patch("webhook.ingest.dispatch_pending_events", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
                result = json.loads(execute_handler("webhook_dispatch", "", memory_store=mock_store))
        assert result["status"] == "error"
        assert "boom" in result["error"]

    def test_webhook_dispatch_via_scheduler(self, memory_store):
        """Full integration: scheduler evaluates due webhook_dispatch task."""
        task = ScheduledTask(
            name="webhook-dispatch",
            schedule_type="interval",
            schedule_config=json.dumps({"minutes": 5}),
            handler_type="webhook_dispatch",
            enabled=True,
            next_run_at="2026-02-20T09:00:00",
        )
        memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        now = datetime(2026, 2, 20, 10, 0, 0)

        with patch("config.WEBHOOK_AUTO_DISPATCH_ENABLED", False):
            results = engine.evaluate_due_tasks(now=now)

        assert len(results) == 1
        result_data = json.loads(results[0]["result"])
        assert result_data["status"] == "skipped"


# --- Daemon Store Passthrough Tests ---


class TestDaemonStorePassthrough:
    def test_daemon_passes_stores_to_engine(self):
        mock_memory = MagicMock()
        mock_registry = MagicMock()
        mock_docs = MagicMock()

        daemon = JarvisDaemon(
            memory_store=mock_memory,
            agent_registry=mock_registry,
            document_store=mock_docs,
        )
        assert daemon.engine.memory_store is mock_memory
        assert daemon.engine.agent_registry is mock_registry
        assert daemon.engine.document_store is mock_docs

    def test_daemon_defaults_stores_to_none(self):
        mock_memory = MagicMock()
        daemon = JarvisDaemon(memory_store=mock_memory)
        assert daemon.engine.agent_registry is None
        assert daemon.engine.document_store is None
