# tests/test_tool_definitions.py
from tools.definitions import get_chief_tools, CHIEF_TOOLS


class TestToolDefinitions:
    def test_all_tools_have_required_fields(self):
        tools = get_chief_tools()
        for tool in tools:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool {tool['name']} missing 'description'"
            assert "input_schema" in tool, f"Tool {tool['name']} missing 'input_schema'"
            assert tool["input_schema"]["type"] == "object"

    def test_expected_tools_exist(self):
        tools = get_chief_tools()
        names = [t["name"] for t in tools]
        assert "query_memory" in names
        assert "store_memory" in names
        assert "search_documents" in names
        assert "list_agents" in names
        assert "dispatch_agent" in names
        assert "create_agent" in names
        assert "dispatch_parallel" in names

    def test_tool_count(self):
        tools = get_chief_tools()
        assert len(tools) == 10
