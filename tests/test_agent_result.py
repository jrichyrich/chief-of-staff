"""Tests for AgentResult typed return value (Fix 7)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.base import AgentResult


class TestAgentResultStringCompat:
    """AgentResult must behave identically to str."""

    def test_isinstance_str(self):
        r = AgentResult("hello")
        assert isinstance(r, str)

    def test_len(self):
        r = AgentResult("hello")
        assert len(r) == 5

    def test_slice(self):
        r = AgentResult("hello world")
        assert r[:5] == "hello"

    def test_json_dumps(self):
        r = AgentResult("some text")
        dumped = json.dumps({"result": r})
        assert '"some text"' in dumped

    def test_equality(self):
        r = AgentResult("abc")
        assert r == "abc"
        assert "abc" == r

    def test_concatenation(self):
        r = AgentResult("hello")
        assert r + " world" == "hello world"

    def test_in_operator(self):
        r = AgentResult("hello world")
        assert "world" in r

    def test_default_status_is_success(self):
        r = AgentResult("ok")
        assert r.status == "success"
        assert r.is_success is True
        assert r.is_error is False

    def test_error_status(self):
        r = AgentResult("failed", status="max_rounds_reached")
        assert r.status == "max_rounds_reached"
        assert r.is_success is False
        assert r.is_error is True

    def test_metadata(self):
        r = AgentResult("x", status="loop_detected", metadata={"rounds": 5})
        assert r.metadata == {"rounds": 5}

    def test_default_metadata_empty(self):
        r = AgentResult("x")
        assert r.metadata == {}


class TestAgentResultPropagation:
    """Callers should be able to detect error status from AgentResult."""

    def test_dispatch_tools_status_check_logic(self):
        """The status check pattern used in dispatch_tools correctly detects errors."""
        # Success result
        success = AgentResult("all good", status="success")
        agent_status = "success"
        if hasattr(success, "is_error") and success.is_error:
            agent_status = getattr(success, "status", "error")
        assert agent_status == "success"

        # Error result (max_rounds_reached)
        error = AgentResult(
            json.dumps({"status": "max_rounds_reached"}),
            status="max_rounds_reached",
        )
        agent_status = "success"
        if hasattr(error, "is_error") and error.is_error:
            agent_status = getattr(error, "status", "error")
        assert agent_status == "max_rounds_reached"

        # Plain str (backward compat — no is_error attr)
        plain = "just a string"
        agent_status = "success"
        if hasattr(plain, "is_error") and plain.is_error:
            agent_status = getattr(plain, "status", "error")
        assert agent_status == "success"

    @pytest.mark.asyncio
    async def test_dispatcher_reflects_agent_error_status(self):
        """EventDispatcher should reflect AgentResult.is_error in dispatch result."""
        from webhook.dispatcher import EventDispatcher

        error_result = AgentResult(
            json.dumps({"status": "loop_detected", "message": "stuck"}),
            status="loop_detected",
        )

        mock_agent = AsyncMock()
        mock_agent.execute.return_value = error_result

        mock_registry = MagicMock()
        mock_config = MagicMock()
        mock_config.name = "test-agent"
        mock_config.model = "sonnet"
        mock_config.max_tokens = 4096
        mock_config.capabilities = []
        mock_config.system_prompt = "test"
        mock_registry.get_agent.return_value = mock_config

        mock_memory = MagicMock()
        mock_memory.match_event_rules.return_value = [
            {"name": "rule-1", "agent_name": "test-agent", "agent_input_template": ""},
        ]

        dispatcher = EventDispatcher(
            agent_registry=mock_registry,
            memory_store=mock_memory,
        )

        mock_event = MagicMock()
        mock_event.source = "test"
        mock_event.event_type = "ping"
        mock_event.payload = "{}"
        mock_event.id = 1
        mock_event.received_at = ""

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            MockAgent.return_value = mock_agent
            with patch("agents.triage.classify_and_resolve", side_effect=lambda cfg, _: cfg):
                results = await dispatcher.dispatch(mock_event)

        assert len(results) == 1
        assert results[0]["status"] == "loop_detected"
