# memory/scheduler_store.py
"""Domain store for scheduled tasks."""
import json as _json
import re
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from memory.models import ScheduledTask


class SchedulerStore:
    """Manages scheduled tasks."""

    _SCHEDULED_TASK_COLUMNS = frozenset({
        "name", "description", "schedule_type", "schedule_config",
        "handler_type", "handler_config", "enabled",
        "last_run_at", "next_run_at", "last_result",
        "delivery_channel", "delivery_config", "updated_at",
    })

    def __init__(self, conn: sqlite3.Connection, *, lock=None):
        self.conn = conn
        self._lock = lock or threading.RLock()

    def store_scheduled_task(self, task: ScheduledTask) -> ScheduledTask:
        now = datetime.now().isoformat()
        delivery_config_str = _json.dumps(task.delivery_config) if task.delivery_config else None
        with self._lock:
            self.conn.execute(
                """INSERT INTO scheduled_tasks (name, description, schedule_type, schedule_config,
                   handler_type, handler_config, enabled, next_run_at,
                   delivery_channel, delivery_config, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       description=excluded.description,
                       schedule_type=excluded.schedule_type,
                       schedule_config=excluded.schedule_config,
                       handler_type=excluded.handler_type,
                       handler_config=excluded.handler_config,
                       enabled=excluded.enabled,
                       next_run_at=excluded.next_run_at,
                       delivery_channel=excluded.delivery_channel,
                       delivery_config=excluded.delivery_config,
                       updated_at=excluded.updated_at""",
                (task.name, task.description, task.schedule_type, task.schedule_config,
                 task.handler_type, task.handler_config, 1 if task.enabled else 0,
                 task.next_run_at, task.delivery_channel, delivery_config_str, now, now),
            )
            self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM scheduled_tasks WHERE name=?", (task.name,)
        ).fetchone()
        return self._row_to_scheduled_task(row)

    def get_scheduled_task(self, task_id: int) -> Optional[ScheduledTask]:
        row = self.conn.execute(
            "SELECT * FROM scheduled_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_scheduled_task(row)

    def get_scheduled_task_by_name(self, name: str) -> Optional[ScheduledTask]:
        row = self.conn.execute(
            "SELECT * FROM scheduled_tasks WHERE name=?", (name,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_scheduled_task(row)

    def list_scheduled_tasks(self, enabled_only: bool = False) -> list[ScheduledTask]:
        if enabled_only:
            rows = self.conn.execute(
                "SELECT * FROM scheduled_tasks WHERE enabled=1"
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM scheduled_tasks").fetchall()
        return [self._row_to_scheduled_task(r) for r in rows]

    def get_due_tasks(self, now: Optional[str] = None) -> list[ScheduledTask]:
        if now is None:
            now = datetime.now().isoformat()
        rows = self.conn.execute(
            "SELECT * FROM scheduled_tasks WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at <= ?",
            (now,),
        ).fetchall()
        return [self._row_to_scheduled_task(r) for r in rows]

    def update_scheduled_task(self, task_id: int, **kwargs) -> Optional[ScheduledTask]:
        kwargs["updated_at"] = datetime.now().isoformat()
        invalid = set(kwargs) - self._SCHEDULED_TASK_COLUMNS
        if invalid:
            raise ValueError(f"Invalid scheduled_task fields: {invalid}")
        if not all(re.match(r'^[a-z_]+$', k) for k in kwargs):
            raise ValueError("Invalid column names: column names must contain only lowercase letters and underscores")
        if "enabled" in kwargs:
            kwargs["enabled"] = 1 if kwargs["enabled"] else 0
        if "delivery_config" in kwargs and isinstance(kwargs["delivery_config"], dict):
            kwargs["delivery_config"] = _json.dumps(kwargs["delivery_config"])
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        with self._lock:
            self.conn.execute(
                f"UPDATE scheduled_tasks SET {set_clause} WHERE id=?", values
            )
            self.conn.commit()
        return self.get_scheduled_task(task_id)

    def delete_scheduled_task(self, task_id: int) -> bool:
        with self._lock:
            cursor = self.conn.execute(
                "DELETE FROM scheduled_tasks WHERE id=?", (task_id,)
            )
            self.conn.commit()
        return cursor.rowcount > 0

    def _row_to_scheduled_task(self, row: sqlite3.Row) -> ScheduledTask:
        delivery_config_raw = row["delivery_config"]
        delivery_config = None
        if delivery_config_raw:
            try:
                delivery_config = _json.loads(delivery_config_raw)
            except (ValueError, TypeError):
                pass
        return ScheduledTask(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            schedule_type=row["schedule_type"],
            schedule_config=row["schedule_config"],
            handler_type=row["handler_type"],
            handler_config=row["handler_config"],
            enabled=bool(row["enabled"]),
            last_run_at=row["last_run_at"],
            next_run_at=row["next_run_at"],
            last_result=row["last_result"],
            delivery_channel=row["delivery_channel"],
            delivery_config=delivery_config,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
