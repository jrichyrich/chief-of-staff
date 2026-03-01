import pytest
from unittest.mock import MagicMock, patch
from proactive.models import Suggestion


@pytest.fixture
def memory_store(tmp_path):
    from memory.store import MemoryStore
    return MemoryStore(tmp_path / "test.db")


def _make_suggestion(category, action, priority="high"):
    return Suggestion(
        category=category,
        priority=priority,
        title=f"Test {category}",
        description=f"Test {category} description",
        action=action,
    )


def test_execute_checkpoint_action(memory_store):
    from proactive.action_executor import execute_suggestion_action

    session_manager = MagicMock()
    session_manager.flush_to_memory.return_value = {"flushed": 3}

    suggestion = _make_suggestion("checkpoint", "checkpoint_session")
    with patch("config.PROACTIVE_ACTION_ENABLED", True):
        result = execute_suggestion_action(
            suggestion, memory_store=memory_store, session_manager=session_manager,
        )
    assert result["executed"] is True
    assert result["action"] == "checkpoint_session"


def test_execute_webhook_action(memory_store):
    from memory.models import WebhookEvent
    from proactive.action_executor import execute_suggestion_action

    # Store a pending webhook event
    memory_store.store_webhook_event(
        WebhookEvent(source="github", event_type="push", payload='{"ref": "main"}')
    )
    events = memory_store.list_webhook_events(status="pending")
    assert len(events) >= 1

    suggestion = _make_suggestion("webhook", "list_webhook_events")
    with patch("config.PROACTIVE_ACTION_ENABLED", True):
        result = execute_suggestion_action(suggestion, memory_store=memory_store)
    assert result["executed"] is True


def test_skip_disallowed_category():
    from proactive.action_executor import execute_suggestion_action

    suggestion = _make_suggestion("skill", "auto_create_skill")
    with patch("config.PROACTIVE_ACTION_ENABLED", True):
        with patch("config.PROACTIVE_ACTION_CATEGORIES", frozenset({"checkpoint"})):
            result = execute_suggestion_action(suggestion, memory_store=MagicMock())
    assert result["executed"] is False
    assert "not in allowed categories" in result["reason"]


def test_skip_when_disabled():
    from proactive.action_executor import execute_suggestion_action

    suggestion = _make_suggestion("checkpoint", "checkpoint_session")
    with patch("config.PROACTIVE_ACTION_ENABLED", False):
        result = execute_suggestion_action(suggestion, memory_store=MagicMock())
    assert result["executed"] is False
