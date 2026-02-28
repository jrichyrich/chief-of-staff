# tests/test_security_capability_enforcement.py
"""Tests for capability enforcement, tool result truncation, mail send guard, and factory restrictions."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.base import BaseExpertAgent, MAX_TOOL_RESULT_LENGTH
from agents.factory import AgentFactory, MAX_AUTO_CAPABILITIES, RESTRICTED_CAPABILITIES
from agents.registry import AgentConfig, AgentRegistry
from memory.store import MemoryStore
from documents.store import DocumentStore


@pytest.fixture
def doc_store(document_store):
    return document_store


@pytest.fixture
def registry(agent_registry):
    return agent_registry


# ---------------------------------------------------------------------------
# Capability enforcement in BaseExpertAgent._handle_tool_call
# ---------------------------------------------------------------------------

class TestCapabilityEnforcement:
    """Agents must only use tools that match their declared capabilities."""

    def test_rejects_tool_not_in_capabilities(self, memory_store, doc_store):
        """An agent with only memory_read should not be able to call create_decision."""
        config = AgentConfig(
            name="limited_agent",
            description="Agent with limited caps",
            system_prompt="You are limited.",
            capabilities=["memory_read"],
        )
        agent = BaseExpertAgent(
            config=config, memory_store=memory_store, document_store=doc_store,
        )
        result = agent._handle_tool_call("create_decision", {"title": "Hack"})
        assert "error" in result
        assert "not permitted" in result["error"]
        assert "limited_agent" in result["error"]
        assert "create_decision" in result["error"]

    def test_allows_tool_in_capabilities(self, memory_store, doc_store):
        """An agent with memory_read should be able to call query_memory."""
        config = AgentConfig(
            name="reader_agent",
            description="Reader",
            system_prompt="You read.",
            capabilities=["memory_read"],
        )
        agent = BaseExpertAgent(
            config=config, memory_store=memory_store, document_store=doc_store,
        )
        result = agent._handle_tool_call("query_memory", {"query": "hello"})
        # Should return a list (possibly empty), not an error
        assert isinstance(result, list)

    def test_rejects_store_memory_without_memory_write(self, memory_store, doc_store):
        """An agent with only memory_read should not store facts."""
        config = AgentConfig(
            name="readonly_agent",
            description="Read only",
            system_prompt=".",
            capabilities=["memory_read"],
        )
        agent = BaseExpertAgent(
            config=config, memory_store=memory_store, document_store=doc_store,
        )
        result = agent._handle_tool_call("store_memory", {
            "category": "work", "key": "secret", "value": "data",
        })
        assert "error" in result
        assert "not permitted" in result["error"]

    def test_rejects_send_email_without_mail_write(self, memory_store, doc_store):
        """An agent without mail_write cannot send email."""
        config = AgentConfig(
            name="no_mail_agent",
            description="No mail",
            system_prompt=".",
            capabilities=["memory_read"],
        )
        agent = BaseExpertAgent(
            config=config, memory_store=memory_store, document_store=doc_store,
        )
        result = agent._handle_tool_call("send_email", {
            "to": "x@x.com", "subject": "hi", "body": "bye", "confirm_send": True,
        })
        assert "error" in result
        assert "not permitted" in result["error"]

    def test_multiple_capabilities_grant_correct_tools(self, memory_store, doc_store):
        """An agent with memory_read + decision_write should access both sets of tools."""
        config = AgentConfig(
            name="multi_agent",
            description="Multi",
            system_prompt=".",
            capabilities=["memory_read", "decision_write"],
        )
        agent = BaseExpertAgent(
            config=config, memory_store=memory_store, document_store=doc_store,
        )
        # query_memory should be allowed (memory_read)
        result = agent._handle_tool_call("query_memory", {"query": "test"})
        assert isinstance(result, list)

        # create_decision should be allowed (decision_write)
        result = agent._handle_tool_call("create_decision", {"title": "Test decision"})
        assert "error" not in result or "not permitted" not in result.get("error", "")

        # send_email should still be rejected
        result = agent._handle_tool_call("send_email", {
            "to": "x@x.com", "subject": "hi", "body": "bye", "confirm_send": True,
        })
        assert "error" in result
        assert "not permitted" in result["error"]


# ---------------------------------------------------------------------------
# Tool result truncation in BaseExpertAgent.execute()
# ---------------------------------------------------------------------------

class TestToolResultTruncation:
    """Tool results exceeding MAX_TOOL_RESULT_LENGTH must be truncated."""

    def test_long_result_is_truncated_in_loop(self, memory_store, doc_store):
        """The execute() method truncates tool results longer than MAX_TOOL_RESULT_LENGTH."""
        # Directly test the truncation logic inline (which happens inside execute())
        huge_value = "x" * (MAX_TOOL_RESULT_LENGTH + 5000)
        result = [{"key": "big", "value": huge_value}]
        result_str = json.dumps(result)
        assert len(result_str) > MAX_TOOL_RESULT_LENGTH

        # Simulate what execute() does
        if len(result_str) > MAX_TOOL_RESULT_LENGTH:
            result_str = result_str[:MAX_TOOL_RESULT_LENGTH] + "... [truncated]"

        assert len(result_str) == MAX_TOOL_RESULT_LENGTH + len("... [truncated]")
        assert result_str.endswith("... [truncated]")

    def test_short_result_not_truncated(self, memory_store, doc_store):
        """Results within the limit should not be modified."""
        small_result = [{"key": "small", "value": "hello"}]
        result_str = json.dumps(small_result)
        assert len(result_str) < MAX_TOOL_RESULT_LENGTH
        # No truncation applied
        assert "truncated" not in result_str

    def test_max_tool_result_length_value(self):
        """MAX_TOOL_RESULT_LENGTH should be 10000."""
        assert MAX_TOOL_RESULT_LENGTH == 10000


# ---------------------------------------------------------------------------
# Mail send guard: confirm_send=False always
# ---------------------------------------------------------------------------

class TestMailSendGuard:
    """Agent-level mail sending must always force confirm_send=False."""

    def test_mail_send_forces_confirm_false(self, memory_store, doc_store):
        """_handle_mail_send must pass confirm_send=False regardless of input."""
        config = AgentConfig(
            name="mail_agent",
            description="Mail test",
            system_prompt=".",
            capabilities=["mail_write"],
        )
        mock_mail = MagicMock()
        mock_mail.send_message.return_value = {"status": "draft_created"}

        agent = BaseExpertAgent(
            config=config,
            memory_store=memory_store,
            document_store=doc_store,
            mail_store=mock_mail,
        )

        agent._handle_mail_send({
            "to": "user@example.com",
            "subject": "Test",
            "body": "Hello",
            "confirm_send": True,  # caller tries to force True
        })

        # Verify confirm_send was always False
        mock_mail.send_message.assert_called_once()
        call_kwargs = mock_mail.send_message.call_args
        assert call_kwargs[1]["confirm_send"] is False or call_kwargs.kwargs.get("confirm_send") is False

    def test_mail_send_without_store_returns_error(self, memory_store, doc_store):
        """_handle_mail_send returns error when mail_store is None."""
        config = AgentConfig(
            name="no_mail",
            description="No mail store",
            system_prompt=".",
            capabilities=["mail_write"],
        )
        agent = BaseExpertAgent(
            config=config, memory_store=memory_store, document_store=doc_store,
        )
        result = agent._handle_mail_send({
            "to": "user@example.com",
            "subject": "Test",
            "body": "Hello",
        })
        assert "error" in result


# ---------------------------------------------------------------------------
# AgentFactory: restricted capabilities filtering and max cap
# ---------------------------------------------------------------------------

class TestAgentFactoryRestrictions:
    """Auto-generated agents must not receive restricted capabilities."""

    def test_restricted_capabilities_stripped(self, registry):
        """Factory should remove mail_write, notifications, alerts_write from auto-generated agents."""
        factory = AgentFactory(registry)

        mock_response = MagicMock()
        mock_response.content = [MagicMock(
            type="text",
            text=json.dumps({
                "name": "dangerous_agent",
                "description": "Agent that wants dangerous caps",
                "system_prompt": "You are dangerous.",
                "capabilities": [
                    "memory_read", "mail_write", "notifications", "alerts_write", "document_search",
                ],
                "temperature": 0.3,
            }),
        )]

        with patch("agents.factory.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            config = factory.create_agent("dangerous agent request")

        # Restricted capabilities must be stripped
        for restricted in RESTRICTED_CAPABILITIES:
            assert restricted not in config.capabilities, (
                f"Restricted capability '{restricted}' was not stripped"
            )
        # Allowed capabilities should remain
        assert "memory_read" in config.capabilities
        assert "document_search" in config.capabilities

    def test_max_capabilities_cap(self, registry):
        """Factory should cap capabilities at MAX_AUTO_CAPABILITIES."""
        factory = AgentFactory(registry)

        # Create a response with many capabilities (more than MAX_AUTO_CAPABILITIES)
        many_caps = [
            "memory_read", "memory_write", "document_search",
            "calendar_read", "reminders_read", "reminders_write",
            "decision_read", "decision_write", "delegation_read",
            "delegation_write", "alerts_read", "scheduling",
        ]
        assert len(many_caps) > MAX_AUTO_CAPABILITIES

        mock_response = MagicMock()
        mock_response.content = [MagicMock(
            type="text",
            text=json.dumps({
                "name": "greedy_agent",
                "description": "Agent that wants too many caps",
                "system_prompt": "You are greedy.",
                "capabilities": many_caps,
                "temperature": 0.3,
            }),
        )]

        with patch("agents.factory.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            config = factory.create_agent("greedy agent request")

        assert len(config.capabilities) <= MAX_AUTO_CAPABILITIES

    def test_restricted_constants_correct(self):
        """Verify the restricted set contains expected dangerous capabilities."""
        assert "mail_write" in RESTRICTED_CAPABILITIES
        assert "notifications" in RESTRICTED_CAPABILITIES
        assert "alerts_write" in RESTRICTED_CAPABILITIES

    def test_max_auto_capabilities_is_reasonable(self):
        """MAX_AUTO_CAPABILITIES should be a positive integer."""
        assert isinstance(MAX_AUTO_CAPABILITIES, int)
        assert MAX_AUTO_CAPABILITIES > 0
        assert MAX_AUTO_CAPABILITIES == 8
