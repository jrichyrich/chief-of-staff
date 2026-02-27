# tests/test_dispatch_tools.py
"""Tests for the dispatch_agents orchestrator MCP tool."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import mcp_server first to trigger registration
import mcp_server
from mcp_tools import dispatch_tools

from agents.registry import AgentConfig, AgentRegistry
from documents.store import DocumentStore
from memory.store import MemoryStore
from mcp_tools.state import ServerState


@pytest.fixture
def memory_store(tmp_path):
    db_path = tmp_path / "test_dispatch.db"
    store = MemoryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def agent_registry(tmp_path):
    configs_dir = tmp_path / "dispatch_agent_configs"
    configs_dir.mkdir()
    registry = AgentRegistry(configs_dir)
    # Save a few test agents with different capabilities
    registry.save_agent(AgentConfig(
        name="researcher",
        description="Researches topics",
        system_prompt="You are a researcher.",
        capabilities=["memory_read", "document_search"],
    ))
    registry.save_agent(AgentConfig(
        name="analyst",
        description="Analyzes data",
        system_prompt="You are an analyst.",
        capabilities=["memory_read"],
    ))
    registry.save_agent(AgentConfig(
        name="writer",
        description="Writes content",
        system_prompt="You are a writer.",
        capabilities=["memory_read", "document_search", "memory_write"],
    ))
    registry.save_agent(AgentConfig(
        name="empty-agent",
        description="Agent with no capabilities",
        system_prompt="You have no tools.",
        capabilities=[],
    ))
    return registry


@pytest.fixture
def document_store():
    return MagicMock()


@pytest.fixture
def state(memory_store, agent_registry, document_store):
    s = ServerState()
    s.memory_store = memory_store
    s.agent_registry = agent_registry
    s.document_store = document_store
    return s


@pytest.fixture(autouse=True)
def _register_tools(state):
    """Register dispatch tools with a mock MCP and inject state."""
    mock_mcp = MagicMock()
    # Capture the decorated function when @mcp.tool() is called
    mock_mcp.tool.return_value = lambda fn: fn
    dispatch_tools.register(mock_mcp, state)


# --- TestDispatchAgentsByName ---

class TestDispatchAgentsByName:
    """Tests for dispatching agents by explicit name."""

    @pytest.mark.asyncio
    async def test_dispatch_single_agent_by_name(self):
        """Dispatch a single agent by name and get result."""
        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Research complete: found 5 articles."
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(
                task="Research quantum computing",
                agent_names="researcher",
            )
            result = json.loads(result_json)

        assert result["agents_dispatched"] == ["researcher"]
        assert len(result["dispatches"]) == 1
        assert result["dispatches"][0]["status"] == "success"
        assert "Research complete" in result["dispatches"][0]["result"]

    @pytest.mark.asyncio
    async def test_dispatch_multiple_agents_parallel(self):
        """Multiple agents should run in parallel and all return results."""
        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(
                task="Analyze project status",
                agent_names="researcher,analyst",
            )
            result = json.loads(result_json)

        assert len(result["dispatches"]) == 2
        assert set(d["agent_name"] for d in result["dispatches"]) == {"researcher", "analyst"}
        assert all(d["status"] == "success" for d in result["dispatches"])

    @pytest.mark.asyncio
    async def test_invalid_agent_name_skipped(self):
        """Invalid agent names should be skipped, valid ones still dispatched."""
        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(
                task="Some task",
                agent_names="researcher,nonexistent-agent",
            )
            result = json.loads(result_json)

        assert result["agents_dispatched"] == ["researcher"]
        assert "nonexistent-agent" in result["agents_skipped"]
        assert len(result["dispatches"]) == 1

    @pytest.mark.asyncio
    async def test_all_invalid_agents_returns_error(self):
        """If all agent names are invalid, return error."""
        result_json = await dispatch_tools.dispatch_agents(
            task="Some task",
            agent_names="bogus-agent,fake-agent",
        )
        result = json.loads(result_json)

        assert "error" in result
        assert len(result.get("dispatches", [])) == 0

    @pytest.mark.asyncio
    async def test_agent_failure_isolated(self):
        """One agent failing should not affect others."""
        call_count = 0

        async def side_effect(task):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Agent crashed")
            return "Success from second agent"

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.side_effect = side_effect
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(
                task="Parallel task",
                agent_names="researcher,analyst",
            )
            result = json.loads(result_json)

        assert len(result["dispatches"]) == 2
        statuses = {d["status"] for d in result["dispatches"]}
        assert "success" in statuses
        assert "error" in statuses


# --- TestDispatchAgentsByCapability ---

class TestDispatchAgentsByCapability:
    """Tests for dispatching agents by capability match."""

    @pytest.mark.asyncio
    async def test_capability_match_selects_correct_agents(self):
        """Only agents with all requested capabilities should be selected."""
        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(
                task="Read documents",
                capability_match="memory_read,document_search",
            )
            result = json.loads(result_json)

        # researcher and writer both have memory_read + document_search
        # analyst only has memory_read (missing document_search)
        dispatched = set(result["agents_dispatched"])
        assert "researcher" in dispatched
        assert "writer" in dispatched
        assert "analyst" not in dispatched

    @pytest.mark.asyncio
    async def test_no_capability_match_returns_error(self):
        """If no agents match the requested capabilities, return error."""
        result_json = await dispatch_tools.dispatch_agents(
            task="Read documents",
            capability_match="nonexistent_capability",
        )
        result = json.loads(result_json)

        assert "error" in result


# --- TestDispatchAgentsGuards ---

class TestDispatchAgentsGuards:
    """Tests for safety guards and resource limits."""

    @pytest.mark.asyncio
    async def test_empty_task_returns_error(self):
        """Empty task string should return validation error."""
        result_json = await dispatch_tools.dispatch_agents(
            task="",
            agent_names="researcher",
        )
        result = json.loads(result_json)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_max_agents_cap(self):
        """Dispatch should cap at DISPATCH_AGENTS_MAX_AGENTS."""
        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            with patch("config.DISPATCH_AGENTS_MAX_AGENTS", 2):
                result_json = await dispatch_tools.dispatch_agents(
                    task="Big task",
                    agent_names="researcher,analyst,writer",
                )
                result = json.loads(result_json)

        # Should only dispatch 2, not 3
        assert len(result["dispatches"]) == 2

    @pytest.mark.asyncio
    async def test_result_truncation(self):
        """Agent results exceeding max length should be truncated."""
        long_result = "x" * 10000

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = long_result
            MockAgent.return_value = mock_instance

            with patch("config.DISPATCH_AGENTS_MAX_RESULT_LENGTH", 100):
                result_json = await dispatch_tools.dispatch_agents(
                    task="Some task",
                    agent_names="researcher",
                )
                result = json.loads(result_json)

        assert len(result["dispatches"][0]["result"]) <= 120  # 100 + "... [truncated]"

    @pytest.mark.asyncio
    async def test_duration_tracked(self):
        """Each dispatch should track duration_seconds."""
        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(
                task="Quick task",
                agent_names="researcher",
            )
            result = json.loads(result_json)

        assert "duration_seconds" in result["dispatches"][0]
        assert isinstance(result["dispatches"][0]["duration_seconds"], float)
        assert "total_duration_seconds" in result
