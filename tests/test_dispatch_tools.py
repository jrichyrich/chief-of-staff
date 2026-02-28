# tests/test_dispatch_tools.py
"""Tests for the dispatch_agents orchestrator MCP tool."""

import asyncio
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

    @pytest.mark.asyncio
    async def test_error_result_does_not_leak_details(self):
        """Error results should contain type name, not raw exception text."""
        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.side_effect = RuntimeError("/secret/path/to/db.sqlite")
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(
                task="Some task",
                agent_names="researcher",
            )
            result = json.loads(result_json)

        error_dispatch = result["dispatches"][0]
        assert error_dispatch["status"] == "error"
        assert "RuntimeError" in error_dispatch["result"]
        assert "/secret/path" not in error_dispatch["result"]


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


# --- TestDispatchAgentsAutoSelect ---

class TestDispatchAgentsAutoSelect:
    """Tests for auto-select mode (Mode C) — no agent_names or capability_match."""

    @pytest.mark.asyncio
    async def test_auto_select_excludes_empty_capability_agents(self):
        """Auto-select should skip agents with no capabilities."""
        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(task="General task")
            result = json.loads(result_json)

        assert "empty-agent" not in result["agents_dispatched"]
        # researcher, analyst, writer all have capabilities
        assert len(result["dispatches"]) == 3

    @pytest.mark.asyncio
    async def test_auto_select_capped_at_five(self, state):
        """Auto-select mode should cap at 5 agents."""
        # Add agents until we have > 5 with capabilities
        for i in range(5):
            state.agent_registry.save_agent(AgentConfig(
                name=f"extra-agent-{i}",
                description=f"Extra {i}",
                system_prompt=f"Extra {i}.",
                capabilities=["memory_read"],
            ))

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(task="Big task")
            result = json.loads(result_json)

        # 3 original + 5 extras = 8 capable, but should be capped at 5
        assert len(result["dispatches"]) == 5


# --- TestDispatchTriageIntegration ---

class TestDispatchTriageIntegration:
    """Tests for triage integration in dispatch_agents."""

    @pytest.mark.asyncio
    async def test_triage_called_when_enabled(self):
        """use_triage=True should call classify_and_resolve."""
        with patch("agents.base.BaseExpertAgent") as MockAgent, \
             patch("agents.triage.classify_and_resolve") as mock_triage:
            triaged = AgentConfig(
                name="researcher", description="Researches topics",
                system_prompt="You are a researcher.",
                capabilities=["memory_read", "document_search"],
                model="haiku",
            )
            mock_triage.return_value = triaged

            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(
                task="Simple task",
                agent_names="researcher",
                use_triage=True,
            )
            result = json.loads(result_json)

            mock_triage.assert_called_once()
            assert result["dispatches"][0]["model_used"] == "haiku"

    @pytest.mark.asyncio
    async def test_triage_skipped_when_disabled(self):
        """use_triage=False should skip classify_and_resolve entirely."""
        with patch("agents.base.BaseExpertAgent") as MockAgent, \
             patch("agents.triage.classify_and_resolve") as mock_triage:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            await dispatch_tools.dispatch_agents(
                task="Task",
                agent_names="researcher",
                use_triage=False,
            )
            mock_triage.assert_not_called()

    @pytest.mark.asyncio
    async def test_triage_failure_falls_back_to_original_config(self):
        """If triage crashes, dispatch should use original config."""
        with patch("agents.base.BaseExpertAgent") as MockAgent, \
             patch("agents.triage.classify_and_resolve", side_effect=RuntimeError("API down")):
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            result_json = await dispatch_tools.dispatch_agents(
                task="Task",
                agent_names="researcher",
                use_triage=True,
            )
            result = json.loads(result_json)

        assert result["dispatches"][0]["status"] == "success"
        assert result["dispatches"][0]["model_used"] == "sonnet"  # default, not haiku


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
    async def test_whitespace_only_task_returns_error(self):
        """Whitespace-only task string should return validation error."""
        result_json = await dispatch_tools.dispatch_agents(
            task="   \n\t  ",
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

    @pytest.mark.asyncio
    async def test_agent_registry_none_returns_error(self, state):
        """If agent_registry is None, return clear error."""
        original = state.agent_registry
        state.agent_registry = None
        # Re-register with updated state
        mock_mcp = MagicMock()
        mock_mcp.tool.return_value = lambda fn: fn
        dispatch_tools.register(mock_mcp, state)
        try:
            result_json = await dispatch_tools.dispatch_agents(
                task="Some task",
                agent_names="researcher",
            )
            result = json.loads(result_json)
            assert "error" in result
            assert "registry" in result["error"].lower()
        finally:
            state.agent_registry = original

    @pytest.mark.asyncio
    async def test_max_concurrent_clamped_to_config(self):
        """max_concurrent should never exceed config ceiling."""
        concurrency_levels = []
        active = 0
        lock = asyncio.Lock()

        async def tracked_execute(task):
            nonlocal active
            async with lock:
                active += 1
                concurrency_levels.append(active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1
            return "Done"

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.side_effect = tracked_execute
            MockAgent.return_value = mock_instance

            # Pass max_concurrent=100 but config ceiling is 2
            with patch("config.MAX_CONCURRENT_AGENT_DISPATCHES", 2):
                result_json = await dispatch_tools.dispatch_agents(
                    task="Parallel task",
                    agent_names="researcher,analyst,writer",
                    max_concurrent=100,
                )
                result = json.loads(result_json)

        assert len(result["dispatches"]) == 3
        assert all(d["status"] == "success" for d in result["dispatches"])
        assert max(concurrency_levels) <= 2, f"Max concurrency was {max(concurrency_levels)}, expected <= 2"

    @pytest.mark.asyncio
    async def test_wall_clock_timeout(self):
        """Dispatch should timeout if agents take too long."""
        async def slow_execute(task):
            await asyncio.sleep(10)  # Way longer than timeout
            return "Done"

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.side_effect = slow_execute
            MockAgent.return_value = mock_instance

            with patch("config.DISPATCH_AGENTS_WALL_CLOCK_TIMEOUT", 0.1):
                result_json = await dispatch_tools.dispatch_agents(
                    task="Slow task",
                    agent_names="researcher",
                )
                result = json.loads(result_json)

        assert "error" in result
        assert "timed out" in result["error"].lower()
