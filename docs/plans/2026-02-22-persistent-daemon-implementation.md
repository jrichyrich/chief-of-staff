# Persistent Daemon Process — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace 3 separate launchd agents (scheduler-engine, alert-evaluator, inbox-monitor) with one persistent asyncio daemon that wraps the existing `SchedulerEngine` in a tick loop.

**Architecture:** New `scheduler/daemon.py` with a `JarvisDaemon` class that runs `SchedulerEngine.evaluate_due_tasks()` on a configurable tick interval via `asyncio.sleep()`. Signal handlers (SIGTERM/SIGINT) set a shutdown flag for graceful exit. One new launchd plist with `KeepAlive=true`. No changes to existing scheduler/handler code.

**Tech Stack:** Python, asyncio, pytest

---

### Task 1: Add config constants and create JarvisDaemon

**Files:**
- Modify: `config.py:31` (after SCHEDULER_ENABLED)
- Create: `scheduler/daemon.py`
- Create: `tests/test_daemon.py`

**Step 1: Write the tests**

Create `tests/test_daemon.py`:

```python
"""Tests for the persistent scheduler daemon."""

import asyncio
import json
import signal
from datetime import datetime
from unittest.mock import MagicMock, patch

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
        with patch("scheduler.engine._run_alert_eval_handler", return_value='{"status":"ok"}'):
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
        import time
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
```

**Step 2: Add config constants**

In `config.py`, after line 31 (`SCHEDULER_ENABLED = ...`), add:

```python
# Daemon settings
DAEMON_TICK_INTERVAL_SECONDS = int(os.environ.get("DAEMON_TICK_INTERVAL_SECONDS", "60"))
DAEMON_LOG_FILE = DATA_DIR / "jarvis-daemon.log"
```

**Step 3: Write the implementation**

Create `scheduler/daemon.py`:

```python
"""Persistent scheduler daemon — replaces 3 launchd agents with one asyncio loop.

Runs SchedulerEngine.evaluate_due_tasks() on a configurable tick interval.
SIGTERM/SIGINT trigger graceful shutdown after the current tick completes.

Replaces:
  - com.chg.scheduler-engine.plist (5 min polling)
  - com.chg.alert-evaluator.plist (2 hour polling — already an alert_eval handler)
  - com.chg.inbox-monitor.plist (5 min polling — already a webhook_poll handler)
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis-daemon")


class JarvisDaemon:
    """Persistent daemon that wraps SchedulerEngine in an async tick loop."""

    def __init__(self, memory_store, tick_interval: int = 60):
        """
        Args:
            memory_store: MemoryStore instance for SchedulerEngine.
            tick_interval: Seconds between evaluation ticks (default 60).
        """
        from scheduler.engine import SchedulerEngine

        self.engine = SchedulerEngine(memory_store)
        self.tick_interval = tick_interval
        self._shutdown = False
        self._sleep_task: Optional[asyncio.Task] = None

    def shutdown(self):
        """Request graceful shutdown after the current tick completes."""
        self._shutdown = True
        if self._sleep_task and not self._sleep_task.done():
            self._sleep_task.cancel()

    def _setup_signals(self, loop: asyncio.AbstractEventLoop):
        """Register SIGTERM and SIGINT handlers for graceful shutdown."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.shutdown)

    async def _tick(self) -> list[dict]:
        """Run one evaluation cycle. Never raises."""
        try:
            results = self.engine.evaluate_due_tasks()
            if results:
                logger.info(
                    "Tick complete: %d tasks evaluated (%d errors)",
                    len(results),
                    sum(1 for r in results if r.get("status") == "error"),
                )
            return results
        except Exception as e:
            logger.error("Tick failed: %s", e)
            return []

    async def run(self):
        """Main daemon loop. Runs ticks until shutdown is requested."""
        loop = asyncio.get_running_loop()
        self._setup_signals(loop)
        logger.info("Daemon started (tick_interval=%ds)", self.tick_interval)

        while not self._shutdown:
            await self._tick()

            if self._shutdown:
                break

            try:
                self._sleep_task = asyncio.ensure_future(
                    asyncio.sleep(self.tick_interval)
                )
                await self._sleep_task
            except asyncio.CancelledError:
                pass  # Shutdown requested during sleep

        logger.info("Daemon shutting down gracefully")


# --- Standalone Entry Point ---

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import DAEMON_LOG_FILE, DAEMON_TICK_INTERVAL_SECONDS, MEMORY_DB_PATH
    from memory.store import MemoryStore

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(DAEMON_LOG_FILE),
            logging.StreamHandler(sys.stderr),
        ],
    )

    if not MEMORY_DB_PATH.exists():
        logger.error("Memory DB not found at %s", MEMORY_DB_PATH)
        sys.exit(1)

    store = MemoryStore(MEMORY_DB_PATH)
    daemon = JarvisDaemon(
        memory_store=store,
        tick_interval=DAEMON_TICK_INTERVAL_SECONDS,
    )

    try:
        asyncio.run(daemon.run())
    finally:
        store.close()
        logger.info("Daemon exited")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_daemon.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add config.py scheduler/daemon.py tests/test_daemon.py
git commit -m "feat: add persistent scheduler daemon with async tick loop"
```

---

### Task 2: Create launchd plist for the daemon

**Files:**
- Create: `scripts/com.chg.jarvis-daemon.plist`

**Step 1: Write the plist**

Create `scripts/com.chg.jarvis-daemon.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.chg.jarvis-daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/env</string>
        <string>python3</string>
        <string>-m</string>
        <string>scheduler.daemon</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>__PROJECT_DIR__</string>
    <key>StandardOutPath</key>
    <string>__PROJECT_DIR__/data/jarvis-daemon.log</string>
    <key>StandardErrorPath</key>
    <string>__PROJECT_DIR__/data/jarvis-daemon.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

**Step 2: Commit**

```bash
git add scripts/com.chg.jarvis-daemon.plist
git commit -m "feat: add launchd plist for persistent daemon (KeepAlive)"
```

---

### Task 3: Run full test suite and verify no regressions

**Files:** None (verification only)

**Step 1: Run full test suite**

Run: `pytest`
Expected: All 1452+ tests pass, zero failures

**Step 2: Commit (final)**

```bash
git add -A
git commit -m "feat: persistent daemon process — unified scheduler with async tick loop

New JarvisDaemon class wraps SchedulerEngine in an asyncio tick loop.
Replaces 3 separate launchd agents (scheduler-engine, alert-evaluator,
inbox-monitor) with one persistent KeepAlive process. SIGTERM/SIGINT
trigger graceful shutdown. Configurable tick interval via
DAEMON_TICK_INTERVAL_SECONDS env var."
```
