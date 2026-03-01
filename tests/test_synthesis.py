import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_synthesize_results_basic():
    from orchestration.synthesis import synthesize_results

    mock_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Combined analysis: both agents agree on X.")]
    )

    with patch("orchestration.synthesis.AsyncAnthropic") as MockClient:
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response
        MockClient.return_value = mock_client

        result = await synthesize_results(
            task="Analyze Q4 performance",
            dispatches=[
                {"agent_name": "analyst", "status": "success", "result": "Revenue up 10%"},
                {"agent_name": "reviewer", "status": "success", "result": "Costs down 5%"},
            ],
        )
        assert "Combined analysis" in result
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
        assert call_kwargs["max_tokens"] == 1024


@pytest.mark.asyncio
async def test_synthesize_results_skips_errors():
    """Error agent results are included as context but flagged."""
    from orchestration.synthesis import synthesize_results

    mock_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Only analyst data available.")]
    )

    with patch("orchestration.synthesis.AsyncAnthropic") as MockClient:
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response
        MockClient.return_value = mock_client

        result = await synthesize_results(
            task="Analyze data",
            dispatches=[
                {"agent_name": "analyst", "status": "success", "result": "Data looks good"},
                {"agent_name": "broken", "status": "error", "result": "Agent execution failed"},
            ],
        )
        assert isinstance(result, str)
        # Verify the prompt included both results
        call_args = mock_client.messages.create.call_args[1]
        user_msg = call_args["messages"][0]["content"]
        assert "analyst" in user_msg
        assert "broken" in user_msg


@pytest.mark.asyncio
async def test_synthesize_results_single_agent_returns_directly():
    """With only one successful agent, return its result directly — no LLM call."""
    from orchestration.synthesis import synthesize_results

    result = await synthesize_results(
        task="Do a thing",
        dispatches=[
            {"agent_name": "solo", "status": "success", "result": "Solo result here"},
        ],
    )
    assert result == "Solo result here"


@pytest.mark.asyncio
async def test_synthesize_results_all_errors():
    """If all agents failed, return a structured error summary."""
    from orchestration.synthesis import synthesize_results

    result = await synthesize_results(
        task="Do a thing",
        dispatches=[
            {"agent_name": "a", "status": "error", "result": "Failed A"},
            {"agent_name": "b", "status": "error", "result": "Failed B"},
        ],
    )
    assert "failed" in result.lower() or "error" in result.lower()


@pytest.mark.asyncio
async def test_synthesize_results_api_failure_returns_fallback():
    """If the synthesis LLM call fails, return a fallback concatenation."""
    from orchestration.synthesis import synthesize_results

    with patch("orchestration.synthesis.AsyncAnthropic") as MockClient:
        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = Exception("API down")
        MockClient.return_value = mock_client

        result = await synthesize_results(
            task="Analyze",
            dispatches=[
                {"agent_name": "a", "status": "success", "result": "Result A"},
                {"agent_name": "b", "status": "success", "result": "Result B"},
            ],
        )
        # Fallback should contain both results
        assert "Result A" in result
        assert "Result B" in result
