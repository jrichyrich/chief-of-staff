# memory/skill_store.py
"""Domain store for skill usage, tool usage log, and skill suggestions."""
import sqlite3
from datetime import datetime
from typing import Optional

from memory.models import SkillSuggestion, SkillSuggestionStatus, SkillUsage


class SkillStore:
    """Manages skill usage tracking, tool invocation logs, and skill suggestions."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

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

    # --- Tool Usage Log ---

    def log_tool_invocation(
        self,
        tool_name: str,
        query_pattern: str = "auto",
        success: bool = True,
        duration_ms: int | None = None,
        session_id: str | None = None,
    ) -> None:
        """Log a single tool invocation to the temporal log table."""
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO tool_usage_log
               (tool_name, query_pattern, success, duration_ms, session_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tool_name, query_pattern, int(success), duration_ms, session_id, now),
        )
        self.conn.commit()

    def get_tool_usage_log(
        self,
        tool_name: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve invocation log entries, optionally filtered by tool name."""
        if tool_name:
            rows = self.conn.execute(
                "SELECT * FROM tool_usage_log WHERE tool_name=? ORDER BY created_at DESC LIMIT ?",
                (tool_name, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tool_usage_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "tool_name": row["tool_name"],
                "query_pattern": row["query_pattern"],
                "success": bool(row["success"]),
                "duration_ms": row["duration_ms"],
                "session_id": row["session_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_tool_stats_summary(self) -> list[dict]:
        """Aggregate tool usage stats from the invocation log."""
        rows = self.conn.execute(
            """SELECT
                   tool_name,
                   COUNT(*) as total_calls,
                   SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
                   SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count,
                   AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END) as avg_duration_ms,
                   MIN(created_at) as first_used,
                   MAX(created_at) as last_used
               FROM tool_usage_log
               GROUP BY tool_name
               ORDER BY total_calls DESC"""
        ).fetchall()
        return [
            {
                "tool_name": row["tool_name"],
                "total_calls": row["total_calls"],
                "success_count": row["success_count"],
                "failure_count": row["failure_count"],
                "avg_duration_ms": round(row["avg_duration_ms"], 2) if row["avg_duration_ms"] else None,
                "first_used": row["first_used"],
                "last_used": row["last_used"],
            }
            for row in rows
        ]

    def get_top_patterns_by_tool(self, limit_per_tool: int = 10) -> dict[str, list[dict]]:
        """Get top query patterns grouped by tool name from the invocation log."""
        rows = self.conn.execute(
            """SELECT tool_name, query_pattern, COUNT(*) as count
               FROM tool_usage_log
               WHERE query_pattern != 'auto'
               GROUP BY tool_name, query_pattern
               ORDER BY tool_name, count DESC"""
        ).fetchall()

        result: dict[str, list[dict]] = {}
        for row in rows:
            tool = row["tool_name"]
            if tool not in result:
                result[tool] = []
            if len(result[tool]) < limit_per_tool:
                result[tool].append({"pattern": row["query_pattern"], "count": row["count"]})
        return result

    # --- Skill Suggestions ---

    def store_skill_suggestion(self, suggestion: SkillSuggestion) -> SkillSuggestion:
        cursor = self.conn.execute(
            """INSERT INTO skill_suggestions (description, suggested_name, suggested_capabilities,
               confidence, status)
               VALUES (?, ?, ?, ?, ?)""",
            (suggestion.description, suggestion.suggested_name,
             suggestion.suggested_capabilities, suggestion.confidence,
             suggestion.status or SkillSuggestionStatus.pending),
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

    def list_skill_suggestions(self, status: str = SkillSuggestionStatus.pending) -> list[SkillSuggestion]:
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
