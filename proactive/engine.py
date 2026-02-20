"""Proactive suggestion engine — surfaces actionable insights from existing data."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from memory.store import MemoryStore
from proactive.models import Suggestion


class ProactiveSuggestionEngine:
    def __init__(self, memory_store: MemoryStore):
        self.memory_store = memory_store

    def generate_suggestions(self) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        suggestions.extend(self._check_skill_suggestions())
        suggestions.extend(self._check_unprocessed_webhooks())
        suggestions.extend(self._check_overdue_delegations())
        suggestions.extend(self._check_stale_decisions())
        suggestions.extend(self._check_upcoming_deadlines())
        # Sort by priority: high first, then medium, then low
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda s: priority_order.get(s.priority, 3))
        return suggestions

    def _check_skill_suggestions(self) -> list[Suggestion]:
        pending = self.memory_store.list_skill_suggestions(status="pending")
        results = []
        for s in pending:
            results.append(Suggestion(
                category="skill",
                priority="medium",
                title=f"New skill suggestion: {s.suggested_name or 'unnamed'}",
                description=s.description,
                action="auto_create_skill",
                created_at=s.created_at or "",
            ))
        return results

    def _check_unprocessed_webhooks(self) -> list[Suggestion]:
        pending = self.memory_store.list_webhook_events(status="pending")
        results = []
        for event in pending:
            results.append(Suggestion(
                category="webhook",
                priority="low",
                title=f"Unprocessed webhook: {event.source}/{event.event_type}",
                description=f"Webhook event from {event.source} ({event.event_type}) received at {event.received_at}",
                action="list_webhook_events",
                created_at=event.received_at or "",
            ))
        return results

    def _check_overdue_delegations(self) -> list[Suggestion]:
        overdue = self.memory_store.list_overdue_delegations()
        results = []
        for d in overdue:
            days_overdue = 0
            if d.due_date:
                days_overdue = (date.today() - date.fromisoformat(d.due_date)).days
            results.append(Suggestion(
                category="delegation",
                priority="high",
                title=f"Overdue: {d.task}",
                description=f"Delegated to {d.delegated_to}, {days_overdue} days overdue (due {d.due_date})",
                action="check_overdue_delegations",
                created_at=d.created_at or "",
            ))
        return results

    def _check_stale_decisions(self) -> list[Suggestion]:
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        pending = self.memory_store.list_decisions_by_status("pending_execution")
        results = []
        for d in pending:
            if d.created_at and d.created_at[:10] < cutoff:
                results.append(Suggestion(
                    category="decision",
                    priority="medium",
                    title=f"Stale decision: {d.title}",
                    description=f"Pending since {d.created_at[:10]}, over 7 days without execution",
                    action="list_pending_decisions",
                    created_at=d.created_at or "",
                ))
        return results

    def _check_upcoming_deadlines(self) -> list[Suggestion]:
        today = date.today()
        soon = (today + timedelta(days=3)).isoformat()
        today_str = today.isoformat()
        active = self.memory_store.list_delegations(status="active")
        results = []
        for d in active:
            if d.due_date and today_str <= d.due_date <= soon:
                days_left = (date.fromisoformat(d.due_date) - today).days
                results.append(Suggestion(
                    category="deadline",
                    priority="high",
                    title=f"Deadline in {days_left}d: {d.task}",
                    description=f"Delegated to {d.delegated_to}, due {d.due_date}",
                    action="list_delegations",
                    created_at=d.created_at or "",
                ))
        return results
