"""Tests for the knowledge linter module."""

import pytest
from datetime import datetime, timedelta

from memory.models import Fact
from knowledge.linter import KnowledgeLinter, _jaccard_similarity


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _store(ms, key, value, category="work", confidence=0.5, pinned=False):
    fact = Fact(category=category, key=key, value=value, confidence=confidence, pinned=pinned)
    ms.store_fact(fact)
    return fact


def _age_fact(ms, key, days):
    """Backdate a fact's updated_at to simulate aging."""
    old_date = (datetime.now() - timedelta(days=days)).isoformat()
    ms.conn.execute("UPDATE facts SET updated_at = ? WHERE key = ?", (old_date, key))
    ms.conn.commit()


# ---------------------------------------------------------------------------
# Jaccard helper
# ---------------------------------------------------------------------------

def test_jaccard_identical():
    assert _jaccard_similarity("hello world", "hello world") == 1.0


def test_jaccard_disjoint():
    assert _jaccard_similarity("apple banana", "cherry date") == 0.0


def test_jaccard_partial():
    sim = _jaccard_similarity("the quick brown fox", "the slow brown dog")
    assert 0.0 < sim < 1.0


def test_jaccard_empty_strings():
    assert _jaccard_similarity("", "") == 0.0


# ---------------------------------------------------------------------------
# check_stale_facts
# ---------------------------------------------------------------------------

def test_stale_no_facts(memory_store):
    linter = KnowledgeLinter(memory_store)
    assert linter.check_stale_facts() == []


def test_stale_recent_fact_not_flagged(memory_store):
    _store(memory_store, "recent_key", "some value", confidence=0.3)
    # fact is brand new — well within max_age_days
    linter = KnowledgeLinter(memory_store)
    findings = linter.check_stale_facts(max_age_days=180, min_confidence=0.6)
    assert findings == []


def test_stale_old_high_confidence_not_flagged(memory_store):
    """Old but high-confidence facts should not be flagged."""
    _store(memory_store, "trusted_key", "trusted value", confidence=0.9)
    _age_fact(memory_store, "trusted_key", 200)
    linter = KnowledgeLinter(memory_store)
    findings = linter.check_stale_facts(max_age_days=180, min_confidence=0.6)
    assert findings == []


def test_stale_old_low_confidence_flagged(memory_store):
    """Old AND low-confidence fact should appear in findings."""
    _store(memory_store, "stale_key", "stale value", confidence=0.3)
    _age_fact(memory_store, "stale_key", 200)
    linter = KnowledgeLinter(memory_store)
    findings = linter.check_stale_facts(max_age_days=180, min_confidence=0.6)
    assert len(findings) == 1
    f = findings[0]
    assert f["issue"] == "stale"
    assert f["key"] == "stale_key"
    assert f["confidence"] == 0.3
    assert "suggestion" in f


def test_stale_pinned_fact_never_flagged(memory_store):
    """Pinned facts are excluded regardless of age and confidence."""
    _store(memory_store, "pinned_key", "important value", confidence=0.1, pinned=True)
    _age_fact(memory_store, "pinned_key", 400)
    linter = KnowledgeLinter(memory_store)
    findings = linter.check_stale_facts(max_age_days=180, min_confidence=0.6)
    assert findings == []


def test_stale_returns_multiple(memory_store):
    for i in range(3):
        _store(memory_store, f"old_{i}", f"value {i}", confidence=0.2)
        _age_fact(memory_store, f"old_{i}", 365)
    linter = KnowledgeLinter(memory_store)
    findings = linter.check_stale_facts()
    assert len(findings) == 3
    assert all(f["issue"] == "stale" for f in findings)


# ---------------------------------------------------------------------------
# check_near_duplicates
# ---------------------------------------------------------------------------

def test_duplicates_no_facts(memory_store):
    linter = KnowledgeLinter(memory_store)
    assert linter.check_near_duplicates() == []


def test_duplicates_single_fact(memory_store):
    _store(memory_store, "solo", "only one fact here")
    linter = KnowledgeLinter(memory_store)
    assert linter.check_near_duplicates() == []


def test_duplicates_distinct_facts_not_flagged(memory_store):
    _store(memory_store, "k1", "apple banana cherry")
    _store(memory_store, "k2", "completely different words here now")
    linter = KnowledgeLinter(memory_store)
    findings = linter.check_near_duplicates(similarity_threshold=0.7)
    assert findings == []


def test_duplicates_detects_near_duplicate(memory_store):
    """Two facts with high word overlap in the same category should be flagged."""
    _store(memory_store, "k1", "the project deadline is next friday morning")
    _store(memory_store, "k2", "the project deadline is next friday morning please note")
    linter = KnowledgeLinter(memory_store)
    findings = linter.check_near_duplicates(similarity_threshold=0.7)
    assert len(findings) >= 1
    f = findings[0]
    assert f["issue"] == "near_duplicate"
    assert f["similarity"] >= 0.7
    assert "suggestion" in f
    assert "fact_a" in f and "fact_b" in f


def test_duplicates_different_categories_not_flagged(memory_store):
    """Near-duplicate values in DIFFERENT categories should not be paired."""
    _store(memory_store, "k1", "shared words overlap many times here", category="work")
    _store(memory_store, "k2", "shared words overlap many times here", category="personal")
    linter = KnowledgeLinter(memory_store)
    # They are in different categories — should not be flagged as duplicates
    findings = linter.check_near_duplicates(similarity_threshold=0.7)
    assert findings == []


def test_duplicates_no_repeated_pairs(memory_store):
    """Each pair should appear at most once in findings."""
    _store(memory_store, "k1", "alpha beta gamma delta epsilon")
    _store(memory_store, "k2", "alpha beta gamma delta epsilon zeta")
    linter = KnowledgeLinter(memory_store)
    findings = linter.check_near_duplicates(similarity_threshold=0.7)
    # Should not have duplicated pair (k1,k2) and (k2,k1)
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------

def test_run_all_empty(memory_store):
    linter = KnowledgeLinter(memory_store)
    assert linter.run_all() == []


def test_run_all_combines_findings(memory_store):
    # Add a stale fact
    _store(memory_store, "stale", "old outdated info", confidence=0.2)
    _age_fact(memory_store, "stale", 300)

    # Add a duplicate pair
    _store(memory_store, "dup_a", "alpha beta gamma delta epsilon zeta")
    _store(memory_store, "dup_b", "alpha beta gamma delta epsilon eta")

    linter = KnowledgeLinter(memory_store)
    findings = linter.run_all(similarity_threshold=0.7)

    issues = [f["issue"] for f in findings]
    assert "stale" in issues
    assert "near_duplicate" in issues
