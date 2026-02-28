# memory/fact_store.py
"""Domain store for facts, locations, and context entries."""
import logging
import math
import re
import sqlite3
from datetime import datetime
from typing import Optional

from memory.models import ContextEntry, Fact, Location

logger = logging.getLogger(__name__)

# FTS5 special characters/operators to strip from user queries
_FTS5_SPECIAL = re.compile(r'[*"^\-():,]|\b(?:OR|AND|NOT|NEAR)\b')


class FactStore:
    """Manages facts (with FTS5 + ChromaDB vector search), locations, and context."""

    def __init__(self, conn: sqlite3.Connection, chroma_collection=None):
        self.conn = conn
        self._facts_collection = chroma_collection

    # --- Facts ---

    def store_fact(self, fact: Fact) -> Fact:
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO facts (category, key, value, confidence, source, pinned, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(category, key) DO UPDATE SET
                   value=excluded.value,
                   confidence=excluded.confidence,
                   source=excluded.source,
                   pinned=excluded.pinned,
                   updated_at=excluded.updated_at""",
            (fact.category, fact.key, fact.value, fact.confidence, fact.source,
             1 if fact.pinned else 0, now, now),
        )
        self.conn.commit()
        if self._facts_collection is not None:
            try:
                self._facts_collection.upsert(
                    ids=[f"{fact.category}:{fact.key}"],
                    documents=[f"{fact.key}: {fact.value}"],
                    metadatas=[{"category": fact.category, "key": fact.key}],
                )
            except Exception as e:
                logger.warning("ChromaDB upsert failed for %s:%s: %s", fact.category, fact.key, e)
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
        Pinned facts bypass decay and return full confidence score.
        Returns list of (Fact, score) tuples sorted by score descending.
        """
        half_life_days = max(half_life_days, 0.001)
        now = datetime.now()
        ln2 = math.log(2)
        scored: list[tuple[Fact, float]] = []
        for fact in facts:
            if fact.pinned:
                scored.append((fact, fact.confidence))
                continue
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
        """Search facts with temporal decay scoring."""
        return self.rank_facts(self.search_facts(query), half_life_days)

    def search_facts_fts(self, query: str) -> list[Fact]:
        """Full-text search over facts using FTS5.

        Falls back to LIKE-based search_facts() if the FTS query fails.
        """
        if not query or not query.strip():
            return []
        try:
            sanitized = _FTS5_SPECIAL.sub(" ", query)
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

    def search_facts_vector(self, query: str, top_k: int = 20) -> list[tuple[Fact, float]]:
        """Semantic vector search over facts using ChromaDB.

        Returns (Fact, score) tuples where score = 1.0 - cosine_distance.
        """
        if not self._facts_collection or not query or not query.strip():
            return []
        try:
            count = self._facts_collection.count()
            if count == 0:
                return []
            n = min(top_k, count)
            results = self._facts_collection.query(
                query_texts=[query], n_results=n,
            )
        except Exception:
            return []
        scored: list[tuple[Fact, float]] = []
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for i, doc_id in enumerate(ids):
            parts = doc_id.split(":", 1)
            if len(parts) != 2:
                continue
            category, key = parts
            fact = self.get_fact(category, key)
            if fact is None:
                continue
            distance = distances[i] if i < len(distances) else 1.0
            score = max(0.0, 1.0 - distance)
            scored.append((fact, score))
        return scored

    @staticmethod
    def _mmr_rerank(
        results: list[tuple[Fact, float]],
        lambda_param: float = 0.7,
        top_k: int | None = None,
    ) -> list[tuple[Fact, float]]:
        """Maximal Marginal Relevance re-ranking to reduce redundancy."""
        if not results:
            return []

        def _jaccard(a: str, b: str) -> float:
            words_a = set(a.lower().split())
            words_b = set(b.lower().split())
            if not words_a or not words_b:
                return 0.0
            return len(words_a & words_b) / len(words_a | words_b)

        remaining = list(results)
        selected: list[tuple[Fact, float]] = []
        k = top_k if top_k is not None else len(results)

        while remaining and len(selected) < k:
            best_idx = 0
            best_mmr = float("-inf")
            for i, (fact, score) in enumerate(remaining):
                max_sim = 0.0
                for sel_fact, _ in selected:
                    sim = _jaccard(fact.value, sel_fact.value)
                    if sim > max_sim:
                        max_sim = sim
                mmr = lambda_param * score - (1 - lambda_param) * max_sim
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = i
            selected.append(remaining.pop(best_idx))

        return selected

    def search_facts_hybrid(self, query: str, diverse: bool = False, half_life_days: float = 90.0) -> list[tuple[Fact, float]]:
        """Hybrid search combining FTS5 BM25, LIKE, and vector search."""
        if not query or not query.strip():
            return []

        merged: dict[int, tuple[Fact, float]] = {}

        # FTS5 results with BM25 rank
        try:
            sanitized = _FTS5_SPECIAL.sub(" ", query)
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
                    score = -float(row["rank"])
                    merged[fact.id] = (fact, score)
        except Exception:
            pass

        # LIKE results
        like_results = self.search_facts(query)
        for fact in like_results:
            if fact.id not in merged:
                merged[fact.id] = (fact, 0.5)

        # Vector results
        vector_results = self.search_facts_vector(query)
        for fact, score in vector_results:
            if fact.id not in merged:
                merged[fact.id] = (fact, score)
            else:
                if score > merged[fact.id][1]:
                    merged[fact.id] = (fact, score)

        # Apply temporal decay
        half_life_days = max(half_life_days, 0.001)
        now = datetime.now()
        ln2 = math.log(2)
        results: list[tuple[Fact, float]] = []
        for fact, score in merged.values():
            if fact.pinned:
                results.append((fact, score))
                continue
            timestamp = fact.updated_at or fact.created_at
            if timestamp:
                dt = datetime.fromisoformat(str(timestamp))
                age_days = (now - dt).total_seconds() / 86400.0
            else:
                age_days = 0.0
            decay = math.exp(-ln2 * age_days / half_life_days)
            results.append((fact, score * decay))
        results.sort(key=lambda x: x[1], reverse=True)

        if diverse:
            results = self._mmr_rerank(results)

        return results

    def delete_fact(self, category: str, key: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM facts WHERE category=? AND key=?", (category, key)
        )
        self.conn.commit()
        if self._facts_collection is not None:
            try:
                self._facts_collection.delete(ids=[f"{category}:{key}"])
            except Exception as e:
                logger.warning("ChromaDB delete failed for %s:%s: %s", category, key, e)
        return cursor.rowcount > 0

    def _row_to_fact(self, row: sqlite3.Row) -> Fact:
        pinned = False
        try:
            pinned = bool(row["pinned"])
        except (IndexError, KeyError):
            pass
        return Fact(
            id=row["id"],
            category=row["category"],
            key=row["key"],
            value=row["value"],
            confidence=row["confidence"],
            source=row["source"],
            pinned=pinned,
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
