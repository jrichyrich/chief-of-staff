# Persistent Daemon Process — Design

**Date**: 2026-02-22
**Status**: Approved
**Backlog**: jarvis_backlog_017_persistent_daemon_process

## Problem

Three separate launchd agents (scheduler-engine, alert-evaluator, inbox-monitor) each spin up a Python process on a timer, import stores, evaluate tasks, then exit. Each cold-start re-initializes the MemoryStore and imports. The alert-evaluator and inbox-monitor are already subsumable by the scheduler engine's `alert_eval` and `webhook_poll` handler types. Unifying them into one persistent process eliminates redundant process spawns and store initializations.

## Design

### New Module: `scheduler/daemon.py`

A persistent asyncio daemon that wraps the existing `SchedulerEngine` in a tick loop. Replaces 3 launchd plists with one always-running process.

### Architecture

```
scheduler/daemon.py
├── JarvisDaemon class
│   ├── __init__(tick_interval=60, memory_store=None)
│   ├── async run()        — main loop: tick → sleep → repeat
│   ├── async _tick()      — calls SchedulerEngine.evaluate_due_tasks()
│   ├── _setup_signals()   — SIGTERM/SIGINT → set shutdown flag
│   └── shutdown()         — graceful stop after current tick
└── __main__ entry point   — init stores, run daemon
```

### Tick Cycle

1. `SchedulerEngine.evaluate_due_tasks()` — finds tasks where `next_run_at <= now`, runs handlers, updates state
2. Log results (tasks evaluated, successes, errors)
3. `await asyncio.sleep(tick_interval)` — non-blocking, respects shutdown flag

### Signal Handling

- `SIGTERM` and `SIGINT` set a `_shutdown` flag
- The tick loop checks the flag after each tick and after sleep
- Current tick completes before shutdown (no interruption mid-handler)

### What It Replaces

| Old Launchd Agent | Frequency | Replacement |
|-------------------|-----------|-------------|
| `com.chg.scheduler-engine.plist` | 5 min | Daemon tick evaluates all due scheduled tasks |
| `com.chg.alert-evaluator.plist` | 2 hours | Already a `alert_eval` handler type in scheduler |
| `com.chg.inbox-monitor.plist` | 5 min | Already a `webhook_poll` handler type in scheduler |

### What Stays As-Is

| Launchd Agent | Reason |
|---------------|--------|
| `com.chg.imessage-daemon.plist` | Separate StateStore (imessage-worker.db), KeepAlive semantics, 5-sec poll loop |
| `com.chg.jarvis-backup.plist` | Daily shell script, well-tested, no benefit from Python wrapping |

### New Launchd Plist

`com.chg.jarvis-daemon.plist` with `KeepAlive=true`. Daemon restarts automatically if it crashes.

### Configuration

- `DAEMON_TICK_INTERVAL_SECONDS`: env var, default 60
- `DAEMON_LOG_FILE`: env var, default `data/jarvis-daemon.log`

### Error Handling

- Handler failures already isolated in `SchedulerEngine._execute_task`
- Tick-level exceptions caught and logged; daemon continues
- SIGTERM triggers graceful shutdown flag; loop exits after current tick completes

### Exclusions

- No changes to `SchedulerEngine`, `CronExpression`, handler functions, or delivery system
- No async conversion of handlers (they stay sync, called from async boundary)
- No watchdog/health-check endpoint
- No changes to iMessage daemon or backup script

## Files Modified

| File | Change |
|------|--------|
| `scheduler/daemon.py` | New: JarvisDaemon class with async tick loop |
| `scripts/com.chg.jarvis-daemon.plist` | New: KeepAlive launchd plist |
| `config.py` | Add DAEMON_TICK_INTERVAL_SECONDS, DAEMON_LOG_FILE |
| `tests/test_daemon.py` | Tests for daemon lifecycle, tick execution, signal handling |
