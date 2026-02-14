# tests/test_memory_store.py
import pytest
from memory.store import MemoryStore
from memory.models import AlertRule, Decision, Delegation, Fact, Location


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


class TestDecisions:
    def test_store_and_retrieve_decision(self, memory_store):
        decision = Decision(
            title="Adopt microservices",
            description="Move to microservices architecture",
            context="Monolith is hitting scale limits",
            decided_by="CTO",
            owner="Platform team",
            source="meeting",
        )
        result = memory_store.store_decision(decision)
        assert result is not None
        assert result.id is not None
        assert result.title == "Adopt microservices"
        assert result.decided_by == "CTO"
        assert result.created_at is not None

    def test_get_nonexistent_decision(self, memory_store):
        result = memory_store.get_decision(999)
        assert result is None

    def test_search_decisions_by_title(self, memory_store):
        memory_store.store_decision(Decision(title="Adopt microservices"))
        memory_store.store_decision(Decision(title="Switch to PostgreSQL"))
        results = memory_store.search_decisions("micro")
        assert len(results) == 1
        assert results[0].title == "Adopt microservices"

    def test_search_decisions_by_description(self, memory_store):
        memory_store.store_decision(Decision(title="DB Choice", description="Use PostgreSQL for analytics"))
        results = memory_store.search_decisions("PostgreSQL")
        assert len(results) == 1

    def test_search_decisions_by_tags(self, memory_store):
        memory_store.store_decision(Decision(title="Infra", tags="infrastructure,cloud"))
        results = memory_store.search_decisions("cloud")
        assert len(results) == 1

    def test_list_decisions_by_status(self, memory_store):
        memory_store.store_decision(Decision(title="Done decision", status="completed"))
        memory_store.store_decision(Decision(title="Pending decision", status="pending_execution"))
        memory_store.store_decision(Decision(title="Another pending", status="pending_execution"))
        results = memory_store.list_decisions_by_status("pending_execution")
        assert len(results) == 2

    def test_update_decision(self, memory_store):
        stored = memory_store.store_decision(Decision(title="Original", status="pending_execution"))
        updated = memory_store.update_decision(stored.id, status="completed", owner="Alice")
        assert updated.status == "completed"
        assert updated.owner == "Alice"
        assert updated.updated_at != stored.updated_at

    def test_delete_decision(self, memory_store):
        stored = memory_store.store_decision(Decision(title="To delete"))
        assert memory_store.delete_decision(stored.id) is True
        assert memory_store.get_decision(stored.id) is None

    def test_delete_nonexistent_decision(self, memory_store):
        assert memory_store.delete_decision(999) is False

    def test_multiple_decisions_no_unique_constraint(self, memory_store):
        memory_store.store_decision(Decision(title="Same title"))
        memory_store.store_decision(Decision(title="Same title"))
        results = memory_store.search_decisions("Same title")
        assert len(results) == 2


class TestDelegations:
    def test_store_and_retrieve_delegation(self, memory_store):
        delegation = Delegation(
            task="Write Q1 report",
            delegated_to="Alice",
            delegated_by="Jason",
            due_date="2026-02-28",
            priority="high",
        )
        result = memory_store.store_delegation(delegation)
        assert result is not None
        assert result.id is not None
        assert result.task == "Write Q1 report"
        assert result.delegated_to == "Alice"
        assert result.priority == "high"
        assert result.created_at is not None

    def test_get_nonexistent_delegation(self, memory_store):
        result = memory_store.get_delegation(999)
        assert result is None

    def test_list_delegations_all(self, memory_store):
        memory_store.store_delegation(Delegation(task="Task 1", delegated_to="Alice"))
        memory_store.store_delegation(Delegation(task="Task 2", delegated_to="Bob"))
        results = memory_store.list_delegations()
        assert len(results) == 2

    def test_list_delegations_by_status(self, memory_store):
        memory_store.store_delegation(Delegation(task="Active task", delegated_to="Alice", status="active"))
        memory_store.store_delegation(Delegation(task="Done task", delegated_to="Bob", status="completed"))
        results = memory_store.list_delegations(status="active")
        assert len(results) == 1
        assert results[0].task == "Active task"

    def test_list_delegations_by_person(self, memory_store):
        memory_store.store_delegation(Delegation(task="Task A", delegated_to="Alice"))
        memory_store.store_delegation(Delegation(task="Task B", delegated_to="Bob"))
        memory_store.store_delegation(Delegation(task="Task C", delegated_to="Alice"))
        results = memory_store.list_delegations(delegated_to="Alice")
        assert len(results) == 2

    def test_list_delegations_by_status_and_person(self, memory_store):
        memory_store.store_delegation(Delegation(task="T1", delegated_to="Alice", status="active"))
        memory_store.store_delegation(Delegation(task="T2", delegated_to="Alice", status="completed"))
        memory_store.store_delegation(Delegation(task="T3", delegated_to="Bob", status="active"))
        results = memory_store.list_delegations(status="active", delegated_to="Alice")
        assert len(results) == 1
        assert results[0].task == "T1"

    def test_list_overdue_delegations(self, memory_store):
        memory_store.store_delegation(Delegation(
            task="Overdue task", delegated_to="Alice", due_date="2020-01-01", status="active",
        ))
        memory_store.store_delegation(Delegation(
            task="Future task", delegated_to="Bob", due_date="2099-12-31", status="active",
        ))
        memory_store.store_delegation(Delegation(
            task="No due date", delegated_to="Charlie", status="active",
        ))
        memory_store.store_delegation(Delegation(
            task="Completed past", delegated_to="Dave", due_date="2020-01-01", status="completed",
        ))
        results = memory_store.list_overdue_delegations()
        assert len(results) == 1
        assert results[0].task == "Overdue task"

    def test_update_delegation(self, memory_store):
        stored = memory_store.store_delegation(Delegation(task="Original", delegated_to="Alice"))
        updated = memory_store.update_delegation(stored.id, status="completed", notes="All done")
        assert updated.status == "completed"
        assert updated.notes == "All done"
        assert updated.updated_at != stored.updated_at

    def test_delete_delegation(self, memory_store):
        stored = memory_store.store_delegation(Delegation(task="To delete", delegated_to="Alice"))
        assert memory_store.delete_delegation(stored.id) is True
        assert memory_store.get_delegation(stored.id) is None

    def test_delete_nonexistent_delegation(self, memory_store):
        assert memory_store.delete_delegation(999) is False

    def test_multiple_delegations_same_task(self, memory_store):
        memory_store.store_delegation(Delegation(task="Same task", delegated_to="Alice"))
        memory_store.store_delegation(Delegation(task="Same task", delegated_to="Bob"))
        results = memory_store.list_delegations()
        assert len(results) == 2


class TestAlertRules:
    def test_store_and_retrieve_alert_rule(self, memory_store):
        rule = AlertRule(
            name="overdue_check",
            description="Check for overdue delegations",
            alert_type="stale_delegation",
            condition='{"days_overdue": 3}',
        )
        result = memory_store.store_alert_rule(rule)
        assert result is not None
        assert result.id is not None
        assert result.name == "overdue_check"
        assert result.alert_type == "stale_delegation"
        assert result.enabled is True
        assert result.created_at is not None

    def test_get_nonexistent_alert_rule(self, memory_store):
        result = memory_store.get_alert_rule(999)
        assert result is None

    def test_upsert_alert_rule(self, memory_store):
        memory_store.store_alert_rule(AlertRule(
            name="test_rule", alert_type="deadline", description="Original",
        ))
        memory_store.store_alert_rule(AlertRule(
            name="test_rule", alert_type="deadline", description="Updated",
        ))
        rules = memory_store.list_alert_rules()
        assert len(rules) == 1
        assert rules[0].description == "Updated"

    def test_list_alert_rules_all(self, memory_store):
        memory_store.store_alert_rule(AlertRule(name="rule1", alert_type="deadline", enabled=True))
        memory_store.store_alert_rule(AlertRule(name="rule2", alert_type="custom", enabled=False))
        results = memory_store.list_alert_rules()
        assert len(results) == 2

    def test_list_alert_rules_enabled_only(self, memory_store):
        memory_store.store_alert_rule(AlertRule(name="enabled_rule", alert_type="deadline", enabled=True))
        memory_store.store_alert_rule(AlertRule(name="disabled_rule", alert_type="custom", enabled=False))
        results = memory_store.list_alert_rules(enabled_only=True)
        assert len(results) == 1
        assert results[0].name == "enabled_rule"

    def test_update_alert_rule(self, memory_store):
        stored = memory_store.store_alert_rule(AlertRule(name="rule", alert_type="deadline"))
        updated = memory_store.update_alert_rule(stored.id, enabled=False, description="Now disabled")
        assert updated.enabled is False
        assert updated.description == "Now disabled"

    def test_delete_alert_rule(self, memory_store):
        stored = memory_store.store_alert_rule(AlertRule(name="to_delete", alert_type="custom"))
        assert memory_store.delete_alert_rule(stored.id) is True
        assert memory_store.get_alert_rule(stored.id) is None

    def test_delete_nonexistent_alert_rule(self, memory_store):
        assert memory_store.delete_alert_rule(999) is False
