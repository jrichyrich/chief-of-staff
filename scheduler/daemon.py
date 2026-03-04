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

    def __init__(
        self,
        memory_store,
        tick_interval: float = 60,
        agent_registry=None,
        document_store=None,
        imessage_daemon=None,
    ):
        """
        Args:
            memory_store: MemoryStore instance for SchedulerEngine.
            tick_interval: Seconds between evaluation ticks (default 60).
            agent_registry: Optional AgentRegistry for agent-based handlers.
            document_store: Optional DocumentStore for document-aware handlers.
            imessage_daemon: Optional IMessageDaemon for iMessage command polling.
        """
        from scheduler.engine import SchedulerEngine

        self.engine = SchedulerEngine(memory_store, agent_registry=agent_registry, document_store=document_store)
        self.tick_interval = tick_interval
        self._shutdown = False
        self._sleep_task: Optional[asyncio.Task] = None
        self.imessage_daemon = imessage_daemon

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
        """Run one evaluation cycle with async timeout support. Never raises."""
        results = []
        try:
            scheduler_results = await self.engine.evaluate_due_tasks_async()
            results.extend(scheduler_results)
            if scheduler_results:
                logger.info(
                    "Tick complete: %d tasks evaluated (%d errors, %d timeouts)",
                    len(scheduler_results),
                    sum(1 for r in scheduler_results if r.get("status") == "error"),
                    sum(1 for r in scheduler_results if r.get("status") == "timeout"),
                )
        except Exception as e:
            logger.error("Tick failed: %s", e)

        # iMessage polling
        if self.imessage_daemon is not None:
            try:
                imsg_result = await self.imessage_daemon.run_once()
                if imsg_result.get("ingested", 0) > 0 or imsg_result.get("dispatched", 0) > 0:
                    logger.info("iMessage poll: %s", imsg_result)
            except Exception as e:
                logger.error("iMessage poll failed: %s", e)

        # Proactive action pass — act on high-priority suggestions autonomously
        try:
            import config as app_config
            if getattr(app_config, "PROACTIVE_ACTION_ENABLED", False):
                from proactive.engine import ProactiveSuggestionEngine
                from proactive.action_executor import execute_suggestion_action

                engine = ProactiveSuggestionEngine(self.engine.memory_store)
                suggestions = engine.generate_suggestions()
                for s in suggestions:
                    if s.priority == "high":
                        action_result = execute_suggestion_action(
                            s, memory_store=self.engine.memory_store,
                        )
                        if action_result.get("executed"):
                            logger.info("Proactive action executed: %s -> %s", s.action, action_result)
        except Exception as e:
            logger.error("Proactive action pass failed: %s", e)

        return results

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


def build_imessage_daemon():
    """Build IMessageDaemon from config if enabled, else return None."""
    from config import (
        ANTHROPIC_API_KEY,
        DATA_DIR,
        IMESSAGE_DAEMON_BOOTSTRAP_LOOKBACK_MINUTES,
        IMESSAGE_DAEMON_ENABLED,
        IMESSAGE_DAEMON_MONITORED_CONVERSATION,
        IMESSAGE_DAEMON_POLL_INTERVAL_SECONDS,
        IMESSAGE_DAEMON_REPLY_HANDLE,
        IMESSAGE_WORKER_DB_PATH,
    )

    if not IMESSAGE_DAEMON_ENABLED:
        return None

    from chief.imessage_daemon import DaemonConfig, IMessageDaemon
    from chief.imessage_executor import IMessageExecutor

    cfg = DaemonConfig(
        project_dir=Path(__file__).resolve().parents[1],
        data_dir=DATA_DIR,
        state_db_path=IMESSAGE_WORKER_DB_PATH,
        poll_interval_seconds=IMESSAGE_DAEMON_POLL_INTERVAL_SECONDS,
        bootstrap_lookback_minutes=IMESSAGE_DAEMON_BOOTSTRAP_LOOKBACK_MINUTES,
        monitored_conversation=IMESSAGE_DAEMON_MONITORED_CONVERSATION,
    )

    # Build executor with Claude API client
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    executor = IMessageExecutor(client=client)

    # Build reply function
    reply_handle = IMESSAGE_DAEMON_REPLY_HANDLE
    reply_fn = None
    if reply_handle:
        from apple_messages.messages import MessageStore

        msg_store = MessageStore()

        def _reply(body: str) -> dict:
            return msg_store.send_message(to=reply_handle, body=body, confirm_send=True)

        reply_fn = _reply

    return IMessageDaemon(cfg, executor=executor, reply_fn=reply_fn)


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
    imessage = build_imessage_daemon()
    daemon = JarvisDaemon(
        memory_store=store,
        tick_interval=DAEMON_TICK_INTERVAL_SECONDS,
        imessage_daemon=imessage,
    )

    try:
        asyncio.run(daemon.run())
    finally:
        store.close()
        logger.info("Daemon exited")
