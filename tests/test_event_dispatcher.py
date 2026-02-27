# tests/test_event_dispatcher.py
"""Tests for event-driven agent dispatch from webhook events."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.models import WebhookEvent
from memory.store import MemoryStore
from agents.registry import AgentConfig, AgentRegistry
from webhook.dispatcher import EventDispatcher


@pytest.fixture
def memory_store(tmp_path):
    db_path = tmp_path / "test_event_dispatcher.db"
    store = MemoryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def agent_registry(tmp_path):
    configs_dir = tmp_path / "agent_configs"
    configs_dir.mkdir()
    registry = AgentRegistry(configs_dir)
    # Save a test agent
    config = AgentConfig(
        name="incident-responder",
        description="Handles incident alerts",
        system_prompt="You are an incident responder.",
        capabilities=[],
    )
    registry.save_agent(config)
    return registry


@pytest.fixture
def document_store():
    return MagicMock()


@pytest.fixture
def dispatcher(agent_registry, memory_store, document_store):
    return EventDispatcher(
        agent_registry=agent_registry,
        memory_store=memory_store,
        document_store=document_store,
    )


def _create_event_rule(memory_store, **overrides):
    """Helper to create an event rule with defaults."""
    defaults = {
        "name": "test-rule",
        "event_source": "github",
        "event_type_pattern": "alert.*",
        "agent_name": "incident-responder",
        "description": "Test rule",
        "agent_input_template": "Handle: $event_type from $source\n$payload",
    }
    defaults.update(overrides)
    return memory_store.create_event_rule(**defaults)


def _create_webhook_event(memory_store, **overrides):
    """Helper to create a webhook event with defaults."""
    defaults = {
        "source": "github",
        "event_type": "alert.critical",
        "payload": json.dumps({"severity": "critical", "message": "Server down"}),
    }
    defaults.update(overrides)
    event = WebhookEvent(**defaults)
    return memory_store.store_webhook_event(event)


# --- Event Rules CRUD ---


class TestEventRulesCRUD:
    def test_create_event_rule(self, memory_store):
        rule = memory_store.create_event_rule(
            name="github-alerts",
            event_source="github",
            event_type_pattern="alert.*",
            agent_name="incident-responder",
            description="GitHub alert handler",
            agent_input_template="Analyze: $payload",
            priority=50,
        )
        assert rule["id"] is not None
        assert rule["name"] == "github-alerts"
        assert rule["event_source"] == "github"
        assert rule["event_type_pattern"] == "alert.*"
        assert rule["agent_name"] == "incident-responder"
        assert rule["enabled"] is True
        assert rule["priority"] == 50
        assert rule["created_at"] is not None

    def test_create_duplicate_name_fails(self, memory_store):
        memory_store.create_event_rule(
            name="unique-rule",
            event_source="github",
            event_type_pattern="*",
            agent_name="test-agent",
        )
        with pytest.raises(Exception):
            memory_store.create_event_rule(
                name="unique-rule",
                event_source="jira",
                event_type_pattern="*",
                agent_name="other-agent",
            )

    def test_get_event_rule(self, memory_store):
        created = _create_event_rule(memory_store)
        fetched = memory_store.get_event_rule(created["id"])
        assert fetched is not None
        assert fetched["name"] == "test-rule"
        assert fetched["event_source"] == "github"

    def test_get_nonexistent_event_rule(self, memory_store):
        assert memory_store.get_event_rule(9999) is None

    def test_list_event_rules_enabled_only(self, memory_store):
        _create_event_rule(memory_store, name="enabled-rule", enabled=True)
        _create_event_rule(memory_store, name="disabled-rule", enabled=False)
        enabled = memory_store.list_event_rules(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0]["name"] == "enabled-rule"

    def test_list_event_rules_all(self, memory_store):
        _create_event_rule(memory_store, name="rule-a", enabled=True)
        _create_event_rule(memory_store, name="rule-b", enabled=False)
        all_rules = memory_store.list_event_rules(enabled_only=False)
        assert len(all_rules) == 2

    def test_list_event_rules_ordered_by_priority(self, memory_store):
        _create_event_rule(memory_store, name="low-priority", priority=200)
        _create_event_rule(memory_store, name="high-priority", priority=10)
        _create_event_rule(memory_store, name="mid-priority", priority=100)
        rules = memory_store.list_event_rules(enabled_only=True)
        priorities = [r["priority"] for r in rules]
        assert priorities == sorted(priorities)
        assert rules[0]["name"] == "high-priority"

    def test_update_event_rule(self, memory_store):
        created = _create_event_rule(memory_store)
        updated = memory_store.update_event_rule(
            created["id"],
            description="Updated description",
            priority=50,
        )
        assert updated["description"] == "Updated description"
        assert updated["priority"] == 50

    def test_update_event_rule_nonexistent(self, memory_store):
        result = memory_store.update_event_rule(9999, description="test")
        assert result is None

    def test_update_event_rule_invalid_field(self, memory_store):
        created = _create_event_rule(memory_store)
        with pytest.raises(ValueError, match="Invalid event_rule fields"):
            memory_store.update_event_rule(created["id"], bogus_field="value")

    def test_delete_event_rule(self, memory_store):
        created = _create_event_rule(memory_store)
        result = memory_store.delete_event_rule(created["id"])
        assert result["status"] == "deleted"
        assert memory_store.get_event_rule(created["id"]) is None

    def test_delete_nonexistent_event_rule(self, memory_store):
        result = memory_store.delete_event_rule(9999)
        assert result["status"] == "not_found"

    def test_update_enabled_flag(self, memory_store):
        created = _create_event_rule(memory_store, enabled=True)
        updated = memory_store.update_event_rule(created["id"], enabled=False)
        assert updated["enabled"] is False


# --- Glob Pattern Matching ---


class TestMatchEventRules:
    def test_exact_match(self, memory_store):
        _create_event_rule(
            memory_store,
            name="exact-rule",
            event_source="github",
            event_type_pattern="push",
        )
        matches = memory_store.match_event_rules("github", "push")
        assert len(matches) == 1
        assert matches[0]["name"] == "exact-rule"

    def test_wildcard_match(self, memory_store):
        _create_event_rule(
            memory_store,
            name="wildcard-rule",
            event_source="github",
            event_type_pattern="alert.*",
        )
        matches = memory_store.match_event_rules("github", "alert.critical")
        assert len(matches) == 1
        matches2 = memory_store.match_event_rules("github", "alert.warning")
        assert len(matches2) == 1

    def test_star_matches_all(self, memory_store):
        _create_event_rule(
            memory_store,
            name="catch-all",
            event_source="github",
            event_type_pattern="*",
        )
        matches = memory_store.match_event_rules("github", "anything.here")
        assert len(matches) == 1

    def test_no_match_wrong_source(self, memory_store):
        _create_event_rule(
            memory_store,
            name="github-only",
            event_source="github",
            event_type_pattern="*",
        )
        matches = memory_store.match_event_rules("jira", "issue.created")
        assert len(matches) == 0

    def test_no_match_wrong_type(self, memory_store):
        _create_event_rule(
            memory_store,
            name="alerts-only",
            event_source="github",
            event_type_pattern="alert.*",
        )
        matches = memory_store.match_event_rules("github", "push")
        assert len(matches) == 0

    def test_multiple_rules_match(self, memory_store):
        _create_event_rule(
            memory_store,
            name="rule-a",
            event_source="github",
            event_type_pattern="alert.*",
            priority=10,
        )
        _create_event_rule(
            memory_store,
            name="rule-b",
            event_source="github",
            event_type_pattern="*",
            priority=100,
        )
        matches = memory_store.match_event_rules("github", "alert.critical")
        assert len(matches) == 2
        # Should be ordered by priority
        assert matches[0]["name"] == "rule-a"
        assert matches[1]["name"] == "rule-b"

    def test_disabled_rules_excluded(self, memory_store):
        _create_event_rule(
            memory_store,
            name="disabled",
            event_source="github",
            event_type_pattern="*",
            enabled=False,
        )
        matches = memory_store.match_event_rules("github", "push")
        assert len(matches) == 0

    def test_question_mark_pattern(self, memory_store):
        _create_event_rule(
            memory_store,
            name="single-char",
            event_source="test",
            event_type_pattern="alert.?",
        )
        matches = memory_store.match_event_rules("test", "alert.X")
        assert len(matches) == 1
        matches2 = memory_store.match_event_rules("test", "alert.XY")
        assert len(matches2) == 0


# --- Template Rendering ---


class TestTemplateRendering:
    def test_default_template(self):
        result = EventDispatcher._format_input(
            "", "github", "alert.critical", '{"msg": "down"}', "2024-01-01T00:00:00"
        )
        assert "github" in result
        assert "alert.critical" in result
        assert '{"msg": "down"}' in result
        assert "2024-01-01" in result

    def test_custom_template(self):
        template = "Incident from $source: $event_type\nDetails: $payload"
        result = EventDispatcher._format_input(
            template, "pagerduty", "incident.trigger", "server crashed", "2024-01-01"
        )
        assert result == "Incident from pagerduty: incident.trigger\nDetails: server crashed"

    def test_template_missing_var(self):
        template = "Type: $event_type, Unknown: $unknown_var"
        result = EventDispatcher._format_input(
            template, "test", "ping", "", ""
        )
        # safe_substitute leaves unknown vars as-is
        assert "Type: ping" in result
        assert "$unknown_var" in result


# --- EventDispatcher ---


@pytest.mark.asyncio
class TestEventDispatcher:
    async def test_no_matching_rules(self, dispatcher, memory_store):
        event = _create_webhook_event(memory_store, source="unknown", event_type="nope")
        results = await dispatcher.dispatch(event)
        assert results == []

    async def test_single_rule_success(self, dispatcher, memory_store):
        _create_event_rule(memory_store)
        event = _create_webhook_event(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Incident analyzed: server down"
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 1
        assert results[0]["status"] == "success"
        assert results[0]["rule_name"] == "test-rule"
        assert results[0]["agent_name"] == "incident-responder"
        assert "Incident analyzed" in results[0]["result_text"]
        assert results[0]["duration_seconds"] >= 0

    async def test_multiple_rules_all_succeed(self, dispatcher, memory_store, agent_registry):
        # Save a second agent
        agent_registry.save_agent(AgentConfig(
            name="logger-agent",
            description="Logs events",
            system_prompt="You log events.",
            capabilities=[],
        ))
        _create_event_rule(memory_store, name="rule-1", agent_name="incident-responder")
        _create_event_rule(memory_store, name="rule-2", event_type_pattern="*", agent_name="logger-agent")
        event = _create_webhook_event(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 2
        assert all(r["status"] == "success" for r in results)

    async def test_agent_failure_isolation(self, dispatcher, memory_store, agent_registry):
        """One agent failing should not prevent others from running."""
        agent_registry.save_agent(AgentConfig(
            name="failing-agent",
            description="Always fails",
            system_prompt="You fail.",
            capabilities=[],
        ))
        _create_event_rule(memory_store, name="good-rule", agent_name="incident-responder", priority=10)
        _create_event_rule(memory_store, name="bad-rule", event_type_pattern="*", agent_name="failing-agent", priority=20)
        event = _create_webhook_event(memory_store)

        call_count = 0

        async def side_effect(task):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Agent crashed")
            return "Success"

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.side_effect = side_effect
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 2
        success_results = [r for r in results if r["status"] == "success"]
        error_results = [r for r in results if r["status"] == "error"]
        assert len(success_results) == 1
        assert len(error_results) == 1
        assert "crashed" in error_results[0]["result_text"]

    async def test_agent_not_found(self, dispatcher, memory_store):
        _create_event_rule(memory_store, agent_name="nonexistent-agent")
        event = _create_webhook_event(memory_store)

        results = await dispatcher.dispatch(event)

        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert "not found" in results[0]["result_text"]

    async def test_delivery_integration(self, memory_store, agent_registry, document_store):
        delivery_calls = []

        def mock_deliver(channel, config, result_text, task_name=""):
            delivery_calls.append({
                "channel": channel,
                "config": config,
                "result_text": result_text,
                "task_name": task_name,
            })
            return {"status": "delivered", "channel": channel}

        dispatcher = EventDispatcher(
            agent_registry=agent_registry,
            memory_store=memory_store,
            document_store=document_store,
            delivery_fn=mock_deliver,
        )

        _create_event_rule(
            memory_store,
            delivery_channel="notification",
            delivery_config=json.dumps({"title_template": "Alert: $task_name"}),
        )
        event = _create_webhook_event(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Analysis complete"
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 1
        assert results[0]["delivery_status"]["status"] == "delivered"
        assert len(delivery_calls) == 1
        assert delivery_calls[0]["channel"] == "notification"

    async def test_delivery_failure_does_not_block(self, memory_store, agent_registry, document_store):
        def mock_deliver_fail(channel, config, result_text, task_name=""):
            raise RuntimeError("Delivery system down")

        dispatcher = EventDispatcher(
            agent_registry=agent_registry,
            memory_store=memory_store,
            document_store=document_store,
            delivery_fn=mock_deliver_fail,
        )

        _create_event_rule(memory_store, delivery_channel="email", delivery_config="{}")
        event = _create_webhook_event(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Result"
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 1
        assert results[0]["status"] == "success"
        assert results[0]["delivery_status"]["status"] == "error"

    async def test_no_delivery_when_channel_not_set(self, dispatcher, memory_store):
        _create_event_rule(memory_store, delivery_channel=None, delivery_config=None)
        event = _create_webhook_event(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 1
        assert results[0]["delivery_status"] is None

    async def test_template_variables_populated(self, dispatcher, memory_store):
        _create_event_rule(
            memory_store,
            agent_input_template="Source=$source Type=$event_type Payload=$payload",
        )
        event = _create_webhook_event(
            memory_store,
            source="github",
            event_type="alert.critical",
            payload="test-payload",
        )

        captured_input = None

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()

            async def capture_execute(task):
                nonlocal captured_input
                captured_input = task
                return "ok"

            mock_instance.execute.side_effect = capture_execute
            MockAgent.return_value = mock_instance

            await dispatcher.dispatch(event)

        assert captured_input is not None
        assert "Source=github" in captured_input
        assert "Type=alert.critical" in captured_input
        assert "Payload=test-payload" in captured_input


# --- Triage Integration ---


@pytest.mark.asyncio
class TestTriageIntegration:
    async def test_triage_called_before_agent_creation(self, dispatcher, memory_store):
        """Triage should be called and its result used for agent config."""
        _create_event_rule(memory_store)
        event = _create_webhook_event(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent, \
             patch("webhook.dispatcher.classify_and_resolve") as mock_triage:
            triaged_config = AgentConfig(
                name="incident-responder",
                description="Handles incident alerts",
                system_prompt="You are an incident responder.",
                capabilities=[],
                model="haiku",
            )
            mock_triage.return_value = triaged_config

            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            await dispatcher.dispatch(event)

            mock_triage.assert_called_once()
            call_kwargs = MockAgent.call_args.kwargs
            assert call_kwargs["config"].model == "haiku"

    async def test_triage_failure_does_not_block_dispatch(self, dispatcher, memory_store):
        """If triage fails, dispatch should still work with original config."""
        _create_event_rule(memory_store)
        event = _create_webhook_event(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent, \
             patch("webhook.dispatcher.classify_and_resolve") as mock_triage:
            mock_triage.side_effect = Exception("Triage crashed")

            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

            assert len(results) == 1
            assert results[0]["status"] == "success"


# --- Parallel Dispatch ---


@pytest.mark.asyncio
class TestParallelDispatch:
    async def test_parallel_dispatch_runs_concurrently(self, memory_store, agent_registry, document_store):
        """Agents dispatched in parallel should run concurrently, not sequentially."""
        agent_registry.save_agent(AgentConfig(
            name="slow-agent",
            description="Slow agent",
            system_prompt="You are slow.",
            capabilities=[],
        ))
        _create_event_rule(memory_store, name="rule-1", agent_name="incident-responder", priority=10)
        _create_event_rule(memory_store, name="rule-2", event_type_pattern="*", agent_name="slow-agent", priority=20)
        event = _create_webhook_event(memory_store)

        dispatcher = EventDispatcher(
            agent_registry=agent_registry,
            memory_store=memory_store,
            document_store=document_store,
            parallel=True,
        )

        import asyncio
        import time

        async def slow_execute(task):
            await asyncio.sleep(0.05)
            return "Done"

        with patch("agents.base.BaseExpertAgent") as MockAgent, \
             patch("webhook.dispatcher.classify_and_resolve", side_effect=lambda cfg, inp: cfg):
            mock_instance = AsyncMock()
            mock_instance.execute.side_effect = slow_execute
            MockAgent.return_value = mock_instance

            start = time.monotonic()
            results = await dispatcher.dispatch(event)
            elapsed = time.monotonic() - start

        assert len(results) == 2
        assert all(r["status"] == "success" for r in results)
        # If sequential, would take ~0.1s. Parallel should take ~0.05s.
        # Use generous headroom to avoid CI flakiness.
        assert elapsed < 0.15, f"Expected parallel (<0.15s), got {elapsed:.3f}s"

    async def test_sequential_dispatch_when_parallel_false(self, memory_store, agent_registry, document_store):
        """When parallel=False, dispatch should be sequential."""
        agent_registry.save_agent(AgentConfig(
            name="agent-b",
            description="Second agent",
            system_prompt="You are second.",
            capabilities=[],
        ))
        _create_event_rule(memory_store, name="rule-1", agent_name="incident-responder", priority=10)
        _create_event_rule(memory_store, name="rule-2", event_type_pattern="*", agent_name="agent-b", priority=20)
        event = _create_webhook_event(memory_store)

        dispatcher = EventDispatcher(
            agent_registry=agent_registry,
            memory_store=memory_store,
            document_store=document_store,
            parallel=False,
        )

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 2
        assert all(r["status"] == "success" for r in results)

    async def test_parallel_preserves_priority_order(self, memory_store, agent_registry, document_store):
        """Results in parallel mode should maintain rule priority order."""
        agent_registry.save_agent(AgentConfig(
            name="agent-b", description="B", system_prompt="B.", capabilities=[],
        ))
        agent_registry.save_agent(AgentConfig(
            name="agent-c", description="C", system_prompt="C.", capabilities=[],
        ))
        _create_event_rule(memory_store, name="low-pri", agent_name="agent-c", priority=200, event_type_pattern="*")
        _create_event_rule(memory_store, name="high-pri", agent_name="incident-responder", priority=10)
        _create_event_rule(memory_store, name="mid-pri", agent_name="agent-b", priority=100, event_type_pattern="*")
        event = _create_webhook_event(memory_store)

        dispatcher = EventDispatcher(
            agent_registry=agent_registry,
            memory_store=memory_store,
            document_store=document_store,
            parallel=True,
        )

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 3
        assert results[0]["rule_name"] == "high-pri"
        assert results[1]["rule_name"] == "mid-pri"
        assert results[2]["rule_name"] == "low-pri"

    async def test_parallel_error_isolation(self, memory_store, agent_registry, document_store):
        """One agent failing in parallel should not affect others."""
        agent_registry.save_agent(AgentConfig(
            name="failing-agent", description="Fails", system_prompt="Fail.", capabilities=[],
        ))
        _create_event_rule(memory_store, name="good-rule", agent_name="incident-responder", priority=10)
        _create_event_rule(memory_store, name="bad-rule", event_type_pattern="*", agent_name="failing-agent", priority=20)
        event = _create_webhook_event(memory_store)

        dispatcher = EventDispatcher(
            agent_registry=agent_registry,
            memory_store=memory_store,
            document_store=document_store,
            parallel=True,
        )

        call_count = 0

        async def side_effect(task):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Agent crashed in parallel")
            return "Success"

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.side_effect = side_effect
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 2
        success_results = [r for r in results if r["status"] == "success"]
        error_results = [r for r in results if r["status"] == "error"]
        assert len(success_results) == 1
        assert len(error_results) == 1

    async def test_concurrency_limit(self, memory_store, agent_registry, document_store):
        """max_concurrent should limit how many agents run simultaneously."""
        for i in range(4):
            name = f"agent-{i}"
            agent_registry.save_agent(AgentConfig(
                name=name, description=f"Agent {i}", system_prompt=f"Agent {i}.", capabilities=[],
            ))
            _create_event_rule(memory_store, name=f"rule-{i}", agent_name=name, event_type_pattern="*", priority=i * 10)
        event = _create_webhook_event(memory_store)

        dispatcher = EventDispatcher(
            agent_registry=agent_registry,
            memory_store=memory_store,
            document_store=document_store,
            parallel=True,
            max_concurrent=2,
        )

        import asyncio

        concurrency_levels = []
        active = 0
        lock = asyncio.Lock()

        async def tracked_execute(task):
            nonlocal active
            async with lock:
                active += 1
                concurrency_levels.append(active)
            await asyncio.sleep(0.1)
            async with lock:
                active -= 1
            return "Done"

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.side_effect = tracked_execute
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 4
        assert all(r["status"] == "success" for r in results)
        assert max(concurrency_levels) <= 2, f"Max concurrency was {max(concurrency_levels)}, expected <= 2"

    async def test_single_rule_no_parallel_overhead(self, memory_store, agent_registry, document_store):
        """A single matched rule should use sequential path even in parallel mode."""
        _create_event_rule(memory_store)
        event = _create_webhook_event(memory_store)

        dispatcher = EventDispatcher(
            agent_registry=agent_registry,
            memory_store=memory_store,
            document_store=document_store,
            parallel=True,
        )

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

        assert len(results) == 1
        assert results[0]["status"] == "success"

    async def test_default_constructor_is_parallel(self, agent_registry, memory_store, document_store):
        """Verify default constructor sets parallel=True."""
        dispatcher = EventDispatcher(
            agent_registry=agent_registry,
            memory_store=memory_store,
            document_store=document_store,
        )
        assert dispatcher.parallel is True
        assert dispatcher.max_concurrent == 0
