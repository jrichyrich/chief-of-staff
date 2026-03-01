import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from playbooks.loader import Playbook, Workstream


def _make_playbook(name="test_pb", workstreams=None, synthesis_prompt="Synthesize all."):
    if workstreams is None:
        workstreams = [
            Workstream(name="ws_a", prompt="Do task A"),
            Workstream(name="ws_b", prompt="Do task B"),
        ]
    return Playbook(
        name=name,
        description="Test playbook",
        inputs=[],
        workstreams=workstreams,
        synthesis_prompt=synthesis_prompt,
    )


@pytest.mark.asyncio
async def test_execute_playbook_dispatches_workstreams():
    from orchestration.playbook_executor import execute_playbook

    mock_dispatch = AsyncMock(return_value=json.dumps({
        "dispatches": [
            {"agent_name": "ws_a", "status": "success", "result": "Result A"},
        ],
        "summary": "1 agents dispatched",
    }))

    mock_synth = AsyncMock(return_value="Final synthesis")

    with patch("orchestration.playbook_executor._dispatch_workstream", mock_dispatch):
        with patch("orchestration.synthesis.synthesize_results", mock_synth):
            result = await execute_playbook(
                playbook=_make_playbook(),
                agent_registry=MagicMock(),
                state=MagicMock(),
            )

    assert result["status"] == "completed"
    assert result["synthesized_summary"] == "Final synthesis"
    assert len(result["workstream_results"]) == 2


@pytest.mark.asyncio
async def test_execute_playbook_respects_conditions():
    from orchestration.playbook_executor import execute_playbook

    ws_always = Workstream(name="always", prompt="Always runs")
    ws_conditional = Workstream(name="conditional", prompt="Only if deep", condition="depth == thorough")

    pb = _make_playbook(workstreams=[ws_always, ws_conditional])

    mock_dispatch = AsyncMock(return_value=json.dumps({
        "dispatches": [{"agent_name": "always", "status": "success", "result": "Done"}],
        "summary": "ok",
    }))
    mock_synth = AsyncMock(return_value="Summary")

    with patch("orchestration.playbook_executor._dispatch_workstream", mock_dispatch):
        with patch("orchestration.synthesis.synthesize_results", mock_synth):
            # Without matching context — only unconditional workstream runs
            result = await execute_playbook(
                playbook=pb,
                agent_registry=MagicMock(),
                state=MagicMock(),
                context={"depth": "quick"},
            )
    assert len(result["workstream_results"]) == 1
    assert result["workstream_results"][0]["workstream"] == "always"


@pytest.mark.asyncio
async def test_execute_playbook_partial_failure():
    """One workstream failing should not prevent synthesis of successful ones."""
    from orchestration.playbook_executor import execute_playbook

    call_count = 0

    async def mock_dispatch(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        workstream = args[0]
        if workstream.name == "ws_b":
            raise Exception("Agent crashed")
        return json.dumps({
            "dispatches": [{"agent_name": workstream.name, "status": "success", "result": f"Result from {workstream.name}"}],
            "summary": "ok",
        })

    mock_synth = AsyncMock(return_value="Partial synthesis")

    with patch("orchestration.playbook_executor._dispatch_workstream", side_effect=mock_dispatch):
        with patch("orchestration.synthesis.synthesize_results", mock_synth):
            result = await execute_playbook(
                playbook=_make_playbook(),
                agent_registry=MagicMock(),
                state=MagicMock(),
            )

    assert result["status"] == "completed"
    assert any(r["status"] == "error" for r in result["workstream_results"])
    assert any(r["status"] == "success" for r in result["workstream_results"])


@pytest.mark.asyncio
async def test_execute_playbook_no_synthesis_prompt():
    """If no synthesis_prompt, skip synthesis and return raw results."""
    from orchestration.playbook_executor import execute_playbook

    mock_dispatch = AsyncMock(return_value=json.dumps({
        "dispatches": [{"agent_name": "ws_a", "status": "success", "result": "Done"}],
        "summary": "ok",
    }))

    with patch("orchestration.playbook_executor._dispatch_workstream", mock_dispatch):
        result = await execute_playbook(
            playbook=_make_playbook(synthesis_prompt=""),
            agent_registry=MagicMock(),
            state=MagicMock(),
        )

    assert "synthesized_summary" not in result
    assert result["status"] == "completed"
