# tests/test_agent_base.py
"""Tests for agents/base.py — targeting >80% coverage."""
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.base import BaseExpertAgent, MAX_TOOL_RESULT_LENGTH
from agents.registry import AgentConfig
from documents.store import DocumentStore
from memory.models import AgentMemory
from memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------



@pytest.fixture
def agent_config():
    return AgentConfig(
        name="test-agent",
        description="A test agent",
        system_prompt="You are a helpful test agent.",
        capabilities=["memory_read", "memory_write"],
    )


@pytest.fixture
def agent(agent_config, memory_store, document_store):
    client = AsyncMock()
    return BaseExpertAgent(
        config=agent_config,
        memory_store=memory_store,
        document_store=document_store,
        client=client,
    )


def _make_text_response(text, stop_reason="end_turn"):
    """Create a mock Claude API response with a text block."""
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(stop_reason=stop_reason, content=[block])


def _make_tool_use_response(tool_name, tool_input, tool_id="toolu_123"):
    """Create a mock Claude API response with a tool_use block."""
    block = SimpleNamespace(type="tool_use", name=tool_name, input=tool_input, id=tool_id)
    return SimpleNamespace(stop_reason="tool_use", content=[block])


# ---------------------------------------------------------------------------
# build_system_prompt tests
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_no_memories(self, agent):
        prompt = agent.build_system_prompt()
        assert prompt.startswith("You are a helpful test agent.")
        assert "## Runtime Context" in prompt
        assert "Agent name: test-agent" in prompt
        assert "Today's date:" in prompt
        assert "Agent Memory" not in prompt

    def test_with_memories(self, agent, memory_store):
        memory_store.store_agent_memory(
            AgentMemory(agent_name="test-agent", memory_type="insight", key="rate_limit", value="100/min")
        )
        memory_store.store_agent_memory(
            AgentMemory(agent_name="test-agent", memory_type="preference", key="format", value="JSON")
        )
        prompt = agent.build_system_prompt()
        assert "## Agent Memory (retained from previous runs)" in prompt
        assert "- rate_limit: 100/min" in prompt
        assert "- format: JSON" in prompt

    def test_other_agent_memories_excluded(self, agent, memory_store):
        memory_store.store_agent_memory(
            AgentMemory(agent_name="other-agent", memory_type="insight", key="secret", value="hidden")
        )
        prompt = agent.build_system_prompt()
        assert "secret" not in prompt
        assert "hidden" not in prompt

    def test_memory_store_error_graceful(self, agent):
        """If get_agent_memories raises, build_system_prompt returns base prompt + runtime context."""
        agent.memory_store.get_agent_memories = MagicMock(side_effect=Exception("db error"))
        prompt = agent.build_system_prompt()
        assert prompt.startswith("You are a helpful test agent.")
        assert "## Runtime Context" in prompt


# ---------------------------------------------------------------------------
# get_tools tests
# ---------------------------------------------------------------------------

class TestGetTools:
    def test_returns_tools_for_capabilities(self, agent):
        tools = agent.get_tools()
        tool_names = {t["name"] for t in tools}
        assert "query_memory" in tool_names
        assert "store_memory" in tool_names

    def test_no_capabilities_returns_empty(self, memory_store, document_store):
        config = AgentConfig(
            name="empty-agent",
            description="No caps",
            system_prompt="Empty.",
            capabilities=[],
        )
        client = AsyncMock()
        agent = BaseExpertAgent(config, memory_store, document_store, client=client)
        tools = agent.get_tools()
        assert tools == []

    def test_capability_gating(self, memory_store, document_store):
        """Agent with only memory_read should not get store_memory."""
        config = AgentConfig(
            name="read-only",
            description="Read only",
            system_prompt="Read only agent.",
            capabilities=["memory_read"],
        )
        client = AsyncMock()
        agent = BaseExpertAgent(config, memory_store, document_store, client=client)
        tools = agent.get_tools()
        tool_names = {t["name"] for t in tools}
        assert "query_memory" in tool_names
        assert "store_memory" not in tool_names


# ---------------------------------------------------------------------------
# execute() — tool-use loop tests
# ---------------------------------------------------------------------------

class TestExecuteLoop:
    @pytest.mark.asyncio
    async def test_simple_text_response(self, agent):
        """Agent returns text on first call with no tool use."""
        agent.client.messages.create = AsyncMock(
            return_value=_make_text_response("Hello!")
        )
        result = await agent.execute("Say hello")
        assert result == "Hello!"

    @pytest.mark.asyncio
    async def test_tool_use_then_text(self, agent):
        """Agent uses a tool, then returns text."""
        tool_response = _make_tool_use_response(
            "query_memory", {"query": "name"}, tool_id="toolu_001"
        )
        text_response = _make_text_response("Your name is Alice.")

        agent.client.messages.create = AsyncMock(
            side_effect=[tool_response, text_response]
        )

        with patch.object(agent, "_handle_tool_call", return_value=[{"key": "name", "value": "Alice"}]):
            result = await agent.execute("What is my name?")

        assert result == "Your name is Alice."
        assert agent.client.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_multiple_tool_rounds(self, agent):
        """Agent uses tools multiple rounds before text."""
        tool_resp_1 = _make_tool_use_response("query_memory", {"query": "name"}, "toolu_001")
        tool_resp_2 = _make_tool_use_response("query_memory", {"query": "age"}, "toolu_002")
        text_resp = _make_text_response("Done.")

        agent.client.messages.create = AsyncMock(
            side_effect=[tool_resp_1, tool_resp_2, text_resp]
        )

        with patch.object(agent, "_handle_tool_call", return_value={"result": "ok"}):
            result = await agent.execute("Tell me about the user")

        assert result == "Done."
        assert agent.client.messages.create.call_count == 3

    @pytest.mark.asyncio
    async def test_max_tool_rounds_cap(self, agent):
        """Agent hits MAX_TOOL_ROUNDS and returns the cap message."""
        tool_response = _make_tool_use_response(
            "query_memory", {"query": "test"}, "toolu_cap"
        )

        agent.client.messages.create = AsyncMock(return_value=tool_response)

        with patch.object(agent, "_handle_tool_call", return_value={"result": "ok"}):
            with patch("agents.base.MAX_TOOL_ROUNDS", 3):
                result = await agent.execute("Loop forever")

        parsed = json.loads(result)
        assert parsed["status"] == "max_rounds_reached"
        assert parsed["rounds"] == 3
        assert "maximum tool rounds" in parsed["message"]
        assert agent.client.messages.create.call_count == 3

    @pytest.mark.asyncio
    async def test_empty_text_response(self, agent):
        """Agent returns empty string when response has no text blocks."""
        response = SimpleNamespace(stop_reason="end_turn", content=[])
        agent.client.messages.create = AsyncMock(return_value=response)

        result = await agent.execute("Empty?")
        assert result == ""

    @pytest.mark.asyncio
    async def test_tool_result_truncation(self, agent):
        """Long tool results get truncated to MAX_TOOL_RESULT_LENGTH."""
        tool_response = _make_tool_use_response(
            "query_memory", {"query": "big"}, "toolu_big"
        )
        text_response = _make_text_response("Truncated.")

        agent.client.messages.create = AsyncMock(
            side_effect=[tool_response, text_response]
        )

        # Return a massive result
        big_result = {"data": "x" * (MAX_TOOL_RESULT_LENGTH + 1000)}
        with patch.object(agent, "_handle_tool_call", return_value=big_result):
            result = await agent.execute("Big query")

        assert result == "Truncated."
        # Verify the tool result message was truncated
        second_call_messages = agent.client.messages.create.call_args_list[1][1].get(
            "messages",
            agent.client.messages.create.call_args_list[1][0][0] if agent.client.messages.create.call_args_list[1][0] else None,
        )
        # The messages are passed as keyword arg
        call_kwargs = agent.client.messages.create.call_args_list[1]
        messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0]
        # Last message is the tool result
        tool_result_msg = messages[-1]
        assert tool_result_msg["role"] == "user"
        content_str = tool_result_msg["content"][0]["content"]
        assert content_str.endswith("... [truncated]")
        assert len(content_str) <= MAX_TOOL_RESULT_LENGTH + len("... [truncated]") + 10


# ---------------------------------------------------------------------------
# _call_api tests
# ---------------------------------------------------------------------------

class TestCallApi:
    @pytest.mark.asyncio
    async def test_includes_tools_when_present(self, agent):
        agent.client.messages.create = AsyncMock(
            return_value=_make_text_response("ok")
        )
        tools = [{"name": "query_memory", "description": "test", "input_schema": {}}]
        await agent._call_api([{"role": "user", "content": "hi"}], tools)

        call_kwargs = agent.client.messages.create.call_args.kwargs
        assert "tools" in call_kwargs
        assert call_kwargs["tools"] == tools

    @pytest.mark.asyncio
    async def test_excludes_tools_when_empty(self, agent):
        agent.client.messages.create = AsyncMock(
            return_value=_make_text_response("ok")
        )
        await agent._call_api([{"role": "user", "content": "hi"}], [])

        call_kwargs = agent.client.messages.create.call_args.kwargs
        assert "tools" not in call_kwargs

    @pytest.mark.asyncio
    async def test_uses_system_prompt(self, agent):
        agent.client.messages.create = AsyncMock(
            return_value=_make_text_response("ok")
        )
        await agent._call_api([{"role": "user", "content": "hi"}], [])

        call_kwargs = agent.client.messages.create.call_args.kwargs
        assert call_kwargs["system"].startswith("You are a helpful test agent.")
        assert "## Runtime Context" in call_kwargs["system"]


# ---------------------------------------------------------------------------
# _handle_tool_call tests
# ---------------------------------------------------------------------------

class TestHandleToolCall:
    def test_disallowed_tool_returns_error(self, agent):
        result = agent._handle_tool_call("send_email", {"to": "x@x.com"})
        assert "error" in result
        assert "not permitted" in result["error"]

    def test_unknown_tool_returns_error(self, agent):
        """Even if tool were "allowed", unknown dispatch returns error."""
        with patch.object(agent, "get_tools", return_value=[{"name": "nonexistent_tool"}]):
            result = agent._handle_tool_call("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_hooks_fire_before_and_after(self, agent):
        """Hooks are fired around tool dispatch."""
        hook_registry = MagicMock()
        hook_registry.fire_hooks.return_value = []
        agent.hook_registry = hook_registry
        agent._handle_tool_call("query_memory", {"query": "test"})
        assert hook_registry.fire_hooks.call_count == 2

    def test_query_memory_dispatches(self, agent, memory_store):
        memory_store.store_fact(
            __import__("memory.models", fromlist=["Fact"]).Fact(
                category="personal", key="name", value="Alice"
            )
        )
        result = agent._handle_tool_call("query_memory", {"query": "name"})
        assert isinstance(result, list)
        assert any(r["key"] == "name" for r in result)

    def test_store_memory_dispatches(self, agent):
        result = agent._handle_tool_call(
            "store_memory",
            {"category": "personal", "key": "color", "value": "blue"},
        )
        assert result["status"] == "stored"

    def test_search_documents_dispatches(self, memory_store, document_store):
        config = AgentConfig(
            name="doc-agent",
            description="Doc search test",
            system_prompt="Test.",
            capabilities=["document_search"],
        )
        agent = BaseExpertAgent(config, memory_store, document_store, client=AsyncMock())
        with patch("agents.base.execute_search_documents", return_value=[]) as mock_search:
            result = agent._handle_tool_call("search_documents", {"query": "test"})
        mock_search.assert_called_once_with(agent.document_store, "test", 5)
        assert result == []

    def test_search_documents_custom_top_k(self, memory_store, document_store):
        config = AgentConfig(
            name="doc-agent2",
            description="Doc search test",
            system_prompt="Test.",
            capabilities=["document_search"],
        )
        agent = BaseExpertAgent(config, memory_store, document_store, client=AsyncMock())
        with patch("agents.base.execute_search_documents", return_value=[]) as mock_search:
            agent._handle_tool_call("search_documents", {"query": "test", "top_k": 10})
        mock_search.assert_called_once_with(agent.document_store, "test", 10)

    def test_calendar_not_available(self, agent):
        assert agent.calendar_store is None
        result = agent._handle_tool_call("get_calendar_events", {
            "start_date": "2026-01-01", "end_date": "2026-01-02"
        })
        # Tool is not in allowed tools for this agent, so it should be "not permitted"
        assert "error" in result

    def test_reminder_not_available(self, memory_store, document_store):
        config = AgentConfig(
            name="reminder-agent",
            description="Test",
            system_prompt="Test.",
            capabilities=["reminders_read"],
        )
        agent = BaseExpertAgent(config, memory_store, document_store, client=AsyncMock())
        result = agent._handle_tool_call("list_reminders", {})
        assert "error" in result
        assert "Reminders not available" in result["error"]

    def test_notification_not_available(self, memory_store, document_store):
        config = AgentConfig(
            name="notif-agent",
            description="Test",
            system_prompt="Test.",
            capabilities=["notifications"],
        )
        agent = BaseExpertAgent(config, memory_store, document_store, client=AsyncMock())
        result = agent._handle_tool_call("send_notification", {
            "title": "Test", "message": "Hello"
        })
        assert "error" in result
        assert "Notifications not available" in result["error"]

    def test_mail_not_available(self, memory_store, document_store):
        config = AgentConfig(
            name="mail-agent",
            description="Test",
            system_prompt="Test.",
            capabilities=["mail_read"],
        )
        agent = BaseExpertAgent(config, memory_store, document_store, client=AsyncMock())
        result = agent._handle_tool_call("get_mail_messages", {})
        assert "error" in result
        assert "Mail not available" in result["error"]


# ---------------------------------------------------------------------------
# Lifecycle tool dispatch tests
# ---------------------------------------------------------------------------

class TestLifecycleToolDispatch:
    @pytest.fixture
    def lifecycle_agent(self, memory_store, document_store):
        config = AgentConfig(
            name="lifecycle-agent",
            description="Lifecycle test",
            system_prompt="Test.",
            capabilities=["decision_read", "decision_write", "delegation_read", "delegation_write", "alerts_read", "alerts_write"],
        )
        return BaseExpertAgent(config, memory_store, document_store, client=AsyncMock())

    def test_create_decision(self, lifecycle_agent):
        result = lifecycle_agent._handle_tool_call("create_decision", {
            "title": "Test decision",
            "description": "A test",
        })
        assert "id" in result or "decision_id" in result or result.get("status") == "created"

    def test_search_decisions(self, lifecycle_agent):
        result = lifecycle_agent._handle_tool_call("search_decisions", {"query": "test"})
        assert isinstance(result, (list, dict))

    def test_list_pending_decisions(self, lifecycle_agent):
        result = lifecycle_agent._handle_tool_call("list_pending_decisions", {})
        assert isinstance(result, (list, dict))

    def test_create_delegation(self, lifecycle_agent):
        result = lifecycle_agent._handle_tool_call("create_delegation", {
            "task": "Review PR",
            "delegated_to": "alice",
        })
        assert isinstance(result, dict)

    def test_list_delegations(self, lifecycle_agent):
        result = lifecycle_agent._handle_tool_call("list_delegations", {})
        assert isinstance(result, (list, dict))

    def test_check_overdue_delegations(self, lifecycle_agent):
        result = lifecycle_agent._handle_tool_call("check_overdue_delegations", {})
        assert isinstance(result, (list, dict))

    def test_create_alert_rule(self, lifecycle_agent):
        result = lifecycle_agent._handle_tool_call("create_alert_rule", {
            "name": "test-alert",
            "alert_type": "deadline",
        })
        assert isinstance(result, dict)

    def test_list_alert_rules(self, lifecycle_agent):
        result = lifecycle_agent._handle_tool_call("list_alert_rules", {})
        assert isinstance(result, (list, dict))

    def test_check_alerts(self, lifecycle_agent):
        result = lifecycle_agent._handle_tool_call("check_alerts", {})
        assert isinstance(result, (list, dict))

    def test_update_decision(self, lifecycle_agent):
        # Create a decision first, then update it
        create_result = lifecycle_agent._handle_tool_call("create_decision", {
            "title": "Updatable decision",
        })
        decision_id = create_result.get("id") or create_result.get("decision_id")
        if decision_id:
            result = lifecycle_agent._handle_tool_call("update_decision", {
                "decision_id": decision_id,
                "status": "executed",
            })
            assert isinstance(result, dict)

    def test_delete_decision(self, lifecycle_agent):
        create_result = lifecycle_agent._handle_tool_call("create_decision", {
            "title": "Deletable decision",
        })
        decision_id = create_result.get("id") or create_result.get("decision_id")
        if decision_id:
            result = lifecycle_agent._handle_tool_call("delete_decision", {
                "decision_id": decision_id,
            })
            assert isinstance(result, dict)

    def test_update_delegation(self, lifecycle_agent):
        create_result = lifecycle_agent._handle_tool_call("create_delegation", {
            "task": "Updatable task",
            "delegated_to": "bob",
        })
        delegation_id = create_result.get("id") or create_result.get("delegation_id")
        if delegation_id:
            result = lifecycle_agent._handle_tool_call("update_delegation", {
                "delegation_id": delegation_id,
                "status": "completed",
            })
            assert isinstance(result, dict)

    def test_delete_delegation(self, lifecycle_agent):
        create_result = lifecycle_agent._handle_tool_call("create_delegation", {
            "task": "Deletable task",
            "delegated_to": "charlie",
        })
        delegation_id = create_result.get("id") or create_result.get("delegation_id")
        if delegation_id:
            result = lifecycle_agent._handle_tool_call("delete_delegation", {
                "delegation_id": delegation_id,
            })
            assert isinstance(result, dict)

    def test_dismiss_alert(self, lifecycle_agent):
        create_result = lifecycle_agent._handle_tool_call("create_alert_rule", {
            "name": "dismissable-alert",
            "alert_type": "deadline",
        })
        rule_id = create_result.get("id") or create_result.get("rule_id")
        if rule_id:
            result = lifecycle_agent._handle_tool_call("dismiss_alert", {
                "rule_id": rule_id,
            })
            assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Calendar / Reminder / Mail tool handlers with stores present
# ---------------------------------------------------------------------------

class TestPlatformToolHandlersWithStores:
    @pytest.fixture
    def calendar_agent(self, memory_store, document_store):
        config = AgentConfig(
            name="cal-agent",
            description="Calendar test",
            system_prompt="Test.",
            capabilities=["calendar_read"],
        )
        calendar_store = MagicMock()
        return BaseExpertAgent(
            config, memory_store, document_store,
            client=AsyncMock(), calendar_store=calendar_store,
        )

    def test_get_calendar_events_dispatches(self, calendar_agent):
        calendar_agent.calendar_store.get_events.return_value = [{"title": "Meeting"}]
        result = calendar_agent._handle_tool_call("get_calendar_events", {
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
        })
        assert calendar_agent.calendar_store.get_events.called
        assert result == [{"title": "Meeting"}]

    def test_search_calendar_events_dispatches(self, calendar_agent):
        calendar_agent.calendar_store.search_events.return_value = [{"title": "Standup"}]
        result = calendar_agent._handle_tool_call("search_calendar_events", {
            "query": "standup",
        })
        assert calendar_agent.calendar_store.search_events.called

    def test_reminder_handlers_with_store(self, memory_store, document_store):
        config = AgentConfig(
            name="rem-agent",
            description="Reminder test",
            system_prompt="Test.",
            capabilities=["reminders_read", "reminders_write"],
        )
        reminder_store = MagicMock()
        reminder_store.list_reminders.return_value = [{"title": "Buy milk"}]
        reminder_store.search_reminders.return_value = [{"title": "Buy milk"}]
        reminder_store.create_reminder.return_value = {"id": "r1", "title": "New"}
        reminder_store.complete_reminder.return_value = {"status": "completed"}

        agent = BaseExpertAgent(
            config, memory_store, document_store,
            client=AsyncMock(), reminder_store=reminder_store,
        )

        assert agent._handle_tool_call("list_reminders", {}) == [{"title": "Buy milk"}]
        assert agent._handle_tool_call("search_reminders", {"query": "milk"}) == [{"title": "Buy milk"}]
        assert agent._handle_tool_call("create_reminder", {"title": "New"})["title"] == "New"
        assert agent._handle_tool_call("complete_reminder", {"reminder_id": "r1"})["status"] == "completed"

    def test_notification_handler_with_store(self, memory_store, document_store):
        config = AgentConfig(
            name="notif-agent2",
            description="Notif test",
            system_prompt="Test.",
            capabilities=["notifications"],
        )
        notifier = MagicMock()
        notifier.send.return_value = {"status": "sent"}
        agent = BaseExpertAgent(
            config, memory_store, document_store,
            client=AsyncMock(), notifier=notifier,
        )
        result = agent._handle_tool_call("send_notification", {"title": "Hi", "message": "Hello"})
        assert result == {"status": "sent"}

    def test_mail_handlers_with_store(self, memory_store, document_store):
        config = AgentConfig(
            name="mail-agent2",
            description="Mail test",
            system_prompt="Test.",
            capabilities=["mail_read", "mail_write"],
        )
        mail_store = MagicMock()
        mail_store.get_messages.return_value = [{"subject": "Test"}]
        mail_store.get_message.return_value = {"subject": "Test", "body": "Hello"}
        mail_store.search_messages.return_value = [{"subject": "Test"}]
        mail_store.list_mailboxes.return_value = [{"name": "INBOX", "account": "test", "unread_count": 5}]
        mail_store.send_message.return_value = {"status": "queued"}
        mail_store.mark_read.return_value = {"status": "ok"}
        mail_store.mark_flagged.return_value = {"status": "ok"}
        mail_store.move_message.return_value = {"status": "ok"}

        agent = BaseExpertAgent(
            config, memory_store, document_store,
            client=AsyncMock(), mail_store=mail_store,
        )

        assert agent._handle_tool_call("get_mail_messages", {}) == [{"subject": "Test"}]
        assert agent._handle_tool_call("get_mail_message", {"message_id": "m1"})["body"] == "Hello"
        assert agent._handle_tool_call("search_mail", {"query": "test"}) == [{"subject": "Test"}]
        assert agent._handle_tool_call("get_unread_count", {})["unread_count"] == 5
        assert agent._handle_tool_call("send_email", {"to": "a@b.com", "subject": "Hi", "body": "Hello"})["status"] == "queued"
        assert agent._handle_tool_call("mark_mail_read", {"message_id": "m1"})["status"] == "ok"
        assert agent._handle_tool_call("mark_mail_flagged", {"message_id": "m1"})["status"] == "ok"
        assert agent._handle_tool_call("move_mail_message", {"message_id": "m1", "target_mailbox": "Archive"})["status"] == "ok"

    def test_get_unread_count_no_match(self, memory_store, document_store):
        config = AgentConfig(
            name="mail-agent3",
            description="Mail test",
            system_prompt="Test.",
            capabilities=["mail_read"],
        )
        mail_store = MagicMock()
        mail_store.list_mailboxes.return_value = []
        agent = BaseExpertAgent(
            config, memory_store, document_store,
            client=AsyncMock(), mail_store=mail_store,
        )
        result = agent._handle_tool_call("get_unread_count", {"mailbox": "Sent"})
        assert result["unread_count"] == 0

    def test_send_email_with_cc_bcc(self, memory_store, document_store):
        config = AgentConfig(
            name="mail-agent4",
            description="Mail test",
            system_prompt="Test.",
            capabilities=["mail_write"],
        )
        mail_store = MagicMock()
        mail_store.send_message.return_value = {"status": "queued"}
        agent = BaseExpertAgent(
            config, memory_store, document_store,
            client=AsyncMock(), mail_store=mail_store,
        )
        agent._handle_tool_call("send_email", {
            "to": "a@b.com, c@d.com",
            "subject": "Hi",
            "body": "Hello",
            "cc": "e@f.com",
            "bcc": "g@h.com",
        })
        call_kwargs = mail_store.send_message.call_args.kwargs
        assert call_kwargs["to"] == ["a@b.com", "c@d.com"]
        assert call_kwargs["cc"] == ["e@f.com"]
        assert call_kwargs["bcc"] == ["g@h.com"]


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_default_client_created(self, agent_config, memory_store, document_store):
        """When no client is passed, a default AsyncAnthropic client is created."""
        with patch("agents.base.anthropic.AsyncAnthropic") as mock_cls:
            agent = BaseExpertAgent(agent_config, memory_store, document_store)
            mock_cls.assert_called_once()

    def test_custom_client_used(self, agent_config, memory_store, document_store):
        client = AsyncMock()
        agent = BaseExpertAgent(agent_config, memory_store, document_store, client=client)
        assert agent.client is client

    def test_optional_stores_default_none(self, agent_config, memory_store, document_store):
        agent = BaseExpertAgent(agent_config, memory_store, document_store, client=AsyncMock())
        assert agent.calendar_store is None
        assert agent.reminder_store is None
        assert agent.notifier is None
        assert agent.mail_store is None


# ---------------------------------------------------------------------------
# Model tier resolution tests
# ---------------------------------------------------------------------------

class TestModelTierResolution:
    @pytest.mark.asyncio
    async def test_default_model_uses_sonnet(self, agent):
        """Agent with default model='sonnet' resolves to sonnet model ID."""
        agent.client.messages.create = AsyncMock(
            return_value=_make_text_response("ok")
        )
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        call_kwargs = agent.client.messages.create.call_args.kwargs
        import config as app_config
        assert call_kwargs["model"] == app_config.MODEL_TIERS["sonnet"]

    @pytest.mark.asyncio
    async def test_haiku_agent_uses_haiku_model(self, memory_store, document_store):
        """Agent with model='haiku' resolves to haiku model ID."""
        config = AgentConfig(
            name="fast-agent",
            description="Fast",
            system_prompt="Fast.",
            capabilities=["memory_read"],
            model="haiku",
        )
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_make_text_response("ok"))
        agent = BaseExpertAgent(config, memory_store, document_store, client=client)
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        call_kwargs = client.messages.create.call_args.kwargs
        import config as app_config
        assert call_kwargs["model"] == app_config.MODEL_TIERS["haiku"]

    @pytest.mark.asyncio
    async def test_opus_agent_uses_opus_model(self, memory_store, document_store):
        """Agent with model='opus' resolves to opus model ID."""
        config = AgentConfig(
            name="deep-agent",
            description="Deep",
            system_prompt="Deep.",
            capabilities=["memory_read"],
            model="opus",
        )
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_make_text_response("ok"))
        agent = BaseExpertAgent(config, memory_store, document_store, client=client)
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        call_kwargs = client.messages.create.call_args.kwargs
        import config as app_config
        assert call_kwargs["model"] == app_config.MODEL_TIERS["opus"]

    @pytest.mark.asyncio
    async def test_unknown_tier_falls_back_to_default(self, memory_store, document_store):
        """Agent with unrecognized model tier falls back to DEFAULT_MODEL_TIER."""
        config = AgentConfig(
            name="bad-tier-agent",
            description="Bad tier",
            system_prompt="Bad.",
            capabilities=["memory_read"],
            model="nonexistent_tier",
        )
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_make_text_response("ok"))
        agent = BaseExpertAgent(config, memory_store, document_store, client=client)
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        call_kwargs = client.messages.create.call_args.kwargs
        import config as app_config
        assert call_kwargs["model"] == app_config.MODEL_TIERS[app_config.DEFAULT_MODEL_TIER]


# ---------------------------------------------------------------------------
# Dispatch table tests
# ---------------------------------------------------------------------------

# Complete list of tools that _get_dispatch_table must contain.
EXPECTED_DISPATCH_TOOLS = {
    "query_memory", "store_memory", "search_documents",
    "create_decision", "search_decisions", "update_decision",
    "list_pending_decisions", "delete_decision",
    "create_delegation", "list_delegations", "update_delegation",
    "check_overdue_delegations", "delete_delegation",
    "create_alert_rule", "list_alert_rules", "check_alerts", "dismiss_alert",
    "get_calendar_events", "search_calendar_events",
    "list_reminders", "search_reminders", "create_reminder", "complete_reminder",
    "send_notification",
    "get_mail_messages", "get_mail_message", "search_mail",
    "get_unread_count", "send_email",
    "mark_mail_read", "mark_mail_flagged", "move_mail_message",
}


class TestDispatchTable:
    def test_dispatch_table_is_dict(self, agent):
        table = agent._get_dispatch_table()
        assert isinstance(table, dict)

    def test_dispatch_table_contains_all_known_tools(self, agent):
        table = agent._get_dispatch_table()
        assert set(table.keys()) == EXPECTED_DISPATCH_TOOLS

    def test_dispatch_table_values_are_callable(self, agent):
        table = agent._get_dispatch_table()
        for name, handler in table.items():
            assert callable(handler), f"Handler for '{name}' is not callable"

    def test_unknown_tool_returns_error(self, agent):
        result = agent._dispatch_tool("totally_fake_tool", {})
        assert result == {"error": "Unknown tool: totally_fake_tool"}

    def test_dispatch_table_is_cached(self, agent):
        table1 = agent._get_dispatch_table()
        table2 = agent._get_dispatch_table()
        assert table1 is table2

    def test_query_memory_via_dispatch(self, agent, memory_store):
        from memory.models import Fact
        memory_store.store_fact(Fact(category="personal", key="city", value="Portland"))
        result = agent._dispatch_tool("query_memory", {"query": "city"})
        assert isinstance(result, list)
        assert any(r["key"] == "city" for r in result)

    def test_store_memory_via_dispatch(self, agent):
        result = agent._dispatch_tool(
            "store_memory",
            {"category": "personal", "key": "lang", "value": "Python"},
        )
        assert result["status"] == "stored"

    def test_zero_arg_handlers_via_dispatch(self, agent):
        """list_pending_decisions, check_overdue_delegations, check_alerts accept tool_input."""
        for tool_name in ("list_pending_decisions", "check_overdue_delegations", "check_alerts"):
            result = agent._dispatch_tool(tool_name, {})
            assert isinstance(result, (list, dict)), f"{tool_name} returned unexpected type"
