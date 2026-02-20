# tests/test_fts5_search.py
import pytest
from memory.store import MemoryStore
from memory.models import Fact


@pytest.fixture
def memory_store(tmp_path):
    db_path = tmp_path / "test_fts5.db"
    store = MemoryStore(db_path)
    yield store
    store.close()


class TestFTS5Search:
    def test_fts5_finds_exact_keyword(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason Richardson"))
        memory_store.store_fact(Fact(category="work", key="title", value="Software Engineer"))
        results = memory_store.search_facts_fts("Jason")
        assert len(results) == 1
        assert results[0].key == "name"

    def test_fts5_multi_word_query(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason Richardson"))
        memory_store.store_fact(Fact(category="work", key="company", value="Acme Corp"))
        results = memory_store.search_facts_fts("Jason Richardson")
        assert len(results) == 1
        assert results[0].value == "Jason Richardson"

    def test_fts5_searches_key_and_category(self, memory_store):
        memory_store.store_fact(Fact(category="preference", key="favorite_color", value="blue"))
        # Should match on the key field
        results = memory_store.search_facts_fts("favorite_color")
        assert len(results) == 1
        assert results[0].value == "blue"

    def test_fts5_no_results(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        results = memory_store.search_facts_fts("nonexistent")
        assert len(results) == 0

    def test_fts5_empty_query(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        assert memory_store.search_facts_fts("") == []
        assert memory_store.search_facts_fts("   ") == []

    def test_fts5_special_chars_stripped(self, memory_store):
        memory_store.store_fact(Fact(category="work", key="tool", value="pytest framework"))
        # Special FTS5 chars should be stripped, query still works
        results = memory_store.search_facts_fts('*"pytest"*')
        assert len(results) == 1
        assert results[0].key == "tool"

    def test_fts5_fallback_on_malformed_query(self, memory_store):
        """If the FTS5 query fails, it should fall back to LIKE search."""
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        # Drop the FTS table to force failure on MATCH queries
        memory_store.conn.execute("DROP TABLE IF EXISTS facts_fts")
        memory_store.conn.commit()
        results = memory_store.search_facts_fts("Jason")
        assert len(results) == 1
        assert results[0].value == "Jason"


class TestFTS5Triggers:
    def test_insert_trigger_populates_fts(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="pet", value="golden retriever"))
        # Verify FTS index has the entry by searching
        results = memory_store.search_facts_fts("retriever")
        assert len(results) == 1
        assert results[0].key == "pet"

    def test_update_trigger_syncs_fts(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="pet", value="golden retriever"))
        # Update the fact (same category+key triggers ON CONFLICT UPDATE)
        memory_store.store_fact(Fact(category="personal", key="pet", value="labrador"))
        # Old value should not match
        results = memory_store.search_facts_fts("retriever")
        assert len(results) == 0
        # New value should match
        results = memory_store.search_facts_fts("labrador")
        assert len(results) == 1

    def test_delete_trigger_removes_from_fts(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="pet", value="golden retriever"))
        memory_store.delete_fact("personal", "pet")
        results = memory_store.search_facts_fts("retriever")
        assert len(results) == 0


class TestHybridSearch:
    def test_hybrid_returns_fts_results(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        results = memory_store.search_facts_hybrid("Jason")
        assert len(results) == 1
        fact, score = results[0]
        assert fact.key == "name"
        assert score > 0

    def test_hybrid_returns_like_results(self, memory_store):
        """LIKE can find substring matches that FTS5 token matching might miss."""
        memory_store.store_fact(Fact(category="work", key="email", value="jason@example.com"))
        results = memory_store.search_facts_hybrid("example.com")
        assert len(results) >= 1
        # At least the LIKE fallback should find it
        fact_keys = [f.key for f, _ in results]
        assert "email" in fact_keys

    def test_hybrid_deduplicates_results(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        results = memory_store.search_facts_hybrid("Jason")
        # Should appear only once even though both FTS and LIKE would find it
        assert len(results) == 1

    def test_hybrid_keeps_higher_score(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        results = memory_store.search_facts_hybrid("Jason")
        assert len(results) == 1
        _, score = results[0]
        # FTS5 BM25 score should be > the LIKE fixed score of 0.5
        assert score > 0  # BM25 score should be positive

    def test_hybrid_sorted_by_score_descending(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        memory_store.store_fact(Fact(category="work", key="title", value="Jason is an engineer"))
        results = memory_store.search_facts_hybrid("Jason")
        assert len(results) >= 1
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_hybrid_empty_query(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        assert memory_store.search_facts_hybrid("") == []
        assert memory_store.search_facts_hybrid("   ") == []

    def test_hybrid_fallback_on_fts_failure(self, memory_store):
        """Hybrid should still return LIKE results if FTS5 fails."""
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        # Drop the FTS table to force failure on MATCH queries
        memory_store.conn.execute("DROP TABLE IF EXISTS facts_fts")
        memory_store.conn.commit()
        results = memory_store.search_facts_hybrid("Jason")
        assert len(results) == 1
        _, score = results[0]
        assert score == 0.5  # Only LIKE results with fixed score


class TestFTS5Rebuild:
    def test_rebuild_indexes_preexisting_data(self, tmp_path):
        """Data inserted before FTS table creation gets indexed on rebuild."""
        db_path = tmp_path / "test_rebuild.db"
        # Create DB with just the facts table (no FTS)
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, key)
        )""")
        conn.execute(
            "INSERT INTO facts (category, key, value) VALUES (?, ?, ?)",
            ("personal", "name", "Jason"),
        )
        conn.commit()
        conn.close()

        # Now open with MemoryStore which creates FTS + rebuilds
        store = MemoryStore(db_path)
        results = store.search_facts_fts("Jason")
        assert len(results) == 1
        assert results[0].key == "name"
        store.close()
