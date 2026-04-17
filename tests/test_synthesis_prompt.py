"""Tests for the synthesis prompt content and behavior."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestration.synthesis import _SYNTHESIS_SYSTEM, synthesize_results


def test_synthesis_system_prompt_includes_ranking_rules():
    """System prompt must specify ranking criteria, not just 'summarize'."""
    prompt = _SYNTHESIS_SYSTEM.lower()
    assert "relevance" in prompt, "prompt must mention relevance-based ranking"
    assert "deduplicat" in prompt, "prompt must instruct deduplication"
    assert "escalation" in prompt or "priority" in prompt, (
        "prompt must establish priority ordering"
    )
    assert "action" in prompt, "prompt must surface action items"


def test_synthesis_system_prompt_forbids_raw_dump():
    """Prompt must explicitly forbid dumping unfiltered agent output."""
    prompt = _SYNTHESIS_SYSTEM.lower()
    assert "do not dump" in prompt or "never dump" in prompt or "no raw" in prompt


@pytest.mark.asyncio
async def test_synthesis_instruction_contains_output_contract():
    """The per-call instruction block must specify output structure."""
    from orchestration import synthesis as s

    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        mock = MagicMock()
        mock.content = [MagicMock(text="ok")]
        mock.usage = MagicMock(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0
        )
        return mock

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch.object(s, "AsyncAnthropic", return_value=mock_client):
        await synthesize_results(
            task="daily brief",
            dispatches=[
                {"agent_name": "a", "status": "success", "result": "x"},
                {"agent_name": "b", "status": "success", "result": "y"},
            ],
        )

    user_content = captured["messages"][0]["content"].lower()
    assert "dedupl" in user_content or "merge" in user_content, (
        "instruction must tell the model how to handle duplicates"
    )
    assert "category" in user_content or "priority" in user_content, (
        "instruction must tell the model how to order items"
    )


@pytest.mark.asyncio
async def test_brief_type_injected_into_user_content():
    """brief_type='cio-weekly' must appear in the user content sent to the model."""
    from orchestration import synthesis as s

    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        mock = MagicMock()
        mock.content = [MagicMock(text="ok")]
        mock.usage = MagicMock(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0
        )
        return mock

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch.object(s, "AsyncAnthropic", return_value=mock_client):
        await synthesize_results(
            task="weekly brief",
            dispatches=[
                {"agent_name": "a", "status": "success", "result": "x"},
                {"agent_name": "b", "status": "success", "result": "y"},
            ],
            brief_type="cio-weekly",
        )

    user_content = captured["messages"][0]["content"].lower()
    assert "brief type" in user_content, (
        "## Brief Type section must appear in user content when brief_type is set"
    )
    assert "cio-weekly" in user_content, (
        "brief_type value must be present in the user content sent to the model"
    )


@pytest.mark.asyncio
async def test_no_brief_type_section_when_not_supplied():
    """When brief_type is not passed, the ## Brief Type section must not appear."""
    from orchestration import synthesis as s

    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        mock = MagicMock()
        mock.content = [MagicMock(text="ok")]
        mock.usage = MagicMock(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0
        )
        return mock

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch.object(s, "AsyncAnthropic", return_value=mock_client):
        await synthesize_results(
            task="daily brief",
            dispatches=[
                {"agent_name": "a", "status": "success", "result": "x"},
                {"agent_name": "b", "status": "success", "result": "y"},
            ],
        )

    user_content = captured["messages"][0]["content"].lower()
    assert "## brief type" not in user_content, (
        "## Brief Type section must NOT appear when brief_type is not supplied"
    )
