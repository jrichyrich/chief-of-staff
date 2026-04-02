"""Integration tests for the knowledge enhancement pipeline."""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from memory.models import Fact
from memory.store import MemoryStore
from documents.store import DocumentStore


@pytest.fixture
def memory_store(tmp_path):
    return MemoryStore(tmp_path / "test.db")


@pytest.fixture
def document_store(tmp_path):
    return DocumentStore(tmp_path / "chroma")


class TestEndToEndIngestionWithSummary:
    def test_ingest_and_search_with_summary(self, document_store, tmp_path):
        """Ingest a file with summary compilation, then search returns both."""
        test_file = tmp_path / "architecture.md"
        test_file.write_text(
            "The Jarvis system uses SQLite for structured data and ChromaDB for "
            "vector embeddings. " + "Additional context. " * 50
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Jarvis uses SQLite and ChromaDB for hybrid storage.")]

        with patch("knowledge.compiler.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = mock_response

            with patch("documents.ingestion.COMPILE_ON_INGEST", True):
                from documents.ingestion import ingest_path
                result = ingest_path(test_file, document_store)

        assert "1 file(s)" in result

        # Search should find both chunks and summary
        all_results = document_store.search("SQLite ChromaDB", top_k=5)
        assert len(all_results) >= 2

        summaries = document_store.search_summaries("SQLite ChromaDB", top_k=5)
        assert len(summaries) == 1
        assert "SQLite" in summaries[0]["text"]


class TestKnowledgeLintScheduledHandler:
    def test_lint_handler_detects_issues(self, memory_store):
        """Scheduled handler finds stale facts and returns them."""
        memory_store.store_fact(Fact(
            category="work", key="ancient_fact",
            value="Very old information", confidence=0.3,
        ))
        memory_store.conn.execute(
            "UPDATE facts SET updated_at = ? WHERE key = ?",
            ((datetime.now() - timedelta(days=365)).isoformat(), "ancient_fact"),
        )
        memory_store.conn.commit()

        from scheduler.handlers import execute_handler
        result = json.loads(execute_handler("knowledge_lint", "{}", memory_store=memory_store))

        assert result["status"] == "ok"
        assert result["findings_count"] >= 1


class TestOutputFeedbackLoop:
    def test_findings_stored_and_queryable(self, memory_store):
        """Extracted findings should be queryable via memory search."""
        doc = "RBAC migration is complete. SentinelOne reached 98% coverage. " * 10

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="- RBAC migration completed\n- SentinelOne at 98%")]

        with patch("knowledge.feedback.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = mock_response

            from knowledge.feedback import extract_and_store_findings
            findings = extract_and_store_findings(doc, "test_brief", memory_store)

        assert len(findings) == 2
        results = memory_store.search_facts("RBAC")
        assert any("RBAC" in f.value for f in results)
