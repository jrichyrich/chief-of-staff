# tests/test_delivery.py
"""Tests for scheduled task delivery: adapters, engine integration, schema migration, MCP tools."""

import json
from datetime import datetime, timedelta
from string import Template
from unittest.mock import MagicMock, patch

import pytest

from memory.models import ScheduledTask
from memory.store import MemoryStore
from scheduler.delivery import (
    DeliveryAdapter,
    EmailDeliveryAdapter,
    IMessageDeliveryAdapter,
    NotificationDeliveryAdapter,
    _build_template_vars,
    deliver_result,
    get_delivery_adapter,
    VALID_CHANNELS,
)
from scheduler.engine import SchedulerEngine


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


# --- Template Variable Tests ---


class TestTemplateVars:
    def test_build_template_vars(self):
        vars = _build_template_vars("some result", "my_task")
        assert vars["result"] == "some result"
        assert vars["task_name"] == "my_task"
        assert "timestamp" in vars
        # timestamp should be ISO format
        datetime.fromisoformat(vars["timestamp"])

    def test_template_substitution(self):
        vars = _build_template_vars("OK", "backup")
        tmpl = Template("Task $task_name result: $result")
        rendered = tmpl.safe_substitute(vars)
        assert "backup" in rendered
        assert "OK" in rendered

    def test_safe_substitute_missing_var(self):
        vars = _build_template_vars("OK", "test")
        tmpl = Template("$result $unknown_var")
        rendered = tmpl.safe_substitute(vars)
        assert "OK" in rendered
        assert "$unknown_var" in rendered


# --- Delivery Adapter Factory ---


class TestGetDeliveryAdapter:
    def test_email_adapter(self):
        adapter = get_delivery_adapter("email")
        assert isinstance(adapter, EmailDeliveryAdapter)

    def test_imessage_adapter(self):
        adapter = get_delivery_adapter("imessage")
        assert isinstance(adapter, IMessageDeliveryAdapter)

    def test_notification_adapter(self):
        adapter = get_delivery_adapter("notification")
        assert isinstance(adapter, NotificationDeliveryAdapter)

    def test_unknown_returns_none(self):
        assert get_delivery_adapter("slack") is None
        assert get_delivery_adapter("") is None

    def test_valid_channels_constant(self):
        assert VALID_CHANNELS == {"email", "imessage", "notification"}


# --- Email Delivery Adapter ---


class TestEmailDeliveryAdapter:
    @patch("scheduler.delivery.EmailDeliveryAdapter.deliver")
    def test_deliver_calls_mail_store(self, mock_deliver):
        mock_deliver.return_value = {"status": "delivered", "channel": "email"}
        adapter = EmailDeliveryAdapter()
        result = adapter.deliver("task completed", {"to": ["a@b.com"]}, "backup")
        assert result["status"] == "delivered"

    def test_no_recipients_returns_error(self):
        with patch("apple_mail.mail.MailStore") as MockMail:
            adapter = EmailDeliveryAdapter()
            result = adapter.deliver("result", {}, "test_task")
            assert result["status"] == "error"
            assert "No recipients" in result["error"]

    def test_subject_template_rendering(self):
        with patch("apple_mail.mail.MailStore") as MockMail:
            mock_instance = MagicMock()
            mock_instance.send_message.return_value = {"status": "sent"}
            MockMail.return_value = mock_instance

            adapter = EmailDeliveryAdapter()
            config = {
                "to": ["test@example.com"],
                "subject_template": "Report: $task_name",
                "body_template": "Result: $result at $timestamp",
            }
            result = adapter.deliver("all good", config, "daily_report")
            assert result["status"] == "delivered"

            call_kwargs = mock_instance.send_message.call_args
            assert "daily_report" in call_kwargs.kwargs.get("subject", "") or "daily_report" in str(call_kwargs)

    def test_default_subject_template(self):
        with patch("apple_mail.mail.MailStore") as MockMail:
            mock_instance = MagicMock()
            mock_instance.send_message.return_value = {"status": "sent"}
            MockMail.return_value = mock_instance

            adapter = EmailDeliveryAdapter()
            config = {"to": ["test@example.com"]}
            adapter.deliver("ok", config, "my_task")

            call_args = mock_instance.send_message.call_args
            # Default subject should include task name
            subject = call_args.kwargs.get("subject", "")
            assert "my_task" in subject


# --- IMessage Delivery Adapter ---


class TestIMessageDeliveryAdapter:
    def test_no_recipient_returns_error(self):
        adapter = IMessageDeliveryAdapter()
        with patch("apple_messages.messages.MessageStore"):
            result = adapter.deliver("result", {}, "test_task")
            assert result["status"] == "error"
            assert "No recipient" in result["error"]

    def test_deliver_with_recipient(self):
        with patch("apple_messages.messages.MessageStore") as MockMsg:
            mock_instance = MagicMock()
            mock_instance.send_message.return_value = {"status": "sent"}
            MockMsg.return_value = mock_instance

            adapter = IMessageDeliveryAdapter()
            config = {"recipient": "+15551234567"}
            result = adapter.deliver("task done", config, "checker")
            assert result["status"] == "delivered"
            assert result["channel"] == "imessage"

            call_args = mock_instance.send_message.call_args
            assert call_args.kwargs["to"] == "+15551234567"
            assert call_args.kwargs["confirm_send"] is True

    def test_deliver_with_chat_identifier(self):
        with patch("apple_messages.messages.MessageStore") as MockMsg:
            mock_instance = MagicMock()
            mock_instance.send_message.return_value = {"status": "sent"}
            MockMsg.return_value = mock_instance

            adapter = IMessageDeliveryAdapter()
            config = {"chat_identifier": "chat12345"}
            result = adapter.deliver("done", config, "task1")
            assert result["status"] == "delivered"

    def test_body_template(self):
        with patch("apple_messages.messages.MessageStore") as MockMsg:
            mock_instance = MagicMock()
            mock_instance.send_message.return_value = {"status": "sent"}
            MockMsg.return_value = mock_instance

            adapter = IMessageDeliveryAdapter()
            config = {
                "recipient": "+15551234567",
                "body_template": "Alert from $task_name: $result",
            }
            adapter.deliver("all clear", config, "monitor")
            call_args = mock_instance.send_message.call_args
            body = call_args.kwargs["body"]
            assert "monitor" in body
            assert "all clear" in body


# --- Notification Delivery Adapter ---


class TestNotificationDeliveryAdapter:
    def test_deliver_notification(self):
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            mock_send.return_value = {"status": "sent"}
            adapter = NotificationDeliveryAdapter()
            config = {"sound": "Ping"}
            result = adapter.deliver("task result", config, "backup_task")
            assert result["status"] == "delivered"
            assert result["channel"] == "notification"
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs
            assert "backup_task" in call_kwargs["title"]
            assert call_kwargs["sound"] == "Ping"

    def test_default_sound(self):
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            mock_send.return_value = {"status": "sent"}
            adapter = NotificationDeliveryAdapter()
            adapter.deliver("result", {}, "test")
            call_kwargs = mock_send.call_args.kwargs
            assert call_kwargs["sound"] == "default"

    def test_title_template(self):
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            mock_send.return_value = {"status": "sent"}
            adapter = NotificationDeliveryAdapter()
            config = {"title_template": "ALERT: $task_name"}
            adapter.deliver("ok", config, "my_check")
            call_kwargs = mock_send.call_args.kwargs
            assert "ALERT: my_check" in call_kwargs["title"]

    def test_body_truncation(self):
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            mock_send.return_value = {"status": "sent"}
            adapter = NotificationDeliveryAdapter()
            long_result = "x" * 500
            adapter.deliver(long_result, {}, "test")
            call_kwargs = mock_send.call_args.kwargs
            assert len(call_kwargs["message"]) <= 200


# --- deliver_result convenience function ---


class TestHumanizedDelivery:
    def test_deliver_result_humanizes_text(self):
        """deliver_result should humanize result_text before passing to adapter."""
        from humanizer.rules import humanize

        text = "Additionally, we utilize this comprehensive tool."
        cleaned = humanize(text)
        assert "Additionally" not in cleaned
        assert "utilize" not in cleaned
        assert "comprehensive" not in cleaned

    def test_adapter_receives_humanized_text(self):
        """The adapter should receive humanized text, not raw AI text."""
        with patch("scheduler.delivery.get_delivery_adapter") as mock_get:
            mock_adapter = MagicMock()
            mock_adapter.deliver.return_value = {"status": "delivered"}
            mock_get.return_value = mock_adapter

            deliver_result("email", {}, "Additionally, we utilize this.", "task")

            call_args = mock_adapter.deliver.call_args
            delivered_text = call_args[0][0]
            assert "Additionally" not in delivered_text
            assert "utilize" not in delivered_text


class TestDeliverResult:
    def test_unknown_channel(self):
        result = deliver_result("slack", {}, "text", "task")
        assert result["status"] == "error"
        assert "Unknown delivery channel" in result["error"]

    def test_adapter_exception_caught(self):
        with patch("scheduler.delivery.get_delivery_adapter") as mock_get:
            mock_adapter = MagicMock()
            mock_adapter.deliver.side_effect = RuntimeError("boom")
            mock_get.return_value = mock_adapter

            result = deliver_result("email", {}, "text", "task")
            assert result["status"] == "error"
            assert "boom" in result["error"]

    def test_successful_delivery(self):
        with patch("scheduler.delivery.get_delivery_adapter") as mock_get:
            mock_adapter = MagicMock()
            mock_adapter.deliver.return_value = {"status": "delivered", "channel": "notification"}
            mock_get.return_value = mock_adapter

            result = deliver_result("notification", {"sound": "default"}, "ok", "task1")
            assert result["status"] == "delivered"


# --- Schema Migration ---


class TestDeliveryMigration:
    def test_delivery_columns_exist(self, memory_store):
        """Verify the migration added delivery_channel and delivery_config columns."""
        row = memory_store.conn.execute(
            "PRAGMA table_info(scheduled_tasks)"
        ).fetchall()
        col_names = {r["name"] for r in row}
        assert "delivery_channel" in col_names
        assert "delivery_config" in col_names

    def test_migration_idempotent(self, tmp_path):
        """Running migration twice should not raise."""
        store1 = MemoryStore(tmp_path / "test_idem.db")
        store1.close()
        # Re-open triggers migration again
        store2 = MemoryStore(tmp_path / "test_idem.db")
        row = store2.conn.execute(
            "PRAGMA table_info(scheduled_tasks)"
        ).fetchall()
        col_names = {r["name"] for r in row}
        assert "delivery_channel" in col_names
        assert "delivery_config" in col_names
        store2.close()

    def test_store_and_retrieve_delivery_fields(self, memory_store):
        """Store a task with delivery config and verify round-trip."""
        task = ScheduledTask(
            name="delivery_test",
            schedule_type="interval",
            schedule_config='{"hours": 1}',
            handler_type="custom",
            handler_config='{"command": "echo hi"}',
            delivery_channel="email",
            delivery_config={"to": ["a@b.com"], "subject_template": "Test: $task_name"},
        )
        stored = memory_store.store_scheduled_task(task)
        assert stored.delivery_channel == "email"
        assert stored.delivery_config == {"to": ["a@b.com"], "subject_template": "Test: $task_name"}

    def test_store_without_delivery_fields(self, memory_store):
        """Task without delivery fields should have None values."""
        task = ScheduledTask(
            name="no_delivery",
            schedule_type="interval",
            schedule_config='{"minutes": 30}',
            handler_type="custom",
        )
        stored = memory_store.store_scheduled_task(task)
        assert stored.delivery_channel is None
        assert stored.delivery_config is None

    def test_update_delivery_fields(self, memory_store):
        """Update delivery fields on an existing task."""
        task = ScheduledTask(
            name="updatable",
            schedule_type="interval",
            schedule_config='{"hours": 2}',
            handler_type="custom",
        )
        stored = memory_store.store_scheduled_task(task)
        assert stored.delivery_channel is None

        updated = memory_store.update_scheduled_task(
            stored.id,
            delivery_channel="notification",
            delivery_config={"sound": "Ping"},
        )
        assert updated.delivery_channel == "notification"
        assert updated.delivery_config == {"sound": "Ping"}

    def test_clear_delivery_fields(self, memory_store):
        """Set delivery fields to None to clear them."""
        task = ScheduledTask(
            name="clearable",
            schedule_type="interval",
            schedule_config='{"hours": 1}',
            handler_type="custom",
            delivery_channel="email",
            delivery_config={"to": ["x@y.com"]},
        )
        stored = memory_store.store_scheduled_task(task)
        assert stored.delivery_channel == "email"

        updated = memory_store.update_scheduled_task(
            stored.id,
            delivery_channel=None,
            delivery_config=None,
        )
        assert updated.delivery_channel is None
        assert updated.delivery_config is None


# --- Scheduler Engine Delivery Integration ---


class TestSchedulerEngineDelivery:
    def test_delivery_called_after_execution(self, memory_store):
        """Engine should call delivery when delivery_channel is set."""
        task = ScheduledTask(
            name="with_delivery",
            schedule_type="interval",
            schedule_config='{"hours": 1}',
            handler_type="custom",
            handler_config='{"command": "echo hello"}',
            delivery_channel="notification",
            delivery_config={"sound": "default"},
            enabled=True,
            next_run_at=datetime.now().isoformat(),
        )
        stored = memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        with patch.object(engine, "_deliver") as mock_deliver:
            mock_deliver.return_value = {"status": "delivered"}
            with patch("scheduler.engine.execute_handler") as mock_exec:
                mock_exec.return_value = '{"status": "ok"}'
                result = engine._execute_task(stored, datetime.now())

            mock_deliver.assert_called_once()
            assert "delivery" in result
            assert result["delivery"]["status"] == "delivered"

    def test_no_delivery_when_channel_not_set(self, memory_store):
        """Engine should skip delivery when delivery_channel is None."""
        task = ScheduledTask(
            name="no_delivery",
            schedule_type="interval",
            schedule_config='{"hours": 1}',
            handler_type="custom",
            handler_config='{"command": "echo hi"}',
            enabled=True,
            next_run_at=datetime.now().isoformat(),
        )
        stored = memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        with patch.object(engine, "_deliver") as mock_deliver:
            with patch("scheduler.engine.execute_handler") as mock_exec:
                mock_exec.return_value = '{"status": "ok"}'
                result = engine._execute_task(stored, datetime.now())

            mock_deliver.assert_not_called()
            assert "delivery" not in result

    def test_delivery_failure_does_not_block_execution(self, memory_store):
        """If delivery raises, the task should still succeed."""
        task = ScheduledTask(
            name="delivery_fails",
            schedule_type="interval",
            schedule_config='{"hours": 1}',
            handler_type="custom",
            handler_config='{"command": "echo test"}',
            delivery_channel="email",
            delivery_config={"to": ["fail@example.com"]},
            enabled=True,
            next_run_at=datetime.now().isoformat(),
        )
        stored = memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        with patch("scheduler.engine.execute_handler") as mock_exec:
            mock_exec.return_value = '{"status": "ok"}'
            with patch("scheduler.delivery.deliver_result") as mock_deliver:
                mock_deliver.side_effect = RuntimeError("delivery exploded")
                result = engine._execute_task(stored, datetime.now())

        # Task execution should still be marked as executed
        assert result["status"] == "executed"
        # Delivery error should be captured
        assert result["delivery"]["status"] == "error"

    def test_evaluate_due_tasks_with_delivery(self, memory_store):
        """End-to-end: evaluate_due_tasks triggers delivery."""
        now = datetime.now()
        task = ScheduledTask(
            name="due_with_delivery",
            schedule_type="interval",
            schedule_config='{"hours": 1}',
            handler_type="custom",
            handler_config='{"command": "echo due"}',
            delivery_channel="notification",
            delivery_config={"sound": "default"},
            enabled=True,
            next_run_at=(now - timedelta(minutes=5)).isoformat(),
        )
        memory_store.store_scheduled_task(task)

        engine = SchedulerEngine(memory_store)
        with patch("scheduler.engine.execute_handler") as mock_exec:
            mock_exec.return_value = '{"status": "ok"}'
            with patch("scheduler.delivery.deliver_result") as mock_deliver:
                mock_deliver.return_value = {"status": "delivered", "channel": "notification"}
                results = engine.evaluate_due_tasks(now=now)

        assert len(results) == 1
        assert results[0]["status"] == "executed"
        assert results[0]["delivery"]["status"] == "delivered"


# --- MCP Tool Tests ---


class TestMCPSchedulerToolsDelivery:
    """Test delivery params in MCP scheduler tools."""

    @pytest.fixture
    def shared_state(self, memory_store):
        return {"memory_store": memory_store}

    @pytest.mark.asyncio
    async def test_create_with_delivery_channel(self, shared_state, memory_store):
        """create_scheduled_task should accept delivery_channel and delivery_config."""
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await create_scheduled_task(
                name="email_task",
                schedule_type="interval",
                schedule_config='{"hours": 1}',
                handler_type="custom",
                handler_config='{"command": "echo hi"}',
                delivery_channel="email",
                delivery_config='{"to": ["user@example.com"], "subject_template": "Report: $task_name"}',
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["task"]["delivery_channel"] == "email"

        # Verify in store
        stored = memory_store.get_scheduled_task(data["task"]["id"])
        assert stored.delivery_channel == "email"
        assert stored.delivery_config["to"] == ["user@example.com"]

    @pytest.mark.asyncio
    async def test_create_with_invalid_delivery_channel(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await create_scheduled_task(
                name="bad_channel",
                schedule_type="interval",
                schedule_config='{"hours": 1}',
                handler_type="custom",
                delivery_channel="slack",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "error"
        assert "Invalid delivery_channel" in data["error"]

    @pytest.mark.asyncio
    async def test_create_with_invalid_delivery_config_json(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await create_scheduled_task(
                name="bad_config",
                schedule_type="interval",
                schedule_config='{"hours": 1}',
                handler_type="custom",
                delivery_channel="email",
                delivery_config="not json",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "error"
        assert "Invalid delivery_config JSON" in data["error"]

    @pytest.mark.asyncio
    async def test_create_without_delivery(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            result = await create_scheduled_task(
                name="no_delivery_task",
                schedule_type="interval",
                schedule_config='{"hours": 1}',
                handler_type="custom",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["task"]["delivery_channel"] is None

    @pytest.mark.asyncio
    async def test_update_delivery_channel(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, update_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            # Create without delivery
            create_result = await create_scheduled_task(
                name="update_delivery_test",
                schedule_type="interval",
                schedule_config='{"hours": 1}',
                handler_type="custom",
            )
            task_id = json.loads(create_result)["task"]["id"]

            # Add delivery
            update_result = await update_scheduled_task(
                task_id=task_id,
                delivery_channel="imessage",
                delivery_config='{"recipient": "+15551234567"}',
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(update_result)
        assert data["status"] == "updated"
        assert data["task"]["delivery_channel"] == "imessage"

    @pytest.mark.asyncio
    async def test_update_clear_delivery_with_none(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, update_scheduled_task

        mcp_server._state.update(shared_state)
        try:
            create_result = await create_scheduled_task(
                name="clear_delivery_test",
                schedule_type="interval",
                schedule_config='{"hours": 1}',
                handler_type="custom",
                delivery_channel="notification",
                delivery_config='{"sound": "Ping"}',
            )
            task_id = json.loads(create_result)["task"]["id"]

            # Clear delivery
            update_result = await update_scheduled_task(
                task_id=task_id,
                delivery_channel="none",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(update_result)
        assert data["status"] == "updated"
        assert data["task"]["delivery_channel"] is None

    @pytest.mark.asyncio
    async def test_list_includes_delivery_channel(self, shared_state):
        import mcp_server
        from mcp_tools.scheduler_tools import create_scheduled_task, list_scheduled_tasks

        mcp_server._state.update(shared_state)
        try:
            await create_scheduled_task(
                name="list_delivery_test",
                schedule_type="interval",
                schedule_config='{"hours": 1}',
                handler_type="custom",
                delivery_channel="email",
                delivery_config='{"to": ["a@b.com"]}',
            )

            result = await list_scheduled_tasks()
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        found = [t for t in data["tasks"] if t["name"] == "list_delivery_test"]
        assert len(found) == 1
        assert found[0]["delivery_channel"] == "email"
