"""Proactive suggestion engine — surfaces actionable insights from existing data."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from memory.store import MemoryStore
from proactive.models import Suggestion

logger = logging.getLogger(__name__)

# Priority ordering used for filtering and sorting
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class ProactiveSuggestionEngine:
    def __init__(self, memory_store: MemoryStore, session_health=None):
        self.memory_store = memory_store
        self.session_health = session_health

    def generate_suggestions(self) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        suggestions.extend(self._check_skill_suggestions())
        suggestions.extend(self._check_unprocessed_webhooks())
        suggestions.extend(self._check_overdue_delegations())
        suggestions.extend(self._check_stale_decisions())
        suggestions.extend(self._check_upcoming_deadlines())
        suggestions.extend(self._check_session_checkpoint_needed())
        # Sort by priority: high first, then medium, then low
        suggestions.sort(key=lambda s: PRIORITY_ORDER.get(s.priority, 3))
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

    def _check_session_checkpoint_needed(self) -> list[Suggestion]:
        if self.session_health is None:
            return []
        health = self.session_health
        if health.tool_call_count < 50:
            return []
        # Check if last checkpoint is stale (>30 min ago or never)
        if health.last_checkpoint:
            try:
                last_cp = datetime.fromisoformat(health.last_checkpoint)
                minutes_ago = (datetime.now() - last_cp).total_seconds() / 60
                if minutes_ago < 30:
                    return []
            except (ValueError, TypeError):
                pass
        return [Suggestion(
            category="checkpoint",
            priority="medium",
            title="Session checkpoint recommended",
            description=(
                f"{health.tool_call_count} tool calls since session start with "
                f"{'no checkpoint yet' if not health.last_checkpoint else 'last checkpoint over 30 min ago'}. "
                "Consider running checkpoint_session to preserve context before compaction."
            ),
            action="checkpoint_session",
        )]

    def push_suggestions(
        self,
        suggestions: list[Suggestion],
        push_threshold: str = "high",
    ) -> list[dict]:
        """Send macOS push notifications for suggestions at or above the threshold.

        Args:
            suggestions: List of Suggestion objects to potentially push.
            push_threshold: Minimum priority to push ("high", "medium", or "low").

        Returns:
            List of notification result dicts for pushed suggestions.
        """
        from apple_notifications.notifier import Notifier

        threshold_val = PRIORITY_ORDER.get(push_threshold, 0)
        results = []
        for s in suggestions:
            if PRIORITY_ORDER.get(s.priority, 3) <= threshold_val:
                result = Notifier.send(
                    title=f"Jarvis: {s.category.title()}",
                    message=s.title,
                    subtitle=s.priority.upper(),
                )
                results.append(result)
                logger.debug("Push notification for %s: %s", s.title, result)
        return results

    def check_all(self, push_enabled: bool = False, push_threshold: str = "high") -> dict:
        """Generate suggestions and optionally push notifications.

        Returns:
            Dict with 'suggestions' list and optionally 'pushed' results.
        """
        suggestions = self.generate_suggestions()
        result: dict = {"suggestions": suggestions}
        if push_enabled and suggestions:
            result["pushed"] = self.push_suggestions(suggestions, push_threshold)
        return result
