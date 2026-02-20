# tests/test_skill_pattern_detector.py
import pytest

from memory.store import MemoryStore
from skills.pattern_detector import PatternDetector, _jaccard_similarity, _cluster_patterns


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


class TestJaccardSimilarity:
    def test_identical_strings(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert _jaccard_similarity("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        sim = _jaccard_similarity("search calendar events", "search calendar meetings")
        # Overlap: {search, calendar} / Union: {search, calendar, events, meetings}
        assert sim == pytest.approx(0.5)

    def test_empty_string(self):
        assert _jaccard_similarity("", "hello") == 0.0
        assert _jaccard_similarity("hello", "") == 0.0
        assert _jaccard_similarity("", "") == 0.0


class TestClusterPatterns:
    def test_clusters_same_tool_similar_patterns(self):
        rows = [
            {"tool_name": "query_memory", "query_pattern": "search work projects", "count": 5},
            {"tool_name": "query_memory", "query_pattern": "search work tasks", "count": 3},
        ]
        clusters = _cluster_patterns(rows, similarity_threshold=0.3)
        # Should merge into one cluster because "search work" overlaps
        assert len(clusters) == 1
        assert clusters[0]["total_count"] == 8
        assert len(clusters[0]["patterns"]) == 2

    def test_different_tools_not_merged(self):
        rows = [
            {"tool_name": "query_memory", "query_pattern": "search work", "count": 5},
            {"tool_name": "search_calendar", "query_pattern": "search work", "count": 3},
        ]
        clusters = _cluster_patterns(rows, similarity_threshold=0.3)
        assert len(clusters) == 2

    def test_dissimilar_patterns_not_merged(self):
        rows = [
            {"tool_name": "query_memory", "query_pattern": "search work projects", "count": 5},
            {"tool_name": "query_memory", "query_pattern": "find personal preferences", "count": 3},
        ]
        clusters = _cluster_patterns(rows, similarity_threshold=0.5)
        assert len(clusters) == 2

    def test_empty_rows(self):
        assert _cluster_patterns([]) == []


class TestPatternDetector:
    def test_no_usage_data(self, memory_store):
        detector = PatternDetector(memory_store)
        patterns = detector.detect_patterns()
        assert patterns == []

    def test_below_min_occurrences(self, memory_store):
        # Record usage 3 times (below default threshold of 5)
        for _ in range(3):
            memory_store.record_skill_usage("query_memory", "search work")

        detector = PatternDetector(memory_store)
        patterns = detector.detect_patterns(min_occurrences=5)
        assert patterns == []

    def test_above_min_occurrences(self, memory_store):
        # Record usage 7 times (above threshold of 5)
        for _ in range(7):
            memory_store.record_skill_usage("query_memory", "search work")

        detector = PatternDetector(memory_store)
        patterns = detector.detect_patterns(min_occurrences=5, confidence_threshold=0.0)
        assert len(patterns) == 1
        assert patterns[0]["tool_name"] == "query_memory"
        assert patterns[0]["total_count"] == 7
        assert patterns[0]["confidence"] > 0

    def test_multiple_patterns(self, memory_store):
        for _ in range(10):
            memory_store.record_skill_usage("query_memory", "search work tasks")
        for _ in range(8):
            memory_store.record_skill_usage("search_calendar_events", "weekly meeting")

        detector = PatternDetector(memory_store)
        patterns = detector.detect_patterns(min_occurrences=5, confidence_threshold=0.0)
        assert len(patterns) == 2

    def test_confidence_threshold_filters(self, memory_store):
        # One pattern with high count, one with lower
        for _ in range(10):
            memory_store.record_skill_usage("query_memory", "high frequency")
        for _ in range(5):
            memory_store.record_skill_usage("search_docs", "low frequency")

        detector = PatternDetector(memory_store)
        # With high threshold, only the dominant pattern should pass
        patterns = detector.detect_patterns(min_occurrences=5, confidence_threshold=0.9)
        assert len(patterns) == 1
        assert patterns[0]["tool_name"] == "query_memory"

    def test_similar_patterns_clustered(self, memory_store):
        for _ in range(4):
            memory_store.record_skill_usage("query_memory", "search work projects")
        for _ in range(4):
            memory_store.record_skill_usage("query_memory", "search work tasks")

        detector = PatternDetector(memory_store)
        # Combined count is 8 which exceeds min_occurrences=5
        patterns = detector.detect_patterns(min_occurrences=5, confidence_threshold=0.0)
        assert len(patterns) == 1
        assert patterns[0]["total_count"] == 8
