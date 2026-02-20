# memory/store.py
import math
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from memory.models import (
    AlertRule, ContextEntry, Decision, Delegation, Fact, Location,
    ScheduledTask, SkillSuggestion, SkillUsage, WebhookEvent,
)


class MemoryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, key)
            );

            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                address TEXT,
                latitude REAL,
                longitude REAL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS context (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                context TEXT DEFAULT '',
                alternatives_considered TEXT DEFAULT '',
                decided_by TEXT DEFAULT '',
                owner TEXT DEFAULT '',
                status TEXT DEFAULT 'pending_execution',
                follow_up_date TEXT,
                tags TEXT DEFAULT '',
                source TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS delegations (
                id INTEGER PRIMARY KEY,
                task TEXT NOT NULL,
                description TEXT DEFAULT '',
                delegated_to TEXT NOT NULL,
                delegated_by TEXT DEFAULT '',
                due_date TEXT,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'active',
                source TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                alert_type TEXT NOT NULL,
                condition TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                last_triggered_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                schedule_type TEXT NOT NULL,
                schedule_config TEXT DEFAULT '',
                handler_type TEXT DEFAULT '',
                handler_config TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                last_run_at TIMESTAMP,
                next_run_at TIMESTAMP,
                last_result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS skill_usage (
                id INTEGER PRIMARY KEY,
                tool_name TEXT NOT NULL,
                query_pattern TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tool_name, query_pattern)
            );

            CREATE TABLE IF NOT EXISTS skill_suggestions (
                id INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                suggested_name TEXT DEFAULT '',
                suggested_capabilities TEXT DEFAULT '',
                confidence REAL DEFAULT 0.0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                key, value, category,
                content='facts', content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
                INSERT INTO facts_fts(rowid, key, value, category) VALUES (new.id, new.key, new.value, new.category);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
                INSERT INTO facts_fts(facts_fts, rowid, key, value, category) VALUES('delete', old.id, old.key, old.value, old.category);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
                INSERT INTO facts_fts(facts_fts, rowid, key, value, category) VALUES('delete', old.id, old.key, old.value, old.category);
                INSERT INTO facts_fts(rowid, key, value, category) VALUES (new.id, new.key, new.value, new.category);
            END;
        """)
        self.conn.commit()
        # Rebuild FTS index to pick up any pre-existing data
        self.conn.execute("INSERT INTO facts_fts(facts_fts) VALUES('rebuild')")
        self.conn.commit()

    # --- Facts ---

    def store_fact(self, fact: Fact) -> Fact:
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO facts (category, key, value, confidence, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(category, key) DO UPDATE SET
                   value=excluded.value,
                   confidence=excluded.confidence,
                   source=excluded.source,
                   updated_at=excluded.updated_at""",
            (fact.category, fact.key, fact.value, fact.confidence, fact.source, now, now),
        )
        self.conn.commit()
        return self.get_fact(fact.category, fact.key)

    def get_fact(self, category: str, key: str) -> Optional[Fact]:
        row = self.conn.execute(
            "SELECT * FROM facts WHERE category=? AND key=?", (category, key)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_fact(row)

    def get_facts_by_category(self, category: str) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE category=?", (category,)
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def search_facts(self, query: str) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE value LIKE ? OR key LIKE ?",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def rank_facts(self, facts: list[Fact], half_life_days: float = 90.0) -> list[tuple[Fact, float]]:
        """Apply temporal decay scoring to a list of facts.

        Score = confidence * exp(-ln(2) * age_days / half_life_days)
        Returns list of (Fact, score) tuples sorted by score descending.
        """
        half_life_days = max(half_life_days, 0.001)
        now = datetime.now()
        ln2 = math.log(2)
        scored: list[tuple[Fact, float]] = []
        for fact in facts:
            timestamp = fact.updated_at or fact.created_at
            if timestamp:
                dt = datetime.fromisoformat(str(timestamp))
                age_days = (now - dt).total_seconds() / 86400.0
            else:
                age_days = 0.0
            score = fact.confidence * math.exp(-ln2 * age_days / half_life_days)
            scored.append((fact, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def search_facts_ranked(self, query: str, half_life_days: float = 90.0) -> list[tuple[Fact, float]]:
        """Search facts with temporal decay scoring.

        Score = confidence * exp(-ln(2) * age_days / half_life_days)
        Returns list of (Fact, score) tuples sorted by score descending.
        """
        return self.rank_facts(self.search_facts(query), half_life_days)

    # FTS5 special characters/operators to strip from user queries
    _FTS5_SPECIAL = re.compile(r'[*"^\-():,]|\b(?:OR|AND|NOT|NEAR)\b')

    def search_facts_fts(self, query: str) -> list[Fact]:
        """Full-text search over facts using FTS5.

        Falls back to LIKE-based search_facts() if the FTS query fails.
        """
        if not query or not query.strip():
            return []
        try:
            sanitized = self._FTS5_SPECIAL.sub(" ", query)
            tokens = sanitized.split()
            if not tokens:
                return []
            fts_query = " ".join(f'"{t}"' for t in tokens)
            rows = self.conn.execute(
                "SELECT f.* FROM facts f JOIN facts_fts fts ON f.id = fts.rowid "
                "WHERE facts_fts MATCH ? ORDER BY rank",
                (fts_query,),
            ).fetchall()
            return [self._row_to_fact(r) for r in rows]
        except Exception:
            return self.search_facts(query)

    def search_facts_hybrid(self, query: str) -> list[tuple[Fact, float]]:
        """Hybrid search combining FTS5 BM25 ranking with LIKE fallback.

        Returns (Fact, score) tuples sorted by score descending.
        """
        if not query or not query.strip():
            return []

        merged: dict[int, tuple[Fact, float]] = {}

        # FTS5 results with BM25 rank (rank is negative; negate for a positive score)
        try:
            sanitized = self._FTS5_SPECIAL.sub(" ", query)
            tokens = sanitized.split()
            if tokens:
                fts_query = " ".join(f'"{t}"' for t in tokens)
                rows = self.conn.execute(
                    "SELECT f.*, fts.rank FROM facts f "
                    "JOIN facts_fts fts ON f.id = fts.rowid "
                    "WHERE facts_fts MATCH ? ORDER BY rank",
                    (fts_query,),
                ).fetchall()
                for row in rows:
                    fact = self._row_to_fact(row)
                    score = -float(row["rank"])  # BM25 rank is negative
                    merged[fact.id] = (fact, score)
        except Exception:
            pass

        # LIKE results with a fixed score
        like_results = self.search_facts(query)
        for fact in like_results:
            if fact.id not in merged:
                merged[fact.id] = (fact, 0.5)

        results = list(merged.values())
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def delete_fact(self, category: str, key: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM facts WHERE category=? AND key=?", (category, key)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _row_to_fact(self, row: sqlite3.Row) -> Fact:
        return Fact(
            id=row["id"],
            category=row["category"],
            key=row["key"],
            value=row["value"],
            confidence=row["confidence"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Locations ---

    def store_location(self, location: Location) -> Location:
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO locations (name, address, latitude, longitude, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   address=excluded.address,
                   latitude=excluded.latitude,
                   longitude=excluded.longitude,
                   notes=excluded.notes""",
            (location.name, location.address, location.latitude, location.longitude, location.notes, now),
        )
        self.conn.commit()
        return self.get_location(location.name)

    def get_location(self, name: str) -> Optional[Location]:
        row = self.conn.execute(
            "SELECT * FROM locations WHERE name=?", (name,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_location(row)

    def list_locations(self) -> list[Location]:
        rows = self.conn.execute("SELECT * FROM locations").fetchall()
        return [self._row_to_location(r) for r in rows]

    def _row_to_location(self, row: sqlite3.Row) -> Location:
        return Location(
            id=row["id"],
            name=row["name"],
            address=row["address"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            notes=row["notes"],
            created_at=row["created_at"],
        )

    # --- Context ---

    def store_context(self, entry: ContextEntry) -> ContextEntry:
        cursor = self.conn.execute(
            """INSERT INTO context (session_id, topic, summary, agent)
               VALUES (?, ?, ?, ?)""",
            (entry.session_id, entry.topic, entry.summary, entry.agent),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM context WHERE id=?", (cursor.lastrowid,)).fetchone()
        return self._row_to_context(row)

    def list_context(self, session_id: Optional[str] = None, limit: int = 20) -> list[ContextEntry]:
        query = "SELECT * FROM context"
        params: list = []
        if session_id:
            query += " WHERE session_id=?"
            params.append(session_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_context(r) for r in rows]

    def search_context(self, query: str, limit: int = 20) -> list[ContextEntry]:
        rows = self.conn.execute(
            """SELECT * FROM context
               WHERE topic LIKE ? OR summary LIKE ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        return [self._row_to_context(r) for r in rows]

    def _row_to_context(self, row: sqlite3.Row) -> ContextEntry:
        return ContextEntry(
            id=row["id"],
            session_id=row["session_id"],
            topic=row["topic"],
            summary=row["summary"],
            agent=row["agent"],
            created_at=row["created_at"],
        )

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

    _DECISION_COLUMNS = frozenset({
        "title", "description", "context", "alternatives_considered",
        "decided_by", "owner", "status", "follow_up_date", "tags", "source", "updated_at",
    })

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

    _DELEGATION_COLUMNS = frozenset({
        "task", "description", "delegated_to", "delegated_by",
        "due_date", "priority", "status", "source", "notes", "updated_at",
    })

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
        # For upsert, fetch by name since lastrowid may be 0 on conflict
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

    _ALERT_RULE_COLUMNS = frozenset({
        "name", "description", "alert_type", "condition", "enabled", "last_triggered_at",
    })

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

    # --- Webhook Events ---

    def store_webhook_event(self, event: WebhookEvent) -> WebhookEvent:
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            """INSERT INTO webhook_events (source, event_type, payload, status, received_at)
               VALUES (?, ?, ?, ?, ?)""",
            (event.source, event.event_type, event.payload, event.status or "pending", now),
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
        now = datetime.now().isoformat() if status in ("processed", "failed") else None
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

    # --- Scheduled Tasks ---

    def store_scheduled_task(self, task: ScheduledTask) -> ScheduledTask:
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            """INSERT INTO scheduled_tasks (name, description, schedule_type, schedule_config,
               handler_type, handler_config, enabled, next_run_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   description=excluded.description,
                   schedule_type=excluded.schedule_type,
                   schedule_config=excluded.schedule_config,
                   handler_type=excluded.handler_type,
                   handler_config=excluded.handler_config,
                   enabled=excluded.enabled,
                   next_run_at=excluded.next_run_at,
                   updated_at=excluded.updated_at""",
            (task.name, task.description, task.schedule_type, task.schedule_config,
             task.handler_type, task.handler_config, 1 if task.enabled else 0,
             task.next_run_at, now, now),
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

    _SCHEDULED_TASK_COLUMNS = frozenset({
        "name", "description", "schedule_type", "schedule_config",
        "handler_type", "handler_config", "enabled",
        "last_run_at", "next_run_at", "last_result", "updated_at",
    })

    def update_scheduled_task(self, task_id: int, **kwargs) -> Optional[ScheduledTask]:
        kwargs["updated_at"] = datetime.now().isoformat()
        invalid = set(kwargs) - self._SCHEDULED_TASK_COLUMNS
        if invalid:
            raise ValueError(f"Invalid scheduled_task fields: {invalid}")
        if not all(re.match(r'^[a-z_]+$', k) for k in kwargs):
            raise ValueError("Invalid column names: column names must contain only lowercase letters and underscores")
        if "enabled" in kwargs:
            kwargs["enabled"] = 1 if kwargs["enabled"] else 0
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        self.conn.execute(
            f"UPDATE scheduled_tasks SET {set_clause} WHERE id=?", values
        )
        self.conn.commit()
        return self.get_scheduled_task(task_id)

    def delete_scheduled_task(self, task_id: int) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM scheduled_tasks WHERE id=?", (task_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _row_to_scheduled_task(self, row: sqlite3.Row) -> ScheduledTask:
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
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Skill Usage ---

    def record_skill_usage(self, tool_name: str, query_pattern: str) -> SkillUsage:
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO skill_usage (tool_name, query_pattern, count, last_used, created_at)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(tool_name, query_pattern) DO UPDATE SET
                   count = count + 1,
                   last_used = excluded.last_used""",
            (tool_name, query_pattern, now, now),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM skill_usage WHERE tool_name=? AND query_pattern=?",
            (tool_name, query_pattern),
        ).fetchone()
        return self._row_to_skill_usage(row)

    def get_skill_usage_patterns(self, min_count: int = 1) -> list[dict]:
        rows = self.conn.execute(
            "SELECT tool_name, query_pattern, count, last_used FROM skill_usage "
            "WHERE count >= ? ORDER BY count DESC",
            (min_count,),
        ).fetchall()
        return [
            {
                "tool_name": row["tool_name"],
                "query_pattern": row["query_pattern"],
                "count": row["count"],
                "last_used": row["last_used"],
            }
            for row in rows
        ]

    def _row_to_skill_usage(self, row: sqlite3.Row) -> SkillUsage:
        return SkillUsage(
            id=row["id"],
            tool_name=row["tool_name"],
            query_pattern=row["query_pattern"],
            count=row["count"],
            last_used=row["last_used"],
            created_at=row["created_at"],
        )

    # --- Skill Suggestions ---

    def store_skill_suggestion(self, suggestion: SkillSuggestion) -> SkillSuggestion:
        cursor = self.conn.execute(
            """INSERT INTO skill_suggestions (description, suggested_name, suggested_capabilities,
               confidence, status)
               VALUES (?, ?, ?, ?, ?)""",
            (suggestion.description, suggestion.suggested_name,
             suggestion.suggested_capabilities, suggestion.confidence,
             suggestion.status or "pending"),
        )
        self.conn.commit()
        return self.get_skill_suggestion(cursor.lastrowid)

    def get_skill_suggestion(self, suggestion_id: int) -> Optional[SkillSuggestion]:
        row = self.conn.execute(
            "SELECT * FROM skill_suggestions WHERE id=?", (suggestion_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_skill_suggestion(row)

    def list_skill_suggestions(self, status: str = "pending") -> list[SkillSuggestion]:
        rows = self.conn.execute(
            "SELECT * FROM skill_suggestions WHERE status=? ORDER BY confidence DESC",
            (status,),
        ).fetchall()
        return [self._row_to_skill_suggestion(r) for r in rows]

    def update_skill_suggestion_status(self, suggestion_id: int, status: str) -> Optional[SkillSuggestion]:
        self.conn.execute(
            "UPDATE skill_suggestions SET status=? WHERE id=?",
            (status, suggestion_id),
        )
        self.conn.commit()
        return self.get_skill_suggestion(suggestion_id)

    def _row_to_skill_suggestion(self, row: sqlite3.Row) -> SkillSuggestion:
        return SkillSuggestion(
            id=row["id"],
            description=row["description"],
            suggested_name=row["suggested_name"],
            suggested_capabilities=row["suggested_capabilities"],
            confidence=row["confidence"],
            status=row["status"],
            created_at=row["created_at"],
        )

    def close(self):
        self.conn.close()
