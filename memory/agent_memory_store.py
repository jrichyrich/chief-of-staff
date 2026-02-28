# memory/agent_memory_store.py
"""Domain store for agent memory and shared memory."""
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from memory.models import AgentMemory


class AgentMemoryStore:
    """Manages per-agent memory and namespace-based shared memory."""

    def __init__(self, conn: sqlite3.Connection, *, lock=None):
        self.conn = conn
        self._lock = lock or threading.RLock()

    # --- Agent Memory ---

    def store_agent_memory(self, memory: AgentMemory) -> AgentMemory:
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                """INSERT INTO agent_memory (agent_name, memory_type, key, value, confidence, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_name, memory_type, key) DO UPDATE SET
                       value=excluded.value,
                       confidence=excluded.confidence,
                       updated_at=excluded.updated_at""",
                (memory.agent_name, memory.memory_type, memory.key, memory.value,
                 memory.confidence, now, now),
            )
            self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM agent_memory WHERE agent_name=? AND memory_type=? AND key=?",
            (memory.agent_name, memory.memory_type, memory.key),
        ).fetchone()
        return self._row_to_agent_memory(row)

    def get_agent_memories(self, agent_name: str, memory_type: str = "") -> list[AgentMemory]:
        if memory_type:
            rows = self.conn.execute(
                "SELECT * FROM agent_memory WHERE agent_name=? AND memory_type=? ORDER BY updated_at DESC",
                (agent_name, memory_type),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM agent_memory WHERE agent_name=? ORDER BY updated_at DESC",
                (agent_name,),
            ).fetchall()
        return [self._row_to_agent_memory(r) for r in rows]

    def search_agent_memories(self, agent_name: str, query: str) -> list[AgentMemory]:
        rows = self.conn.execute(
            "SELECT * FROM agent_memory WHERE agent_name=? AND (key LIKE ? OR value LIKE ?) ORDER BY updated_at DESC",
            (agent_name, f"%{query}%", f"%{query}%"),
        ).fetchall()
        return [self._row_to_agent_memory(r) for r in rows]

    def delete_agent_memory(self, agent_name: str, key: str, memory_type: str = "") -> bool:
        with self._lock:
            if memory_type:
                cursor = self.conn.execute(
                    "DELETE FROM agent_memory WHERE agent_name=? AND key=? AND memory_type=?",
                    (agent_name, key, memory_type),
                )
            else:
                cursor = self.conn.execute(
                    "DELETE FROM agent_memory WHERE agent_name=? AND key=?",
                    (agent_name, key),
                )
            self.conn.commit()
        return cursor.rowcount > 0

    def clear_agent_memories(self, agent_name: str) -> int:
        with self._lock:
            cursor = self.conn.execute(
                "DELETE FROM agent_memory WHERE agent_name=?", (agent_name,)
            )
            self.conn.commit()
        return cursor.rowcount

    def _row_to_agent_memory(self, row: sqlite3.Row) -> AgentMemory:
        namespace = None
        try:
            namespace = row["namespace"]
        except (IndexError, KeyError):
            pass
        return AgentMemory(
            id=row["id"],
            agent_name=row["agent_name"],
            memory_type=row["memory_type"],
            key=row["key"],
            value=row["value"],
            confidence=row["confidence"],
            namespace=namespace,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Shared Memory (namespace-based agent collaboration) ---

    @staticmethod
    def _shared_agent_name(namespace: str) -> str:
        return f"__shared__:{namespace}"

    def store_shared_memory(
        self, namespace: str, memory_type: str, key: str, value: str, confidence: float = 1.0
    ) -> AgentMemory:
        agent_name = self._shared_agent_name(namespace)
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                """INSERT INTO agent_memory (agent_name, memory_type, key, value, confidence, namespace, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_name, memory_type, key) DO UPDATE SET
                       value=excluded.value,
                       confidence=excluded.confidence,
                       namespace=excluded.namespace,
                       updated_at=excluded.updated_at""",
                (agent_name, memory_type, key, value, confidence, namespace, now, now),
            )
            self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM agent_memory WHERE agent_name=? AND memory_type=? AND key=?",
            (agent_name, memory_type, key),
        ).fetchone()
        return self._row_to_agent_memory(row)

    def get_shared_memories(self, namespace: str, memory_type: str = "") -> list[AgentMemory]:
        agent_name = self._shared_agent_name(namespace)
        if memory_type:
            rows = self.conn.execute(
                "SELECT * FROM agent_memory WHERE agent_name=? AND namespace=? AND memory_type=? ORDER BY updated_at DESC",
                (agent_name, namespace, memory_type),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM agent_memory WHERE agent_name=? AND namespace=? ORDER BY updated_at DESC",
                (agent_name, namespace),
            ).fetchall()
        return [self._row_to_agent_memory(r) for r in rows]

    def search_shared_memories(self, namespace: str, query: str) -> list[AgentMemory]:
        agent_name = self._shared_agent_name(namespace)
        rows = self.conn.execute(
            "SELECT * FROM agent_memory WHERE agent_name=? AND namespace=? AND (key LIKE ? OR value LIKE ?) ORDER BY updated_at DESC",
            (agent_name, namespace, f"%{query}%", f"%{query}%"),
        ).fetchall()
        return [self._row_to_agent_memory(r) for r in rows]
