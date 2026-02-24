"""Tests for teams_write capability."""

from capabilities.registry import (
    CAPABILITY_DEFINITIONS,
    TOOL_SCHEMAS,
    get_tools_for_capabilities,
    validate_capabilities,
)


def test_teams_write_capability_defined():
    assert "teams_write" in CAPABILITY_DEFINITIONS
    defn = CAPABILITY_DEFINITIONS["teams_write"]
    assert "post_teams_message" in defn.tool_names


def test_teams_write_tool_schema_exists():
    assert "post_teams_message" in TOOL_SCHEMAS
    schema = TOOL_SCHEMAS["post_teams_message"]
    assert schema["name"] == "post_teams_message"
    assert "channel_url" in schema["input_schema"]["properties"]
    assert "message" in schema["input_schema"]["properties"]


def test_teams_write_capability_returns_tools():
    tools = get_tools_for_capabilities(["teams_write"])
    tool_names = [t["name"] for t in tools]
    assert "post_teams_message" in tool_names


def test_teams_write_validates():
    validated = validate_capabilities(["teams_write"])
    assert "teams_write" in validated
