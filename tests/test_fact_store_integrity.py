# tests/test_fact_store_integrity.py
"""Tests for SQLite + ChromaDB synchronization integrity."""
from unittest.mock import MagicMock

import pytest

from memory.models import Fact
from memory.fact_store import FactStore
from memory.store import MemoryStore


class TestChromaDBSyncIntegrity:
    """Verify that SQLite and ChromaDB stay in sync on failures."""

    def _make_fact_store_with_mock_chroma(self, tmp_path):
        """Create a FactStore with a real SQLite conn and mock ChromaDB collection."""
        store = MemoryStore(tmp_path / "test.db")
        mock_collection = MagicMock()
        store._fact_store._facts_collection = mock_collection
        return store, mock_collection

    def test_store_fact_chromadb_failure_rolls_back_sqlite(self, tmp_path):
        store, mock_collection = self._make_fact_store_with_mock_chroma(tmp_path)
        mock_collection.upsert.side_effect = RuntimeError("ChromaDB down")

        with pytest.raises(RuntimeError, match="ChromaDB down"):
            store.store_fact(Fact(category="personal", key="name", value="Jason"))

        # Fact should NOT be in SQLite after rollback
        assert store.get_fact("personal", "name") is None
        store.close()

    def test_delete_fact_chromadb_failure_keeps_fact(self, tmp_path):
        # Store fact without ChromaDB first
        store = MemoryStore(tmp_path / "test.db")
        store.store_fact(Fact(category="personal", key="name", value="Jason"))
        assert store.get_fact("personal", "name") is not None

        # Now attach a failing mock ChromaDB
        mock_collection = MagicMock()
        mock_collection.delete.side_effect = RuntimeError("ChromaDB down")
        store._fact_store._facts_collection = mock_collection

        with pytest.raises(RuntimeError, match="ChromaDB down"):
            store.delete_fact("personal", "name")

        # Fact should STILL be in SQLite after rollback
        assert store.get_fact("personal", "name") is not None
        assert store.get_fact("personal", "name").value == "Jason"
        store.close()

    def test_repair_vector_index_syncs_all_facts(self, tmp_path):
        # Store facts without ChromaDB
        store = MemoryStore(tmp_path / "test.db")
        store.store_fact(Fact(category="personal", key="name", value="Jason"))
        store.store_fact(Fact(category="work", key="title", value="Engineer"))
        store.store_fact(Fact(category="preference", key="color", value="blue"))

        # Attach mock ChromaDB and repair
        mock_collection = MagicMock()
        store._fact_store._facts_collection = mock_collection

        count = store.repair_vector_index()

        assert count == 3
        assert mock_collection.upsert.call_count == 3

        # Verify each fact was upserted with correct IDs
        upserted_ids = sorted(
            call.kwargs["ids"][0] if "ids" in call.kwargs else call[1]["ids"][0]
            for call in mock_collection.upsert.call_args_list
        )
        assert "personal:name" in upserted_ids
        assert "preference:color" in upserted_ids
        assert "work:title" in upserted_ids
        store.close()

    def test_repair_vector_index_without_chromadb_returns_zero(self, tmp_path):
        store = MemoryStore(tmp_path / "test.db")
        store.store_fact(Fact(category="personal", key="name", value="Jason"))
        assert store.repair_vector_index() == 0
        store.close()

    def test_store_fact_without_chromadb_still_works(self, tmp_path):
        store = MemoryStore(tmp_path / "test.db")
        result = store.store_fact(Fact(category="personal", key="name", value="Jason"))
        assert result is not None
        assert result.value == "Jason"
        store.close()

    def test_delete_fact_without_chromadb_still_works(self, tmp_path):
        store = MemoryStore(tmp_path / "test.db")
        store.store_fact(Fact(category="personal", key="name", value="Jason"))
        assert store.delete_fact("personal", "name") is True
        assert store.get_fact("personal", "name") is None
        store.close()

    def test_store_fact_with_working_chromadb(self, tmp_path):
        store, mock_collection = self._make_fact_store_with_mock_chroma(tmp_path)
        result = store.store_fact(Fact(category="personal", key="name", value="Jason"))
        assert result is not None
        assert result.value == "Jason"
        mock_collection.upsert.assert_called_once()
        store.close()

    def test_delete_fact_with_working_chromadb(self, tmp_path):
        # Store without ChromaDB
        store = MemoryStore(tmp_path / "test.db")
        store.store_fact(Fact(category="personal", key="name", value="Jason"))

        # Attach working mock ChromaDB
        mock_collection = MagicMock()
        store._fact_store._facts_collection = mock_collection

        assert store.delete_fact("personal", "name") is True
        mock_collection.delete.assert_called_once()
        assert store.get_fact("personal", "name") is None
        store.close()
