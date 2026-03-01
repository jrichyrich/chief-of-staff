import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import mcp_server


@pytest.fixture
def playbooks_dir(tmp_path):
    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    (pb_dir / "test_pb.yaml").write_text("""
name: test_pb
description: Test playbook
inputs:
  - topic
workstreams:
  - name: researcher
    prompt: "Research $topic"
  - name: analyst
    prompt: "Analyze $topic"
synthesis:
  prompt: "Combine research and analysis on $topic"
delivery:
  default: inline
""")
    return pb_dir


@pytest.fixture
def agent_registry(tmp_path):
    from agents.registry import AgentConfig, AgentRegistry
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    registry = AgentRegistry(agents_dir)
    registry.save_agent(AgentConfig(
        name="researcher",
        description="Research agent",
        system_prompt="You research things",
        capabilities=["memory_read", "document_search"],
        model="claude-haiku-4-5-20251001",
    ))
    return registry


@pytest.fixture
def state(tmp_path, agent_registry):
    from memory.store import MemoryStore
    from mcp_tools.state import ServerState
    ms = MemoryStore(tmp_path / "test.db")
    return ServerState(memory_store=ms, agent_registry=agent_registry)


@pytest.fixture(autouse=True)
def inject_state(state):
    orig_ms = mcp_server._state.memory_store
    orig_ar = mcp_server._state.agent_registry
    mcp_server._state.memory_store = state.memory_store
    mcp_server._state.agent_registry = state.agent_registry
    yield
    mcp_server._state.memory_store = orig_ms
    mcp_server._state.agent_registry = orig_ar


@pytest.mark.asyncio
async def test_execute_playbook_tool(playbooks_dir):
    from mcp_tools.playbook_tools import execute_playbook

    mock_exec = AsyncMock(return_value={
        "playbook": "test_pb",
        "status": "completed",
        "workstream_results": [
            {"workstream": "researcher", "status": "success", "result": "Found data"},
            {"workstream": "analyst", "status": "success", "result": "Analyzed data"},
        ],
        "synthesized_summary": "Combined findings",
    })

    with patch("mcp_tools.playbook_tools._get_loader_dir", return_value=playbooks_dir):
        with patch("orchestration.playbook_executor.execute_playbook", mock_exec):
            result = json.loads(await execute_playbook(
                name="test_pb",
                inputs='{"topic": "AI safety"}',
            ))

    assert result["status"] == "completed"
    assert result["synthesized_summary"] == "Combined findings"


@pytest.mark.asyncio
async def test_execute_playbook_tool_not_found(playbooks_dir):
    from mcp_tools.playbook_tools import execute_playbook

    with patch("mcp_tools.playbook_tools._get_loader_dir", return_value=playbooks_dir):
        result = json.loads(await execute_playbook(
            name="nonexistent",
            inputs="{}",
        ))

    assert "error" in result


@pytest.mark.asyncio
async def test_execute_playbook_tool_missing_inputs(playbooks_dir):
    from mcp_tools.playbook_tools import execute_playbook

    mock_exec = AsyncMock(return_value={
        "playbook": "test_pb",
        "status": "completed",
        "workstream_results": [],
    })

    with patch("mcp_tools.playbook_tools._get_loader_dir", return_value=playbooks_dir):
        with patch("orchestration.playbook_executor.execute_playbook", mock_exec):
            result = json.loads(await execute_playbook(
                name="test_pb",
                inputs="{}",
            ))

    assert "warning" in result  # Should warn about missing 'topic' input
