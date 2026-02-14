# tests/test_memory_models.py
from memory.models import Fact, Location


def test_fact_creation():
    fact = Fact(
        category="personal",
        key="name",
        value="Jason",
        confidence=1.0,
        source="chief_of_staff",
    )
    assert fact.category == "personal"
    assert fact.key == "name"
    assert fact.value == "Jason"
    assert fact.confidence == 1.0
    assert fact.source == "chief_of_staff"


def test_fact_defaults():
    fact = Fact(category="preference", key="color", value="blue")
    assert fact.confidence == 1.0
    assert fact.source is None
    assert fact.id is None


def test_location_creation():
    loc = Location(
        name="office",
        address="123 Main St",
        latitude=37.7749,
        longitude=-122.4194,
        notes='{"floor": 3}',
    )
    assert loc.name == "office"
    assert loc.address == "123 Main St"
    assert loc.latitude == 37.7749
