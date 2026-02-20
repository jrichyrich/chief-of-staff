# skills/pattern_detector.py
"""Detects repeated tool usage patterns and suggests new agent configurations."""

from memory.store import MemoryStore


def _jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two strings based on word sets."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _cluster_patterns(rows: list[dict], similarity_threshold: float = 0.4) -> list[dict]:
    """Group similar query patterns by tool_name and keyword overlap.

    Returns a list of cluster dicts:
      {tool_name, patterns: [str], total_count, representative}
    """
    clusters: list[dict] = []
    for row in rows:
        tool = row["tool_name"]
        pattern = row["query_pattern"]
        count = row["count"]
        merged = False
        for cluster in clusters:
            if cluster["tool_name"] != tool:
                continue
            if _jaccard_similarity(pattern, cluster["representative"]) >= similarity_threshold:
                cluster["patterns"].append(pattern)
                cluster["total_count"] += count
                merged = True
                break
        if not merged:
            clusters.append({
                "tool_name": tool,
                "patterns": [pattern],
                "total_count": count,
                "representative": pattern,
            })
    return clusters


class PatternDetector:
    def __init__(self, memory_store: MemoryStore):
        self.memory_store = memory_store

    def detect_patterns(
        self,
        min_occurrences: int = 5,
        confidence_threshold: float = 0.7,
    ) -> list[dict]:
        """Analyze skill_usage rows and return pattern descriptions with confidence.

        Returns list of dicts:
          {description, tool_name, patterns, total_count, confidence}
        """
        rows = self.memory_store.get_skill_usage_patterns()
        if not rows:
            return []

        clusters = _cluster_patterns(rows)
        results = []
        # Compute max count for relative confidence scoring
        max_count = max((c["total_count"] for c in clusters), default=1)
        for cluster in clusters:
            if cluster["total_count"] < min_occurrences:
                continue
            confidence = min(cluster["total_count"] / max(max_count, 1), 1.0)
            if confidence < confidence_threshold:
                continue
            description = (
                f"Repeated use of '{cluster['tool_name']}' with patterns: "
                + ", ".join(cluster["patterns"][:5])
            )
            results.append({
                "description": description,
                "tool_name": cluster["tool_name"],
                "patterns": cluster["patterns"],
                "total_count": cluster["total_count"],
                "confidence": round(confidence, 3),
            })
        return results
