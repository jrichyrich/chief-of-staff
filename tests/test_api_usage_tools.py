# tests/test_api_usage_tools.py
"""Tests for the API usage MCP query tools."""
import json
from unittest.mock import MagicMock

import pytest

# Must import mcp_server first to trigger tool registration
import mcp_server  # noqa: F401
from mcp_tools.api_usage_tools import get_api_usage_summary, get_api_usage_log
from memory.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "test.db")


@pytest.fixture
def state(store):
    s = MagicMock()
    s.memory_store = store
    return s


def _seed_data(store):
    """Insert test data for query tool tests."""
    store.log_api_call(
        model_id="claude-sonnet-4-5-20250929",
        input_tokens=500, output_tokens=200,
        duration_ms=1000, agent_name="research", caller="base_agent",
    )
    store.log_api_call(
        model_id="claude-sonnet-4-5-20250929",
        input_tokens=300, output_tokens=100,
        duration_ms=800, agent_name="research", caller="base_agent",
    )
    store.log_api_call(
        model_id="claude-haiku-4-5-20251001",
        input_tokens=50, output_tokens=20,
        duration_ms=200, agent_name=None, caller="triage",
    )
    store.log_api_call(
        model_id="claude-haiku-4-5-20251001",
        input_tokens=100, output_tokens=50,
        cache_creation_input_tokens=30, cache_read_input_tokens=70,
        duration_ms=300, agent_name=None, caller="synthesis",
    )


class TestGetApiUsageSummary:
    @pytest.mark.asyncio
    async def test_returns_grand_totals(self, store, state):
        _seed_data(store)
        # Patch state into the module's closure by calling directly
        mcp_server._state.memory_store = store
        result = json.loads(await get_api_usage_summary())
        assert "grand_totals" in result
        assert result["grand_totals"]["total_calls"] == 4
        assert result["grand_totals"]["total_input_tokens"] == 950
        assert result["grand_totals"]["total_output_tokens"] == 370

    @pytest.mark.asyncio
    async def test_returns_grouped_rows(self, store):
        _seed_data(store)
        mcp_server._state.memory_store = store
        result = json.loads(await get_api_usage_summary())
        assert "by_group" in result
        assert len(result["by_group"]) > 0

    @pytest.mark.asyncio
    async def test_filter_by_agent(self, store):
        _seed_data(store)
        mcp_server._state.memory_store = store
        result = json.loads(await get_api_usage_summary(agent_name="research"))
        assert result["grand_totals"]["total_calls"] == 2

    @pytest.mark.asyncio
    async def test_empty_table(self, store):
        mcp_server._state.memory_store = store
        result = json.loads(await get_api_usage_summary())
        assert result["grand_totals"]["total_calls"] == 0
        assert result["by_group"] == []


class TestGetApiUsageLog:
    @pytest.mark.asyncio
    async def test_returns_entries(self, store):
        _seed_data(store)
        mcp_server._state.memory_store = store
        result = json.loads(await get_api_usage_log())
        assert result["count"] == 4
        assert len(result["entries"]) == 4

    @pytest.mark.asyncio
    async def test_filter_by_caller(self, store):
        _seed_data(store)
        mcp_server._state.memory_store = store
        result = json.loads(await get_api_usage_log(caller="triage"))
        assert result["count"] == 1
        assert result["entries"][0]["caller"] == "triage"

    @pytest.mark.asyncio
    async def test_limit_capped_at_500(self, store):
        mcp_server._state.memory_store = store
        result = json.loads(await get_api_usage_log(limit=9999))
        # Should not error — limit gets capped internally
        assert "entries" in result

    @pytest.mark.asyncio
    async def test_filter_by_model(self, store):
        _seed_data(store)
        mcp_server._state.memory_store = store
        result = json.loads(await get_api_usage_log(model="claude-haiku-4-5-20251001"))
        assert result["count"] == 2
        for entry in result["entries"]:
            assert entry["model_id"] == "claude-haiku-4-5-20251001"
