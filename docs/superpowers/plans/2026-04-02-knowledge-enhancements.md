# Knowledge Layer Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three knowledge management enhancements to Jarvis — document summary compilation at ingest time, a knowledge linting scheduled task, and selective output feedback — inspired by Karpathy's LLM Knowledge Base pattern, adapted for Jarvis's operational intelligence use case.

**Architecture:** These enhancements layer on top of the existing SQLite + ChromaDB infrastructure with no architectural changes. Document summaries are stored as additional ChromaDB entries with `doc_type: "summary"` metadata. Knowledge linting runs as a new scheduled handler type that surfaces findings through the existing proactive suggestion engine. Output feedback extracts key findings from generated documents and stores them as facts.

**Tech Stack:** Python, SQLite, ChromaDB, Anthropic API (Haiku tier for summarization), existing scheduler/proactive infrastructure.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `knowledge/compiler.py` (create) | Document summary generation via Haiku LLM call |
| `knowledge/linter.py` (create) | Fact consistency checking, staleness detection, gap identification |
| `knowledge/feedback.py` (create) | Extract key findings from generated documents, store as facts |
| `documents/ingestion.py` (modify) | Hook summary generation into ingest pipeline |
| `documents/store.py` (modify) | Add `search_summaries()` method for summary-only retrieval |
| `scheduler/handlers.py` (modify) | Add `knowledge_lint` handler type |
| `memory/models.py` (modify) | Add `knowledge_lint` to `HandlerType` enum |
| `proactive/engine.py` (modify) | Add `_check_knowledge_lint_findings()` check |
| `mcp_tools/document_tools.py` (modify) | Wire summary search into `search_documents` |
| `tests/test_knowledge_compiler.py` (create) | Tests for summary generation |
| `tests/test_knowledge_linter.py` (create) | Tests for fact linting |
| `tests/test_knowledge_feedback.py` (create) | Tests for output feedback |

---

### Task 1: Document Summary Compilation — Core Module

**Files:**
- Create: `knowledge/__init__.py`
- Create: `knowledge/compiler.py`
- Test: `tests/test_knowledge_compiler.py`

- [ ] **Step 1: Create the knowledge package**

```bash
mkdir -p knowledge
```

- [ ] **Step 2: Write failing test for summary generation**

```python
# tests/test_knowledge_compiler.py
"""Tests for the knowledge compiler — document summary generation."""

import pytest
from unittest.mock import patch, MagicMock

from knowledge.compiler import generate_summary, compile_document_summary


class TestGenerateSummary:
    def test_returns_summary_string(self):
        """generate_summary calls Haiku and returns the text response."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="This document describes Python basics.")]

        with patch("knowledge.compiler.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = mock_response

            result = generate_summary("Python is a programming language. It was created by Guido van Rossum.")

        assert result == "This document describes Python basics."
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
        assert call_kwargs["max_tokens"] == 512

    def test_returns_none_on_empty_text(self):
        result = generate_summary("")
        assert result is None

    def test_returns_none_on_short_text(self):
        """Text under 50 words is too short to summarize."""
        result = generate_summary("Hello world")
        assert result is None

    def test_returns_none_on_api_error(self):
        with patch("knowledge.compiler.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.side_effect = Exception("API error")

            result = generate_summary("x " * 100)

        assert result is None


class TestCompileDocumentSummary:
    def test_stores_summary_in_chromadb(self):
        """compile_document_summary generates summary and upserts into document store."""
        mock_doc_store = MagicMock()
        text = "word " * 100
        source = "test_doc.md"
        file_hash = "abc123"

        with patch("knowledge.compiler.generate_summary", return_value="A summary of the document."):
            result = compile_document_summary(text, source, file_hash, mock_doc_store)

        assert result == "A summary of the document."
        mock_doc_store.add_documents.assert_called_once()
        call_args = mock_doc_store.add_documents.call_args
        assert call_args[1]["metadatas"][0]["doc_type"] == "summary"
        assert call_args[1]["metadatas"][0]["source"] == source
        assert call_args[1]["ids"] == [f"{file_hash}_summary"]

    def test_skips_when_summary_is_none(self):
        mock_doc_store = MagicMock()

        with patch("knowledge.compiler.generate_summary", return_value=None):
            result = compile_document_summary("short", "test.md", "abc", mock_doc_store)

        assert result is None
        mock_doc_store.add_documents.assert_not_called()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_knowledge_compiler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'knowledge.compiler'`

- [ ] **Step 4: Write the compiler module**

```python
# knowledge/__init__.py
```

```python
# knowledge/compiler.py
"""Document summary compilation via LLM.

Generates concise summaries of ingested documents using Haiku,
storing them as additional ChromaDB entries alongside raw chunks.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import anthropic

from config import MODEL_TIERS, ANTHROPIC_API_KEY

if TYPE_CHECKING:
    from documents.store import DocumentStore

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """Summarize this document in 2-4 sentences. Focus on:
- What the document is about (topic, purpose)
- Key facts, decisions, or conclusions
- Who/what is involved

Be concise and factual. Do not include meta-commentary like "This document discusses..."

Document text:
{text}"""

# Minimum word count to attempt summarization
_MIN_WORDS = 50

# Truncate input to avoid excessive token usage on very large documents
_MAX_INPUT_WORDS = 3000


def generate_summary(text: str) -> Optional[str]:
    """Generate a summary of the given text using Haiku.

    Returns the summary string, or None if the text is too short,
    empty, or the API call fails.
    """
    if not text or not text.strip():
        return None

    words = text.split()
    if len(words) < _MIN_WORDS:
        return None

    # Truncate very long documents to keep costs low
    truncated = " ".join(words[:_MAX_INPUT_WORDS])

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=MODEL_TIERS["haiku"],
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": _SUMMARY_PROMPT.format(text=truncated),
            }],
        )
        return response.content[0].text
    except Exception:
        logger.exception("Failed to generate document summary")
        return None


def compile_document_summary(
    text: str,
    source: str,
    file_hash: str,
    document_store: "DocumentStore",
) -> Optional[str]:
    """Generate a summary and store it in the document store.

    The summary is stored with doc_type="summary" metadata so it can be
    distinguished from raw chunks during retrieval.

    Args:
        text: Full document text to summarize.
        source: Source filename (e.g., "policy.md").
        file_hash: Content hash prefix used for chunk IDs.
        document_store: ChromaDB-backed document store.

    Returns:
        The generated summary text, or None if skipped.
    """
    summary = generate_summary(text)
    if summary is None:
        return None

    now = datetime.now(timezone.utc).isoformat()
    document_store.add_documents(
        texts=[summary],
        metadatas=[{
            "source": source,
            "doc_type": "summary",
            "chunk_index": -1,
            "created_at": now,
        }],
        ids=[f"{file_hash}_summary"],
    )
    logger.info("Stored summary for %s (%d chars)", source, len(summary))
    return summary
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_knowledge_compiler.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add knowledge/__init__.py knowledge/compiler.py tests/test_knowledge_compiler.py
git commit -m "feat: add knowledge compiler for document summary generation"
```

---

### Task 2: Wire Summary Compilation into Ingestion Pipeline

**Files:**
- Modify: `documents/ingestion.py:110-183` (ingest_path function)
- Modify: `documents/store.py:63-74` (add search_summaries method)
- Test: `tests/test_document_store.py` (add summary tests)

- [ ] **Step 1: Write failing test for summary-aware ingestion**

Add to `tests/test_document_store.py`:

```python
class TestSummarySearch:
    def test_search_summaries_only(self, doc_store):
        """search_summaries returns only doc_type=summary entries."""
        doc_store.add_documents(
            texts=["Raw chunk about Python"],
            metadatas=[{"source": "doc.md", "doc_type": "chunk", "chunk_index": 0}],
            ids=["hash_0"],
        )
        doc_store.add_documents(
            texts=["Summary: Python programming overview"],
            metadatas=[{"source": "doc.md", "doc_type": "summary", "chunk_index": -1}],
            ids=["hash_summary"],
        )
        results = doc_store.search_summaries("Python", top_k=5)
        assert len(results) == 1
        assert results[0]["metadata"]["doc_type"] == "summary"

    def test_search_summaries_empty(self, doc_store):
        results = doc_store.search_summaries("anything")
        assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_document_store.py::TestSummarySearch -v`
Expected: FAIL with `AttributeError: 'DocumentStore' object has no attribute 'search_summaries'`

- [ ] **Step 3: Add search_summaries to DocumentStore**

Add to `documents/store.py` after the existing `search` method (after line 74):

```python
    def search_summaries(self, query: str, top_k: int = 5) -> list[dict]:
        """Search only summary entries (doc_type=summary) in the collection."""
        if self.collection.count() == 0:
            return []
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where={"doc_type": "summary"},
        )
        if not results["documents"] or not results["documents"][0]:
            return []
        output = []
        for i in range(len(results["documents"][0])):
            output.append({
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else None,
            })
        return output
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_document_store.py::TestSummarySearch -v`
Expected: PASS

- [ ] **Step 5: Write failing test for ingestion with summary compilation**

Add to `tests/test_document_store.py`:

```python
from unittest.mock import patch

class TestIngestionWithSummary:
    def test_ingest_generates_summary_when_enabled(self, doc_store, tmp_path):
        """ingest_path calls compile_document_summary when KNOWLEDGE_COMPILE_ON_INGEST is True."""
        test_file = tmp_path / "test.md"
        test_file.write_text("word " * 100)  # Long enough to trigger summary

        with patch("documents.ingestion.COMPILE_ON_INGEST", True), \
             patch("documents.ingestion.compile_document_summary", return_value="A summary") as mock_compile:
            from documents.ingestion import ingest_path
            result = ingest_path(test_file, doc_store)

        assert "1 file(s)" in result
        mock_compile.assert_called_once()

    def test_ingest_skips_summary_when_disabled(self, doc_store, tmp_path):
        """ingest_path skips summary when COMPILE_ON_INGEST is False."""
        test_file = tmp_path / "test.md"
        test_file.write_text("word " * 100)

        with patch("documents.ingestion.COMPILE_ON_INGEST", False), \
             patch("documents.ingestion.compile_document_summary") as mock_compile:
            from documents.ingestion import ingest_path
            result = ingest_path(test_file, doc_store)

        mock_compile.assert_not_called()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_document_store.py::TestIngestionWithSummary -v`
Expected: FAIL with `AttributeError: module 'documents.ingestion' has no attribute 'COMPILE_ON_INGEST'`

- [ ] **Step 7: Modify ingestion.py to compile summaries**

Add to `documents/ingestion.py` after the imports (after line 12):

```python
# Feature flag: compile summaries at ingest time (requires Anthropic API key)
COMPILE_ON_INGEST = os.environ.get("KNOWLEDGE_COMPILE_ON_INGEST", "false").strip().lower() in {"1", "true", "yes"}
```

Then modify `ingest_path()` — add summary compilation after the `document_store.add_documents()` call. Replace lines 176-177:

```python
        document_store.add_documents(texts=texts, metadatas=metadatas, ids=ids)
        total_chunks += len(chunks)

        # Optionally compile a summary for the document
        if COMPILE_ON_INGEST:
            try:
                from knowledge.compiler import compile_document_summary
                compile_document_summary(text, str(file.name), file_hash, document_store)
            except Exception:
                logger.warning("Summary compilation failed for %s", file.name, exc_info=True)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_document_store.py -v`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
git add documents/ingestion.py documents/store.py tests/test_document_store.py
git commit -m "feat: wire summary compilation into document ingestion pipeline"
```

---

### Task 3: Enhance search_documents to Include Summaries

**Files:**
- Modify: `mcp_tools/document_tools.py:21-36` (search_documents tool)

- [ ] **Step 1: Write failing test**

Add to `tests/test_document_store.py`:

```python
class TestSearchWithSummaries:
    def test_search_documents_includes_summaries_flag(self, doc_store):
        """When include_summaries=True, summaries appear first in results."""
        doc_store.add_documents(
            texts=["Raw chunk about RBAC policies"],
            metadatas=[{"source": "rbac.md", "doc_type": "chunk", "chunk_index": 0}],
            ids=["hash_0"],
        )
        doc_store.add_documents(
            texts=["Summary: RBAC policy defines role-based access control rules."],
            metadatas=[{"source": "rbac.md", "doc_type": "summary", "chunk_index": -1}],
            ids=["hash_summary"],
        )
        # Standard search returns both
        results = doc_store.search("RBAC", top_k=5)
        assert len(results) == 2

        # Summary search returns only summaries
        summaries = doc_store.search_summaries("RBAC", top_k=5)
        assert len(summaries) == 1
        assert summaries[0]["metadata"]["doc_type"] == "summary"
```

- [ ] **Step 2: Run to verify it passes (validates plumbing)**

Run: `pytest tests/test_document_store.py::TestSearchWithSummaries -v`
Expected: PASS

- [ ] **Step 3: Update search_documents MCP tool to surface summaries**

In `mcp_tools/document_tools.py`, modify the `search_documents` function to accept an optional `include_summaries` parameter and return summaries alongside chunks:

Replace the search_documents function (lines 21-36):

```python
    @mcp.tool()
    @tool_errors("Document search error", expected=_EXPECTED)
    async def search_documents(query: str, top_k: int = 5, include_summaries: bool = True) -> str:
        """Semantic search over ingested documents. Returns the most relevant chunks.

        Args:
            query: Natural language search query
            top_k: Number of results to return (default 5)
            include_summaries: If True, also return document summaries when available (default True)
        """
        document_store = state.document_store
        results = _retry_on_transient(document_store.search, query, top_k=top_k)

        response = {}

        # Include summaries if available and requested
        if include_summaries:
            summaries = _retry_on_transient(document_store.search_summaries, query, top_k=3)
            if summaries:
                response["summaries"] = summaries

        if not results and not response.get("summaries"):
            return json.dumps({"message": "No documents found. Ingest documents first.", "results": []})

        response["results"] = results
        return json.dumps(response)
```

- [ ] **Step 4: Run full document test suite**

Run: `pytest tests/test_document_store.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_tools/document_tools.py tests/test_document_store.py
git commit -m "feat: surface document summaries in search_documents results"
```

---

### Task 4: Knowledge Linter — Core Module

**Files:**
- Create: `knowledge/linter.py`
- Test: `tests/test_knowledge_linter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_knowledge_linter.py
"""Tests for the knowledge linter — fact consistency and staleness checks."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from memory.models import Fact
from memory.store import MemoryStore
from knowledge.linter import KnowledgeLinter


@pytest.fixture
def linter(memory_store):
    return KnowledgeLinter(memory_store)


class TestStaleFactDetection:
    def test_no_facts_returns_empty(self, linter):
        findings = linter.check_stale_facts()
        assert findings == []

    def test_recent_facts_not_flagged(self, memory_store, linter):
        memory_store.store_fact(Fact(
            category="work", key="current_project",
            value="Jarvis enhancements", confidence=0.9,
        ))
        findings = linter.check_stale_facts()
        assert findings == []

    def test_old_low_confidence_facts_flagged(self, memory_store, linter):
        """Facts older than threshold with low confidence should be flagged."""
        memory_store.store_fact(Fact(
            category="work", key="old_project",
            value="Something from long ago", confidence=0.5,
        ))
        # Manually age the fact
        memory_store.conn.execute(
            "UPDATE facts SET updated_at = ? WHERE key = ?",
            ((datetime.now() - timedelta(days=200)).isoformat(), "old_project"),
        )
        memory_store.conn.commit()
        findings = linter.check_stale_facts(max_age_days=180, min_confidence=0.6)
        assert len(findings) == 1
        assert findings[0]["key"] == "old_project"
        assert findings[0]["issue"] == "stale"

    def test_pinned_facts_never_flagged(self, memory_store, linter):
        memory_store.store_fact(Fact(
            category="work", key="pinned_fact",
            value="Important permanent fact", confidence=0.5, pinned=True,
        ))
        memory_store.conn.execute(
            "UPDATE facts SET updated_at = ? WHERE key = ?",
            ((datetime.now() - timedelta(days=365)).isoformat(), "pinned_fact"),
        )
        memory_store.conn.commit()
        findings = linter.check_stale_facts(max_age_days=180, min_confidence=0.6)
        assert findings == []


class TestDuplicateDetection:
    def test_no_duplicates(self, memory_store, linter):
        memory_store.store_fact(Fact(
            category="work", key="project_a", value="Building a widget", confidence=0.9,
        ))
        memory_store.store_fact(Fact(
            category="personal", key="hobby", value="Playing guitar", confidence=0.8,
        ))
        findings = linter.check_near_duplicates()
        assert findings == []

    def test_detects_near_duplicates(self, memory_store, linter):
        memory_store.store_fact(Fact(
            category="work", key="project_status",
            value="The RBAC project is on track for Q2 delivery", confidence=0.9,
        ))
        memory_store.store_fact(Fact(
            category="work", key="rbac_update",
            value="RBAC project is on track for Q2 delivery date", confidence=0.8,
        ))
        findings = linter.check_near_duplicates(similarity_threshold=0.7)
        assert len(findings) == 1
        assert findings[0]["issue"] == "near_duplicate"


class TestRunAll:
    def test_run_all_combines_findings(self, linter):
        """run_all returns combined findings from all checks."""
        findings = linter.run_all()
        assert isinstance(findings, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_knowledge_linter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'knowledge.linter'`

- [ ] **Step 3: Write the linter module**

```python
# knowledge/linter.py
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

    def check_stale_facts(
        self,
        max_age_days: int = 180,
        min_confidence: float = 0.6,
    ) -> list[dict]:
        """Find facts that are old AND low-confidence (likely outdated).

        Pinned facts are always excluded. High-confidence facts are excluded
        even if old (the user explicitly set high confidence).
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

    def check_near_duplicates(
        self,
        similarity_threshold: float = 0.7,
    ) -> list[dict]:
        """Find fact pairs with high word overlap (likely duplicates).

        Compares all facts within the same category using Jaccard similarity.
        """
        rows = self.memory_store.conn.execute(
            "SELECT * FROM facts ORDER BY category, key"
        ).fetchall()

        # Group by category
        by_category: dict[str, list] = {}
        for row in rows:
            cat = row["category"]
            by_category.setdefault(cat, []).append(row)

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

    def run_all(
        self,
        max_age_days: int = 180,
        min_confidence: float = 0.6,
        similarity_threshold: float = 0.7,
    ) -> list[dict]:
        """Run all lint checks and return combined findings."""
        findings = []
        findings.extend(self.check_stale_facts(max_age_days, min_confidence))
        findings.extend(self.check_near_duplicates(similarity_threshold))
        return findings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_knowledge_linter.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/linter.py tests/test_knowledge_linter.py
git commit -m "feat: add knowledge linter for fact staleness and duplicate detection"
```

---

### Task 5: Wire Knowledge Lint into Scheduler

**Files:**
- Modify: `memory/models.py:57-65` (add HandlerType)
- Modify: `scheduler/handlers.py:244-271` (add handler)
- Test: `tests/test_knowledge_linter.py` (add handler test)

- [ ] **Step 1: Write failing test for the handler**

Add to `tests/test_knowledge_linter.py`:

```python
import json

class TestKnowledgeLintHandler:
    def test_handler_returns_findings(self, memory_store):
        """The knowledge_lint handler type should run the linter and return findings JSON."""
        from scheduler.handlers import execute_handler
        result_json = execute_handler("knowledge_lint", "{}", memory_store=memory_store)
        result = json.loads(result_json)
        assert result["status"] == "ok"
        assert result["handler"] == "knowledge_lint"
        assert "findings_count" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_knowledge_linter.py::TestKnowledgeLintHandler -v`
Expected: FAIL — handler type not recognized, returns "skipped"

- [ ] **Step 3: Add knowledge_lint to HandlerType enum**

In `memory/models.py`, add to the `HandlerType` class (after line 65, before the blank line):

```python
    knowledge_lint = "knowledge_lint"
```

- [ ] **Step 4: Add handler function to scheduler/handlers.py**

Add before the `execute_handler` function (before line 244):

```python
def _run_knowledge_lint_handler(memory_store) -> str:
    """Run the knowledge linter to check fact consistency."""
    try:
        from knowledge.linter import KnowledgeLinter

        linter = KnowledgeLinter(memory_store)
        findings = linter.run_all()
        return json.dumps({
            "status": "ok",
            "handler": "knowledge_lint",
            "findings_count": len(findings),
            "findings": findings[:20],  # Cap output size
        })
    except Exception as e:
        logger.error("Knowledge lint handler failed: %s", e)
        return json.dumps({"status": "error", "handler": "knowledge_lint", "error": str(e)})
```

Add to the `execute_handler` dispatch (after the `morning_brief` case, before `custom`):

```python
    elif handler_type == HandlerType.knowledge_lint:
        return _run_knowledge_lint_handler(memory_store)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_knowledge_linter.py::TestKnowledgeLintHandler -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add memory/models.py scheduler/handlers.py tests/test_knowledge_linter.py
git commit -m "feat: wire knowledge lint handler into scheduler"
```

---

### Task 6: Wire Lint Findings into Proactive Suggestions

**Files:**
- Modify: `proactive/engine.py:38-52` (add lint check to generate_suggestions)
- Test: `tests/test_proactive_engine.py` (add lint suggestion test)

- [ ] **Step 1: Write failing test**

Add to `tests/test_proactive_engine.py`:

```python
class TestCheckKnowledgeLintFindings:
    def test_no_findings_returns_empty(self, engine):
        result = engine._check_knowledge_lint_findings()
        assert result == []

    def test_stale_facts_surface_as_suggestions(self, memory_store, engine):
        """Stale low-confidence facts should appear as proactive suggestions."""
        from datetime import datetime, timedelta
        from memory.models import Fact

        memory_store.store_fact(Fact(
            category="work", key="old_info",
            value="Some outdated information", confidence=0.4,
        ))
        memory_store.conn.execute(
            "UPDATE facts SET updated_at = ? WHERE key = ?",
            ((datetime.now() - timedelta(days=200)).isoformat(), "old_info"),
        )
        memory_store.conn.commit()

        result = engine._check_knowledge_lint_findings()
        assert len(result) >= 1
        assert result[0].category == "knowledge"
        assert result[0].priority == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_proactive_engine.py::TestCheckKnowledgeLintFindings -v`
Expected: FAIL with `AttributeError: 'ProactiveSuggestionEngine' object has no attribute '_check_knowledge_lint_findings'`

- [ ] **Step 3: Add lint check to ProactiveSuggestionEngine**

In `proactive/engine.py`, add this method to the class (before `_check_stale_documents`):

```python
    def _check_knowledge_lint_findings(self) -> list[Suggestion]:
        """Surface knowledge linter findings as low-priority suggestions."""
        try:
            from knowledge.linter import KnowledgeLinter
            linter = KnowledgeLinter(self.memory_store)
            findings = linter.run_all()
        except Exception:
            logger.debug("Knowledge lint check failed", exc_info=True)
            return []

        results = []
        for f in findings[:5]:  # Cap at 5 to avoid suggestion overload
            results.append(Suggestion(
                category="knowledge",
                priority="low",
                title=f"Knowledge issue: {f['issue']} — {f.get('key', f.get('fact_a', {}).get('key', 'unknown'))}",
                description=f.get("suggestion", str(f)),
                action="query_memory",
            ))
        return results
```

Add the call to `generate_suggestions()` — in the method body (after `_check_session_brain_items` call, before `_check_stale_documents`):

```python
        suggestions.extend(self._check_knowledge_lint_findings())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_proactive_engine.py::TestCheckKnowledgeLintFindings -v`
Expected: PASS

- [ ] **Step 5: Run full proactive engine test suite**

Run: `pytest tests/test_proactive_engine.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add proactive/engine.py tests/test_proactive_engine.py
git commit -m "feat: surface knowledge lint findings in proactive suggestions"
```

---

### Task 7: Output Feedback — Extract Findings from Generated Documents

**Files:**
- Create: `knowledge/feedback.py`
- Test: `tests/test_knowledge_feedback.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_knowledge_feedback.py
"""Tests for knowledge feedback — extracting findings from generated documents."""

import pytest
from unittest.mock import patch, MagicMock

from memory.models import Fact
from memory.store import MemoryStore
from knowledge.feedback import extract_and_store_findings


@pytest.fixture
def mock_haiku_response():
    """Helper to create a mock Anthropic response."""
    def _make(text):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=text)]
        return mock_response
    return _make


class TestExtractAndStoreFindings:
    def test_extracts_findings_and_stores_as_facts(self, memory_store, mock_haiku_response):
        document_text = """# Weekly CIO Brief - 2026-04-01

## Key Wins
- RBAC migration completed ahead of schedule
- SentinelOne deployment reached 98% coverage

## On Your Radar
- PST incident still unresolved, blocking CompHealth Allied
"""
        # Mock the LLM to return structured findings
        llm_output = """- RBAC migration completed ahead of Q2 schedule
- SentinelOne endpoint coverage reached 98%
- PST incident remains unresolved, blocking CompHealth Allied"""

        with patch("knowledge.feedback.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = mock_haiku_response(llm_output)

            findings = extract_and_store_findings(
                document_text,
                source="weekly_cio_brief_2026-04-01",
                memory_store=memory_store,
            )

        assert len(findings) == 3
        # Verify facts were stored
        stored = memory_store.search_facts("RBAC")
        assert len(stored) >= 1

    def test_skips_empty_document(self, memory_store):
        findings = extract_and_store_findings("", source="empty", memory_store=memory_store)
        assert findings == []

    def test_handles_api_error_gracefully(self, memory_store):
        with patch("knowledge.feedback.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.side_effect = Exception("API down")

            findings = extract_and_store_findings(
                "Some document content " * 50,
                source="test",
                memory_store=memory_store,
            )

        assert findings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_knowledge_feedback.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'knowledge.feedback'`

- [ ] **Step 3: Write the feedback module**

```python
# knowledge/feedback.py
"""Output feedback — extract key findings from generated documents and store as facts.

When Jarvis generates a document (weekly brief, analysis, meeting prep),
this module extracts the 3-5 most important findings and stores them as
facts so they persist in the knowledge base for future queries.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import anthropic

from config import MODEL_TIERS, ANTHROPIC_API_KEY

if TYPE_CHECKING:
    from memory.store import MemoryStore
    from memory.models import Fact

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """Extract the 3-5 most important findings, decisions, or status updates from this document.
Return them as a simple bulleted list (one bullet per finding).
Each bullet should be a single, self-contained sentence.
Focus on facts that would be useful to recall in future conversations.
Do NOT include meta-commentary or formatting instructions.

Document:
{text}"""

_MIN_WORDS = 50
_MAX_INPUT_WORDS = 4000


def extract_and_store_findings(
    document_text: str,
    source: str,
    memory_store: "MemoryStore",
) -> list[str]:
    """Extract key findings from a document and store them as facts.

    Args:
        document_text: The full text of the generated document.
        source: Identifier for the source (e.g., "weekly_cio_brief_2026-04-01").
        memory_store: MemoryStore instance for fact storage.

    Returns:
        List of extracted finding strings, or empty list on failure.
    """
    if not document_text or len(document_text.split()) < _MIN_WORDS:
        return []

    truncated = " ".join(document_text.split()[:_MAX_INPUT_WORDS])

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=MODEL_TIERS["haiku"],
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": _EXTRACT_PROMPT.format(text=truncated),
            }],
        )
        raw_output = response.content[0].text
    except Exception:
        logger.exception("Failed to extract findings from document")
        return []

    # Parse bullet points
    findings = []
    for line in raw_output.strip().splitlines():
        line = line.strip().lstrip("-•*").strip()
        if line:
            findings.append(line)

    # Store each finding as a fact
    from memory.models import Fact

    now = datetime.now().isoformat()
    for i, finding in enumerate(findings[:5]):  # Cap at 5
        fact = Fact(
            category="work",
            key=f"{source}_finding_{i}",
            value=finding,
            confidence=0.7,
            source=f"output_feedback:{source}",
        )
        try:
            memory_store.store_fact(fact)
        except Exception:
            logger.warning("Failed to store finding %d from %s", i, source, exc_info=True)

    return findings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_knowledge_feedback.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/feedback.py tests/test_knowledge_feedback.py
git commit -m "feat: add output feedback to extract findings and store as facts"
```

---

### Task 8: Add Config Flags and Documentation

**Files:**
- Modify: `config.py` (add feature flags)

- [ ] **Step 1: Add configuration to config.py**

Add after the `PROACTIVE_ACTION_CATEGORIES` block (after line 83):

```python
# Knowledge enhancement settings
KNOWLEDGE_COMPILE_ON_INGEST = os.environ.get(
    "KNOWLEDGE_COMPILE_ON_INGEST", "false"
).strip().lower() in {"1", "true", "yes"}
KNOWLEDGE_LINT_MAX_AGE_DAYS = int(os.environ.get("KNOWLEDGE_LINT_MAX_AGE_DAYS", "180"))
KNOWLEDGE_LINT_MIN_CONFIDENCE = float(os.environ.get("KNOWLEDGE_LINT_MIN_CONFIDENCE", "0.6"))
KNOWLEDGE_LINT_SIMILARITY_THRESHOLD = float(os.environ.get("KNOWLEDGE_LINT_SIMILARITY_THRESHOLD", "0.7"))
KNOWLEDGE_FEEDBACK_ENABLED = os.environ.get(
    "KNOWLEDGE_FEEDBACK_ENABLED", "false"
).strip().lower() in {"1", "true", "yes"}
```

- [ ] **Step 2: Update ingestion.py to use config instead of local env check**

In `documents/ingestion.py`, replace the local `COMPILE_ON_INGEST` definition with an import:

```python
from config import KNOWLEDGE_COMPILE_ON_INGEST as COMPILE_ON_INGEST
```

- [ ] **Step 3: Run all knowledge tests to confirm nothing broke**

Run: `pytest tests/test_knowledge_compiler.py tests/test_knowledge_linter.py tests/test_knowledge_feedback.py tests/test_document_store.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add config.py documents/ingestion.py
git commit -m "feat: add config flags for knowledge enhancements"
```

---

### Task 9: Integration Smoke Test

**Files:**
- Create: `tests/test_knowledge_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_knowledge_integration.py
"""Integration tests for the knowledge enhancement pipeline."""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from memory.models import Fact, ScheduledTask
from memory.store import MemoryStore
from documents.store import DocumentStore


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
        assert len(all_results) >= 2  # At least one chunk + one summary

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

        # Should be queryable
        results = memory_store.search_facts("RBAC")
        assert any("RBAC" in f.value for f in results)
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_knowledge_integration.py -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Run full test suite to confirm no regressions**

Run: `pytest --tb=short -q`
Expected: All existing tests PASS, no regressions

- [ ] **Step 4: Commit**

```bash
git add tests/test_knowledge_integration.py
git commit -m "test: add integration tests for knowledge enhancement pipeline"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Document summary compilation at ingest time (Tasks 1-3)
- [x] Knowledge linting as scheduled handler (Tasks 4-6)
- [x] Selective output feedback (Task 7)
- [x] Config flags for all features (Task 8)
- [x] Integration tests (Task 9)

**Placeholder scan:** No TBD/TODO/placeholders — all code blocks are complete.

**Type consistency:** `compile_document_summary`, `KnowledgeLinter`, `extract_and_store_findings` — names consistent across all tasks. `HandlerType.knowledge_lint` used consistently in models and handlers.
