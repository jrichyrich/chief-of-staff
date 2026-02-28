# tests/test_event_rule_tools.py
"""Tests for the event rule MCP tools."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import mcp_server  # noqa: F401 — triggers tool registrations
from memory.models import WebhookEvent
from memory.store import MemoryStore
from agents.registry import AgentConfig, AgentRegistry
from mcp_tools import event_rule_tools



@pytest.fixture
def agent_registry(tmp_path):
    configs_dir = tmp_path / "agent_configs"
    configs_dir.mkdir()
    registry = AgentRegistry(configs_dir)
    registry.save_agent(AgentConfig(
        name="test-agent",
        description="Test agent",
        system_prompt="You are a test agent.",
        capabilities=[],
    ))
    return registry


@pytest.fixture(autouse=True)
def setup_state(memory_store, agent_registry):
    """Inject test stores into MCP server state."""
    from mcp_server import _state
    original_memory = _state.memory_store
    original_registry = _state.agent_registry
    original_doc = _state.document_store
    _state.memory_store = memory_store
    _state.agent_registry = agent_registry
    _state.document_store = None
    yield
    _state.memory_store = original_memory
    _state.agent_registry = original_registry
    _state.document_store = original_doc


@pytest.mark.asyncio
class TestCreateEventRule:
    async def test_create_basic(self):
        result = json.loads(await event_rule_tools.create_event_rule(
            name="my-rule",
            event_source="github",
            event_type_pattern="push",
            agent_name="test-agent",
        ))
        assert result["name"] == "my-rule"
        assert result["event_source"] == "github"
        assert result["event_type_pattern"] == "push"
        assert result["agent_name"] == "test-agent"
        assert result["enabled"] is True
        assert result["priority"] == 100

    async def test_create_with_all_fields(self):
        result = json.loads(await event_rule_tools.create_event_rule(
            name="full-rule",
            event_source="jira",
            event_type_pattern="issue.*",
            agent_name="test-agent",
            description="Handle all Jira issues",
            agent_input_template="Issue: $payload",
            delivery_channel="notification",
            delivery_config='{"title_template": "Jira: $task_name"}',
            enabled=True,
            priority=50,
        ))
        assert result["description"] == "Handle all Jira issues"
        assert result["agent_input_template"] == "Issue: $payload"
        assert result["delivery_channel"] == "notification"
        assert result["priority"] == 50

    async def test_create_agent_not_found(self):
        result = json.loads(await event_rule_tools.create_event_rule(
            name="bad-agent-rule",
            event_source="github",
            event_type_pattern="*",
            agent_name="nonexistent-agent",
        ))
        assert "error" in result
        assert "not found" in result["error"]

    async def test_create_duplicate_name(self):
        await event_rule_tools.create_event_rule(
            name="dup-rule",
            event_source="github",
            event_type_pattern="*",
            agent_name="test-agent",
        )
        result = json.loads(await event_rule_tools.create_event_rule(
            name="dup-rule",
            event_source="jira",
            event_type_pattern="*",
            agent_name="test-agent",
        ))
        assert "error" in result


@pytest.mark.asyncio
class TestUpdateEventRule:
    async def test_update(self, memory_store):
        created = json.loads(await event_rule_tools.create_event_rule(
            name="update-me",
            event_source="github",
            event_type_pattern="push",
            agent_name="test-agent",
        ))
        result = json.loads(await event_rule_tools.update_event_rule(
            rule_id=created["id"],
            description="Updated description",
            priority=10,
        ))
        assert result["description"] == "Updated description"
        assert result["priority"] == 10

    async def test_update_nonexistent(self):
        result = json.loads(await event_rule_tools.update_event_rule(
            rule_id=9999,
            description="test",
        ))
        assert "error" in result

    async def test_disable_rule(self, memory_store):
        created = json.loads(await event_rule_tools.create_event_rule(
            name="disable-me",
            event_source="github",
            event_type_pattern="*",
            agent_name="test-agent",
        ))
        result = json.loads(await event_rule_tools.update_event_rule(
            rule_id=created["id"],
            enabled=False,
        ))
        assert result["enabled"] is False


@pytest.mark.asyncio
class TestDeleteEventRule:
    async def test_delete_existing(self, memory_store):
        created = json.loads(await event_rule_tools.create_event_rule(
            name="delete-me",
            event_source="github",
            event_type_pattern="*",
            agent_name="test-agent",
        ))
        result = json.loads(await event_rule_tools.delete_event_rule(created["id"]))
        assert result["status"] == "deleted"

    async def test_delete_nonexistent(self):
        result = json.loads(await event_rule_tools.delete_event_rule(9999))
        assert result["status"] == "not_found"


@pytest.mark.asyncio
class TestListEventRules:
    async def test_empty_list(self):
        result = json.loads(await event_rule_tools.list_event_rules())
        assert result["rules"] == []
        assert result["count"] == 0

    async def test_list_enabled_only(self, memory_store):
        await event_rule_tools.create_event_rule(
            name="enabled-rule",
            event_source="github",
            event_type_pattern="*",
            agent_name="test-agent",
        )
        # Create a disabled rule directly via store
        memory_store.create_event_rule(
            name="disabled-rule",
            event_source="github",
            event_type_pattern="*",
            agent_name="test-agent",
            enabled=False,
        )
        result = json.loads(await event_rule_tools.list_event_rules(enabled_only=True))
        assert result["count"] == 1
        assert result["rules"][0]["name"] == "enabled-rule"

    async def test_list_all(self, memory_store):
        memory_store.create_event_rule(
            name="rule-a", event_source="a", event_type_pattern="*", agent_name="test-agent",
        )
        memory_store.create_event_rule(
            name="rule-b", event_source="b", event_type_pattern="*", agent_name="test-agent", enabled=False,
        )
        result = json.loads(await event_rule_tools.list_event_rules(enabled_only=False))
        assert result["count"] == 2


@pytest.mark.asyncio
class TestProcessWebhookEventWithAgents:
    async def test_process_with_matching_rule(self, memory_store):
        memory_store.create_event_rule(
            name="auto-rule",
            event_source="github",
            event_type_pattern="push",
            agent_name="test-agent",
        )
        event = WebhookEvent(source="github", event_type="push", payload='{"ref": "main"}')
        stored = memory_store.store_webhook_event(event)

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Processed push event"
            MockAgent.return_value = mock_instance

            result = json.loads(
                await event_rule_tools.process_webhook_event_with_agents(stored.id)
            )

        assert result["event_id"] == stored.id
        assert result["rules_matched"] == 1
        assert result["dispatches"][0]["status"] == "success"
        assert result["event_status"] == "processed"

        # Verify event status updated in DB
        updated = memory_store.get_webhook_event(stored.id)
        assert updated.status == "processed"

    async def test_process_no_matching_rules(self, memory_store):
        event = WebhookEvent(source="unknown", event_type="nope", payload="")
        stored = memory_store.store_webhook_event(event)

        result = json.loads(
            await event_rule_tools.process_webhook_event_with_agents(stored.id)
        )
        assert result["rules_matched"] == 0
        assert result["event_status"] == "processed"

    async def test_process_nonexistent_event(self):
        result = json.loads(
            await event_rule_tools.process_webhook_event_with_agents(9999)
        )
        assert "error" in result

    async def test_process_with_agent_failure(self, memory_store):
        memory_store.create_event_rule(
            name="fail-rule",
            event_source="github",
            event_type_pattern="*",
            agent_name="test-agent",
        )
        event = WebhookEvent(source="github", event_type="push", payload="")
        stored = memory_store.store_webhook_event(event)

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.side_effect = RuntimeError("Agent crashed")
            MockAgent.return_value = mock_instance

            result = json.loads(
                await event_rule_tools.process_webhook_event_with_agents(stored.id)
            )

        assert result["dispatches"][0]["status"] == "error"
        assert result["event_status"] == "failed"
