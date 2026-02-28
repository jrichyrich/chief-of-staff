# memory/lifecycle_store.py
"""Domain store for decisions, delegations, and alert rules."""
import re
import sqlite3
from datetime import date, datetime
from typing import Optional

from memory.models import AlertRule, Decision, Delegation


class LifecycleStore:
    """Manages decisions, delegations, and alert rules."""

    _DECISION_COLUMNS = frozenset({
        "title", "description", "context", "alternatives_considered",
        "decided_by", "owner", "status", "follow_up_date", "tags", "source", "updated_at",
    })

    _DELEGATION_COLUMNS = frozenset({
        "task", "description", "delegated_to", "delegated_by",
        "due_date", "priority", "status", "source", "notes", "updated_at",
    })

    _ALERT_RULE_COLUMNS = frozenset({
        "name", "description", "alert_type", "condition", "enabled", "last_triggered_at",
    })

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Decisions ---

    def store_decision(self, decision: Decision) -> Decision:
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            """INSERT INTO decisions (title, description, context, alternatives_considered,
               decided_by, owner, status, follow_up_date, tags, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (decision.title, decision.description, decision.context,
             decision.alternatives_considered, decision.decided_by, decision.owner,
             decision.status, decision.follow_up_date, decision.tags, decision.source,
             now, now),
        )
        self.conn.commit()
        return self.get_decision(cursor.lastrowid)

    def get_decision(self, decision_id: int) -> Optional[Decision]:
        row = self.conn.execute(
            "SELECT * FROM decisions WHERE id=?", (decision_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_decision(row)

    def search_decisions(self, query: str) -> list[Decision]:
        rows = self.conn.execute(
            "SELECT * FROM decisions WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?",
            (f"%{query}%", f"%{query}%", f"%{query}%"),
        ).fetchall()
        return [self._row_to_decision(r) for r in rows]

    def list_decisions_by_status(self, status: str) -> list[Decision]:
        rows = self.conn.execute(
            "SELECT * FROM decisions WHERE status=?", (status,)
        ).fetchall()
        return [self._row_to_decision(r) for r in rows]

    def update_decision(self, decision_id: int, **kwargs) -> Optional[Decision]:
        kwargs["updated_at"] = datetime.now().isoformat()
        invalid = set(kwargs) - self._DECISION_COLUMNS
        if invalid:
            raise ValueError(f"Invalid decision fields: {invalid}")
        if not all(re.match(r'^[a-z_]+$', k) for k in kwargs):
            raise ValueError("Invalid column names: column names must contain only lowercase letters and underscores")
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [decision_id]
        self.conn.execute(
            f"UPDATE decisions SET {set_clause} WHERE id=?", values
        )
        self.conn.commit()
        return self.get_decision(decision_id)

    def delete_decision(self, decision_id: int) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM decisions WHERE id=?", (decision_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _row_to_decision(self, row: sqlite3.Row) -> Decision:
        return Decision(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            context=row["context"],
            alternatives_considered=row["alternatives_considered"],
            decided_by=row["decided_by"],
            owner=row["owner"],
            status=row["status"],
            follow_up_date=row["follow_up_date"],
            tags=row["tags"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Delegations ---

    def store_delegation(self, delegation: Delegation) -> Delegation:
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            """INSERT INTO delegations (task, description, delegated_to, delegated_by,
               due_date, priority, status, source, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (delegation.task, delegation.description, delegation.delegated_to,
             delegation.delegated_by, delegation.due_date, delegation.priority,
             delegation.status, delegation.source, delegation.notes, now, now),
        )
        self.conn.commit()
        return self.get_delegation(cursor.lastrowid)

    def get_delegation(self, delegation_id: int) -> Optional[Delegation]:
        row = self.conn.execute(
            "SELECT * FROM delegations WHERE id=?", (delegation_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_delegation(row)

    def list_delegations(self, status: Optional[str] = None, delegated_to: Optional[str] = None) -> list[Delegation]:
        query = "SELECT * FROM delegations WHERE 1=1"
        params = []
        if status is not None:
            query += " AND status=?"
            params.append(status)
        if delegated_to is not None:
            query += " AND delegated_to=?"
            params.append(delegated_to)
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_delegation(r) for r in rows]

    def list_overdue_delegations(self) -> list[Delegation]:
        today = date.today().isoformat()
        rows = self.conn.execute(
            "SELECT * FROM delegations WHERE status='active' AND due_date IS NOT NULL AND due_date < ?",
            (today,),
        ).fetchall()
        return [self._row_to_delegation(r) for r in rows]

    def update_delegation(self, delegation_id: int, **kwargs) -> Optional[Delegation]:
        kwargs["updated_at"] = datetime.now().isoformat()
        invalid = set(kwargs) - self._DELEGATION_COLUMNS
        if invalid:
            raise ValueError(f"Invalid delegation fields: {invalid}")
        if not all(re.match(r'^[a-z_]+$', k) for k in kwargs):
            raise ValueError("Invalid column names: column names must contain only lowercase letters and underscores")
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [delegation_id]
        self.conn.execute(
            f"UPDATE delegations SET {set_clause} WHERE id=?", values
        )
        self.conn.commit()
        return self.get_delegation(delegation_id)

    def delete_delegation(self, delegation_id: int) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM delegations WHERE id=?", (delegation_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _row_to_delegation(self, row: sqlite3.Row) -> Delegation:
        return Delegation(
            id=row["id"],
            task=row["task"],
            description=row["description"],
            delegated_to=row["delegated_to"],
            delegated_by=row["delegated_by"],
            due_date=row["due_date"],
            priority=row["priority"],
            status=row["status"],
            source=row["source"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Alert Rules ---

    def store_alert_rule(self, rule: AlertRule) -> AlertRule:
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            """INSERT INTO alert_rules (name, description, alert_type, condition, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   description=excluded.description,
                   alert_type=excluded.alert_type,
                   condition=excluded.condition,
                   enabled=excluded.enabled""",
            (rule.name, rule.description, rule.alert_type, rule.condition,
             1 if rule.enabled else 0, now),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM alert_rules WHERE name=?", (rule.name,)
        ).fetchone()
        return self._row_to_alert_rule(row)

    def get_alert_rule(self, rule_id: int) -> Optional[AlertRule]:
        row = self.conn.execute(
            "SELECT * FROM alert_rules WHERE id=?", (rule_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_alert_rule(row)

    def list_alert_rules(self, enabled_only: bool = False) -> list[AlertRule]:
        if enabled_only:
            rows = self.conn.execute(
                "SELECT * FROM alert_rules WHERE enabled=1"
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM alert_rules").fetchall()
        return [self._row_to_alert_rule(r) for r in rows]

    def update_alert_rule(self, rule_id: int, **kwargs) -> Optional[AlertRule]:
        invalid = set(kwargs) - self._ALERT_RULE_COLUMNS
        if invalid:
            raise ValueError(f"Invalid alert_rule fields: {invalid}")
        if not all(re.match(r'^[a-z_]+$', k) for k in kwargs):
            raise ValueError("Invalid column names: column names must contain only lowercase letters and underscores")
        if "enabled" in kwargs:
            kwargs["enabled"] = 1 if kwargs["enabled"] else 0
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [rule_id]
        self.conn.execute(
            f"UPDATE alert_rules SET {set_clause} WHERE id=?", values
        )
        self.conn.commit()
        return self.get_alert_rule(rule_id)

    def delete_alert_rule(self, rule_id: int) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM alert_rules WHERE id=?", (rule_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _row_to_alert_rule(self, row: sqlite3.Row) -> AlertRule:
        return AlertRule(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            alert_type=row["alert_type"],
            condition=row["condition"],
            enabled=bool(row["enabled"]),
            last_triggered_at=row["last_triggered_at"],
            created_at=row["created_at"],
        )
