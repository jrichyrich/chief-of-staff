# memory/webhook_store.py
"""Domain store for webhook events and event rules."""
import fnmatch
import re
import sqlite3
from datetime import datetime
from typing import Optional

from memory.models import WebhookEvent, WebhookStatus


class WebhookStore:
    """Manages webhook events and event rules."""

    _EVENT_RULE_COLUMNS = frozenset({
        "name", "description", "event_source", "event_type_pattern",
        "agent_name", "agent_input_template", "delivery_channel",
        "delivery_config", "enabled", "priority", "updated_at",
    })

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Webhook Events ---

    def store_webhook_event(self, event: WebhookEvent) -> WebhookEvent:
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            """INSERT INTO webhook_events (source, event_type, payload, status, received_at)
               VALUES (?, ?, ?, ?, ?)""",
            (event.source, event.event_type, event.payload, event.status or WebhookStatus.pending, now),
        )
        self.conn.commit()
        return self.get_webhook_event(cursor.lastrowid)

    def get_webhook_event(self, event_id: int) -> Optional[WebhookEvent]:
        row = self.conn.execute(
            "SELECT * FROM webhook_events WHERE id=?", (event_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_webhook_event(row)

    def list_webhook_events(
        self, status: Optional[str] = None, source: Optional[str] = None, limit: int = 50
    ) -> list[WebhookEvent]:
        query = "SELECT * FROM webhook_events WHERE 1=1"
        params: list = []
        if status is not None:
            query += " AND status=?"
            params.append(status)
        if source is not None:
            query += " AND source=?"
            params.append(source)
        query += " ORDER BY received_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_webhook_event(r) for r in rows]

    def update_webhook_event_status(self, event_id: int, status: str) -> Optional[WebhookEvent]:
        now = datetime.now().isoformat() if status in (WebhookStatus.processed, WebhookStatus.failed) else None
        self.conn.execute(
            "UPDATE webhook_events SET status=?, processed_at=? WHERE id=?",
            (status, now, event_id),
        )
        self.conn.commit()
        return self.get_webhook_event(event_id)

    def _row_to_webhook_event(self, row: sqlite3.Row) -> WebhookEvent:
        return WebhookEvent(
            id=row["id"],
            source=row["source"],
            event_type=row["event_type"],
            payload=row["payload"],
            status=row["status"],
            received_at=row["received_at"],
            processed_at=row["processed_at"],
        )

    # --- Event Rules ---

    def create_event_rule(
        self,
        name: str,
        event_source: str,
        event_type_pattern: str,
        agent_name: str,
        description: str = "",
        agent_input_template: str = "",
        delivery_channel: str | None = None,
        delivery_config: str | None = None,
        enabled: bool = True,
        priority: int = 100,
    ) -> dict:
        import json as _json
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO event_rules (name, description, event_source, event_type_pattern,
               agent_name, agent_input_template, delivery_channel, delivery_config,
               enabled, priority, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, description, event_source, event_type_pattern, agent_name,
             agent_input_template, delivery_channel, delivery_config,
             1 if enabled else 0, priority, now, now),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM event_rules WHERE name=?", (name,)
        ).fetchone()
        return self._row_to_event_rule_dict(row)

    def get_event_rule(self, rule_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM event_rules WHERE id=?", (rule_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_event_rule_dict(row)

    def list_event_rules(self, enabled_only: bool = True) -> list[dict]:
        if enabled_only:
            rows = self.conn.execute(
                "SELECT * FROM event_rules WHERE enabled=1 ORDER BY priority ASC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM event_rules ORDER BY priority ASC"
            ).fetchall()
        return [self._row_to_event_rule_dict(r) for r in rows]

    def update_event_rule(self, rule_id: int, **kwargs) -> dict | None:
        kwargs["updated_at"] = datetime.now().isoformat()
        invalid = set(kwargs) - self._EVENT_RULE_COLUMNS
        if invalid:
            raise ValueError(f"Invalid event_rule fields: {invalid}")
        if not all(re.match(r'^[a-z_]+$', k) for k in kwargs):
            raise ValueError("Invalid column names: column names must contain only lowercase letters and underscores")
        if "enabled" in kwargs:
            kwargs["enabled"] = 1 if kwargs["enabled"] else 0
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [rule_id]
        self.conn.execute(
            f"UPDATE event_rules SET {set_clause} WHERE id=?", values
        )
        self.conn.commit()
        return self.get_event_rule(rule_id)

    def delete_event_rule(self, rule_id: int) -> dict:
        cursor = self.conn.execute(
            "DELETE FROM event_rules WHERE id=?", (rule_id,)
        )
        self.conn.commit()
        if cursor.rowcount > 0:
            return {"status": "deleted", "id": rule_id}
        return {"status": "not_found", "id": rule_id}

    def match_event_rules(self, source: str, event_type: str) -> list[dict]:
        """Find all enabled event rules that match the given source and event_type."""
        rules = self.list_event_rules(enabled_only=True)
        matched = []
        for rule in rules:
            if rule["event_source"] != source:
                continue
            if fnmatch.fnmatch(event_type, rule["event_type_pattern"]):
                matched.append(rule)
        return matched

    def _row_to_event_rule_dict(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "event_source": row["event_source"],
            "event_type_pattern": row["event_type_pattern"],
            "agent_name": row["agent_name"],
            "agent_input_template": row["agent_input_template"],
            "delivery_channel": row["delivery_channel"],
            "delivery_config": row["delivery_config"],
            "enabled": bool(row["enabled"]),
            "priority": row["priority"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
