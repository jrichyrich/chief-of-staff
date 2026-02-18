# tests/test_tools_lifecycle.py
import json
from datetime import date, timedelta

import pytest

from memory.models import AlertRule, Decision, Delegation
from memory.store import MemoryStore
from tools.lifecycle import (
    create_delegation as add_delegation,
    check_alerts,
    check_overdue_delegations,
    create_alert_rule,
    delete_decision,
    delete_delegation,
    dismiss_alert,
    list_alert_rules,
    list_delegations,
    list_pending_decisions,
    create_decision as log_decision,
    search_decisions,
    update_decision,
    update_delegation,
)


@pytest.fixture
def memory_store(tmp_path):
    db_path = tmp_path / "test_lifecycle.db"
    store = MemoryStore(db_path)
    yield store
    store.close()


class TestDecisionLifecycle:
    def test_log_decision_minimal(self, memory_store):
        result = log_decision(memory_store, title="Adopt microservices")
        assert result["status"] == "logged"
        assert result["id"] is not None
        assert result["title"] == "Adopt microservices"
        assert result["decision_status"] == "pending_execution"

    def test_log_decision_with_all_fields(self, memory_store):
        result = log_decision(
            memory_store,
            title="Switch to PostgreSQL",
            description="Migration from MySQL",
            context="Performance issues with current DB",
            decided_by="CTO",
            owner="Platform team",
            status="executed",
            follow_up_date="2026-03-01",
            tags="database,infrastructure",
            source="architecture meeting",
        )
        assert result["status"] == "logged"
        assert result["decision_status"] == "executed"

        stored = memory_store.get_decision(result["id"])
        assert stored.title == "Switch to PostgreSQL"
        assert stored.description == "Migration from MySQL"
        assert stored.context == "Performance issues with current DB"
        assert stored.decided_by == "CTO"
        assert stored.owner == "Platform team"
        assert stored.follow_up_date == "2026-03-01"
        assert stored.tags == "database,infrastructure"
        assert stored.source == "architecture meeting"

    def test_log_decision_with_tags(self, memory_store):
        result = log_decision(
            memory_store,
            title="Tagged decision",
            tags="urgent,security",
        )
        stored = memory_store.get_decision(result["id"])
        assert stored.tags == "urgent,security"

    def test_search_decisions_by_query(self, memory_store):
        log_decision(memory_store, title="Adopt microservices")
        log_decision(memory_store, title="Switch to PostgreSQL")
        log_decision(memory_store, title="Implement caching")

        result = search_decisions(memory_store, query="micro")
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Adopt microservices"

    def test_search_decisions_by_status(self, memory_store):
        log_decision(memory_store, title="Done", status="executed")
        log_decision(memory_store, title="Pending 1", status="pending_execution")
        log_decision(memory_store, title="Pending 2", status="pending_execution")

        result = search_decisions(memory_store, status="pending_execution")
        assert len(result["results"]) == 2

    def test_search_decisions_by_query_and_status(self, memory_store):
        log_decision(memory_store, title="Microservices done", status="executed")
        log_decision(memory_store, title="Microservices pending", status="pending_execution")
        log_decision(memory_store, title="Database pending", status="pending_execution")

        result = search_decisions(memory_store, query="micro", status="pending_execution")
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Microservices pending"

    def test_search_decisions_empty_results(self, memory_store):
        log_decision(memory_store, title="Something")

        result = search_decisions(memory_store, query="nonexistent")
        assert result["message"] == "No decisions found."
        assert result["results"] == []

    def test_search_decisions_by_tags(self, memory_store):
        log_decision(memory_store, title="Decision 1", tags="infrastructure")
        log_decision(memory_store, title="Decision 2", tags="security")

        result = search_decisions(memory_store, query="security")
        assert len(result["results"]) == 1

    def test_update_decision_status(self, memory_store):
        logged = log_decision(memory_store, title="Original")
        decision_id = logged["id"]

        result = update_decision(memory_store, decision_id=decision_id, status="executed")
        assert result["status"] == "updated"
        assert result["decision_status"] == "executed"

        stored = memory_store.get_decision(decision_id)
        assert stored.status == "executed"

    def test_update_decision_with_notes(self, memory_store):
        logged = log_decision(memory_store, title="Original", description="Initial desc")
        decision_id = logged["id"]

        result = update_decision(memory_store, decision_id=decision_id, notes="Follow-up note")
        assert result["status"] == "updated"

        stored = memory_store.get_decision(decision_id)
        assert "[Update] Follow-up note" in stored.description

    def test_update_decision_with_status_and_notes(self, memory_store):
        logged = log_decision(memory_store, title="Test")
        decision_id = logged["id"]

        result = update_decision(
            memory_store,
            decision_id=decision_id,
            status="deferred",
            notes="Need more analysis",
        )
        assert result["decision_status"] == "deferred"

        stored = memory_store.get_decision(decision_id)
        assert stored.status == "deferred"
        assert "Need more analysis" in stored.description

    def test_update_decision_not_found(self, memory_store):
        result = update_decision(memory_store, decision_id=999, status="executed")
        assert "error" in result
        assert "Decision 999 not found" in result["error"]

    def test_update_decision_no_fields(self, memory_store):
        logged = log_decision(memory_store, title="Test")
        decision_id = logged["id"]

        result = update_decision(memory_store, decision_id=decision_id)
        assert "error" in result
        assert "No fields to update" in result["error"]

    def test_list_pending_decisions(self, memory_store):
        log_decision(memory_store, title="Pending 1", status="pending_execution")
        log_decision(memory_store, title="Executed", status="executed")
        log_decision(memory_store, title="Pending 2", status="pending_execution")

        result = list_pending_decisions(memory_store)
        assert len(result["results"]) == 2

    def test_list_pending_decisions_empty(self, memory_store):
        log_decision(memory_store, title="Executed", status="executed")

        result = list_pending_decisions(memory_store)
        assert result["message"] == "No pending decisions."
        assert result["results"] == []

    def test_delete_decision_success(self, memory_store):
        logged = log_decision(memory_store, title="To delete")
        decision_id = logged["id"]

        result = delete_decision(memory_store, decision_id=decision_id)
        assert result["status"] == "deleted"
        assert result["id"] == decision_id

        assert memory_store.get_decision(decision_id) is None

    def test_delete_decision_not_found(self, memory_store):
        result = delete_decision(memory_store, decision_id=999)
        assert "error" in result
        assert "Decision 999 not found" in result["error"]


class TestDelegationLifecycle:
    def test_add_delegation_minimal(self, memory_store):
        result = add_delegation(
            memory_store,
            task="Write Q1 report",
            delegated_to="Alice",
        )
        assert result["status"] == "created"
        assert result["id"] is not None
        assert result["task"] == "Write Q1 report"
        assert result["delegated_to"] == "Alice"
        assert result["due_date"] is None

    def test_add_delegation_with_all_fields(self, memory_store):
        result = add_delegation(
            memory_store,
            task="Review PRs",
            delegated_to="Bob",
            description="High priority PRs for release",
            due_date="2026-02-28",
            priority="high",
            source="standup meeting",
        )
        assert result["status"] == "created"
        assert result["due_date"] == "2026-02-28"

        stored = memory_store.get_delegation(result["id"])
        assert stored.task == "Review PRs"
        assert stored.delegated_to == "Bob"
        assert stored.description == "High priority PRs for release"
        assert stored.due_date == "2026-02-28"
        assert stored.priority == "high"
        assert stored.source == "standup meeting"

    def test_add_delegation_priorities(self, memory_store):
        for priority in ["low", "medium", "high", "critical"]:
            result = add_delegation(
                memory_store,
                task=f"Task {priority}",
                delegated_to="Alice",
                priority=priority,
            )
            stored = memory_store.get_delegation(result["id"])
            assert stored.priority == priority

    def test_list_delegations_all(self, memory_store):
        add_delegation(memory_store, task="Task 1", delegated_to="Alice")
        add_delegation(memory_store, task="Task 2", delegated_to="Bob")
        add_delegation(memory_store, task="Task 3", delegated_to="Charlie")

        result = list_delegations(memory_store)
        assert len(result["results"]) == 3

    def test_list_delegations_by_status(self, memory_store):
        d1 = add_delegation(memory_store, task="Active", delegated_to="Alice")
        d2 = add_delegation(memory_store, task="Completed", delegated_to="Bob")
        memory_store.update_delegation(d2["id"], status="completed")

        result = list_delegations(memory_store, status="active")
        assert len(result["results"]) == 1
        assert result["results"][0]["task"] == "Active"

    def test_list_delegations_by_delegated_to(self, memory_store):
        add_delegation(memory_store, task="Task A", delegated_to="Alice")
        add_delegation(memory_store, task="Task B", delegated_to="Bob")
        add_delegation(memory_store, task="Task C", delegated_to="Alice")

        result = list_delegations(memory_store, delegated_to="Alice")
        assert len(result["results"]) == 2

    def test_list_delegations_empty(self, memory_store):
        result = list_delegations(memory_store)
        assert result["message"] == "No delegations found."
        assert result["results"] == []

    def test_update_delegation_status(self, memory_store):
        created = add_delegation(memory_store, task="Test", delegated_to="Alice")
        delegation_id = created["id"]

        result = update_delegation(memory_store, delegation_id=delegation_id, status="completed")
        assert result["status"] == "updated"
        assert result["delegation_status"] == "completed"

        stored = memory_store.get_delegation(delegation_id)
        assert stored.status == "completed"

    def test_update_delegation_with_notes(self, memory_store):
        created = add_delegation(memory_store, task="Test", delegated_to="Alice")
        delegation_id = created["id"]

        result = update_delegation(memory_store, delegation_id=delegation_id, notes="Progress note")
        assert result["status"] == "updated"

        stored = memory_store.get_delegation(delegation_id)
        assert "Progress note" in stored.notes

    def test_update_delegation_not_found(self, memory_store):
        result = update_delegation(memory_store, delegation_id=999, status="completed")
        assert "error" in result
        assert "Delegation 999 not found" in result["error"]

    def test_update_delegation_no_fields(self, memory_store):
        created = add_delegation(memory_store, task="Test", delegated_to="Alice")
        delegation_id = created["id"]

        result = update_delegation(memory_store, delegation_id=delegation_id)
        assert "error" in result
        assert "No fields to update" in result["error"]

    def test_check_overdue_delegations(self, memory_store):
        past_date = (date.today() - timedelta(days=7)).isoformat()
        future_date = (date.today() + timedelta(days=7)).isoformat()

        add_delegation(
            memory_store,
            task="Overdue task",
            delegated_to="Alice",
            due_date=past_date,
        )
        add_delegation(
            memory_store,
            task="Future task",
            delegated_to="Bob",
            due_date=future_date,
        )
        add_delegation(
            memory_store,
            task="No due date",
            delegated_to="Charlie",
        )

        result = check_overdue_delegations(memory_store)
        assert len(result["results"]) == 1
        assert result["results"][0]["task"] == "Overdue task"
        assert result["results"][0]["delegated_to"] == "Alice"

    def test_check_overdue_delegations_empty(self, memory_store):
        future_date = (date.today() + timedelta(days=7)).isoformat()
        add_delegation(
            memory_store,
            task="Future task",
            delegated_to="Alice",
            due_date=future_date,
        )

        result = check_overdue_delegations(memory_store)
        assert result["message"] == "No overdue delegations."
        assert result["results"] == []

    def test_delete_delegation_success(self, memory_store):
        created = add_delegation(memory_store, task="To delete", delegated_to="Alice")
        delegation_id = created["id"]

        result = delete_delegation(memory_store, delegation_id=delegation_id)
        assert result["status"] == "deleted"
        assert result["id"] == delegation_id

        assert memory_store.get_delegation(delegation_id) is None

    def test_delete_delegation_not_found(self, memory_store):
        result = delete_delegation(memory_store, delegation_id=999)
        assert "error" in result
        assert "Delegation 999 not found" in result["error"]


class TestAlertRuleLifecycle:
    def test_create_alert_rule_minimal(self, memory_store):
        result = create_alert_rule(
            memory_store,
            name="test_alert",
            alert_type="overdue_delegation",
        )
        assert result["status"] == "created"
        assert result["id"] is not None
        assert result["name"] == "test_alert"
        assert result["alert_type"] == "overdue_delegation"
        assert result["enabled"] is True

    def test_create_alert_rule_with_all_fields(self, memory_store):
        condition = json.dumps({"days_overdue": 5})
        result = create_alert_rule(
            memory_store,
            name="overdue_check",
            alert_type="overdue_delegation",
            description="Check for tasks overdue by 5+ days",
            condition=condition,
            enabled=True,
        )
        assert result["status"] == "created"

        stored = memory_store.get_alert_rule(result["id"])
        assert stored.name == "overdue_check"
        assert stored.description == "Check for tasks overdue by 5+ days"
        assert stored.condition == condition
        assert stored.enabled is True

    def test_create_alert_rule_disabled(self, memory_store):
        result = create_alert_rule(
            memory_store,
            name="disabled_alert",
            alert_type="custom",
            enabled=False,
        )
        assert result["enabled"] is False

        stored = memory_store.get_alert_rule(result["id"])
        assert stored.enabled is False

    def test_list_alert_rules_all(self, memory_store):
        create_alert_rule(memory_store, name="rule1", alert_type="deadline", enabled=True)
        create_alert_rule(memory_store, name="rule2", alert_type="custom", enabled=False)

        result = list_alert_rules(memory_store)
        assert len(result["results"]) == 2

    def test_list_alert_rules_enabled_only(self, memory_store):
        create_alert_rule(memory_store, name="enabled", alert_type="deadline", enabled=True)
        create_alert_rule(memory_store, name="disabled", alert_type="custom", enabled=False)

        result = list_alert_rules(memory_store, enabled_only=True)
        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "enabled"

    def test_list_alert_rules_empty(self, memory_store):
        result = list_alert_rules(memory_store)
        assert result["message"] == "No alert rules configured."
        assert result["results"] == []

    def test_dismiss_alert(self, memory_store):
        created = create_alert_rule(
            memory_store,
            name="to_dismiss",
            alert_type="custom",
            enabled=True,
        )
        rule_id = created["id"]

        result = dismiss_alert(memory_store, rule_id=rule_id)
        assert result["status"] == "dismissed"
        assert result["enabled"] is False

        stored = memory_store.get_alert_rule(rule_id)
        assert stored.enabled is False

    def test_dismiss_alert_not_found(self, memory_store):
        result = dismiss_alert(memory_store, rule_id=999)
        assert "error" in result
        assert "Alert rule 999 not found" in result["error"]


class TestCheckAlerts:
    def test_check_alerts_overdue_delegations(self, memory_store):
        past_date = (date.today() - timedelta(days=7)).isoformat()
        add_delegation(
            memory_store,
            task="Overdue task",
            delegated_to="Alice",
            due_date=past_date,
        )

        result = check_alerts(memory_store)
        assert result["total_alerts"] >= 1
        assert len(result["alerts"]["overdue_delegations"]) == 1
        assert result["alerts"]["overdue_delegations"][0]["task"] == "Overdue task"

    def test_check_alerts_stale_decisions(self, memory_store):
        # Store a decision with created_at in the past
        old_date = (date.today() - timedelta(days=10)).isoformat()
        decision = Decision(
            title="Stale decision",
            status="pending_execution",
        )
        stored = memory_store.store_decision(decision)
        # Manually update created_at to simulate old decision
        memory_store.conn.execute(
            "UPDATE decisions SET created_at=? WHERE id=?",
            (old_date, stored.id),
        )
        memory_store.conn.commit()

        result = check_alerts(memory_store)
        assert result["total_alerts"] >= 1
        assert len(result["alerts"]["stale_decisions"]) == 1
        assert result["alerts"]["stale_decisions"][0]["title"] == "Stale decision"

    def test_check_alerts_upcoming_deadlines(self, memory_store):
        soon_date = (date.today() + timedelta(days=2)).isoformat()
        add_delegation(
            memory_store,
            task="Upcoming task",
            delegated_to="Bob",
            due_date=soon_date,
        )

        result = check_alerts(memory_store)
        assert result["total_alerts"] >= 1
        assert len(result["alerts"]["upcoming_deadlines"]) == 1
        assert result["alerts"]["upcoming_deadlines"][0]["task"] == "Upcoming task"

    def test_check_alerts_rule_based_overdue(self, memory_store):
        # Create an alert rule for overdue delegations
        condition = json.dumps({"days_overdue": 2})
        create_alert_rule(
            memory_store,
            name="overdue_rule",
            alert_type="overdue_delegation",
            condition=condition,
            enabled=True,
        )

        # Create an overdue delegation
        past_date = (date.today() - timedelta(days=5)).isoformat()
        add_delegation(
            memory_store,
            task="Very overdue",
            delegated_to="Alice",
            due_date=past_date,
        )

        result = check_alerts(memory_store)
        assert result["total_alerts"] >= 1
        rule_alerts = result.get("rule_alerts", [])
        assert len(rule_alerts) >= 1

        overdue_alert = next(
            (r for r in rule_alerts if r["alert_type"] == "overdue_delegation"),
            None,
        )
        assert overdue_alert is not None
        assert overdue_alert["count"] == 1

    def test_check_alerts_rule_based_stale_decision(self, memory_store):
        # Create an alert rule for stale decisions
        condition = json.dumps({"days_stale": 5})
        create_alert_rule(
            memory_store,
            name="stale_rule",
            alert_type="stale_decision",
            condition=condition,
            enabled=True,
        )

        # Store an old pending decision
        old_date = (date.today() - timedelta(days=8)).isoformat()
        decision = Decision(
            title="Very stale",
            status="pending_execution",
        )
        stored = memory_store.store_decision(decision)
        memory_store.conn.execute(
            "UPDATE decisions SET created_at=? WHERE id=?",
            (old_date, stored.id),
        )
        memory_store.conn.commit()

        result = check_alerts(memory_store)
        rule_alerts = result.get("rule_alerts", [])
        stale_alert = next(
            (r for r in rule_alerts if r["alert_type"] == "stale_decision"),
            None,
        )
        assert stale_alert is not None
        assert stale_alert["count"] == 1

    def test_check_alerts_rule_based_upcoming_deadline(self, memory_store):
        # Create an alert rule for upcoming deadlines
        condition = json.dumps({"within_days": 2})
        create_alert_rule(
            memory_store,
            name="deadline_rule",
            alert_type="upcoming_deadline",
            condition=condition,
            enabled=True,
        )

        # Create a delegation due soon
        soon_date = (date.today() + timedelta(days=1)).isoformat()
        add_delegation(
            memory_store,
            task="Due soon",
            delegated_to="Charlie",
            due_date=soon_date,
        )

        result = check_alerts(memory_store)
        rule_alerts = result.get("rule_alerts", [])
        deadline_alert = next(
            (r for r in rule_alerts if r["alert_type"] == "upcoming_deadline"),
            None,
        )
        assert deadline_alert is not None
        assert deadline_alert["count"] >= 1

    def test_check_alerts_disabled_rules_ignored(self, memory_store):
        # Create a disabled alert rule
        create_alert_rule(
            memory_store,
            name="disabled_rule",
            alert_type="overdue_delegation",
            condition=json.dumps({"days_overdue": 1}),
            enabled=False,
        )

        # Create an overdue delegation
        past_date = (date.today() - timedelta(days=5)).isoformat()
        add_delegation(
            memory_store,
            task="Overdue",
            delegated_to="Alice",
            due_date=past_date,
        )

        result = check_alerts(memory_store)
        rule_alerts = result.get("rule_alerts", [])
        # Rule should not trigger because it's disabled
        disabled_alert = next(
            (r for r in rule_alerts if r["name"] == "disabled_rule"),
            None,
        )
        assert disabled_alert is None

    def test_check_alerts_no_alerts(self, memory_store):
        # No delegations or decisions
        result = check_alerts(memory_store)
        assert result["total_alerts"] == 0
        assert result["alerts"]["overdue_delegations"] == []
        assert result["alerts"]["stale_decisions"] == []
        assert result["alerts"]["upcoming_deadlines"] == []

    def test_check_alerts_invalid_rule_condition(self, memory_store):
        # Create a rule with invalid JSON condition
        create_alert_rule(
            memory_store,
            name="bad_rule",
            alert_type="overdue_delegation",
            condition="not valid json",
            enabled=True,
        )

        # Should not crash
        result = check_alerts(memory_store)
        assert result is not None
        assert "total_alerts" in result


class TestEdgeCases:
    def test_log_decision_missing_title_handled_by_dataclass(self, memory_store):
        # Decision dataclass allows title=None but SQLite NOT NULL constraint fails
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            log_decision(memory_store, title=None)

    def test_add_delegation_missing_required_fields(self, memory_store):
        # Delegation requires task and delegated_to
        with pytest.raises(TypeError):
            add_delegation(memory_store, task="Test")

    def test_search_decisions_with_empty_query(self, memory_store):
        log_decision(memory_store, title="Decision 1")
        log_decision(memory_store, title="Decision 2")

        result = search_decisions(memory_store, query="")
        assert len(result["results"]) == 2

    def test_list_delegations_no_filters(self, memory_store):
        add_delegation(memory_store, task="Task 1", delegated_to="Alice")
        add_delegation(memory_store, task="Task 2", delegated_to="Bob")

        result = list_delegations(memory_store, status="", delegated_to="")
        assert len(result["results"]) == 2
