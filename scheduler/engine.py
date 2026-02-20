"""Built-in scheduler engine with cron parsing and task execution."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Commands that are never allowed in custom handlers
_DANGEROUS_COMMANDS = frozenset({
    "rm", "rmdir", "del", "format", "mkfs", "dd", "shred",
    "shutdown", "reboot", "halt", "poweroff",
    "chmod", "chown", "chgrp",
    "kill", "killall", "pkill",
    "sudo", "su", "doas",
})

# Maximum timeout for custom subprocess execution (seconds)
_CUSTOM_HANDLER_TIMEOUT = 30


# --- Cron Parser ---

class CronExpression:
    """Minimal cron expression parser supporting: minute hour day month weekday.

    Supports:
      - Exact values: 5
      - Wildcards: *
      - Ranges: 1-5
      - Lists: 1,3,5
      - Steps: */15, 1-30/5
    """

    def __init__(self, expression: str):
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Cron expression must have 5 fields, got {len(parts)}: '{expression}'")
        self.minute = self._parse_field(parts[0], 0, 59)
        self.hour = self._parse_field(parts[1], 0, 23)
        self.day = self._parse_field(parts[2], 1, 31)
        self.month = self._parse_field(parts[3], 1, 12)
        self.weekday = self._parse_field(parts[4], 0, 6)  # 0=Monday

    @staticmethod
    def _parse_field(field: str, min_val: int, max_val: int) -> set[int]:
        """Parse a single cron field into a set of valid integer values."""
        result: set[int] = set()
        for part in field.split(","):
            part = part.strip()
            if not part:
                continue
            # Handle step notation: */N or range/N
            step = 1
            if "/" in part:
                base, step_str = part.split("/", 1)
                step = int(step_str)
                if step < 1:
                    raise ValueError(f"Step must be >= 1, got {step}")
                part = base

            if part == "*":
                result.update(range(min_val, max_val + 1, step))
            elif "-" in part:
                low_str, high_str = part.split("-", 1)
                low, high = int(low_str), int(high_str)
                if low < min_val or high > max_val or low > high:
                    raise ValueError(f"Range {low}-{high} out of bounds [{min_val}-{max_val}]")
                result.update(range(low, high + 1, step))
            else:
                val = int(part)
                if val < min_val or val > max_val:
                    raise ValueError(f"Value {val} out of bounds [{min_val}-{max_val}]")
                result.add(val)

        return result

    def next_time(self, after: datetime) -> datetime:
        """Find the next datetime matching this cron expression after the given time."""
        # Start from the next minute
        dt = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # Search up to 4 years ahead (covers all cron patterns)
        max_iterations = 366 * 24 * 60 * 4
        for _ in range(max_iterations):
            if (dt.month in self.month
                    and dt.day in self.day
                    and dt.weekday() in self.weekday
                    and dt.hour in self.hour
                    and dt.minute in self.minute):
                return dt
            dt += timedelta(minutes=1)

        raise ValueError(f"Could not find next matching time within 4 years")


def calculate_next_run(
    schedule_type: str,
    schedule_config: str,
    from_time: Optional[datetime] = None,
) -> Optional[str]:
    """Calculate the next run time for a scheduled task.

    Returns ISO format string or None (for once-type tasks that have already run).
    """
    if from_time is None:
        from_time = datetime.now()

    config = _parse_json_config(schedule_config)

    if schedule_type == "interval":
        minutes = config.get("minutes", 0)
        hours = config.get("hours", 0)
        total_minutes = minutes + (hours * 60)
        if total_minutes <= 0:
            raise ValueError("Interval schedule must specify positive minutes or hours")
        next_time = from_time + timedelta(minutes=total_minutes)
        return next_time.isoformat()

    elif schedule_type == "cron":
        expression = config.get("expression", "")
        if not expression:
            raise ValueError("Cron schedule must specify an 'expression' field")
        cron = CronExpression(expression)
        next_time = cron.next_time(from_time)
        return next_time.isoformat()

    elif schedule_type == "once":
        run_at = config.get("run_at", "")
        if not run_at:
            raise ValueError("Once schedule must specify a 'run_at' field")
        target = datetime.fromisoformat(run_at)
        if target > from_time:
            return target.isoformat()
        return None  # Already past, won't run again

    else:
        raise ValueError(f"Unknown schedule_type: {schedule_type}")


def _parse_json_config(config_str: str) -> dict:
    """Safely parse a JSON config string."""
    if not config_str or not config_str.strip():
        return {}
    try:
        value = json.loads(config_str)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _validate_custom_command(command_str: str) -> str:
    """Validate and sanitize a custom handler command. Returns the command or raises ValueError."""
    if not command_str or not command_str.strip():
        raise ValueError("Custom handler command cannot be empty")

    # Parse the command to check for dangerous patterns
    parts = command_str.strip().split()
    base_cmd = Path(parts[0]).name.lower()

    if base_cmd in _DANGEROUS_COMMANDS:
        raise ValueError(f"Command '{base_cmd}' is not allowed in custom handlers")

    # Check for shell metacharacters that could enable injection
    dangerous_chars = set(";|&`$(){}!")
    if dangerous_chars & set(command_str):
        raise ValueError("Shell metacharacters are not allowed in custom handler commands")

    return command_str.strip()


# --- Handler Execution ---

def _run_alert_eval_handler() -> str:
    """Run the alert evaluator handler."""
    try:
        from scheduler.alert_evaluator import evaluate_alerts
        evaluate_alerts()
        return json.dumps({"status": "ok", "handler": "alert_eval"})
    except Exception as e:
        return json.dumps({"status": "error", "handler": "alert_eval", "error": str(e)})


def _run_custom_handler(handler_config: str) -> str:
    """Run a custom subprocess handler."""
    config = _parse_json_config(handler_config)
    command = config.get("command", "")

    try:
        validated_command = _validate_custom_command(command)
    except ValueError as e:
        return json.dumps({"status": "error", "handler": "custom", "error": str(e)})

    parts = validated_command.split()

    try:
        result = subprocess.run(
            parts,
            capture_output=True,
            text=True,
            timeout=_CUSTOM_HANDLER_TIMEOUT,
            shell=False,
        )
        return json.dumps({
            "status": "ok" if result.returncode == 0 else "error",
            "handler": "custom",
            "returncode": result.returncode,
            "stdout": result.stdout[:1000],
            "stderr": result.stderr[:500],
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"status": "error", "handler": "custom", "error": "timeout"})
    except FileNotFoundError:
        return json.dumps({"status": "error", "handler": "custom", "error": f"command not found: {parts[0]}"})
    except Exception as e:
        return json.dumps({"status": "error", "handler": "custom", "error": str(e)})


def execute_handler(handler_type: str, handler_config: str) -> str:
    """Execute a task handler and return a JSON result string."""
    if handler_type == "alert_eval":
        return _run_alert_eval_handler()
    elif handler_type == "custom":
        return _run_custom_handler(handler_config)
    else:
        return json.dumps({
            "status": "skipped",
            "handler": handler_type,
            "message": f"Handler type '{handler_type}' is not yet implemented",
        })


# --- Scheduler Engine ---

class SchedulerEngine:
    """Evaluates due scheduled tasks and executes their handlers."""

    def __init__(self, memory_store):
        self.memory_store = memory_store

    def evaluate_due_tasks(self, now: Optional[datetime] = None) -> list[dict]:
        """Find and execute all due tasks. Returns list of execution results."""
        if now is None:
            now = datetime.now()

        due_tasks = self.memory_store.get_due_tasks(now=now.isoformat())
        results = []

        for task in due_tasks:
            result = self._execute_task(task, now)
            results.append(result)

        return results

    def _execute_task(self, task, now: datetime) -> dict:
        """Execute a single scheduled task and update its state."""
        task_result = {
            "task_id": task.id,
            "name": task.name,
            "handler_type": task.handler_type,
        }

        try:
            handler_result = execute_handler(task.handler_type, task.handler_config)
            task_result["result"] = handler_result

            # Calculate next run
            next_run = calculate_next_run(task.schedule_type, task.schedule_config, from_time=now)

            # Update task state
            self.memory_store.update_scheduled_task(
                task.id,
                last_run_at=now.isoformat(),
                next_run_at=next_run,
                last_result=handler_result,
            )

            task_result["next_run_at"] = next_run
            task_result["status"] = "executed"

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            task_result["status"] = "error"
            task_result["error"] = error_msg
            logger.error(f"Error executing task {task.name}: {error_msg}")

            # Still update last_run_at so we don't retry immediately
            try:
                self.memory_store.update_scheduled_task(
                    task.id,
                    last_run_at=now.isoformat(),
                    last_result=json.dumps({"status": "error", "error": error_msg}),
                )
            except Exception:
                pass

        return task_result


# --- Standalone Entry Point ---

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import MEMORY_DB_PATH
    from memory.store import MemoryStore

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if not MEMORY_DB_PATH.exists():
        logger.error(f"Memory DB not found at {MEMORY_DB_PATH}")
        sys.exit(1)

    store = MemoryStore(MEMORY_DB_PATH)
    engine = SchedulerEngine(store)
    results = engine.evaluate_due_tasks()

    for r in results:
        logger.info(f"Task '{r['name']}': {r['status']}")

    store.close()
