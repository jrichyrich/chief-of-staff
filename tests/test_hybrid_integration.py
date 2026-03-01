"""End-to-end integration test for hybrid orchestration features."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from types import SimpleNamespace

from agents.registry import AgentConfig, AgentRegistry
from mcp_tools.state import ServerState
import mcp_tools.dispatch_tools as dispatch_tools
import mcp_server  # trigger registration


@pytest.fixture
def playbooks_dir(tmp_path):
    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    (pb_dir / "integration_test.yaml").write_text("""
name: integration_test
description: Integration test playbook
inputs:
  - query
workstreams:
  - name: source_a
    prompt: "Fetch data about $query from source A"
  - name: source_b
    prompt: "Fetch data about $query from source B"
synthesis:
  prompt: "Merge source A and B findings about $query"
delivery:
  default: inline
""")
    return pb_dir


@pytest.fixture
def full_state(tmp_path):
    from memory.store import MemoryStore

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    registry = AgentRegistry(agents_dir)

    for name in ("source_a", "source_b"):
        registry.save_agent(AgentConfig(
            name=name,
            description=f"Agent for {name}",
            system_prompt=f"You are {name}",
            capabilities=["memory_read"],
            model="claude-haiku-4-5-20251001",
        ))

    ms = MemoryStore(tmp_path / "test.db")
    s = ServerState()
    s.memory_store = ms
    s.agent_registry = registry
    return s


@pytest.fixture(autouse=True)
def inject_state(full_state):
    """Inject state into both mcp_server._state AND re-register dispatch tools."""
    orig_ms = mcp_server._state.memory_store
    orig_ar = mcp_server._state.agent_registry
    mcp_server._state.memory_store = full_state.memory_store
    mcp_server._state.agent_registry = full_state.agent_registry
    # Re-register dispatch tools so they capture our state
    mock_mcp = MagicMock()
    mock_mcp.tool.return_value = lambda fn: fn
    dispatch_tools.register(mock_mcp, full_state)
    yield
    mcp_server._state.memory_store = orig_ms
    mcp_server._state.agent_registry = orig_ar


@pytest.mark.asyncio
async def test_full_playbook_execution(playbooks_dir, full_state):
    """Full flow: load playbook -> dispatch workstreams -> synthesize."""
    from mcp_tools.playbook_tools import execute_playbook

    mock_agent = AsyncMock()
    mock_agent.execute.side_effect = [
        "Source A found: metric increased 15%",
        "Source B found: customer satisfaction up 20%",
    ]

    synth_response = SimpleNamespace(
        content=[SimpleNamespace(
            type="text",
            text="Both sources confirm positive trends: 15% metric increase and 20% satisfaction improvement.",
        )]
    )

    with patch("mcp_tools.playbook_tools._get_loader_dir", return_value=playbooks_dir):
        with patch("agents.base.BaseExpertAgent", return_value=mock_agent):
            with patch("orchestration.synthesis.AsyncAnthropic") as MockClient:
                mock_client = AsyncMock()
                mock_client.messages.create.return_value = synth_response
                MockClient.return_value = mock_client

                result = json.loads(await execute_playbook(
                    name="integration_test",
                    inputs='{"query": "Q4 performance"}',
                ))

    assert result["status"] == "completed"
    assert len(result["workstream_results"]) == 2
    assert "synthesized_summary" in result
    assert "positive trends" in result["synthesized_summary"]


@pytest.mark.asyncio
async def test_dispatch_with_synthesis_e2e():
    """dispatch_agents with synthesize=True produces a synthesized summary."""
    from mcp_tools.dispatch_tools import dispatch_agents

    mock_agent = AsyncMock()
    mock_agent.execute.return_value = "Analysis complete"

    synth_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Unified analysis from all agents.")]
    )

    with patch("agents.base.BaseExpertAgent", return_value=mock_agent):
        with patch("config.DISPATCH_SYNTHESIS_ENABLED", True):
            with patch("orchestration.synthesis.AsyncAnthropic") as MockClient:
                mock_client = AsyncMock()
                mock_client.messages.create.return_value = synth_response
                MockClient.return_value = mock_client

                result = json.loads(await dispatch_agents(
                    task="Analyze everything",
                    agent_names="source_a,source_b",
                    synthesize=True,
                ))

    assert "synthesized_summary" in result
    assert "Unified analysis" in result["synthesized_summary"]
