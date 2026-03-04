# tests/test_agent_base_tracking.py
"""Tests for API usage tracking in BaseExpertAgent._call_api."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import config as app_config
from agents.base import BaseExpertAgent
from agents.registry import AgentConfig
from memory.store import MemoryStore


def _make_usage(input_tokens=100, output_tokens=50,
                cache_creation_input_tokens=0, cache_read_input_tokens=0):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )


def _make_response(text="ok", stop_reason="end_turn", usage=None):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[block],
        usage=usage or _make_usage(),
    )


@pytest.fixture
def memory_store(tmp_path):
    return MemoryStore(tmp_path / "test.db")


@pytest.fixture
def document_store():
    return MagicMock()


@pytest.fixture
def agent(memory_store, document_store):
    config = AgentConfig(
        name="test-tracker",
        description="Test",
        system_prompt="Test.",
        capabilities=["memory_read"],
        model="sonnet",
    )
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=_make_response())
    return BaseExpertAgent(config, memory_store, document_store, client=client)


class TestApiUsageTracking:
    @pytest.mark.asyncio
    async def test_call_api_logs_usage(self, agent, memory_store):
        """_call_api should log model, tokens, and duration to agent_api_log."""
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        rows = memory_store.get_api_usage_log()
        assert len(rows) == 1
        row = rows[0]
        assert row["model_id"] == app_config.MODEL_TIERS["sonnet"]
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 50
        assert row["agent_name"] == "test-tracker"
        assert row["caller"] == "base_agent"
        assert row["duration_ms"] is not None
        assert row["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_call_api_logs_cache_tokens(self, memory_store, document_store):
        """Cache tokens from response.usage should be captured."""
        config = AgentConfig(
            name="cache-test",
            description="Test",
            system_prompt="Test.",
            capabilities=["memory_read"],
        )
        usage = _make_usage(
            input_tokens=200,
            output_tokens=80,
            cache_creation_input_tokens=50,
            cache_read_input_tokens=150,
        )
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_make_response(usage=usage))
        agent = BaseExpertAgent(config, memory_store, document_store, client=client)
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        row = memory_store.get_api_usage_log()[0]
        assert row["cache_creation_input_tokens"] == 50
        assert row["cache_read_input_tokens"] == 150

    @pytest.mark.asyncio
    async def test_tracking_failure_does_not_break_agent(self, document_store):
        """If log_api_call raises, the agent should still return the response."""
        broken_store = MagicMock()
        broken_store.log_api_call = MagicMock(side_effect=RuntimeError("DB locked"))
        # Need get_agent_memories for build_system_prompt
        broken_store.get_agent_memories = MagicMock(return_value=[])

        config = AgentConfig(
            name="resilient-agent",
            description="Test",
            system_prompt="Test.",
            capabilities=["memory_read"],
        )
        client = AsyncMock()
        expected_response = _make_response(text="all good")
        client.messages.create = AsyncMock(return_value=expected_response)
        agent = BaseExpertAgent(config, broken_store, document_store, client=client)
        result = await agent._call_api([{"role": "user", "content": "hi"}], [])
        # Should still return the response despite tracking failure
        assert result.content[0].text == "all good"

    @pytest.mark.asyncio
    async def test_haiku_model_logged_correctly(self, memory_store, document_store):
        """Haiku agent should log the haiku model ID."""
        config = AgentConfig(
            name="fast-agent",
            description="Fast",
            system_prompt="Fast.",
            capabilities=["memory_read"],
            model="haiku",
        )
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_make_response())
        agent = BaseExpertAgent(config, memory_store, document_store, client=client)
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        row = memory_store.get_api_usage_log()[0]
        assert row["model_id"] == app_config.MODEL_TIERS["haiku"]

    @pytest.mark.asyncio
    async def test_multiple_api_calls_all_logged(self, agent, memory_store):
        """Each _call_api invocation should create a separate log entry."""
        for _ in range(3):
            await agent._call_api([{"role": "user", "content": "hi"}], [])
        rows = memory_store.get_api_usage_log()
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_none_memory_store_no_error(self, document_store):
        """Agent with memory_store=None should not crash on tracking."""
        config = AgentConfig(
            name="no-store",
            description="Test",
            system_prompt="Test.",
            capabilities=["memory_read"],
        )
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_make_response())
        agent = BaseExpertAgent(config, None, document_store, client=client)
        # Should not raise
        result = await agent._call_api([{"role": "user", "content": "hi"}], [])
        assert result.content[0].text == "ok"
