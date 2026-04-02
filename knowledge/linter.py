"""Knowledge linter — detects stale facts, near-duplicates, and inconsistencies.

Designed to run as a scheduled task. Returns a list of finding dicts
that surface through the proactive suggestion engine.
"""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.store import MemoryStore

logger = logging.getLogger(__name__)


def _jaccard_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


class KnowledgeLinter:
    """Checks fact store health and returns actionable findings."""

    def __init__(self, memory_store: "MemoryStore"):
        self.memory_store = memory_store

    def check_stale_facts(self, max_age_days: int = 180, min_confidence: float = 0.6) -> list[dict]:
        """Find facts that are old AND low-confidence (likely outdated).
        Pinned facts are always excluded.
        """
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        rows = self.memory_store.conn.execute(
            """SELECT * FROM facts
               WHERE pinned = 0
               AND confidence < ?
               AND updated_at < ?
               ORDER BY updated_at ASC""",
            (min_confidence, cutoff),
        ).fetchall()

        findings = []
        for row in rows:
            findings.append({
                "issue": "stale",
                "category": row["category"],
                "key": row["key"],
                "value": row["value"][:100],
                "confidence": row["confidence"],
                "updated_at": row["updated_at"],
                "suggestion": f"Review or delete fact '{row['key']}' — last updated {row['updated_at'][:10]}, confidence {row['confidence']}",
            })
        return findings

    def check_near_duplicates(self, similarity_threshold: float = 0.7) -> list[dict]:
        """Find fact pairs with high word overlap within the same category."""
        rows = self.memory_store.conn.execute(
            "SELECT * FROM facts ORDER BY category, key"
        ).fetchall()

        by_category: dict[str, list] = {}
        for row in rows:
            by_category.setdefault(row["category"], []).append(row)

        findings = []
        seen_pairs: set[tuple] = set()
        for category, facts in by_category.items():
            for i in range(len(facts)):
                for j in range(i + 1, len(facts)):
                    a, b = facts[i], facts[j]
                    pair_key = (a["id"], b["id"])
                    if pair_key in seen_pairs:
                        continue
                    sim = _jaccard_similarity(a["value"], b["value"])
                    if sim >= similarity_threshold:
                        seen_pairs.add(pair_key)
                        findings.append({
                            "issue": "near_duplicate",
                            "category": category,
                            "fact_a": {"key": a["key"], "value": a["value"][:80]},
                            "fact_b": {"key": b["key"], "value": b["value"][:80]},
                            "similarity": round(sim, 2),
                            "suggestion": f"Merge or deduplicate: '{a['key']}' and '{b['key']}' ({round(sim * 100)}% similar)",
                        })
        return findings

    def run_all(self, max_age_days=180, min_confidence=0.6, similarity_threshold=0.7) -> list[dict]:
        """Run all lint checks and return combined findings."""
        findings = []
        findings.extend(self.check_stale_facts(max_age_days, min_confidence))
        findings.extend(self.check_near_duplicates(similarity_threshold))
        return findings
