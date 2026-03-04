import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_executor_sends_instruction_to_claude():
    """Executor should send message text to Claude and return result."""
    from chief.imessage_executor import IMessageExecutor

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_content_block = MagicMock()
    mock_content_block.type = "text"
    mock_content_block.text = "You have 3 meetings tomorrow."
    mock_response.content = [mock_content_block]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    executor = IMessageExecutor(client=mock_client)
    result = await executor.execute("Check my calendar for tomorrow")

    assert result == "You have 3 meetings tomorrow."
    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert "Check my calendar for tomorrow" in str(call_kwargs["messages"])


@pytest.mark.asyncio
async def test_executor_handles_tool_use_loop():
    """Executor should call tool handlers and feed results back to Claude."""
    from chief.imessage_executor import IMessageExecutor

    mock_client = AsyncMock()

    # First response: tool_use
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "get_calendar_events"
    tool_block.id = "tool_123"
    tool_block.input = {"days": 1}

    first_response = MagicMock()
    first_response.stop_reason = "tool_use"
    first_response.content = [tool_block]

    # Second response: text
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "You have a standup at 9am and a 1:1 at 2pm."

    second_response = MagicMock()
    second_response.stop_reason = "end_turn"
    second_response.content = [text_block]

    mock_client.messages.create = AsyncMock(side_effect=[first_response, second_response])

    async def mock_calendar(**kwargs):
        return '[{"title": "Standup", "time": "9:00"}, {"title": "1:1", "time": "14:00"}]'

    executor = IMessageExecutor(
        client=mock_client,
        tool_handlers={"get_calendar_events": mock_calendar},
    )
    result = await executor.execute("What meetings do I have today?")

    assert "standup" in result.lower() or "9am" in result.lower()
    assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_executor_handles_missing_tool():
    """Unknown tool should return error result to Claude, not crash."""
    from chief.imessage_executor import IMessageExecutor

    mock_client = AsyncMock()

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "nonexistent_tool"
    tool_block.id = "tool_999"
    tool_block.input = {}

    first_response = MagicMock()
    first_response.stop_reason = "tool_use"
    first_response.content = [tool_block]

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Sorry, I cannot do that."

    second_response = MagicMock()
    second_response.stop_reason = "end_turn"
    second_response.content = [text_block]

    mock_client.messages.create = AsyncMock(side_effect=[first_response, second_response])

    executor = IMessageExecutor(client=mock_client)
    result = await executor.execute("Do something special")

    assert result == "Sorry, I cannot do that."
    assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_executor_handles_tool_error():
    """Tool handler exception should be reported back to Claude."""
    from chief.imessage_executor import IMessageExecutor

    mock_client = AsyncMock()

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "broken_tool"
    tool_block.id = "tool_err"
    tool_block.input = {}

    first_response = MagicMock()
    first_response.stop_reason = "tool_use"
    first_response.content = [tool_block]

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "The tool failed, sorry."

    second_response = MagicMock()
    second_response.stop_reason = "end_turn"
    second_response.content = [text_block]

    mock_client.messages.create = AsyncMock(side_effect=[first_response, second_response])

    async def broken_handler(**kwargs):
        raise ValueError("database connection lost")

    executor = IMessageExecutor(
        client=mock_client,
        tool_handlers={"broken_tool": broken_handler},
    )
    result = await executor.execute("Use the broken tool")
    assert "failed" in result.lower() or "sorry" in result.lower()


@pytest.mark.asyncio
async def test_executor_respects_max_rounds():
    """Executor should stop after MAX_TOOL_ROUNDS even if Claude keeps calling tools."""
    from chief.imessage_executor import IMessageExecutor, MAX_TOOL_ROUNDS

    mock_client = AsyncMock()

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "infinite_tool"
    tool_block.id = "tool_loop"
    tool_block.input = {}

    loop_response = MagicMock()
    loop_response.stop_reason = "tool_use"
    loop_response.content = [tool_block]

    mock_client.messages.create = AsyncMock(return_value=loop_response)

    async def noop_handler(**kwargs):
        return "ok"

    executor = IMessageExecutor(
        client=mock_client,
        tool_handlers={"infinite_tool": noop_handler},
    )
    result = await executor.execute("Loop forever")

    assert "max tool rounds" in result.lower()
    assert mock_client.messages.create.call_count == MAX_TOOL_ROUNDS


@pytest.mark.asyncio
async def test_executor_no_text_returns_no_response():
    """If Claude returns no text blocks, result should be '(no response)'."""
    from chief.imessage_executor import IMessageExecutor

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = []  # no text blocks
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    executor = IMessageExecutor(client=mock_client)
    result = await executor.execute("Hello")
    assert result == "(no response)"
