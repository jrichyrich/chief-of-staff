"""Tests for session/context_loader.py."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from session.context_config import ContextLoaderConfig
from session.context_loader import (
    SessionContext,
    load_session_context,
    _fetch_calendar,
    _fetch_mail_count,
    _fetch_overdue_delegations,
    _fetch_pending_decisions,
    _fetch_due_reminders,
    _fetch_brain_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**overrides) -> MagicMock:
    """Create a mock ServerState with sensible defaults."""
    state = MagicMock()
    state.calendar_store = overrides.get("calendar_store", MagicMock())
    state.mail_store = overrides.get("mail_store", MagicMock())
    state.memory_store = overrides.get("memory_store", MagicMock())
    state.reminder_store = overrides.get("reminder_store", MagicMock())
    state.session_brain = overrides.get("session_brain", MagicMock())
    return state


# ---------------------------------------------------------------------------
# SessionContext dataclass tests
# ---------------------------------------------------------------------------

class TestSessionContext:
    def test_to_dict_serialization(self):
        """to_dict returns all expected keys as a JSON-serializable dict."""
        ctx = SessionContext(
            loaded_at="2026-03-01T08:00:00",
            calendar_events=[{"title": "Standup"}],
            unread_mail_count=3,
            overdue_delegations=[{"id": 1, "task": "Review PR"}],
            pending_decisions=[{"id": 2, "title": "Choose DB"}],
            due_reminders=[{"name": "Submit report"}],
            session_brain_summary={"active_workstreams": []},
            errors={"mail": "Timeout"},
        )

        d = ctx.to_dict()

        assert d["loaded_at"] == "2026-03-01T08:00:00"
        assert d["calendar_events"] == [{"title": "Standup"}]
        assert d["unread_mail_count"] == 3
        assert d["overdue_delegations"] == [{"id": 1, "task": "Review PR"}]
        assert d["pending_decisions"] == [{"id": 2, "title": "Choose DB"}]
        assert d["due_reminders"] == [{"name": "Submit report"}]
        assert d["session_brain_summary"] == {"active_workstreams": []}
        assert d["errors"] == {"mail": "Timeout"}

    def test_to_dict_excludes_private_fields(self):
        """_ttl_minutes should not appear in to_dict output."""
        ctx = SessionContext(loaded_at="2026-03-01T08:00:00", _ttl_minutes=30)
        d = ctx.to_dict()
        assert "_ttl_minutes" not in d

    def test_is_stale_within_ttl(self):
        """Context loaded recently is not stale."""
        ctx = SessionContext(
            loaded_at=datetime.now().isoformat(),
            _ttl_minutes=15,
        )
        assert ctx.is_stale is False

    def test_is_stale_after_ttl(self):
        """Context loaded longer than TTL ago is stale."""
        old_time = (datetime.now() - timedelta(minutes=20)).isoformat()
        ctx = SessionContext(loaded_at=old_time, _ttl_minutes=15)
        assert ctx.is_stale is True

    def test_is_stale_empty_loaded_at(self):
        """Empty loaded_at is always stale."""
        ctx = SessionContext(loaded_at="")
        assert ctx.is_stale is True

    def test_is_stale_invalid_loaded_at(self):
        """Invalid loaded_at is treated as stale."""
        ctx = SessionContext(loaded_at="not-a-date")
        assert ctx.is_stale is True

    def test_default_values(self):
        """Default SessionContext has empty lists and zero counts."""
        ctx = SessionContext()
        assert ctx.loaded_at == ""
        assert ctx.calendar_events == []
        assert ctx.unread_mail_count == 0
        assert ctx.overdue_delegations == []
        assert ctx.pending_decisions == []
        assert ctx.due_reminders == []
        assert ctx.session_brain_summary == {}
        assert ctx.errors == {}


# ---------------------------------------------------------------------------
# Individual fetcher tests
# ---------------------------------------------------------------------------

class TestFetchCalendar:
    def test_returns_events(self):
        """Fetches today's events from calendar store."""
        state = _make_state()
        state.calendar_store.get_events.return_value = [
            {"title": "Standup", "start": "09:00"},
            {"title": "1:1", "start": "10:00"},
        ]

        result = _fetch_calendar(state)

        assert len(result) == 2
        assert result[0]["title"] == "Standup"

        # Verify it was called with today's date range and both providers
        call_kwargs = state.calendar_store.get_events.call_args[1]
        assert call_kwargs["provider_preference"] == "both"
        assert call_kwargs["start_dt"].hour == 0
        assert call_kwargs["start_dt"].minute == 0

    def test_caps_at_50_events(self):
        """Calendar events are capped at 50."""
        state = _make_state()
        state.calendar_store.get_events.return_value = [{"title": f"Event {i}"} for i in range(100)]

        result = _fetch_calendar(state)
        assert len(result) == 50

    def test_returns_empty_if_store_is_none(self):
        """Returns empty list when calendar_store is None."""
        state = _make_state(calendar_store=None)
        assert _fetch_calendar(state) == []


class TestFetchMailCount:
    def test_sums_unread_counts(self):
        """Sums unread counts across mailboxes."""
        state = _make_state()
        state.mail_store.list_mailboxes.return_value = [
            {"name": "INBOX", "unread_count": 5},
            {"name": "Junk", "unread_count": 2},
        ]

        assert _fetch_mail_count(state) == 7

    def test_handles_non_int_unread(self):
        """Skips non-integer unread counts."""
        state = _make_state()
        state.mail_store.list_mailboxes.return_value = [
            {"name": "INBOX", "unread_count": "bad"},
            {"name": "Sent", "unread_count": 3},
        ]

        assert _fetch_mail_count(state) == 3

    def test_returns_zero_if_store_is_none(self):
        """Returns 0 when mail_store is None."""
        state = _make_state(mail_store=None)
        assert _fetch_mail_count(state) == 0


class TestFetchOverdueDelegations:
    def test_serializes_delegations(self):
        """Overdue delegations are serialized to dicts with expected keys."""
        state = _make_state()

        delegation = MagicMock()
        delegation.id = 42
        delegation.task = "Review security doc"
        delegation.delegated_to = "Alice"
        delegation.due_date = "2026-02-28"
        delegation.priority = "high"

        state.memory_store.list_overdue_delegations.return_value = [delegation]

        result = _fetch_overdue_delegations(state)

        assert len(result) == 1
        assert result[0]["id"] == 42
        assert result[0]["task"] == "Review security doc"
        assert result[0]["delegated_to"] == "Alice"
        assert result[0]["due_date"] == "2026-02-28"
        assert result[0]["priority"] == "high"

    def test_returns_empty_if_store_is_none(self):
        """Returns empty list when memory_store is None."""
        state = _make_state(memory_store=None)
        assert _fetch_overdue_delegations(state) == []


class TestFetchPendingDecisions:
    def test_serializes_decisions(self):
        """Pending decisions are serialized with expected keys."""
        state = _make_state()

        decision = MagicMock()
        decision.id = 99
        decision.title = "Choose cloud provider"
        decision.owner = "Jason"
        decision.follow_up_date = "2026-03-05"

        state.memory_store.list_decisions_by_status.return_value = [decision]

        result = _fetch_pending_decisions(state)

        assert len(result) == 1
        assert result[0]["id"] == 99
        assert result[0]["title"] == "Choose cloud provider"
        assert result[0]["owner"] == "Jason"

        # Verify correct status filter was used
        from memory.models import DecisionStatus
        state.memory_store.list_decisions_by_status.assert_called_once_with(
            DecisionStatus.pending_execution,
        )

    def test_returns_empty_if_store_is_none(self):
        """Returns empty list when memory_store is None."""
        state = _make_state(memory_store=None)
        assert _fetch_pending_decisions(state) == []


class TestFetchDueReminders:
    def test_filters_to_today_or_overdue(self):
        """Only reminders due today or earlier are included."""
        state = _make_state()

        today = datetime.now().date().isoformat()
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()

        state.reminder_store.list_reminders.return_value = [
            {"name": "Today task", "due_date": today},
            {"name": "Overdue task", "due_date": yesterday},
            {"name": "Future task", "due_date": tomorrow},
            {"name": "No due date"},
        ]

        result = _fetch_due_reminders(state)

        names = [r["name"] for r in result]
        assert "Today task" in names
        assert "Overdue task" in names
        assert "Future task" not in names
        assert "No due date" not in names

    def test_handles_dueDate_key(self):
        """Also accepts 'dueDate' key (camelCase variant)."""
        state = _make_state()
        today = datetime.now().date().isoformat()
        state.reminder_store.list_reminders.return_value = [
            {"name": "CamelCase task", "dueDate": today},
        ]

        result = _fetch_due_reminders(state)
        assert len(result) == 1
        assert result[0]["name"] == "CamelCase task"

    def test_returns_empty_if_store_is_none(self):
        """Returns empty list when reminder_store is None."""
        state = _make_state(reminder_store=None)
        assert _fetch_due_reminders(state) == []

    def test_handles_exception(self):
        """Returns empty list if list_reminders raises."""
        state = _make_state()
        state.reminder_store.list_reminders.side_effect = RuntimeError("EventKit error")
        assert _fetch_due_reminders(state) == []


class TestFetchBrainSummary:
    def test_extracts_open_items(self):
        """Extracts active workstreams and open action items from brain."""
        state = _make_state()
        state.session_brain.to_dict.return_value = {
            "workstreams": [{"name": "Security audit", "status": "active"}],
            "action_items": [
                {"text": "Review PR", "done": False},
                {"text": "Send email", "done": True},
            ],
            "decisions": [{"text": "Use AWS"}, {"text": "Use Postgres"}],
            "handoff_notes": ["Check Jira"],
        }

        result = _fetch_brain_summary(state)

        assert len(result["active_workstreams"]) == 1
        assert len(result["open_action_items"]) == 1
        assert result["open_action_items"][0]["text"] == "Review PR"
        assert len(result["recent_decisions"]) == 2
        assert result["handoff_notes"] == ["Check Jira"]

    def test_returns_empty_if_brain_is_none(self):
        """Returns empty dict when session_brain is None."""
        state = _make_state(session_brain=None)
        assert _fetch_brain_summary(state) == {}

    def test_handles_missing_keys(self):
        """Handles brain data with missing keys gracefully."""
        state = _make_state()
        state.session_brain.to_dict.return_value = {}

        result = _fetch_brain_summary(state)

        assert result["active_workstreams"] == []
        assert result["open_action_items"] == []
        assert result["recent_decisions"] == []
        assert result["handoff_notes"] == []


# ---------------------------------------------------------------------------
# load_session_context tests
# ---------------------------------------------------------------------------

class TestLoadSessionContext:
    def test_load_all_sources_success(self):
        """All sources succeed and populate the context."""
        state = _make_state()

        # Calendar
        state.calendar_store.get_events.return_value = [{"title": "Meeting"}]
        # Mail
        state.mail_store.list_mailboxes.return_value = [{"unread_count": 4}]
        # Delegations
        deleg = MagicMock(id=1, task="Do thing", delegated_to="Bob", due_date="2026-02-28", priority="high")
        state.memory_store.list_overdue_delegations.return_value = [deleg]
        # Decisions
        dec = MagicMock(id=2, title="Pick DB", owner="Alice", follow_up_date="2026-03-05")
        state.memory_store.list_decisions_by_status.return_value = [dec]
        # Reminders
        today = datetime.now().date().isoformat()
        state.reminder_store.list_reminders.return_value = [
            {"name": "Due today", "due_date": today},
        ]
        # Brain
        state.session_brain.to_dict.return_value = {
            "workstreams": [{"name": "Security"}],
            "action_items": [{"text": "Review", "done": False}],
            "decisions": [],
            "handoff_notes": [],
        }

        config = ContextLoaderConfig()
        ctx = load_session_context(state, config)

        assert ctx.loaded_at != ""
        assert len(ctx.calendar_events) == 1
        assert ctx.unread_mail_count == 4
        assert len(ctx.overdue_delegations) == 1
        assert len(ctx.pending_decisions) == 1
        assert len(ctx.due_reminders) == 1
        assert "active_workstreams" in ctx.session_brain_summary
        assert ctx.errors == {}

    def test_source_timeout_captured_in_errors(self):
        """A slow source times out and the error is captured."""
        state = _make_state()

        # Make calendar hang
        def slow_get_events(**kwargs):
            time.sleep(5)
            return []

        state.calendar_store.get_events.side_effect = slow_get_events
        # Other stores return quickly
        state.mail_store.list_mailboxes.return_value = []
        state.memory_store.list_overdue_delegations.return_value = []
        state.memory_store.list_decisions_by_status.return_value = []
        state.reminder_store.list_reminders.return_value = []
        state.session_brain.to_dict.return_value = {}

        config = ContextLoaderConfig(per_source_timeout_seconds=1)
        ctx = load_session_context(state, config)

        assert "calendar" in ctx.errors
        assert "Timeout" in ctx.errors["calendar"]
        assert ctx.calendar_events == []
        # Other sources should still succeed
        assert "mail" not in ctx.errors

    def test_source_exception_captured_in_errors(self):
        """An exception in one source is captured; others still succeed."""
        state = _make_state()

        state.calendar_store.get_events.side_effect = OSError("Permission denied")
        state.mail_store.list_mailboxes.return_value = [{"unread_count": 2}]
        state.memory_store.list_overdue_delegations.return_value = []
        state.memory_store.list_decisions_by_status.return_value = []
        state.reminder_store.list_reminders.return_value = []
        state.session_brain.to_dict.return_value = {}

        ctx = load_session_context(state)

        assert "calendar" in ctx.errors
        assert "Permission denied" in ctx.errors["calendar"]
        assert ctx.unread_mail_count == 2

    def test_all_sources_fail_returns_defaults(self):
        """When all sources fail, context has empty defaults with errors dict.

        Note: reminders fetcher catches its own exceptions internally and returns [],
        so it won't appear in the errors dict (5 errors, not 6).
        """
        state = _make_state()

        state.calendar_store.get_events.side_effect = RuntimeError("cal fail")
        state.mail_store.list_mailboxes.side_effect = RuntimeError("mail fail")
        state.memory_store.list_overdue_delegations.side_effect = RuntimeError("deleg fail")
        state.memory_store.list_decisions_by_status.side_effect = RuntimeError("dec fail")
        state.reminder_store.list_reminders.side_effect = RuntimeError("rem fail")
        state.session_brain.to_dict.side_effect = RuntimeError("brain fail")

        ctx = load_session_context(state)

        assert ctx.calendar_events == []
        assert ctx.unread_mail_count == 0
        assert ctx.overdue_delegations == []
        assert ctx.pending_decisions == []
        assert ctx.due_reminders == []
        assert ctx.session_brain_summary == {}
        # Reminders fetcher catches its own exception, so only 5 of 6 propagate
        assert len(ctx.errors) == 5
        assert "calendar" in ctx.errors
        assert "mail" in ctx.errors
        assert "delegations" in ctx.errors
        assert "decisions" in ctx.errors
        assert "brain" in ctx.errors

    def test_disabled_sources_skipped(self):
        """Sources set to False in config are not fetched."""
        state = _make_state()

        # Only enable calendar
        config = ContextLoaderConfig(
            sources={
                "calendar": True,
                "mail": False,
                "delegations": False,
                "decisions": False,
                "reminders": False,
                "brain": False,
            }
        )
        state.calendar_store.get_events.return_value = [{"title": "Only event"}]

        ctx = load_session_context(state, config)

        assert len(ctx.calendar_events) == 1
        # Disabled sources should keep defaults
        assert ctx.unread_mail_count == 0
        # mail_store should NOT have been called
        state.mail_store.list_mailboxes.assert_not_called()

    def test_master_switch_disabled(self):
        """When enabled=False, returns context with defaults (no fetches)."""
        state = _make_state()

        config = ContextLoaderConfig(enabled=False)
        ctx = load_session_context(state, config)

        assert ctx.loaded_at != ""
        assert ctx.calendar_events == []
        assert ctx.unread_mail_count == 0
        state.calendar_store.get_events.assert_not_called()

    def test_default_config_used_when_none(self):
        """When config is None, default ContextLoaderConfig is used."""
        state = _make_state()
        state.calendar_store.get_events.return_value = []
        state.mail_store.list_mailboxes.return_value = []
        state.memory_store.list_overdue_delegations.return_value = []
        state.memory_store.list_decisions_by_status.return_value = []
        state.reminder_store.list_reminders.return_value = []
        state.session_brain.to_dict.return_value = {}

        ctx = load_session_context(state, None)

        assert ctx.loaded_at != ""
        assert ctx.errors == {}

    def test_ttl_passed_to_context(self):
        """TTL from config is propagated to SessionContext._ttl_minutes."""
        state = _make_state()
        state.calendar_store.get_events.return_value = []
        state.mail_store.list_mailboxes.return_value = []
        state.memory_store.list_overdue_delegations.return_value = []
        state.memory_store.list_decisions_by_status.return_value = []
        state.reminder_store.list_reminders.return_value = []
        state.session_brain.to_dict.return_value = {}

        config = ContextLoaderConfig(ttl_minutes=30)
        ctx = load_session_context(state, config)

        assert ctx._ttl_minutes == 30
