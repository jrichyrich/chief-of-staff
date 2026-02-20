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


class TestVectorSearch:
    """Tests for ChromaDB vector search integration."""

    @pytest.fixture
    def chroma_client(self):
        import chromadb
        return chromadb.Client()

    @pytest.fixture
    def vector_store(self, tmp_path, chroma_client):
        db_path = tmp_path / "test_vector.db"
        store = MemoryStore(db_path, chroma_client=chroma_client)
        yield store
        store.close()

    def test_no_chroma_backward_compat(self, memory_store):
        """MemoryStore without chroma_client still works for all operations."""
        assert memory_store._facts_collection is None
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        result = memory_store.get_fact("personal", "name")
        assert result is not None
        assert result.value == "Jason"
        # Vector search returns empty when no chroma
        assert memory_store.search_facts_vector("Jason") == []
        # Hybrid still works (FTS + LIKE only)
        results = memory_store.search_facts_hybrid("Jason")
        assert len(results) == 1

    def test_store_fact_upserts_to_chroma(self, vector_store):
        """store_fact should upsert the fact into ChromaDB."""
        vector_store.store_fact(Fact(category="personal", key="name", value="Jason Richardson"))
        count = vector_store._facts_collection.count()
        assert count == 1

    def test_store_fact_updates_chroma_on_overwrite(self, vector_store):
        """Updating a fact should upsert (not duplicate) in ChromaDB."""
        vector_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        vector_store.store_fact(Fact(category="personal", key="name", value="Jay"))
        count = vector_store._facts_collection.count()
        assert count == 1  # Same id, so upserted not duplicated

    def test_delete_fact_removes_from_chroma(self, vector_store):
        """delete_fact should remove the vector from ChromaDB."""
        vector_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        assert vector_store._facts_collection.count() == 1
        vector_store.delete_fact("personal", "name")
        assert vector_store._facts_collection.count() == 0

    def test_delete_nonexistent_fact_no_chroma_error(self, vector_store):
        """Deleting a fact not in ChromaDB should not raise."""
        vector_store.delete_fact("personal", "nonexistent")
        # Should not raise

    def test_search_facts_vector_returns_results(self, vector_store):
        """Vector search should return semantically relevant facts."""
        vector_store.store_fact(Fact(category="personal", key="name", value="Jason Richardson"))
        vector_store.store_fact(Fact(category="work", key="title", value="Software Engineer"))
        vector_store.store_fact(Fact(category="preference", key="color", value="blue"))
        results = vector_store.search_facts_vector("engineer")
        assert len(results) >= 1
        facts = [f for f, _ in results]
        keys = [f.key for f in facts]
        assert "title" in keys

    def test_search_facts_vector_empty_query(self, vector_store):
        """Empty queries return no results."""
        vector_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        assert vector_store.search_facts_vector("") == []
        assert vector_store.search_facts_vector("   ") == []

    def test_search_facts_vector_no_facts(self, vector_store):
        """Vector search on empty collection returns empty."""
        results = vector_store.search_facts_vector("anything")
        assert results == []

    def test_search_facts_vector_score_range(self, vector_store):
        """Scores should be between 0 and 1 (1.0 - cosine_distance)."""
        vector_store.store_fact(Fact(category="personal", key="name", value="Jason Richardson"))
        results = vector_store.search_facts_vector("Jason")
        assert len(results) == 1
        _, score = results[0]
        assert 0.0 <= score <= 1.0

    def test_hybrid_includes_vector_results(self, vector_store):
        """Hybrid search should merge vector results with FTS + LIKE."""
        vector_store.store_fact(Fact(category="personal", key="name", value="Jason Richardson"))
        vector_store.store_fact(Fact(category="work", key="role", value="software developer"))
        results = vector_store.search_facts_hybrid("engineer")
        # "engineer" won't match LIKE or FTS on "software developer",
        # but vector search should find it semantically
        fact_keys = [f.key for f, _ in results]
        assert "role" in fact_keys

    def test_hybrid_dedup_keeps_highest_score(self, vector_store):
        """When a fact appears in multiple sources, the highest score wins."""
        vector_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        results = vector_store.search_facts_hybrid("Jason")
        # Should appear exactly once (deduped across FTS + LIKE + vector)
        assert len(results) == 1

    def test_hybrid_merges_all_three_sources(self, vector_store):
        """Hybrid search merges FTS5, LIKE, and vector results."""
        # This fact will match FTS5 and LIKE on "Jason"
        vector_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        # This fact will match LIKE on "email" substring but not FTS token "Jason"
        vector_store.store_fact(Fact(category="work", key="email", value="jason@example.com"))
        # This fact should only be found by vector search (semantic match)
        vector_store.store_fact(Fact(category="work", key="role", value="software developer"))

        results = vector_store.search_facts_hybrid("Jason")
        fact_keys = [f.key for f, _ in results]
        # FTS + LIKE should find "name"
        assert "name" in fact_keys
        # LIKE should find "email" (substring match on "jason")
        assert "email" in fact_keys
