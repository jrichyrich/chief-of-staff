# memory/store.py
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from memory.models import Fact, Location


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
        """)
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

    def close(self):
        self.conn.close()
