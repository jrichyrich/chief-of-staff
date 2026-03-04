"""Tests for chief/imessage_tools.py — tool schema registry for async iMessage execution."""

import pytest
from unittest.mock import MagicMock


def test_build_tool_registry_returns_schemas_and_handlers():
    """Tool registry should return tool schemas and async handler functions."""
    from chief.imessage_tools import build_tool_registry

    mock_state = MagicMock()
    tools, handlers = build_tool_registry(mock_state)

    # Should have at least calendar, memory, and reminder tools
    tool_names = {t["name"] for t in tools}
    assert "get_calendar_events" in tool_names
    assert "query_memory" in tool_names
    assert "list_reminders" in tool_names
    assert "search_mail" in tool_names

    # Handlers should be callable for each tool
    for tool in tools:
        assert tool["name"] in handlers, f"Missing handler for {tool['name']}"
        assert callable(handlers[tool["name"]])


def test_async_safe_tools_list_is_conservative():
    """ASYNC_SAFE_TOOLS should only include read-heavy, low-risk tools."""
    from chief.imessage_tools import ASYNC_SAFE_TOOLS

    # Should NOT include destructive/write-heavy tools
    dangerous_tools = [
        "send_email",
        "reply_to_email",
        "delete_fact",
        "delete_decision",
        "delete_delegation",
        "delete_reminder",
        "create_calendar_event",
        "update_calendar_event",
        "delete_calendar_event",
        "send_notification",
        "post_teams_message",
        "move_mail_message",
        "mark_mail_read",
        "mark_mail_flagged",
        "send_imessage_reply",
    ]
    for tool in dangerous_tools:
        assert tool not in ASYNC_SAFE_TOOLS, f"{tool} should not be in ASYNC_SAFE_TOOLS"


def test_tool_schemas_have_required_fields():
    """Each tool schema should have name, description, and input_schema."""
    from chief.imessage_tools import build_tool_registry

    mock_state = MagicMock()
    tools, _ = build_tool_registry(mock_state)

    for tool in tools:
        assert "name" in tool, f"Tool missing 'name': {tool}"
        assert "description" in tool, f"Tool {tool.get('name', '?')} missing 'description'"
        assert "input_schema" in tool, f"Tool {tool['name']} missing 'input_schema'"
        schema = tool["input_schema"]
        assert schema.get("type") == "object", f"Tool {tool['name']} input_schema type must be 'object'"


def test_build_tool_registry_returns_all_async_safe_tools():
    """Registry should include all tools from ASYNC_SAFE_TOOLS that have handlers."""
    from chief.imessage_tools import build_tool_registry, ASYNC_SAFE_TOOLS

    mock_state = MagicMock()
    tools, handlers = build_tool_registry(mock_state)

    tool_names = {t["name"] for t in tools}
    handler_names = set(handlers.keys())

    # Every returned tool should have a handler
    assert tool_names == handler_names

    # Every tool should be from the ASYNC_SAFE_TOOLS list
    for name in tool_names:
        assert name in ASYNC_SAFE_TOOLS, f"Unexpected tool {name} not in ASYNC_SAFE_TOOLS"


def test_build_tool_registry_schemas_are_deep_copies():
    """Schemas should be independent copies, not references to the source."""
    from chief.imessage_tools import build_tool_registry

    mock_state = MagicMock()
    tools1, _ = build_tool_registry(mock_state)
    tools2, _ = build_tool_registry(mock_state)

    # Mutating one should not affect the other
    if tools1:
        tools1[0]["description"] = "MUTATED"
        assert tools2[0]["description"] != "MUTATED"


@pytest.mark.asyncio
async def test_handlers_are_async_callable():
    """Handlers returned by the registry should be async functions (or at least callable)."""
    from chief.imessage_tools import build_tool_registry

    mock_state = MagicMock()
    _, handlers = build_tool_registry(mock_state)

    # All handlers should be callable
    for name, handler in handlers.items():
        assert callable(handler), f"Handler {name} is not callable"
