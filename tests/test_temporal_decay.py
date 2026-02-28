# tests/test_temporal_decay.py
import math
from datetime import datetime, timedelta

import pytest
from memory.models import Fact
from memory.store import MemoryStore



def _insert_fact_with_timestamps(memory_store, category, key, value, confidence,
                                  created_at, updated_at=None):
    """Insert a fact with explicit timestamps for testing decay."""
    memory_store.conn.execute(
        """INSERT INTO facts (category, key, value, confidence, source, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (category, key, value, confidence, "test", created_at, updated_at),
    )
    memory_store.conn.commit()


class TestSearchFactsRanked:
    def test_recent_fact_ranks_higher_than_old_fact(self, memory_store):
        now = datetime.now()
        recent = (now - timedelta(days=1)).isoformat()
        old = (now - timedelta(days=180)).isoformat()

        _insert_fact_with_timestamps(memory_store, "work", "project_new", "Alpha project", 1.0,
                                      created_at=recent, updated_at=recent)
        _insert_fact_with_timestamps(memory_store, "work", "project_old", "Alpha legacy", 1.0,
                                      created_at=old, updated_at=old)

        results = memory_store.search_facts_ranked("Alpha")
        assert len(results) == 2
        # Recent fact should rank first
        assert results[0][0].key == "project_new"
        assert results[1][0].key == "project_old"
        # Recent score should be higher
        assert results[0][1] > results[1][1]

    def test_high_confidence_old_fact_outranks_low_confidence_new_fact(self, memory_store):
        now = datetime.now()
        recent = (now - timedelta(days=1)).isoformat()
        old = (now - timedelta(days=30)).isoformat()

        _insert_fact_with_timestamps(memory_store, "personal", "name_certain", "Jason R",
                                      confidence=1.0, created_at=old, updated_at=old)
        _insert_fact_with_timestamps(memory_store, "personal", "name_guess", "Jason maybe",
                                      confidence=0.2, created_at=recent, updated_at=recent)

        results = memory_store.search_facts_ranked("Jason")
        assert len(results) == 2
        # High-confidence old fact should outrank low-confidence new fact
        assert results[0][0].key == "name_certain"
        assert results[0][1] > results[1][1]

    def test_null_updated_at_falls_back_to_created_at(self, memory_store):
        now = datetime.now()
        created = (now - timedelta(days=10)).isoformat()

        _insert_fact_with_timestamps(memory_store, "work", "task_info", "Deploy service",
                                      confidence=1.0, created_at=created, updated_at=None)

        results = memory_store.search_facts_ranked("Deploy")
        assert len(results) == 1
        fact, score = results[0]
        assert fact.key == "task_info"
        # Score should reflect ~10 days of decay with 90-day half-life
        expected = 1.0 * math.exp(-math.log(2) * 10 / 90.0)
        assert abs(score - expected) < 0.01

    def test_empty_results_for_no_matches(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        results = memory_store.search_facts_ranked("nonexistent_query_xyz")
        assert results == []

    def test_custom_half_life(self, memory_store):
        now = datetime.now()
        ts = (now - timedelta(days=30)).isoformat()

        _insert_fact_with_timestamps(memory_store, "work", "item", "test value",
                                      confidence=1.0, created_at=ts, updated_at=ts)

        # With 30-day half-life, score at 30 days should be ~0.5
        results_short = memory_store.search_facts_ranked("test", half_life_days=30.0)
        assert len(results_short) == 1
        assert abs(results_short[0][1] - 0.5) < 0.05

        # With 365-day half-life, score at 30 days should be much higher
        results_long = memory_store.search_facts_ranked("test", half_life_days=365.0)
        assert results_long[0][1] > results_short[0][1]

    def test_scores_are_sorted_descending(self, memory_store):
        now = datetime.now()
        for i in range(5):
            ts = (now - timedelta(days=i * 30)).isoformat()
            _insert_fact_with_timestamps(memory_store, "work", f"item_{i}", "search term",
                                          confidence=1.0, created_at=ts, updated_at=ts)

        results = memory_store.search_facts_ranked("search term")
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)
