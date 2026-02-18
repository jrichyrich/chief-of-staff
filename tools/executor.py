# tools/executor.py
"""Shared tool execution logic for memory, document, and agent tools."""
from typing import Any

from config import VALID_FACT_CATEGORIES
from documents.store import DocumentStore
from memory.models import Fact
from memory.store import MemoryStore


def execute_query_memory(
    memory_store: MemoryStore, query: str, category: str | None = None
) -> Any:
    """Query memory facts, optionally filtered by category."""
    if category == "location":
        locations = memory_store.list_locations()
        return [
            {"name": l.name, "address": l.address}
            for l in locations
            if query.lower() in (l.name or "").lower()
            or query.lower() in (l.address or "").lower()
        ]
    if category:
        facts = memory_store.get_facts_by_category(category)
        facts = [
            f
            for f in facts
            if query.lower() in f.value.lower() or query.lower() in f.key.lower()
        ]
    else:
        facts = memory_store.search_facts(query)
    return [{"category": f.category, "key": f.key, "value": f.value} for f in facts]


def execute_store_memory(
    memory_store: MemoryStore, category: str, key: str, value: str, source: str = "chief_of_staff"
) -> Any:
    """Store a fact in memory."""
    if category not in VALID_FACT_CATEGORIES:
        return {"error": f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_FACT_CATEGORIES))}"}
    fact = Fact(category=category, key=key, value=value, source=source)
    memory_store.store_fact(fact)
    return {"status": "stored", "key": key}


def execute_search_documents(
    document_store: DocumentStore, query: str, top_k: int = 5
) -> Any:
    """Semantic search over ingested documents."""
    results = document_store.search(query, top_k=top_k)
    return [
        {"text": r["text"], "source": r["metadata"].get("source", "unknown")}
        for r in results
    ]
