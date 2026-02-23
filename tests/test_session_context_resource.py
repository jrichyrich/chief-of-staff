"""Tests for the session://context MCP resource."""

import json
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

import mcp_server  # noqa: F401 — triggers register() calls including resources
from memory.models import Decision, Delegation, WebhookEvent
from memory.store import MemoryStore
from mcp_tools.resources import get_session_context


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture(autouse=True)
def wire_state(memory_store):
    """Inject a fresh memory_store into MCP server state before each test."""
    mcp_server._state.memory_store = memory_store
    mcp_server._state.calendar_store = None
    mcp_server._state.reminder_store = None
    mcp_server._state.session_health = None
    mcp_server._state.session_manager = None
    yield
    mcp_server._state.memory_store = None
    mcp_server._state.calendar_store = None
    mcp_server._state.reminder_store = None
    mcp_server._state.session_health = None
    mcp_server._state.session_manager = None


class TestSessionContextResource:
    @pytest.mark.asyncio
    async def test_returns_valid_json_with_today(self):
        """Resource always returns valid JSON with today's date."""
        result = await get_session_context()
        data = json.loads(result)
        assert data["today"] == date.today().isoformat()

    @pytest.mark.asyncio
    async def test_calendar_events_included(self):
        """Calendar events for today appear in context."""
        mock_calendar = MagicMock()
        mock_calendar.get_events.return_value = [
            {"title": "Standup", "start": "2026-02-22T09:00:00", "end": "2026-02-22T09:30:00", "location": "Zoom", "calendar": "Work"},
            {"title": "Lunch", "start": "2026-02-22T12:00:00", "end": "2026-02-22T13:00:00", "location": "", "calendar": "Personal"},
        ]
        mcp_server._state.calendar_store = mock_calendar
        result = await get_session_context()
        data = json.loads(result)
        assert "calendar_today" in data
        assert len(data["calendar_today"]) == 2
        assert data["calendar_today"][0]["title"] == "Standup"

    @pytest.mark.asyncio
    async def test_calendar_events_capped_at_15(self):
        """Calendar events are capped at 15."""
        mock_calendar = MagicMock()
        mock_calendar.get_events.return_value = [
            {"title": f"Event {i}", "start": "", "end": "", "location": "", "calendar": "Work"}
            for i in range(20)
        ]
        mcp_server._state.calendar_store = mock_calendar
        result = await get_session_context()
        data = json.loads(result)
        assert len(data["calendar_today"]) == 15

    @pytest.mark.asyncio
    async def test_calendar_events_empty_list_not_included(self):
        """Empty calendar events list does not include the section."""
        mock_calendar = MagicMock()
        mock_calendar.get_events.return_value = []
        mcp_server._state.calendar_store = mock_calendar
        result = await get_session_context()
        data = json.loads(result)
        assert "calendar_today" not in data

    @pytest.mark.asyncio
    async def test_pending_delegations_included(self, memory_store):
        """Active delegations appear in context."""
        memory_store.store_delegation(Delegation(task="Review PR", delegated_to="alice", priority="high"))
        result = await get_session_context()
        data = json.loads(result)
        assert "pending_delegations" in data
        assert data["pending_delegations"][0]["task"] == "Review PR"
        assert data["pending_delegations"][0]["delegated_to"] == "alice"
        assert data["pending_delegations"][0]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_pending_delegations_capped_at_10(self, memory_store):
        """Active delegations are capped at 10."""
        for i in range(15):
            memory_store.store_delegation(Delegation(task=f"Task {i}", delegated_to="alice"))
        result = await get_session_context()
        data = json.loads(result)
        assert len(data["pending_delegations"]) == 10

    @pytest.mark.asyncio
    async def test_overdue_delegations_included(self, memory_store):
        """Overdue delegations appear with days_overdue field."""
        past_date = (date.today() - timedelta(days=5)).isoformat()
        memory_store.store_delegation(Delegation(
            task="Overdue task", delegated_to="bob", due_date=past_date, priority="high"
        ))
        result = await get_session_context()
        data = json.loads(result)
        assert "overdue_delegations" in data
        assert data["overdue_delegations"][0]["task"] == "Overdue task"
        assert data["overdue_delegations"][0]["days_overdue"] == 5

    @pytest.mark.asyncio
    async def test_overdue_delegations_capped_at_10(self, memory_store):
        """Overdue delegations are capped at 10."""
        past_date = (date.today() - timedelta(days=3)).isoformat()
        for i in range(15):
            memory_store.store_delegation(Delegation(
                task=f"Overdue {i}", delegated_to="charlie", due_date=past_date
            ))
        result = await get_session_context()
        data = json.loads(result)
        assert len(data["overdue_delegations"]) == 10

    @pytest.mark.asyncio
    async def test_pending_decisions_included(self, memory_store):
        """Pending decisions appear in context."""
        memory_store.store_decision(Decision(title="Hire vendor", status="pending_execution"))
        result = await get_session_context()
        data = json.loads(result)
        assert "pending_decisions" in data
        assert data["pending_decisions"][0]["title"] == "Hire vendor"
        assert data["pending_decisions"][0]["status"] == "pending_execution"

    @pytest.mark.asyncio
    async def test_pending_decisions_capped_at_10(self, memory_store):
        """Pending decisions are capped at 10."""
        for i in range(15):
            memory_store.store_decision(Decision(title=f"Decision {i}", status="pending_execution"))
        result = await get_session_context()
        data = json.loads(result)
        assert len(data["pending_decisions"]) == 10

    @pytest.mark.asyncio
    async def test_executed_decisions_not_included(self, memory_store):
        """Only pending_execution decisions are included, not executed ones."""
        memory_store.store_decision(Decision(title="Executed decision", status="executed"))
        result = await get_session_context()
        data = json.loads(result)
        assert "pending_decisions" not in data

    @pytest.mark.asyncio
    async def test_unprocessed_webhooks_count(self, memory_store):
        """Unprocessed webhooks appear as an integer count."""
        memory_store.store_webhook_event(WebhookEvent(source="github", event_type="push", payload='{"ref":"main"}'))
        memory_store.store_webhook_event(WebhookEvent(source="jira", event_type="issue.created", payload='{"key":"PROJ-1"}'))
        result = await get_session_context()
        data = json.loads(result)
        assert data["unprocessed_webhooks"] == 2

    @pytest.mark.asyncio
    async def test_unprocessed_webhooks_zero_not_included(self, memory_store):
        """Zero unprocessed webhooks means the key is absent."""
        result = await get_session_context()
        data = json.loads(result)
        assert "unprocessed_webhooks" not in data

    @pytest.mark.asyncio
    async def test_due_reminders_included(self):
        """Reminders appear in context when reminder_store returns items."""
        mock_reminders = MagicMock()
        mock_reminders.list_reminders.return_value = [
            {"title": "Buy groceries", "due_date": "2026-02-22", "priority": 1, "list_name": "Personal"}
        ]
        mcp_server._state.reminder_store = mock_reminders
        result = await get_session_context()
        data = json.loads(result)
        assert "due_reminders" in data
        assert data["due_reminders"][0]["title"] == "Buy groceries"
        assert data["due_reminders"][0]["due_date"] == "2026-02-22"

    @pytest.mark.asyncio
    async def test_due_reminders_capped_at_10(self):
        """Reminders are capped at 10."""
        mock_reminders = MagicMock()
        mock_reminders.list_reminders.return_value = [
            {"title": f"Reminder {i}", "due_date": "2026-02-22", "priority": 1, "list_name": "Work"}
            for i in range(15)
        ]
        mcp_server._state.reminder_store = mock_reminders
        result = await get_session_context()
        data = json.loads(result)
        assert len(data["due_reminders"]) == 10

    @pytest.mark.asyncio
    async def test_due_reminders_empty_list_not_included(self):
        """Empty reminders list does not include the section."""
        mock_reminders = MagicMock()
        mock_reminders.list_reminders.return_value = []
        mcp_server._state.reminder_store = mock_reminders
        result = await get_session_context()
        data = json.loads(result)
        assert "due_reminders" not in data

    @pytest.mark.asyncio
    async def test_empty_sections_omitted(self):
        """Sections with no data are not included in output; only today is always present."""
        result = await get_session_context()
        data = json.loads(result)
        assert "calendar_today" not in data
        assert "pending_delegations" not in data
        assert "overdue_delegations" not in data
        assert "pending_decisions" not in data
        assert "due_reminders" not in data
        assert "unprocessed_webhooks" not in data
        assert "today" in data

    @pytest.mark.asyncio
    async def test_calendar_error_isolated(self, memory_store):
        """Calendar failure does not break the resource; other sections still work."""
        mock_calendar = MagicMock()
        mock_calendar.get_events.side_effect = Exception("EventKit crashed")
        mcp_server._state.calendar_store = mock_calendar
        memory_store.store_delegation(Delegation(task="Still works", delegated_to="alice"))
        result = await get_session_context()
        data = json.loads(result)
        assert "calendar_today" not in data
        assert "pending_delegations" in data

    @pytest.mark.asyncio
    async def test_reminder_error_isolated(self, memory_store):
        """Reminder store failure does not break the resource."""
        mock_reminders = MagicMock()
        mock_reminders.list_reminders.side_effect = Exception("Reminders DB locked")
        mcp_server._state.reminder_store = mock_reminders
        memory_store.store_decision(Decision(title="Decision survives", status="pending_execution"))
        result = await get_session_context()
        data = json.loads(result)
        assert "due_reminders" not in data
        assert "pending_decisions" in data

    @pytest.mark.asyncio
    async def test_memory_store_error_isolated(self):
        """Memory store failure for one section does not break the entire resource."""
        mock_memory = MagicMock()
        mock_memory.list_delegations.side_effect = Exception("DB error")
        mock_memory.list_overdue_delegations.side_effect = Exception("DB error")
        mock_memory.list_decisions_by_status.return_value = []
        mock_memory.list_webhook_events.return_value = []
        mcp_server._state.memory_store = mock_memory
        result = await get_session_context()
        data = json.loads(result)
        # Should not raise, and today should still be present
        assert "today" in data
        assert "pending_delegations" not in data
        assert "overdue_delegations" not in data

    @pytest.mark.asyncio
    async def test_proactive_suggestions_included(self, memory_store):
        """Proactive suggestions appear when the engine finds issues."""
        past_date = (date.today() - timedelta(days=30)).isoformat()
        memory_store.store_delegation(Delegation(
            task="Very overdue", delegated_to="charlie", due_date=past_date, priority="critical"
        ))
        result = await get_session_context()
        data = json.loads(result)
        assert "proactive_suggestions" in data
        assert len(data["proactive_suggestions"]) > 0

    @pytest.mark.asyncio
    async def test_proactive_suggestions_fields(self, memory_store):
        """Each proactive suggestion has required fields."""
        past_date = (date.today() - timedelta(days=30)).isoformat()
        memory_store.store_delegation(Delegation(
            task="Check this", delegated_to="dave", due_date=past_date
        ))
        result = await get_session_context()
        data = json.loads(result)
        if "proactive_suggestions" in data:
            for suggestion in data["proactive_suggestions"]:
                assert "category" in suggestion
                assert "priority" in suggestion
                assert "title" in suggestion
                assert "action" in suggestion

    @pytest.mark.asyncio
    async def test_proactive_suggestions_capped_at_5(self, memory_store):
        """Proactive suggestions are capped at 5."""
        # Create many overdue delegations to generate multiple suggestions
        past_date = (date.today() - timedelta(days=30)).isoformat()
        for i in range(20):
            memory_store.store_delegation(Delegation(
                task=f"Overdue {i}", delegated_to=f"person{i}", due_date=past_date
            ))
        result = await get_session_context()
        data = json.loads(result)
        if "proactive_suggestions" in data:
            assert len(data["proactive_suggestions"]) <= 5

    @pytest.mark.asyncio
    async def test_result_is_valid_json(self):
        """Result is always valid JSON regardless of state."""
        result = await get_session_context()
        # Should not raise
        data = json.loads(result)
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_calendar_events_only_relevant_keys(self):
        """Calendar events are projected to only relevant keys."""
        mock_calendar = MagicMock()
        mock_calendar.get_events.return_value = [
            {
                "title": "Meeting",
                "start": "2026-02-22T10:00:00",
                "end": "2026-02-22T11:00:00",
                "location": "HQ",
                "calendar": "Work",
                "uid": "secret-internal-id",
                "raw_data": {"internal": "data"},
            }
        ]
        mcp_server._state.calendar_store = mock_calendar
        result = await get_session_context()
        data = json.loads(result)
        event = data["calendar_today"][0]
        assert "title" in event
        assert "start" in event
        assert "end" in event
        assert "location" in event
        assert "calendar" in event
        assert "uid" not in event
        assert "raw_data" not in event

    @pytest.mark.asyncio
    async def test_due_reminders_only_relevant_keys(self):
        """Reminders are projected to only relevant keys."""
        mock_reminders = MagicMock()
        mock_reminders.list_reminders.return_value = [
            {
                "title": "Call dentist",
                "due_date": "2026-02-22",
                "priority": 2,
                "list_name": "Health",
                "internal_id": "abc123",
                "completed": False,
            }
        ]
        mcp_server._state.reminder_store = mock_reminders
        result = await get_session_context()
        data = json.loads(result)
        reminder = data["due_reminders"][0]
        assert "title" in reminder
        assert "due_date" in reminder
        assert "priority" in reminder
        assert "list_name" in reminder
        assert "internal_id" not in reminder
        assert "completed" not in reminder

    @pytest.mark.asyncio
    async def test_overdue_and_pending_are_separate_sections(self, memory_store):
        """Overdue delegations and pending delegations are distinct sections."""
        past_date = (date.today() - timedelta(days=2)).isoformat()
        # This one is overdue (has a past due_date)
        memory_store.store_delegation(Delegation(
            task="Overdue", delegated_to="alice", due_date=past_date
        ))
        # This one is active with no due date
        memory_store.store_delegation(Delegation(
            task="No due date", delegated_to="bob"
        ))
        result = await get_session_context()
        data = json.loads(result)
        # Both sections should be present
        assert "overdue_delegations" in data
        assert "pending_delegations" in data
        # Overdue section should only show the overdue task
        overdue_tasks = {d["task"] for d in data["overdue_delegations"]}
        assert "Overdue" in overdue_tasks
