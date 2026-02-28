# ADR-006: Persistent Daemon Replacing launchd Agents

## Status

Accepted (2026-02-22)

## Context

The system originally used three separate launchd agents for background processing:
- `com.chg.scheduler-engine.plist` -- Run scheduler every 5 minutes
- `com.chg.alert-evaluator.plist` -- Evaluate alert rules every 2 hours
- `com.chg.inbox-monitor.plist` -- Poll webhook inbox every 5 minutes

Problems with this approach:
- Each launchd agent spawns a new Python process, incurring interpreter startup and module import overhead each time
- macOS TCC blocks launchd from opening log files in `~/Documents/` (exit code 78)
- Three separate plist files to manage, each with its own scheduling configuration
- No shared state between invocations (each run initializes a fresh MemoryStore)
- Debugging requires checking three separate log streams

## Decision

Replace all three launchd agents with a single `JarvisDaemon` -- a persistent asyncio process that wraps `SchedulerEngine` in a configurable tick loop.

### Architecture

```python
class JarvisDaemon:
    async def run(self):
        while not self._shutdown:
            await self._tick()  # SchedulerEngine.evaluate_due_tasks_async()
            await asyncio.sleep(self.tick_interval)
```

### Key Design Choices

1. **Single process** -- One Python interpreter, one MemoryStore instance, one set of module imports
2. **SQLite-driven scheduling** -- All timing is in the `scheduled_tasks` table (interval, cron, once), not in launchd plists
3. **Graceful shutdown** -- SIGTERM/SIGINT set a `_shutdown` flag; the current tick completes before exit
4. **Timeout protection** -- Each handler runs under `asyncio.wait_for()` with `SCHEDULER_HANDLER_TIMEOUT_SECONDS`
5. **Error isolation** -- A failing handler never crashes the daemon loop; errors are logged and the next tick proceeds

### Migration

The three launchd tasks became rows in `scheduled_tasks`:
- `alert_eval` -- interval 2 hours
- `webhook_poll` -- interval 5 minutes
- `webhook_dispatch` -- interval 5 minutes
- `skill_analysis` -- interval 24 hours

These are seeded automatically by `mcp_server.py` on first run.

## Consequences

**Benefits:**
- One process instead of three, with shared connection pool and module cache
- Unified logging to a single file (`data/jarvis-daemon.log`) plus stderr
- All scheduling is in SQLite -- visible via `list_scheduled_tasks` MCP tool
- New scheduled tasks can be added at runtime without modifying plist files
- Per-handler timeout protection prevents hung tasks from blocking others

**Tradeoffs:**
- The daemon must be kept running (managed by a single launchd plist or manual start)
- A crash kills all scheduled processing until restart (mitigated by launchd KeepAlive)
- The tick loop polls every N seconds even when no tasks are due (low overhead but not zero)
- Async timeout via `asyncio.wait_for` cannot kill blocking synchronous code; it only cancels the asyncio task

## Related

- `scheduler/daemon.py` -- JarvisDaemon implementation
- `scheduler/engine.py` -- SchedulerEngine with async evaluation
- `scheduler/handlers.py` -- Handler dispatch
- `config.py` -- DAEMON_TICK_INTERVAL_SECONDS, SCHEDULER_HANDLER_TIMEOUT_SECONDS
- `scripts/com.chg.jarvis-daemon.plist` -- launchd plist for the daemon
