# tests/test_tool_executor.py
import pytest
from memory.store import MemoryStore
from memory.models import Fact, Location
from documents.store import DocumentStore
from tools.executor import (
    execute_query_memory,
    execute_store_memory,
    execute_search_documents,
)


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def doc_store(tmp_path):
    return DocumentStore(persist_dir=tmp_path / "chroma")


class TestExecuteQueryMemory:
    def test_search_all_facts(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        memory_store.store_fact(Fact(category="work", key="title", value="Engineer"))
        results = execute_query_memory(memory_store, "Jason")
        assert len(results) == 1
        assert results[0]["key"] == "name"
        assert results[0]["value"] == "Jason"

    def test_search_by_category(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        memory_store.store_fact(Fact(category="personal", key="hobby", value="coding"))
        memory_store.store_fact(Fact(category="work", key="name", value="Jason Inc"))
        results = execute_query_memory(memory_store, "Jason", category="personal")
        assert len(results) == 1
        assert results[0]["category"] == "personal"

    def test_search_locations(self, memory_store):
        memory_store.store_location(Location(name="office", address="123 Main St"))
        memory_store.store_location(Location(name="home", address="456 Oak Ave"))
        results = execute_query_memory(memory_store, "office", category="location")
        assert len(results) == 1
        assert results[0]["name"] == "office"

    def test_search_locations_by_address(self, memory_store):
        memory_store.store_location(Location(name="office", address="123 Main St"))
        results = execute_query_memory(memory_store, "Main St", category="location")
        assert len(results) == 1

    def test_search_no_results(self, memory_store):
        results = execute_query_memory(memory_store, "nonexistent")
        assert results == []

    def test_search_locations_no_results(self, memory_store):
        memory_store.store_location(Location(name="office", address="123 Main St"))
        results = execute_query_memory(memory_store, "nonexistent", category="location")
        assert results == []


class TestExecuteStoreMemory:
    def test_store_fact(self, memory_store):
        result = execute_store_memory(memory_store, "work", "project", "Jarvis")
        assert result == {"status": "stored", "key": "project"}
        fact = memory_store.get_fact("work", "project")
        assert fact is not None
        assert fact.value == "Jarvis"
        assert fact.source == "chief_of_staff"

    def test_store_fact_custom_source(self, memory_store):
        result = execute_store_memory(memory_store, "personal", "color", "blue", source="user")
        assert result["status"] == "stored"
        fact = memory_store.get_fact("personal", "color")
        assert fact.source == "user"

    def test_store_fact_overwrites(self, memory_store):
        execute_store_memory(memory_store, "personal", "name", "Jason")
        execute_store_memory(memory_store, "personal", "name", "Jay")
        fact = memory_store.get_fact("personal", "name")
        assert fact.value == "Jay"


class TestExecuteSearchDocuments:
    def test_search_returns_formatted_results(self, doc_store):
        doc_store.add_documents(
            texts=["Python is a programming language"],
            metadatas=[{"source": "docs/python.md"}],
            ids=["doc1"],
        )
        results = execute_search_documents(doc_store, "Python")
        assert len(results) >= 1
        assert "text" in results[0]
        assert "source" in results[0]
        assert results[0]["source"] == "docs/python.md"

    def test_search_empty_store(self, doc_store):
        results = execute_search_documents(doc_store, "anything")
        assert results == []

    def test_search_respects_top_k(self, doc_store):
        for i in range(5):
            doc_store.add_documents(
                texts=[f"Document number {i} about testing"],
                metadatas=[{"source": f"doc{i}.md"}],
                ids=[f"doc{i}"],
            )
        results = execute_search_documents(doc_store, "testing", top_k=2)
        assert len(results) == 2
