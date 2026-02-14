# tests/test_memory_store.py
import pytest
from memory.store import MemoryStore
from memory.models import Fact, Location


@pytest.fixture
def memory_store(tmp_path):
    db_path = tmp_path / "test_memory.db"
    store = MemoryStore(db_path)
    yield store
    store.close()


class TestFacts:
    def test_store_and_retrieve_fact(self, memory_store):
        fact = Fact(category="personal", key="name", value="Jason", source="test")
        memory_store.store_fact(fact)
        result = memory_store.get_fact("personal", "name")
        assert result is not None
        assert result.value == "Jason"
        assert result.source == "test"
        assert result.id is not None

    def test_get_nonexistent_fact(self, memory_store):
        result = memory_store.get_fact("personal", "nonexistent")
        assert result is None

    def test_update_fact_overwrites(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        memory_store.store_fact(Fact(category="personal", key="name", value="Jay"))
        result = memory_store.get_fact("personal", "name")
        assert result.value == "Jay"

    def test_get_facts_by_category(self, memory_store):
        memory_store.store_fact(Fact(category="preference", key="color", value="blue"))
        memory_store.store_fact(Fact(category="preference", key="food", value="sushi"))
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        results = memory_store.get_facts_by_category("preference")
        assert len(results) == 2

    def test_search_facts(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        memory_store.store_fact(Fact(category="work", key="title", value="Engineer"))
        results = memory_store.search_facts("Jason")
        assert len(results) == 1
        assert results[0].key == "name"


class TestLocations:
    def test_store_and_retrieve_location(self, memory_store):
        loc = Location(name="office", address="123 Main St", latitude=37.77, longitude=-122.41)
        memory_store.store_location(loc)
        result = memory_store.get_location("office")
        assert result is not None
        assert result.address == "123 Main St"

    def test_get_nonexistent_location(self, memory_store):
        result = memory_store.get_location("nowhere")
        assert result is None

    def test_list_locations(self, memory_store):
        memory_store.store_location(Location(name="home", address="456 Oak Ave"))
        memory_store.store_location(Location(name="office", address="123 Main St"))
        results = memory_store.list_locations()
        assert len(results) == 2
