"""Tests for teams_write capability."""

from capabilities.registry import (
    CAPABILITY_DEFINITIONS,
    TOOL_SCHEMAS,
    get_tools_for_capabilities,
    validate_capabilities,
)


def test_teams_write_capability_defined():
    defn = CAPABILITY_DEFINITIONS["teams_write"]
    assert "open_teams_browser" in defn.tool_names
    assert "post_teams_message" in defn.tool_names
    assert "confirm_teams_post" in defn.tool_names
    assert "cancel_teams_post" in defn.tool_names
    assert "close_teams_browser" in defn.tool_names


def test_teams_write_tool_schemas_exist():
    for name in ("open_teams_browser", "post_teams_message",
                 "confirm_teams_post", "cancel_teams_post", "close_teams_browser"):
        assert name in TOOL_SCHEMAS
        assert TOOL_SCHEMAS[name]["name"] == name


def test_post_teams_message_schema_has_target():
    schema = TOOL_SCHEMAS["post_teams_message"]
    props = schema["input_schema"]["properties"]
    assert "target" in props
    assert "message" in props
    assert "channel_url" not in props


def test_teams_write_returns_all_tools():
    tools = get_tools_for_capabilities(["teams_write"])
    names = [t["name"] for t in tools]
    assert "open_teams_browser" in names
    assert "close_teams_browser" in names
    assert "post_teams_message" in names


def test_teams_write_validates():
    validated = validate_capabilities(["teams_write"])
    assert "teams_write" in validated
