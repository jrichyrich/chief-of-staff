"""Tests for proactive push notifications and skill auto-execution."""

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from agents.registry import AgentConfig, AgentRegistry
from memory.models import Delegation, SkillSuggestion
from memory.store import MemoryStore
from proactive.engine import ProactiveSuggestionEngine
from proactive.models import Suggestion


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def agent_registry(tmp_path):
    configs_dir = tmp_path / "agent_configs"
    configs_dir.mkdir()
    return AgentRegistry(configs_dir)


@pytest.fixture
def engine(memory_store):
    return ProactiveSuggestionEngine(memory_store)


# --- Part 1: Proactive push notifications ---


class TestPushSuggestions:
    def test_push_high_priority_sends_notification(self, engine):
        suggestions = [
            Suggestion(
                category="delegation",
                priority="high",
                title="Overdue: Write report",
                description="5 days overdue",
                action="check_overdue_delegations",
            ),
        ]
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            mock_send.return_value = {"status": "sent"}
            results = engine.push_suggestions(suggestions, push_threshold="high")

        assert len(results) == 1
        mock_send.assert_called_once_with(
            title="Jarvis: Delegation",
            message="Overdue: Write report",
            subtitle="HIGH",
        )

    def test_push_skips_low_priority_with_high_threshold(self, engine):
        suggestions = [
            Suggestion(
                category="webhook",
                priority="low",
                title="Unprocessed webhook",
                description="Some webhook event",
                action="list_webhook_events",
            ),
        ]
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            results = engine.push_suggestions(suggestions, push_threshold="high")

        assert len(results) == 0
        mock_send.assert_not_called()

    def test_push_skips_medium_priority_with_high_threshold(self, engine):
        suggestions = [
            Suggestion(
                category="skill",
                priority="medium",
                title="New skill suggestion",
                description="test",
                action="auto_create_skill",
            ),
        ]
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            results = engine.push_suggestions(suggestions, push_threshold="high")

        assert len(results) == 0
        mock_send.assert_not_called()

    def test_push_medium_threshold_includes_medium_and_high(self, engine):
        suggestions = [
            Suggestion(category="delegation", priority="high", title="High item",
                       description="high desc", action="check"),
            Suggestion(category="skill", priority="medium", title="Medium item",
                       description="med desc", action="check"),
            Suggestion(category="webhook", priority="low", title="Low item",
                       description="low desc", action="check"),
        ]
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            mock_send.return_value = {"status": "sent"}
            results = engine.push_suggestions(suggestions, push_threshold="medium")

        assert len(results) == 2
        assert mock_send.call_count == 2

    def test_push_low_threshold_includes_all(self, engine):
        suggestions = [
            Suggestion(category="delegation", priority="high", title="High",
                       description="desc", action="a"),
            Suggestion(category="skill", priority="medium", title="Medium",
                       description="desc", action="a"),
            Suggestion(category="webhook", priority="low", title="Low",
                       description="desc", action="a"),
        ]
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            mock_send.return_value = {"status": "sent"}
            results = engine.push_suggestions(suggestions, push_threshold="low")

        assert len(results) == 3

    def test_push_empty_suggestions(self, engine):
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            results = engine.push_suggestions([], push_threshold="high")

        assert results == []
        mock_send.assert_not_called()


class TestCheckAll:
    def test_check_all_without_push(self, memory_store, engine):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        memory_store.store_delegation(Delegation(
            task="overdue task", delegated_to="alice", due_date=yesterday,
        ))
        result = engine.check_all(push_enabled=False)
        assert len(result["suggestions"]) >= 1
        assert "pushed" not in result

    def test_check_all_with_push_enabled(self, memory_store, engine):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        memory_store.store_delegation(Delegation(
            task="overdue task", delegated_to="alice", due_date=yesterday,
        ))
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            mock_send.return_value = {"status": "sent"}
            result = engine.check_all(push_enabled=True, push_threshold="high")

        assert len(result["suggestions"]) >= 1
        assert "pushed" in result
        assert len(result["pushed"]) >= 1

    def test_check_all_no_suggestions_no_push(self, engine):
        with patch("apple_notifications.notifier.Notifier.send") as mock_send:
            result = engine.check_all(push_enabled=True)

        assert result["suggestions"] == []
        assert "pushed" not in result
        mock_send.assert_not_called()


# --- Part 2: Skill auto-execution ---


class TestAutoExecute:
    def test_auto_execute_above_threshold(self, memory_store, agent_registry):
        from skills.pattern_detector import PatternDetector

        memory_store.store_skill_suggestion(SkillSuggestion(
            description="Repeated calendar lookups",
            suggested_name="calendar_specialist",
            suggested_capabilities="calendar_read",
            confidence=0.95,
        ))

        mock_config = AgentConfig(
            name="calendar_specialist",
            description="Calendar specialist",
            system_prompt="You are a calendar specialist.",
            capabilities=["calendar_read"],
        )

        detector = PatternDetector(memory_store, auto_create_threshold=0.9)

        with patch("agents.factory.AgentFactory.create_agent") as mock_create:
            mock_create.return_value = mock_config
            created = detector.auto_execute(memory_store, agent_registry)

        assert created == ["calendar_specialist"]
        mock_create.assert_called_once_with("Repeated calendar lookups")

        # Verify suggestion status updated
        accepted = memory_store.list_skill_suggestions(status="accepted")
        assert len(accepted) == 1

    def test_auto_execute_below_threshold(self, memory_store, agent_registry):
        from skills.pattern_detector import PatternDetector

        memory_store.store_skill_suggestion(SkillSuggestion(
            description="Low confidence pattern",
            suggested_name="low_agent",
            suggested_capabilities="memory_read",
            confidence=0.5,
        ))

        detector = PatternDetector(memory_store, auto_create_threshold=0.9)

        with patch("agents.factory.AgentFactory.create_agent") as mock_create:
            created = detector.auto_execute(memory_store, agent_registry)

        assert created == []
        mock_create.assert_not_called()

        # Verify suggestion still pending
        pending = memory_store.list_skill_suggestions(status="pending")
        assert len(pending) == 1

    def test_auto_execute_mixed_confidence(self, memory_store, agent_registry):
        from skills.pattern_detector import PatternDetector

        # One above threshold, one below
        memory_store.store_skill_suggestion(SkillSuggestion(
            description="High confidence pattern",
            suggested_name="high_agent",
            confidence=0.95,
        ))
        memory_store.store_skill_suggestion(SkillSuggestion(
            description="Low confidence pattern",
            suggested_name="low_agent",
            confidence=0.5,
        ))

        mock_config = AgentConfig(
            name="high_agent", description="High agent",
            system_prompt="prompt", capabilities=["memory_read"],
        )

        detector = PatternDetector(memory_store, auto_create_threshold=0.9)

        with patch("agents.factory.AgentFactory.create_agent") as mock_create:
            mock_create.return_value = mock_config
            created = detector.auto_execute(memory_store, agent_registry)

        assert created == ["high_agent"]
        assert mock_create.call_count == 1

    def test_auto_execute_no_pending_suggestions(self, memory_store, agent_registry):
        from skills.pattern_detector import PatternDetector

        detector = PatternDetector(memory_store)

        with patch("agents.factory.AgentFactory.create_agent") as mock_create:
            created = detector.auto_execute(memory_store, agent_registry)

        assert created == []
        mock_create.assert_not_called()


# --- Config flag tests ---


class TestConfigFlags:
    @pytest.mark.asyncio
    async def test_auto_execute_skills_disabled(self, memory_store, agent_registry):
        import mcp_server
        from mcp_tools.skill_tools import auto_execute_skills

        mcp_server._state.memory_store = memory_store
        mcp_server._state.agent_registry = agent_registry
        try:
            with patch("config.SKILL_AUTO_EXECUTE_ENABLED", False):
                result = await auto_execute_skills()
        finally:
            mcp_server._state.memory_store = None
            mcp_server._state.agent_registry = None

        data = json.loads(result)
        assert data["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_auto_execute_skills_enabled(self, memory_store, agent_registry):
        import mcp_server
        from mcp_tools.skill_tools import auto_execute_skills

        memory_store.store_skill_suggestion(SkillSuggestion(
            description="High confidence pattern",
            suggested_name="auto_agent",
            confidence=0.95,
        ))

        mock_config = AgentConfig(
            name="auto_agent", description="Auto agent",
            system_prompt="prompt", capabilities=["memory_read"],
        )

        mcp_server._state.memory_store = memory_store
        mcp_server._state.agent_registry = agent_registry
        try:
            with patch("config.SKILL_AUTO_EXECUTE_ENABLED", True), \
                 patch("agents.factory.AgentFactory.create_agent") as mock_create:
                mock_create.return_value = mock_config
                result = await auto_execute_skills()
        finally:
            mcp_server._state.memory_store = None
            mcp_server._state.agent_registry = None

        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["agents_created"] == 1
        assert "auto_agent" in data["agent_names"]

    def test_proactive_push_handler_disabled(self, memory_store):
        from scheduler.engine import execute_handler

        with patch("config.PROACTIVE_PUSH_ENABLED", False):
            result = json.loads(execute_handler("proactive_push", "{}", memory_store=memory_store))

        assert result["status"] == "skipped"
        assert result["handler"] == "proactive_push"

    def test_proactive_push_handler_enabled(self, memory_store):
        from scheduler.engine import execute_handler

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        memory_store.store_delegation(Delegation(
            task="overdue task", delegated_to="alice", due_date=yesterday,
        ))

        with patch("config.PROACTIVE_PUSH_ENABLED", True), \
             patch("config.PROACTIVE_PUSH_THRESHOLD", "high"), \
             patch("apple_notifications.notifier.Notifier.send") as mock_send:
            mock_send.return_value = {"status": "sent"}
            result = json.loads(execute_handler("proactive_push", "{}", memory_store=memory_store))

        assert result["status"] == "ok"
        assert result["handler"] == "proactive_push"
        assert result["suggestions_count"] >= 1
        assert result["pushed_count"] >= 1

    def test_skill_auto_exec_handler_disabled(self, memory_store):
        from scheduler.engine import execute_handler

        with patch("config.SKILL_AUTO_EXECUTE_ENABLED", False):
            result = json.loads(execute_handler("skill_auto_exec", "{}", memory_store=memory_store))

        assert result["status"] == "skipped"
        assert result["handler"] == "skill_auto_exec"

    def test_skill_auto_exec_handler_enabled(self, memory_store, agent_registry):
        from scheduler.engine import execute_handler

        memory_store.store_skill_suggestion(SkillSuggestion(
            description="High confidence", suggested_name="test_agent", confidence=0.95,
        ))

        mock_config = AgentConfig(
            name="test_agent", description="Test",
            system_prompt="prompt", capabilities=["memory_read"],
        )

        with patch("config.SKILL_AUTO_EXECUTE_ENABLED", True), \
             patch("agents.factory.AgentFactory.create_agent") as mock_create:
            mock_create.return_value = mock_config
            result = json.loads(execute_handler(
                "skill_auto_exec", "{}",
                memory_store=memory_store, agent_registry=agent_registry,
            ))

        assert result["status"] == "ok"
        assert result["agents_created"] == 1
        assert "test_agent" in result["agent_names"]


# --- Part 3: Push via delivery channels ---


class TestPushViaDeliveryChannels:
    @patch("scheduler.delivery.deliver_result")
    def test_push_via_email(self, mock_deliver, memory_store):
        mock_deliver.return_value = {"status": "delivered"}
        engine = ProactiveSuggestionEngine(memory_store)
        suggestions = [Suggestion(
            category="delegation",
            priority="high",
            title="Overdue task",
            description="Task X is 3 days overdue",
            action="check_overdue_delegations",
        )]
        results = engine.push_via_channel(
            suggestions, channel="email",
            config={"to": ["jason@test.com"]},
        )
        assert len(results) == 1
        mock_deliver.assert_called_once()

    @patch("scheduler.delivery.deliver_result")
    def test_push_filters_by_threshold(self, mock_deliver, memory_store):
        mock_deliver.return_value = {"status": "delivered"}
        engine = ProactiveSuggestionEngine(memory_store)
        suggestions = [
            Suggestion(category="delegation", priority="high",
                       title="High", description="", action=""),
            Suggestion(category="skill", priority="low",
                       title="Low", description="", action=""),
        ]
        results = engine.push_via_channel(
            suggestions, channel="email",
            config={"to": ["jason@test.com"]},
            push_threshold="high",
        )
        assert len(results) == 1

    @patch("scheduler.delivery.deliver_result")
    def test_push_medium_threshold_includes_medium(self, mock_deliver, memory_store):
        mock_deliver.return_value = {"status": "delivered"}
        engine = ProactiveSuggestionEngine(memory_store)
        suggestions = [
            Suggestion(category="delegation", priority="high",
                       title="High", description="", action=""),
            Suggestion(category="decision", priority="medium",
                       title="Medium", description="", action=""),
            Suggestion(category="skill", priority="low",
                       title="Low", description="", action=""),
        ]
        results = engine.push_via_channel(
            suggestions, channel="imessage",
            config={"recipient": "+18015551234"},
            push_threshold="medium",
        )
        assert len(results) == 2

    @patch("scheduler.delivery.deliver_result")
    def test_push_empty_suggestions(self, mock_deliver, memory_store):
        engine = ProactiveSuggestionEngine(memory_store)
        results = engine.push_via_channel([], channel="email", config={})
        assert results == []
        mock_deliver.assert_not_called()

    @patch("scheduler.delivery.deliver_result")
    def test_push_formats_text(self, mock_deliver, memory_store):
        mock_deliver.return_value = {"status": "delivered"}
        engine = ProactiveSuggestionEngine(memory_store)
        suggestions = [Suggestion(
            category="delegation",
            priority="high",
            title="Overdue task",
            description="3 days overdue",
            action="check",
        )]
        engine.push_via_channel(suggestions, channel="email", config={"to": ["test@test.com"]})
        call_args = mock_deliver.call_args
        text = call_args[0][2]  # third positional arg is result_text
        assert "[DELEGATION]" in text
        assert "Overdue task" in text
