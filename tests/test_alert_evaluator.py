"""Tests for scheduler/alert_evaluator.py."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memory.models import AlertRule, Decision, Delegation, Fact
from memory.store import MemoryStore



@pytest.fixture
def log_path(tmp_path):
    """Create a temporary log file path."""
    return tmp_path / "alert-eval.log"


def test_parse_rule_condition():
    """Test JSON condition parsing."""
    from scheduler.alert_evaluator import _parse_rule_condition

    assert _parse_rule_condition("") == {}
    assert _parse_rule_condition('{"days_overdue": 3}') == {"days_overdue": 3}
    assert _parse_rule_condition("invalid json") == {}
    assert _parse_rule_condition('["not", "a", "dict"]') == {}


def test_evaluate_overdue_delegation_rule(memory_store):
    """Test evaluation of overdue_delegation alert rule."""
    from scheduler.alert_evaluator import _evaluate_rule

    # Create overdue delegation
    overdue_date = (date.today() - timedelta(days=5)).isoformat()
    delegation = Delegation(
        task="Overdue task",
        delegated_to="Alice",
        due_date=overdue_date,
        status="active"
    )
    memory_store.store_delegation(delegation)

    # Create alert rule
    rule = AlertRule(
        name="overdue_check",
        alert_type="overdue_delegation",
        condition=json.dumps({"days_overdue": 3}),
        enabled=True
    )
    stored_rule = memory_store.store_alert_rule(rule)

    # Evaluate
    result = _evaluate_rule(memory_store, stored_rule)

    assert result["rule_id"] == stored_rule.id
    assert result["name"] == "overdue_check"
    assert result["count"] == 1
    assert result["matches"][0]["task"] == "Overdue task"
    assert result["matches"][0]["days_overdue"] == 5


def test_evaluate_stale_decision_rule(memory_store):
    """Test evaluation of stale_decision alert rule."""
    from scheduler.alert_evaluator import _evaluate_rule

    # Create old pending decision
    old_date = (date.today() - timedelta(days=10)).isoformat()

    # Directly insert to bypass auto timestamp
    memory_store.conn.execute(
        """INSERT INTO decisions (title, status, created_at, updated_at)
           VALUES (?, ?, ?, ?)""",
        ("Old decision", "pending_execution", old_date, old_date)
    )
    memory_store.conn.commit()

    # Create alert rule
    rule = AlertRule(
        name="stale_decisions",
        alert_type="stale_decision",
        condition=json.dumps({"days_stale": 7}),
        enabled=True
    )
    stored_rule = memory_store.store_alert_rule(rule)

    # Evaluate
    result = _evaluate_rule(memory_store, stored_rule)

    assert result["count"] == 1
    assert result["matches"][0]["title"] == "Old decision"


def test_evaluate_upcoming_deadline_rule(memory_store):
    """Test evaluation of upcoming_deadline alert rule."""
    from scheduler.alert_evaluator import _evaluate_rule

    # Create delegation with upcoming deadline
    upcoming_date = (date.today() + timedelta(days=2)).isoformat()
    delegation = Delegation(
        task="Upcoming task",
        delegated_to="Bob",
        due_date=upcoming_date,
        status="active"
    )
    memory_store.store_delegation(delegation)

    # Create alert rule
    rule = AlertRule(
        name="upcoming_check",
        alert_type="upcoming_deadline",
        condition=json.dumps({"within_days": 3}),
        enabled=True
    )
    stored_rule = memory_store.store_alert_rule(rule)

    # Evaluate
    result = _evaluate_rule(memory_store, stored_rule)

    assert result["count"] == 1
    assert result["matches"][0]["task"] == "Upcoming task"


def test_evaluate_stale_backup_rule_triggers(memory_store):
    """Test stale_backup alert fires when backup is older than threshold."""
    from scheduler.alert_evaluator import _evaluate_rule

    # Store a backup success fact from 3 days ago
    old_date = (date.today() - timedelta(days=3)).isoformat()
    memory_store.store_fact(Fact(
        category="work", key="backup_last_success",
        value=f"{old_date}: 150 files, 17M",
    ))

    rule = AlertRule(
        name="stale_backup_check",
        alert_type="stale_backup",
        condition=json.dumps({"max_age_hours": 48}),
        enabled=True,
    )
    stored_rule = memory_store.store_alert_rule(rule)

    result = _evaluate_rule(memory_store, stored_rule)

    assert result["count"] == 1
    assert result["matches"][0]["hours_ago"] > 48
    assert result["matches"][0]["threshold_hours"] == 48


def test_evaluate_stale_backup_rule_passes(memory_store):
    """Test stale_backup alert does NOT fire when backup is recent."""
    from scheduler.alert_evaluator import _evaluate_rule

    today = date.today().isoformat()
    memory_store.store_fact(Fact(
        category="work", key="backup_last_success",
        value=f"{today}: 177 files, 26M",
    ))

    rule = AlertRule(
        name="stale_backup_check",
        alert_type="stale_backup",
        condition=json.dumps({"max_age_hours": 48}),
        enabled=True,
    )
    stored_rule = memory_store.store_alert_rule(rule)

    result = _evaluate_rule(memory_store, stored_rule)

    assert result["count"] == 0
    assert result["matches"] == []


def test_evaluate_stale_backup_rule_no_fact(memory_store):
    """Test stale_backup alert fires when no backup fact exists at all."""
    from scheduler.alert_evaluator import _evaluate_rule

    rule = AlertRule(
        name="stale_backup_check",
        alert_type="stale_backup",
        condition=json.dumps({"max_age_hours": 48}),
        enabled=True,
    )
    stored_rule = memory_store.store_alert_rule(rule)

    result = _evaluate_rule(memory_store, stored_rule)

    assert result["count"] == 1
    assert "No backup_last_success fact found" in result["matches"][0]["reason"]


def test_evaluate_unknown_alert_type(memory_store):
    """Test evaluation handles unknown alert types gracefully."""
    from scheduler.alert_evaluator import _evaluate_rule

    rule = AlertRule(
        name="unknown_type",
        alert_type="unknown_type",
        condition="{}",
        enabled=True
    )
    stored_rule = memory_store.store_alert_rule(rule)

    result = _evaluate_rule(memory_store, stored_rule)

    assert result["count"] == 0
    assert result["matches"] == []


def test_log_appends_timestamp(log_path):
    """Test that _log appends timestamped messages."""
    from scheduler.alert_evaluator import _log

    _log(log_path, "First message")
    _log(log_path, "Second message")

    content = log_path.read_text()
    lines = content.strip().split("\n")

    assert len(lines) == 2
    assert "First message" in lines[0]
    assert "Second message" in lines[1]
    assert lines[0].startswith("[")
    assert lines[1].startswith("[")


@patch("apple_notifications.notifier.Notifier.send")
def test_send_notification_success(mock_send, log_path):
    """Test successful notification sending."""
    from scheduler.alert_evaluator import _send_notification

    mock_send.return_value = {"status": "sent"}

    _send_notification("Test Title", "Test Message", log_path)

    log_content = log_path.read_text()
    assert "Notification sent: Test Title" in log_content
    mock_send.assert_called_once_with(title="Test Title", message="Test Message")


@patch("apple_notifications.notifier.Notifier.send")
def test_send_notification_error(mock_send, log_path):
    """Test notification error handling."""
    from scheduler.alert_evaluator import _send_notification

    mock_send.return_value = {"error": "osascript failed"}

    _send_notification("Test Title", "Test Message", log_path)

    log_content = log_path.read_text()
    assert "Notification error: osascript failed" in log_content


def test_evaluate_alerts_no_rules(memory_store, tmp_path, monkeypatch):
    """Test evaluate_alerts with no enabled rules."""
    from scheduler import alert_evaluator

    # Mock config paths
    monkeypatch.setattr(alert_evaluator, "DATA_DIR", tmp_path)
    monkeypatch.setattr(alert_evaluator, "MEMORY_DB_PATH", memory_store.db_path)

    alert_evaluator.evaluate_alerts()

    log_path = tmp_path / "alert-eval.log"
    log_content = log_path.read_text()

    assert "Alert evaluator started" in log_content
    assert "No enabled rules to evaluate" in log_content


def test_evaluate_alerts_with_triggered_rule(memory_store, tmp_path, monkeypatch):
    """Test evaluate_alerts with a triggered rule."""
    from scheduler import alert_evaluator

    # Create overdue delegation
    overdue_date = (date.today() - timedelta(days=5)).isoformat()
    delegation = Delegation(
        task="Overdue task",
        delegated_to="Alice",
        due_date=overdue_date,
        status="active"
    )
    memory_store.store_delegation(delegation)

    # Create alert rule
    rule = AlertRule(
        name="overdue_check",
        alert_type="overdue_delegation",
        condition=json.dumps({"days_overdue": 3}),
        enabled=True
    )
    memory_store.store_alert_rule(rule)

    # Mock config and notification
    monkeypatch.setattr(alert_evaluator, "DATA_DIR", tmp_path)
    monkeypatch.setattr(alert_evaluator, "MEMORY_DB_PATH", memory_store.db_path)

    with patch("scheduler.alert_evaluator._send_notification") as mock_notify:
        alert_evaluator.evaluate_alerts()

        # Check notification was called
        mock_notify.assert_called_once()
        args = mock_notify.call_args[0]
        assert "overdue_check" in args[0]
        assert "1" in args[1]

    # Check log
    log_path = tmp_path / "alert-eval.log"
    log_content = log_path.read_text()

    assert "Alert evaluator started" in log_content
    assert "Found 1 enabled alert rules" in log_content
    assert "Evaluating rule: overdue_check" in log_content
    assert "Rule triggered: overdue_check (1 matches)" in log_content
    assert "Evaluation complete: 1/1 rules triggered" in log_content


def test_evaluate_alerts_error_handling(memory_store, tmp_path, monkeypatch):
    """Test that errors in individual rules don't crash the evaluator."""
    from scheduler import alert_evaluator

    # Create two rules - one will error, one will succeed
    rule1 = AlertRule(
        name="bad_rule",
        alert_type="overdue_delegation",
        condition='{"days_overdue": "not_a_number"}',  # This will cause error
        enabled=True
    )
    memory_store.store_alert_rule(rule1)

    # Create delegation for second rule
    overdue_date = (date.today() - timedelta(days=5)).isoformat()
    delegation = Delegation(
        task="Overdue task",
        delegated_to="Alice",
        due_date=overdue_date,
        status="active"
    )
    memory_store.store_delegation(delegation)

    rule2 = AlertRule(
        name="good_rule",
        alert_type="overdue_delegation",
        condition=json.dumps({"days_overdue": 3}),
        enabled=True
    )
    memory_store.store_alert_rule(rule2)

    # Mock config and notification
    monkeypatch.setattr(alert_evaluator, "DATA_DIR", tmp_path)
    monkeypatch.setattr(alert_evaluator, "MEMORY_DB_PATH", memory_store.db_path)

    with patch("scheduler.alert_evaluator._send_notification"):
        alert_evaluator.evaluate_alerts()

    # Check log shows both error and success
    log_path = tmp_path / "alert-eval.log"
    log_content = log_path.read_text()

    assert "Error evaluating rule bad_rule" in log_content
    assert "Rule triggered: good_rule" in log_content
