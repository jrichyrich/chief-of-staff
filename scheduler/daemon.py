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

    def __init__(self, memory_store, tick_interval: float = 60, agent_registry=None, document_store=None):
        """
        Args:
            memory_store: MemoryStore instance for SchedulerEngine.
            tick_interval: Seconds between evaluation ticks (default 60).
            agent_registry: Optional AgentRegistry for agent-based handlers.
            document_store: Optional DocumentStore for document-aware handlers.
        """
        from scheduler.engine import SchedulerEngine

        self.engine = SchedulerEngine(memory_store, agent_registry=agent_registry, document_store=document_store)
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
