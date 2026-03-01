import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.registry import AgentConfig, AgentRegistry
from mcp_tools.state import ServerState
import mcp_tools.dispatch_tools as dispatch_tools


@pytest.fixture
def agent_registry(tmp_path):
    registry = AgentRegistry(tmp_path)
    registry.save_agent(AgentConfig(
        name="test-agent",
        description="Test",
        system_prompt="You are a test agent",
        capabilities=["memory_read"],
        model="claude-haiku-4-5-20251001",
    ))
    return registry


@pytest.fixture
def state(tmp_path, agent_registry):
    from memory.store import MemoryStore
    ms = MemoryStore(tmp_path / "test.db")
    s = ServerState()
    s.memory_store = ms
    s.agent_registry = agent_registry
    return s


@pytest.fixture(autouse=True)
def _register_tools(state):
    """Register dispatch tools with a mock MCP and inject state."""
    mock_mcp = MagicMock()
    mock_mcp.tool.return_value = lambda fn: fn
    dispatch_tools.register(mock_mcp, state)


@pytest.mark.asyncio
async def test_dispatch_with_synthesis():
    from mcp_tools.dispatch_tools import dispatch_agents

    with patch("agents.base.BaseExpertAgent") as MockAgent:
        mock_instance = AsyncMock()
        mock_instance.execute.return_value = "Agent result here"
        MockAgent.return_value = mock_instance

        with patch("orchestration.synthesis.synthesize_results", new_callable=AsyncMock) as mock_synth:
            mock_synth.return_value = "Synthesized output"

            with patch("config.DISPATCH_SYNTHESIS_ENABLED", True):
                result = json.loads(await dispatch_agents(
                    task="analyze something",
                    agent_names="test-agent",
                    synthesize=True,
                ))
                assert result.get("synthesized_summary") == "Synthesized output"
                mock_synth.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_without_synthesis_flag():
    from mcp_tools.dispatch_tools import dispatch_agents

    with patch("agents.base.BaseExpertAgent") as MockAgent:
        mock_instance = AsyncMock()
        mock_instance.execute.return_value = "Agent result"
        MockAgent.return_value = mock_instance

        result = json.loads(await dispatch_agents(
            task="analyze something",
            agent_names="test-agent",
            synthesize=False,
        ))
        assert "synthesized_summary" not in result


@pytest.mark.asyncio
async def test_dispatch_synthesis_disabled_by_config():
    from mcp_tools.dispatch_tools import dispatch_agents

    with patch("agents.base.BaseExpertAgent") as MockAgent:
        mock_instance = AsyncMock()
        mock_instance.execute.return_value = "Agent result"
        MockAgent.return_value = mock_instance

        with patch("config.DISPATCH_SYNTHESIS_ENABLED", False):
            result = json.loads(await dispatch_agents(
                task="analyze something",
                agent_names="test-agent",
                synthesize=True,
            ))
            # Config override: synthesis disabled even if requested
            assert "synthesized_summary" not in result
