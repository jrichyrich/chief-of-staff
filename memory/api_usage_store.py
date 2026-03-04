# memory/api_usage_store.py
"""Domain store for API usage tracking."""
import sqlite3
import threading
from datetime import datetime
from typing import Optional


class ApiUsageStore:
    """Manages API usage logging and aggregation for Anthropic API calls."""

    def __init__(self, conn: sqlite3.Connection, *, lock=None):
        self.conn = conn
        self._lock = lock or threading.RLock()

    def log_api_call(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        duration_ms: int | None = None,
        agent_name: str | None = None,
        caller: str = "unknown",
        session_id: str | None = None,
    ) -> None:
        """Insert a single API call record."""
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                """INSERT INTO agent_api_log
                   (model_id, input_tokens, output_tokens,
                    cache_creation_input_tokens, cache_read_input_tokens,
                    duration_ms, agent_name, caller, session_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    model_id,
                    input_tokens,
                    output_tokens,
                    cache_creation_input_tokens,
                    cache_read_input_tokens,
                    duration_ms,
                    agent_name,
                    caller,
                    session_id,
                    now,
                ),
            )
            self.conn.commit()

    def get_api_usage_summary(
        self,
        since: str | None = None,
        agent_name: str | None = None,
        model: str | None = None,
    ) -> list[dict]:
        """Aggregated totals grouped by model_id and agent_name.

        Returns list of dicts with model_id, agent_name, call_count,
        total_input_tokens, total_output_tokens, total_cache_creation,
        total_cache_read, avg_duration_ms.
        """
        query = """SELECT
                       model_id,
                       agent_name,
                       COUNT(*) as call_count,
                       SUM(input_tokens) as total_input_tokens,
                       SUM(output_tokens) as total_output_tokens,
                       SUM(cache_creation_input_tokens) as total_cache_creation,
                       SUM(cache_read_input_tokens) as total_cache_read,
                       AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END) as avg_duration_ms
                   FROM agent_api_log"""
        conditions = []
        params: list = []
        if since:
            conditions.append("created_at >= ?")
            params.append(since)
        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)
        if model:
            conditions.append("model_id = ?")
            params.append(model)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " GROUP BY model_id, agent_name ORDER BY call_count DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [
            {
                "model_id": row["model_id"],
                "agent_name": row["agent_name"],
                "call_count": row["call_count"],
                "total_input_tokens": row["total_input_tokens"],
                "total_output_tokens": row["total_output_tokens"],
                "total_cache_creation": row["total_cache_creation"],
                "total_cache_read": row["total_cache_read"],
                "avg_duration_ms": (
                    round(row["avg_duration_ms"], 2)
                    if row["avg_duration_ms"]
                    else None
                ),
            }
            for row in rows
        ]

    def get_api_usage_log(
        self,
        since: str | None = None,
        agent_name: str | None = None,
        model: str | None = None,
        caller: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Raw log entries with optional filters. Returns list of dicts."""
        query = "SELECT * FROM agent_api_log"
        conditions = []
        params: list = []
        if since:
            conditions.append("created_at >= ?")
            params.append(since)
        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)
        if model:
            conditions.append("model_id = ?")
            params.append(model)
        if caller:
            conditions.append("caller = ?")
            params.append(caller)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [
            {
                "id": row["id"],
                "model_id": row["model_id"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_creation_input_tokens": row["cache_creation_input_tokens"],
                "cache_read_input_tokens": row["cache_read_input_tokens"],
                "duration_ms": row["duration_ms"],
                "agent_name": row["agent_name"],
                "caller": row["caller"],
                "session_id": row["session_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
