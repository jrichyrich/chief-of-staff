import pytest
from unittest.mock import MagicMock, patch
from scheduler.daemon import JarvisDaemon


@pytest.mark.asyncio
async def test_daemon_tick_runs_proactive_check():
    """When PROACTIVE_ACTION_ENABLED, daemon tick should check and act on suggestions."""
    mock_store = MagicMock()
    mock_store.get_due_tasks.return_value = []

    daemon = JarvisDaemon(memory_store=mock_store, tick_interval=60)

    mock_suggestion = MagicMock()
    mock_suggestion.category = "checkpoint"
    mock_suggestion.action = "checkpoint_session"
    mock_suggestion.priority = "high"

    with patch("config.PROACTIVE_ACTION_ENABLED", True):
        with patch("proactive.engine.ProactiveSuggestionEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.generate_suggestions.return_value = [mock_suggestion]
            MockEngine.return_value = mock_engine

            with patch("proactive.action_executor.execute_suggestion_action") as mock_exec:
                mock_exec.return_value = {"executed": True, "action": "checkpoint_session"}

                results = await daemon._tick()
                mock_exec.assert_called_once()


@pytest.mark.asyncio
async def test_daemon_tick_skips_proactive_when_disabled():
    """When PROACTIVE_ACTION_ENABLED is False, no proactive actions should run."""
    mock_store = MagicMock()
    mock_store.get_due_tasks.return_value = []

    daemon = JarvisDaemon(memory_store=mock_store, tick_interval=60)

    with patch("config.PROACTIVE_ACTION_ENABLED", False):
        with patch("proactive.action_executor.execute_suggestion_action") as mock_exec:
            results = await daemon._tick()
            mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_daemon_tick_only_acts_on_high_priority():
    """Only high-priority suggestions should trigger proactive action."""
    mock_store = MagicMock()
    mock_store.get_due_tasks.return_value = []

    daemon = JarvisDaemon(memory_store=mock_store, tick_interval=60)

    medium_suggestion = MagicMock()
    medium_suggestion.category = "decision"
    medium_suggestion.action = "list_pending_decisions"
    medium_suggestion.priority = "medium"

    with patch("config.PROACTIVE_ACTION_ENABLED", True):
        with patch("proactive.engine.ProactiveSuggestionEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.generate_suggestions.return_value = [medium_suggestion]
            MockEngine.return_value = mock_engine

            with patch("proactive.action_executor.execute_suggestion_action") as mock_exec:
                results = await daemon._tick()
                mock_exec.assert_not_called()  # Medium priority = no action
