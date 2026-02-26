#!/usr/bin/env python3
"""Standalone alert rule evaluator for scheduled execution via launchd."""

from __future__ import annotations

import json
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATA_DIR, MEMORY_DB_PATH
from memory.store import MemoryStore


def _setup_logging():
    """Configure logging to data/alert-eval.log."""
    log_path = DATA_DIR / "alert-eval.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


def _log(log_path: Path, message: str):
    """Append timestamped message to log file."""
    timestamp = datetime.now().isoformat()
    with open(log_path, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def _parse_rule_condition(condition: str) -> dict:
    """Parse JSON condition string from alert rule."""
    condition = (condition or "").strip()
    if not condition:
        return {}
    try:
        value = json.loads(condition)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _evaluate_rule(memory_store: MemoryStore, rule) -> dict:
    """Evaluate a single alert rule against current data."""
    parsed = _parse_rule_condition(rule.condition)
    alert_type = (rule.alert_type or "").strip().lower()

    if alert_type == "overdue_delegation":
        min_days = int(parsed.get("days_overdue", 1))
        today = date.today()
        matches = [
            {
                "id": d.id,
                "task": d.task,
                "delegated_to": d.delegated_to,
                "due_date": d.due_date,
                "days_overdue": (today - date.fromisoformat(d.due_date)).days,
            }
            for d in memory_store.list_overdue_delegations()
            if d.due_date and (today - date.fromisoformat(d.due_date)).days >= min_days
        ]
    elif alert_type in ("pending_decision", "stale_decision"):
        stale_days = int(parsed.get("days_stale", 7))
        cutoff = (date.today() - timedelta(days=stale_days)).isoformat()
        matches = [
            {
                "id": d.id,
                "title": d.title,
                "created_at": d.created_at,
            }
            for d in memory_store.list_decisions_by_status("pending_execution")
            if d.created_at and d.created_at[:10] < cutoff
        ]
    elif alert_type == "upcoming_deadline":
        within_days = int(parsed.get("within_days", 3))
        today = date.today()
        soon = (today + timedelta(days=within_days)).isoformat()
        today_str = today.isoformat()
        matches = [
            {
                "id": d.id,
                "task": d.task,
                "delegated_to": d.delegated_to,
                "due_date": d.due_date,
            }
            for d in memory_store.list_delegations(status="active")
            if d.due_date and today_str <= d.due_date <= soon
        ]
    elif alert_type == "stale_backup":
        max_age_hours = int(parsed.get("max_age_hours", 48))
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        fact = memory_store.get_fact("work", "backup_last_success")
        matches = []
        if fact is None:
            matches.append({"reason": "No backup_last_success fact found"})
        else:
            # Value format: "YYYY-MM-DD: summary text"
            try:
                date_str = fact.value.split(":")[0].strip()
                last_backup = datetime.strptime(date_str, "%Y-%m-%d")
                if last_backup < cutoff:
                    age_hours = (datetime.now() - last_backup).total_seconds() / 3600
                    matches.append({
                        "last_success": fact.value,
                        "hours_ago": round(age_hours, 1),
                        "threshold_hours": max_age_hours,
                    })
            except (ValueError, IndexError):
                matches.append({
                    "reason": f"Could not parse backup timestamp: {fact.value}"
                })
    else:
        matches = []

    return {
        "rule_id": rule.id,
        "name": rule.name,
        "alert_type": rule.alert_type,
        "count": len(matches),
        "matches": matches,
    }


def _send_notification(title: str, message: str, log_path: Path):
    """Send macOS notification for triggered alert."""
    try:
        from apple_notifications.notifier import Notifier
        result = Notifier.send(title=title, message=message)
        if "error" in result:
            _log(log_path, f"Notification error: {result['error']}")
        else:
            _log(log_path, f"Notification sent: {title}")
    except ImportError:
        _log(log_path, "Notification module not available (non-macOS?)")
    except Exception as e:
        _log(log_path, f"Notification failed: {e}")


def evaluate_alerts():
    """Main evaluation loop - load rules, evaluate, send notifications."""
    log_path = _setup_logging()
    _log(log_path, "Alert evaluator started")

    try:
        # Initialize memory store
        if not MEMORY_DB_PATH.exists():
            _log(log_path, f"Memory DB not found at {MEMORY_DB_PATH}")
            return

        memory_store = MemoryStore(MEMORY_DB_PATH)
        _log(log_path, "Connected to memory store")

        # Get all enabled alert rules
        rules = memory_store.list_alert_rules(enabled_only=True)
        _log(log_path, f"Found {len(rules)} enabled alert rules")

        if not rules:
            _log(log_path, "No enabled rules to evaluate")
            return

        # Evaluate each rule
        triggered_count = 0
        for rule in rules:
            try:
                _log(log_path, f"Evaluating rule: {rule.name} (type={rule.alert_type})")
                result = _evaluate_rule(memory_store, rule)

                if result["count"] > 0:
                    triggered_count += 1
                    _log(log_path, f"Rule triggered: {rule.name} ({result['count']} matches)")

                    # Send notification
                    title = f"Alert: {rule.name}"
                    message = f"{result['count']} {rule.alert_type} found"
                    _send_notification(title, message, log_path)

                    # Update last_triggered_at timestamp
                    memory_store.update_alert_rule(
                        rule.id,
                        last_triggered_at=datetime.now().isoformat()
                    )
                else:
                    _log(log_path, f"Rule passed: {rule.name} (no matches)")

            except Exception as e:
                # Log error but continue with other rules
                _log(log_path, f"Error evaluating rule {rule.name}: {e}")
                _log(log_path, traceback.format_exc())

        _log(log_path, f"Evaluation complete: {triggered_count}/{len(rules)} rules triggered")
        memory_store.close()

    except Exception as e:
        _log(log_path, f"Fatal error: {e}")
        _log(log_path, traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    evaluate_alerts()
