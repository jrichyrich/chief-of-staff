"""Tests for the persistent scheduler daemon."""

import asyncio
import signal
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scheduler.daemon import JarvisDaemon


class TestJarvisDaemonInit:
    def test_default_tick_interval(self):
        """Default tick interval is 60 seconds."""
        daemon = JarvisDaemon(memory_store=MagicMock())
        assert daemon.tick_interval == 60

    def test_custom_tick_interval(self):
        """Tick interval is configurable."""
        daemon = JarvisDaemon(memory_store=MagicMock(), tick_interval=30)
        assert daemon.tick_interval == 30

    def test_shutdown_flag_initially_false(self):
        """Shutdown flag starts as False."""
        daemon = JarvisDaemon(memory_store=MagicMock())
        assert daemon._shutdown is False

    def test_stores_memory_store(self):
        """Memory store is stored for SchedulerEngine."""
        store = MagicMock()
        daemon = JarvisDaemon(memory_store=store)
        assert daemon.engine.memory_store is store


class TestJarvisDaemonShutdown:
    def test_shutdown_sets_flag(self):
        """shutdown() sets the _shutdown flag."""
        daemon = JarvisDaemon(memory_store=MagicMock())
        daemon.shutdown()
        assert daemon._shutdown is True

    def test_shutdown_idempotent(self):
        """Multiple shutdown() calls don't error."""
        daemon = JarvisDaemon(memory_store=MagicMock())
        daemon.shutdown()
        daemon.shutdown()
        assert daemon._shutdown is True


class TestJarvisDaemonTick:
    @pytest.mark.asyncio
    async def test_tick_calls_evaluate_due_tasks(self):
        """Each tick calls SchedulerEngine.evaluate_due_tasks()."""
        store = MagicMock()
        store.get_due_tasks.return_value = []
        daemon = JarvisDaemon(memory_store=store)
        results = await daemon._tick()
        store.get_due_tasks.assert_called_once()
        assert results == []

    @pytest.mark.asyncio
    async def test_tick_returns_results(self):
        """Tick returns the list of execution results."""
        store = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.name = "test_task"
        mock_task.handler_type = "alert_eval"
        mock_task.handler_config = ""
        mock_task.schedule_type = "interval"
        mock_task.schedule_config = '{"minutes": 60}'
        mock_task.delivery_channel = None
        store.get_due_tasks.return_value = [mock_task]
        daemon = JarvisDaemon(memory_store=store)
        with patch("scheduler.handlers._run_alert_eval_handler", return_value='{"status":"ok"}'):
            results = await daemon._tick()
        assert len(results) == 1
        assert results[0]["name"] == "test_task"

    @pytest.mark.asyncio
    async def test_tick_catches_exceptions(self):
        """Tick-level exceptions are caught, daemon doesn't crash."""
        store = MagicMock()
        store.get_due_tasks.side_effect = Exception("DB locked")
        daemon = JarvisDaemon(memory_store=store)
        results = await daemon._tick()
        assert results == []


class TestJarvisDaemonRun:
    @pytest.mark.asyncio
    async def test_run_exits_on_shutdown(self):
        """Daemon run() exits when shutdown flag is set."""
        store = MagicMock()
        store.get_due_tasks.return_value = []
        daemon = JarvisDaemon(memory_store=store, tick_interval=0.01)

        async def set_shutdown():
            await asyncio.sleep(0.05)
            daemon.shutdown()

        task = asyncio.create_task(set_shutdown())
        await daemon.run()
        await task
        assert daemon._shutdown is True

    @pytest.mark.asyncio
    async def test_run_calls_tick_multiple_times(self):
        """Daemon run() calls _tick on each iteration."""
        store = MagicMock()
        store.get_due_tasks.return_value = []
        daemon = JarvisDaemon(memory_store=store, tick_interval=0.01)

        call_count = 0
        original_tick = daemon._tick

        async def counting_tick():
            nonlocal call_count
            call_count += 1
            result = await original_tick()
            if call_count >= 3:
                daemon.shutdown()
            return result

        daemon._tick = counting_tick
        await daemon.run()
        assert call_count >= 3

    @pytest.mark.asyncio
    async def test_run_respects_shutdown_during_sleep(self):
        """Daemon exits promptly when shutdown is called during sleep."""
        store = MagicMock()
        store.get_due_tasks.return_value = []
        daemon = JarvisDaemon(memory_store=store, tick_interval=10)

        async def shutdown_soon():
            await asyncio.sleep(0.05)
            daemon.shutdown()

        task = asyncio.create_task(shutdown_soon())
        start = time.monotonic()
        await daemon.run()
        elapsed = time.monotonic() - start
        await task
        # Should exit well before the 10s tick interval
        assert elapsed < 2.0


class TestJarvisDaemonSignals:
    def test_setup_signals_registers_handlers(self):
        """_setup_signals registers SIGTERM and SIGINT handlers."""
        daemon = JarvisDaemon(memory_store=MagicMock())
        loop = asyncio.new_event_loop()
        try:
            daemon._setup_signals(loop)
            # Verify handlers were added (we can't easily inspect, but no error = success)
        finally:
            loop.close()


class TestIMessageIntegration:
    def test_imessage_daemon_default_none(self):
        """imessage_daemon defaults to None."""
        daemon = JarvisDaemon(memory_store=MagicMock())
        assert daemon.imessage_daemon is None

    def test_imessage_daemon_stored(self):
        """imessage_daemon is stored when provided."""
        mock_imsg = MagicMock()
        daemon = JarvisDaemon(memory_store=MagicMock(), imessage_daemon=mock_imsg)
        assert daemon.imessage_daemon is mock_imsg

    @pytest.mark.asyncio
    async def test_tick_runs_imessage_polling(self):
        """Daemon tick should run iMessage polling when enabled."""
        store = MagicMock()
        store.get_due_tasks.return_value = []
        daemon = JarvisDaemon(memory_store=store)

        mock_imessage_daemon = AsyncMock()
        mock_imessage_daemon.run_once = AsyncMock(return_value={"ingested": 2, "dispatched": 1})
        daemon.imessage_daemon = mock_imessage_daemon

        await daemon._tick()
        mock_imessage_daemon.run_once.assert_called_once()

    @pytest.mark.asyncio
    async def test_tick_skips_imessage_when_none(self):
        """Tick should not fail when imessage_daemon is None."""
        store = MagicMock()
        store.get_due_tasks.return_value = []
        daemon = JarvisDaemon(memory_store=store)
        # No error should occur
        results = await daemon._tick()
        assert results == []

    @pytest.mark.asyncio
    async def test_tick_catches_imessage_errors(self):
        """iMessage poll errors should not crash the daemon."""
        store = MagicMock()
        store.get_due_tasks.return_value = []
        daemon = JarvisDaemon(memory_store=store)

        mock_imessage_daemon = AsyncMock()
        mock_imessage_daemon.run_once = AsyncMock(side_effect=RuntimeError("chat.db locked"))
        daemon.imessage_daemon = mock_imessage_daemon

        # Should not raise
        results = await daemon._tick()
        assert results == []


class TestBuildImessageDaemon:
    def test_returns_none_when_disabled(self):
        """build_imessage_daemon returns None when disabled."""
        from scheduler.daemon import build_imessage_daemon

        with patch("config.IMESSAGE_DAEMON_ENABLED", False):
            result = build_imessage_daemon()
        assert result is None

    def test_returns_daemon_when_enabled(self, tmp_path):
        """build_imessage_daemon creates daemon when enabled."""
        from scheduler.daemon import build_imessage_daemon

        with patch("config.IMESSAGE_DAEMON_ENABLED", True), \
             patch("config.IMESSAGE_WORKER_DB_PATH", tmp_path / "worker.db"), \
             patch("config.IMESSAGE_DAEMON_REPLY_HANDLE", ""), \
             patch("config.DATA_DIR", tmp_path), \
             patch("config.IMESSAGE_DAEMON_POLL_INTERVAL_SECONDS", 60), \
             patch("config.IMESSAGE_DAEMON_BOOTSTRAP_LOOKBACK_MINUTES", 30), \
             patch("config.IMESSAGE_DAEMON_MONITORED_CONVERSATION", ""), \
             patch("config.ANTHROPIC_API_KEY", "test-key"):
            daemon = build_imessage_daemon()

        assert daemon is not None
        assert daemon.executor is not None
        # No reply handle → no reply_fn
        assert daemon.reply_fn is None


class TestDaemonConfig:
    def test_tick_interval_from_config(self):
        """DAEMON_TICK_INTERVAL_SECONDS config is importable."""
        from config import DAEMON_TICK_INTERVAL_SECONDS
        assert isinstance(DAEMON_TICK_INTERVAL_SECONDS, int)
        assert DAEMON_TICK_INTERVAL_SECONDS > 0

    def test_log_file_from_config(self):
        """DAEMON_LOG_FILE config is importable."""
        from config import DAEMON_LOG_FILE
        assert str(DAEMON_LOG_FILE).endswith("jarvis-daemon.log")

    def test_imessage_config_constants(self):
        """iMessage config constants are importable."""
        from config import (
            IMESSAGE_DAEMON_ENABLED,
            IMESSAGE_DAEMON_POLL_INTERVAL_SECONDS,
            IMESSAGE_DAEMON_BOOTSTRAP_LOOKBACK_MINUTES,
            IMESSAGE_DAEMON_MONITORED_CONVERSATION,
            IMESSAGE_DAEMON_REPLY_HANDLE,
            IMESSAGE_WORKER_DB_PATH,
        )
        assert isinstance(IMESSAGE_DAEMON_ENABLED, bool)
        assert isinstance(IMESSAGE_DAEMON_POLL_INTERVAL_SECONDS, int)
        assert isinstance(IMESSAGE_DAEMON_BOOTSTRAP_LOOKBACK_MINUTES, int)
