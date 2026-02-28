"""Tests for the proactive suggestion engine."""

from datetime import date, datetime, timedelta

import pytest

from memory.models import Decision, Delegation, SkillSuggestion, WebhookEvent
from memory.store import MemoryStore
from mcp_tools.state import SessionHealth
from proactive.engine import ProactiveSuggestionEngine
from session.brain import SessionBrain



@pytest.fixture
def engine(memory_store):
    return ProactiveSuggestionEngine(memory_store)


class TestGenerateSuggestions:
    def test_empty_state_returns_no_suggestions(self, engine):
        suggestions = engine.generate_suggestions()
        assert suggestions == []

    def test_priority_ordering(self, memory_store, engine):
        """High priority items should come before medium and low."""
        # Add an overdue delegation (high priority)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        memory_store.store_delegation(Delegation(
            task="overdue task", delegated_to="alice", due_date=yesterday,
        ))
        # Add a pending skill suggestion (medium priority)
        memory_store.store_skill_suggestion(SkillSuggestion(
            description="test pattern", suggested_name="test_specialist",
        ))
        # Add an unprocessed webhook (low priority)
        memory_store.store_webhook_event(WebhookEvent(
            source="github", event_type="push",
        ))

        suggestions = engine.generate_suggestions()
        assert len(suggestions) >= 3
        priorities = [s.priority for s in suggestions]
        assert priorities.index("high") < priorities.index("medium")
        assert priorities.index("medium") < priorities.index("low")


class TestCheckSkillSuggestions:
    def test_no_pending_suggestions(self, engine):
        result = engine._check_skill_suggestions()
        assert result == []

    def test_pending_suggestions_returned(self, memory_store, engine):
        memory_store.store_skill_suggestion(SkillSuggestion(
            description="Repeated calendar queries",
            suggested_name="calendar_specialist",
            confidence=0.85,
        ))
        result = engine._check_skill_suggestions()
        assert len(result) == 1
        assert result[0].category == "skill"
        assert result[0].priority == "medium"
        assert "calendar_specialist" in result[0].title
        assert result[0].action == "auto_create_skill"

    def test_accepted_suggestions_not_returned(self, memory_store, engine):
        s = memory_store.store_skill_suggestion(SkillSuggestion(
            description="old pattern", suggested_name="old_specialist",
        ))
        memory_store.update_skill_suggestion_status(s.id, "accepted")
        result = engine._check_skill_suggestions()
        assert result == []


class TestCheckUnprocessedWebhooks:
    def test_no_pending_webhooks(self, engine):
        result = engine._check_unprocessed_webhooks()
        assert result == []

    def test_pending_webhooks_returned(self, memory_store, engine):
        memory_store.store_webhook_event(WebhookEvent(
            source="github", event_type="push", payload="{}",
        ))
        memory_store.store_webhook_event(WebhookEvent(
            source="slack", event_type="message", payload="{}",
        ))
        result = engine._check_unprocessed_webhooks()
        assert len(result) == 2
        assert all(s.category == "webhook" for s in result)
        assert all(s.priority == "low" for s in result)

    def test_processed_webhooks_not_returned(self, memory_store, engine):
        event = memory_store.store_webhook_event(WebhookEvent(
            source="github", event_type="push",
        ))
        memory_store.update_webhook_event_status(event.id, "processed")
        result = engine._check_unprocessed_webhooks()
        assert result == []


class TestCheckOverdueDelegations:
    def test_no_overdue_delegations(self, engine):
        result = engine._check_overdue_delegations()
        assert result == []

    def test_overdue_delegation_returned(self, memory_store, engine):
        past_date = (date.today() - timedelta(days=5)).isoformat()
        memory_store.store_delegation(Delegation(
            task="Write report", delegated_to="bob", due_date=past_date,
        ))
        result = engine._check_overdue_delegations()
        assert len(result) == 1
        assert result[0].category == "delegation"
        assert result[0].priority == "high"
        assert "Write report" in result[0].title
        assert "5 days overdue" in result[0].description

    def test_future_delegation_not_returned(self, memory_store, engine):
        future_date = (date.today() + timedelta(days=10)).isoformat()
        memory_store.store_delegation(Delegation(
            task="Future task", delegated_to="charlie", due_date=future_date,
        ))
        result = engine._check_overdue_delegations()
        assert result == []

    def test_completed_delegation_not_returned(self, memory_store, engine):
        past_date = (date.today() - timedelta(days=5)).isoformat()
        d = memory_store.store_delegation(Delegation(
            task="Done task", delegated_to="dave", due_date=past_date,
        ))
        memory_store.update_delegation(d.id, status="completed")
        result = engine._check_overdue_delegations()
        assert result == []


class TestCheckStaleDecisions:
    def test_no_stale_decisions(self, engine):
        result = engine._check_stale_decisions()
        assert result == []

    def test_stale_decision_returned(self, memory_store, engine):
        # Insert a decision with old created_at
        d = memory_store.store_decision(Decision(title="Old decision"))
        # Manually backdating via SQL since store_decision uses now()
        old_date = (date.today() - timedelta(days=10)).isoformat()
        memory_store.conn.execute(
            "UPDATE decisions SET created_at=? WHERE id=?",
            (old_date, d.id),
        )
        memory_store.conn.commit()

        result = engine._check_stale_decisions()
        assert len(result) == 1
        assert result[0].category == "decision"
        assert result[0].priority == "medium"
        assert "Old decision" in result[0].title

    def test_recent_decision_not_returned(self, memory_store, engine):
        memory_store.store_decision(Decision(title="Fresh decision"))
        result = engine._check_stale_decisions()
        assert result == []

    def test_executed_decision_not_returned(self, memory_store, engine):
        d = memory_store.store_decision(Decision(title="Executed decision"))
        memory_store.update_decision(d.id, status="executed")
        # Backdate it
        old_date = (date.today() - timedelta(days=10)).isoformat()
        memory_store.conn.execute(
            "UPDATE decisions SET created_at=? WHERE id=?",
            (old_date, d.id),
        )
        memory_store.conn.commit()
        result = engine._check_stale_decisions()
        assert result == []


class TestCheckUpcomingDeadlines:
    def test_no_upcoming_deadlines(self, engine):
        result = engine._check_upcoming_deadlines()
        assert result == []

    def test_upcoming_deadline_returned(self, memory_store, engine):
        soon = (date.today() + timedelta(days=2)).isoformat()
        memory_store.store_delegation(Delegation(
            task="Urgent task", delegated_to="eve", due_date=soon,
        ))
        result = engine._check_upcoming_deadlines()
        assert len(result) == 1
        assert result[0].category == "deadline"
        assert result[0].priority == "high"
        assert "Urgent task" in result[0].title
        assert "2d" in result[0].title

    def test_today_deadline_returned(self, memory_store, engine):
        today = date.today().isoformat()
        memory_store.store_delegation(Delegation(
            task="Today task", delegated_to="frank", due_date=today,
        ))
        result = engine._check_upcoming_deadlines()
        assert len(result) == 1
        assert "0d" in result[0].title

    def test_far_future_deadline_not_returned(self, memory_store, engine):
        far = (date.today() + timedelta(days=30)).isoformat()
        memory_store.store_delegation(Delegation(
            task="Far task", delegated_to="grace", due_date=far,
        ))
        result = engine._check_upcoming_deadlines()
        assert result == []

    def test_past_deadline_not_returned_as_upcoming(self, memory_store, engine):
        """Past deadlines appear in overdue, not upcoming."""
        past = (date.today() - timedelta(days=1)).isoformat()
        memory_store.store_delegation(Delegation(
            task="Past task", delegated_to="heidi", due_date=past,
        ))
        result = engine._check_upcoming_deadlines()
        assert result == []


class TestCheckSessionCheckpointNeeded:
    def test_no_session_health_returns_empty(self, memory_store):
        engine = ProactiveSuggestionEngine(memory_store, session_health=None)
        result = engine._check_session_checkpoint_needed()
        assert result == []

    def test_low_tool_calls_returns_empty(self, memory_store):
        health = SessionHealth(tool_call_count=10)
        engine = ProactiveSuggestionEngine(memory_store, session_health=health)
        result = engine._check_session_checkpoint_needed()
        assert result == []

    def test_high_calls_no_checkpoint_returns_suggestion(self, memory_store):
        health = SessionHealth(tool_call_count=60)
        engine = ProactiveSuggestionEngine(memory_store, session_health=health)
        result = engine._check_session_checkpoint_needed()
        assert len(result) == 1
        assert result[0].category == "checkpoint"
        assert result[0].priority == "medium"
        assert result[0].action == "checkpoint_session"
        assert "60 tool calls" in result[0].description
        assert "no checkpoint yet" in result[0].description

    def test_high_calls_stale_checkpoint_returns_suggestion(self, memory_store):
        old_time = (datetime.now() - timedelta(minutes=45)).isoformat()
        health = SessionHealth(tool_call_count=55, last_checkpoint=old_time)
        engine = ProactiveSuggestionEngine(memory_store, session_health=health)
        result = engine._check_session_checkpoint_needed()
        assert len(result) == 1
        assert "last checkpoint over 30 min ago" in result[0].description

    def test_high_calls_recent_checkpoint_returns_empty(self, memory_store):
        recent = (datetime.now() - timedelta(minutes=5)).isoformat()
        health = SessionHealth(tool_call_count=100, last_checkpoint=recent)
        engine = ProactiveSuggestionEngine(memory_store, session_health=health)
        result = engine._check_session_checkpoint_needed()
        assert result == []

    def test_exactly_50_calls_triggers(self, memory_store):
        health = SessionHealth(tool_call_count=50)
        engine = ProactiveSuggestionEngine(memory_store, session_health=health)
        result = engine._check_session_checkpoint_needed()
        assert len(result) == 1

    def test_49_calls_does_not_trigger(self, memory_store):
        health = SessionHealth(tool_call_count=49)
        engine = ProactiveSuggestionEngine(memory_store, session_health=health)
        result = engine._check_session_checkpoint_needed()
        assert result == []

    def test_checkpoint_suggestion_appears_in_generate_suggestions(self, memory_store):
        health = SessionHealth(tool_call_count=60)
        engine = ProactiveSuggestionEngine(memory_store, session_health=health)
        suggestions = engine.generate_suggestions()
        checkpoint_suggestions = [s for s in suggestions if s.category == "checkpoint"]
        assert len(checkpoint_suggestions) == 1


class TestSessionBrainChecks:
    def test_no_brain_returns_empty(self, memory_store):
        engine = ProactiveSuggestionEngine(memory_store, session_brain=None)
        suggestions = engine._check_session_brain_items()
        assert suggestions == []

    def test_open_action_items_suggestion(self, memory_store, tmp_path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_action_item("File IC3 report", source="email")
        brain.add_action_item("Review PR", source="session")
        engine = ProactiveSuggestionEngine(memory_store, session_brain=brain)
        suggestions = engine._check_session_brain_items()
        found = [s for s in suggestions if "action item" in s.title.lower()]
        assert len(found) == 1
        assert "2" in found[0].title

    def test_completed_items_not_surfaced(self, memory_store, tmp_path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_action_item("Done task")
        brain.complete_action_item("Done task")
        engine = ProactiveSuggestionEngine(memory_store, session_brain=brain)
        suggestions = engine._check_session_brain_items()
        action_suggestions = [s for s in suggestions if "action item" in s.title.lower()]
        assert len(action_suggestions) == 0

    def test_active_workstreams_suggestion(self, memory_store, tmp_path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_workstream("Project X", "active", "Phase 1")
        brain.add_workstream("Project Y", "completed", "Done")
        engine = ProactiveSuggestionEngine(memory_store, session_brain=brain)
        suggestions = engine._check_session_brain_items()
        ws_suggestions = [s for s in suggestions if "workstream" in s.title.lower()]
        assert len(ws_suggestions) == 1
        assert "1" in ws_suggestions[0].title  # only 1 active

    def test_brain_items_in_generate_suggestions(self, memory_store, tmp_path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_action_item("Test item")
        engine = ProactiveSuggestionEngine(memory_store, session_brain=brain)
        suggestions = engine.generate_suggestions()
        assert any("action item" in s.title.lower() for s in suggestions)
