"""Tests for knowledge/feedback.py — output feedback module."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def memory_store(tmp_path):
    from memory.store import MemoryStore
    return MemoryStore(tmp_path / "test.db")


class TestExtractAndStoreFindings:
    def test_extracts_and_stores_findings(self, memory_store):
        """Happy path: extract findings from a document and verify facts are stored."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="- RBAC rollout completed on schedule\n- Finding 2")]

        mock_anthropic_module = MagicMock()
        mock_client = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_response

        document = " ".join(["word"] * 60) + " RBAC rollout completed on schedule."

        with patch("knowledge.feedback.anthropic", mock_anthropic_module):
            from knowledge.feedback import extract_and_store_findings
            findings = extract_and_store_findings(document, "weekly_cio_brief_2026-04-01", memory_store)

        assert len(findings) == 2
        assert findings[0] == "RBAC rollout completed on schedule"
        assert findings[1] == "Finding 2"

        # Verify facts stored in memory
        stored = memory_store.search_facts("RBAC")
        assert len(stored) >= 1
        assert any("RBAC" in f.value for f in stored)

    def test_skips_empty_document(self, memory_store):
        """Empty document should return empty list without calling the API."""
        mock_anthropic_module = MagicMock()

        with patch("knowledge.feedback.anthropic", mock_anthropic_module):
            from knowledge.feedback import extract_and_store_findings
            findings = extract_and_store_findings("", "source_empty", memory_store)

        assert findings == []
        mock_anthropic_module.Anthropic.assert_not_called()

    def test_skips_short_document(self, memory_store):
        """Document under the minimum word threshold should return empty list."""
        mock_anthropic_module = MagicMock()

        with patch("knowledge.feedback.anthropic", mock_anthropic_module):
            from knowledge.feedback import extract_and_store_findings
            findings = extract_and_store_findings("Too short.", "source_short", memory_store)

        assert findings == []
        mock_anthropic_module.Anthropic.assert_not_called()

    def test_handles_api_error_gracefully(self, memory_store):
        """API failure should return empty list without raising."""
        mock_anthropic_module = MagicMock()
        mock_client = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API down")

        document = " ".join(["word"] * 60)

        with patch("knowledge.feedback.anthropic", mock_anthropic_module):
            from knowledge.feedback import extract_and_store_findings
            findings = extract_and_store_findings(document, "source_error", memory_store)

        assert findings == []

    def test_caps_findings_at_five(self, memory_store):
        """Even if the model returns more than 5 bullets, only 5 are stored."""
        bullets = "\n".join(f"- Finding {i}" for i in range(8))
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=bullets)]

        mock_anthropic_module = MagicMock()
        mock_client = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_response

        document = " ".join(["word"] * 60)

        with patch("knowledge.feedback.anthropic", mock_anthropic_module):
            from knowledge.feedback import extract_and_store_findings
            findings = extract_and_store_findings(document, "source_many", memory_store)

        # All 8 parsed findings are returned...
        assert len(findings) == 8
        # ...but only 5 facts are stored (keys _finding_0 through _finding_4)
        all_facts = memory_store.search_facts("Finding")
        stored_keys = {f.key for f in all_facts}
        assert "source_many_finding_4" in stored_keys
        assert "source_many_finding_5" not in stored_keys

    def test_fact_metadata(self, memory_store):
        """Stored facts have correct category, source, and confidence."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="- Key project milestone reached")]

        mock_anthropic_module = MagicMock()
        mock_client = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_response

        document = " ".join(["word"] * 60)

        with patch("knowledge.feedback.anthropic", mock_anthropic_module):
            from knowledge.feedback import extract_and_store_findings
            extract_and_store_findings(document, "meta_test", memory_store)

        facts = memory_store.search_facts("milestone")
        assert len(facts) >= 1
        fact = facts[0]
        assert fact.category == "work"
        assert fact.source == "output_feedback:meta_test"
        assert fact.confidence == pytest.approx(0.7)
