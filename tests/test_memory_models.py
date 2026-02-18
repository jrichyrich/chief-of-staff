# tests/test_memory_models.py
from memory.models import AlertRule, ContextEntry, Decision, Delegation, Fact, Location


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


def test_context_entry_creation():
    entry = ContextEntry(
        topic="project planning",
        summary="Discussed priorities for Q2",
        session_id="sess_123",
        agent="project_manager",
    )
    assert entry.topic == "project planning"
    assert entry.summary == "Discussed priorities for Q2"
    assert entry.session_id == "sess_123"
    assert entry.agent == "project_manager"


def test_decision_creation():
    decision = Decision(
        title="Adopt microservices",
        description="Move to microservices architecture",
        context="Monolith is hitting scale limits",
        alternatives_considered="Modular monolith, serverless",
        decided_by="CTO",
        owner="Platform team",
        status="pending_execution",
        follow_up_date="2026-03-01",
        tags="architecture,infrastructure",
        source="meeting",
    )
    assert decision.title == "Adopt microservices"
    assert decision.decided_by == "CTO"
    assert decision.owner == "Platform team"
    assert decision.tags == "architecture,infrastructure"
    assert decision.source == "meeting"


def test_decision_defaults():
    decision = Decision(title="Quick decision")
    assert decision.description == ""
    assert decision.context == ""
    assert decision.alternatives_considered == ""
    assert decision.status == "pending_execution"
    assert decision.follow_up_date is None
    assert decision.tags == ""
    assert decision.id is None


def test_delegation_creation():
    delegation = Delegation(
        task="Write Q1 report",
        delegated_to="Alice",
        description="Quarterly performance report",
        delegated_by="Jason",
        due_date="2026-02-28",
        priority="high",
        status="active",
        source="email",
        notes="Include metrics from dashboard",
    )
    assert delegation.task == "Write Q1 report"
    assert delegation.delegated_to == "Alice"
    assert delegation.delegated_by == "Jason"
    assert delegation.priority == "high"
    assert delegation.source == "email"


def test_delegation_defaults():
    delegation = Delegation(task="Do something", delegated_to="Bob")
    assert delegation.description == ""
    assert delegation.delegated_by == ""
    assert delegation.due_date is None
    assert delegation.priority == "medium"
    assert delegation.status == "active"
    assert delegation.notes == ""
    assert delegation.id is None


def test_alert_rule_creation():
    rule = AlertRule(
        name="overdue_check",
        description="Check for overdue delegations",
        alert_type="stale_delegation",
        condition='{"days_overdue": 3}',
        enabled=True,
    )
    assert rule.name == "overdue_check"
    assert rule.alert_type == "stale_delegation"
    assert rule.condition == '{"days_overdue": 3}'
    assert rule.enabled is True


def test_alert_rule_defaults():
    rule = AlertRule(name="test_rule")
    assert rule.description == ""
    assert rule.alert_type == ""
    assert rule.condition == ""
    assert rule.enabled is True
    assert rule.last_triggered_at is None
    assert rule.id is None
