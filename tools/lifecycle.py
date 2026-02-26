"""Shared lifecycle operations for decisions, delegations, and alerts."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from memory.models import AlertRule, Decision, Delegation


def create_decision(memory_store, *, title: str, description: str = "", context: str = "",
                    decided_by: str = "", owner: str = "", status: str = "pending_execution",
                    follow_up_date: str = "", tags: str = "", source: str = "") -> dict[str, Any]:
    decision = Decision(
        title=title,
        description=description,
        context=context,
        decided_by=decided_by,
        owner=owner,
        status=status,
        follow_up_date=follow_up_date or None,
        tags=tags,
        source=source,
    )
    stored = memory_store.store_decision(decision)
    return {
        "status": "logged",
        "id": stored.id,
        "title": stored.title,
        "decision_status": stored.status,
    }


def search_decisions(memory_store, *, query: str = "", status: str = "") -> dict[str, Any]:
    if status and query:
        decisions = memory_store.search_decisions(query)
        decisions = [d for d in decisions if d.status == status]
    elif status:
        decisions = memory_store.list_decisions_by_status(status)
    elif query:
        decisions = memory_store.search_decisions(query)
    else:
        decisions = memory_store.search_decisions("")

    if not decisions:
        return {"message": "No decisions found.", "results": []}

    results = [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "owner": d.owner,
            "decided_by": d.decided_by,
            "follow_up_date": d.follow_up_date,
            "tags": d.tags,
            "created_at": d.created_at,
        }
        for d in decisions
    ]
    return {"results": results}


def update_decision(memory_store, *, decision_id: int, status: str = "", notes: str = "") -> dict[str, Any]:
    existing = memory_store.get_decision(decision_id)
    if not existing:
        return {"error": f"Decision {decision_id} not found."}

    kwargs: dict[str, Any] = {}
    if status:
        kwargs["status"] = status
    if notes:
        updated_desc = f"{existing.description}\n\n[Update] {notes}".strip()
        kwargs["description"] = updated_desc

    if not kwargs:
        return {"error": "No fields to update. Provide status or notes."}

    updated = memory_store.update_decision(decision_id, **kwargs)
    return {
        "status": "updated",
        "id": updated.id,
        "title": updated.title,
        "decision_status": updated.status,
    }


def list_pending_decisions(memory_store) -> dict[str, Any]:
    decisions = memory_store.list_decisions_by_status("pending_execution")

    if not decisions:
        return {"message": "No pending decisions.", "results": []}

    results = [
        {
            "id": d.id,
            "title": d.title,
            "owner": d.owner,
            "follow_up_date": d.follow_up_date,
            "created_at": d.created_at,
        }
        for d in decisions
    ]
    return {"results": results}


def delete_decision(memory_store, *, decision_id: int) -> dict[str, Any]:
    deleted = memory_store.delete_decision(decision_id)
    if deleted:
        return {"status": "deleted", "id": decision_id}
    return {"error": f"Decision {decision_id} not found."}


def create_delegation(memory_store, *, task: str, delegated_to: str, description: str = "",
                      due_date: str = "", priority: str = "medium", source: str = "") -> dict[str, Any]:
    delegation = Delegation(
        task=task,
        delegated_to=delegated_to,
        description=description,
        due_date=due_date or None,
        priority=priority,
        source=source,
    )
    stored = memory_store.store_delegation(delegation)
    return {
        "status": "created",
        "id": stored.id,
        "task": stored.task,
        "delegated_to": stored.delegated_to,
        "due_date": stored.due_date,
    }


def list_delegations(memory_store, *, status: str = "", delegated_to: str = "") -> dict[str, Any]:
    delegations = memory_store.list_delegations(
        status=status or None,
        delegated_to=delegated_to or None,
    )

    if not delegations:
        return {"message": "No delegations found.", "results": []}

    results = [
        {
            "id": d.id,
            "task": d.task,
            "delegated_to": d.delegated_to,
            "status": d.status,
            "priority": d.priority,
            "due_date": d.due_date,
            "created_at": d.created_at,
        }
        for d in delegations
    ]
    return {"results": results}


def update_delegation(memory_store, *, delegation_id: int, status: str = "", notes: str = "") -> dict[str, Any]:
    existing = memory_store.get_delegation(delegation_id)
    if not existing:
        return {"error": f"Delegation {delegation_id} not found."}

    kwargs: dict[str, Any] = {}
    if status:
        kwargs["status"] = status
    if notes:
        updated_notes = f"{existing.notes}\n{notes}".strip()
        kwargs["notes"] = updated_notes

    if not kwargs:
        return {"error": "No fields to update. Provide status or notes."}

    updated = memory_store.update_delegation(delegation_id, **kwargs)
    return {
        "status": "updated",
        "id": updated.id,
        "task": updated.task,
        "delegation_status": updated.status,
    }


def check_overdue_delegations(memory_store) -> dict[str, Any]:
    overdue = memory_store.list_overdue_delegations()

    if not overdue:
        return {"message": "No overdue delegations.", "results": []}

    results = [
        {
            "id": d.id,
            "task": d.task,
            "delegated_to": d.delegated_to,
            "due_date": d.due_date,
            "priority": d.priority,
        }
        for d in overdue
    ]
    return {"results": results}


def delete_delegation(memory_store, *, delegation_id: int) -> dict[str, Any]:
    deleted = memory_store.delete_delegation(delegation_id)
    if deleted:
        return {"status": "deleted", "id": delegation_id}
    return {"error": f"Delegation {delegation_id} not found."}


def create_alert_rule(memory_store, *, name: str, alert_type: str, description: str = "",
                      condition: str = "", enabled: bool = True) -> dict[str, Any]:
    rule = AlertRule(
        name=name,
        description=description,
        alert_type=alert_type,
        condition=condition,
        enabled=enabled,
    )
    stored = memory_store.store_alert_rule(rule)
    return {
        "status": "created",
        "id": stored.id,
        "name": stored.name,
        "alert_type": stored.alert_type,
        "enabled": stored.enabled,
    }


def list_alert_rules(memory_store, *, enabled_only: bool = False) -> dict[str, Any]:
    rules = memory_store.list_alert_rules(enabled_only=enabled_only)

    if not rules:
        return {"message": "No alert rules configured.", "results": []}

    results = [
        {
            "id": r.id,
            "name": r.name,
            "alert_type": r.alert_type,
            "description": r.description,
            "enabled": r.enabled,
            "condition": r.condition,
        }
        for r in rules
    ]
    return {"results": results}


def _parse_rule_condition(condition: str) -> dict[str, Any]:
    condition = (condition or "").strip()
    if not condition:
        return {}
    try:
        value = json.loads(condition)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _evaluate_rule(memory_store, rule) -> dict[str, Any]:
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


def check_alerts(memory_store) -> dict[str, Any]:
    alerts = {"overdue_delegations": [], "stale_decisions": [], "upcoming_deadlines": []}

    overdue = memory_store.list_overdue_delegations()
    for d in overdue:
        alerts["overdue_delegations"].append({
            "id": d.id,
            "task": d.task,
            "delegated_to": d.delegated_to,
            "due_date": d.due_date,
        })

    pending = memory_store.list_decisions_by_status("pending_execution")
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    for d in pending:
        if d.created_at and d.created_at[:10] < cutoff:
            alerts["stale_decisions"].append({
                "id": d.id,
                "title": d.title,
                "created_at": d.created_at,
            })

    today = date.today()
    soon = (today + timedelta(days=3)).isoformat()
    today_str = today.isoformat()
    active = memory_store.list_delegations(status="active")
    for d in active:
        if d.due_date and today_str <= d.due_date <= soon:
            alerts["upcoming_deadlines"].append({
                "id": d.id,
                "task": d.task,
                "delegated_to": d.delegated_to,
                "due_date": d.due_date,
            })

    rule_alerts = []
    for rule in memory_store.list_alert_rules(enabled_only=True):
        evaluated = _evaluate_rule(memory_store, rule)
        if evaluated["count"] > 0:
            rule_alerts.append(evaluated)

    total = sum(len(v) for v in alerts.values()) + sum(r["count"] for r in rule_alerts)
    return {
        "total_alerts": total,
        "alerts": alerts,
        "rule_alerts": rule_alerts,
    }


def dismiss_alert(memory_store, *, rule_id: int) -> dict[str, Any]:
    existing = memory_store.get_alert_rule(rule_id)
    if not existing:
        return {"error": f"Alert rule {rule_id} not found."}

    updated = memory_store.update_alert_rule(rule_id, enabled=False)
    return {
        "status": "dismissed",
        "id": updated.id,
        "name": updated.name,
        "enabled": updated.enabled,
    }
