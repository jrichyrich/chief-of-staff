# tests/test_meeting_agents.py
"""Tests for meeting_prep and meeting_debrief agent configs."""
import re
from pathlib import Path

import pytest

from agents.registry import AgentRegistry, AgentConfig
from capabilities.registry import get_tools_for_capabilities, validate_capabilities

# Use the real agent_configs directory so we test the actual YAML files.
AGENT_CONFIGS_DIR = Path(__file__).resolve().parent.parent / "agent_configs"


@pytest.fixture
def registry():
    return AgentRegistry(AGENT_CONFIGS_DIR)


class TestMeetingPrepConfig:
    def test_loads_correctly(self, registry):
        config = registry.get_agent("meeting_prep")
        assert config is not None
        assert config.name == "meeting_prep"

    def test_has_required_capabilities(self, registry):
        config = registry.get_agent("meeting_prep")
        assert config is not None
        required = {
            "memory_read",
            "document_search",
            "calendar_read",
            "reminders_read",
            "mail_read",
            "decision_read",
            "delegation_read",
        }
        assert required.issubset(set(config.capabilities))

    def test_prompt_contains_freshness_language(self, registry):
        config = registry.get_agent("meeting_prep")
        assert config is not None
        prompt_lower = config.system_prompt.lower()
        assert "always pull fresh" in prompt_lower or "never use cached" in prompt_lower

    def test_produces_valid_tool_list(self, registry):
        config = registry.get_agent("meeting_prep")
        assert config is not None
        tools = get_tools_for_capabilities(config.capabilities)
        assert len(tools) > 0
        tool_names = {t["name"] for t in tools}
        # Should include tools from decision_read and delegation_read
        assert "search_decisions" in tool_names
        assert "list_delegations" in tool_names


class TestMeetingDebriefConfig:
    def test_loads_correctly(self, registry):
        config = registry.get_agent("meeting_debrief")
        assert config is not None
        assert config.name == "meeting_debrief"

    def test_has_required_capabilities(self, registry):
        config = registry.get_agent("meeting_debrief")
        assert config is not None
        required = {
            "memory_read",
            "memory_write",
            "decision_write",
            "delegation_write",
            "calendar_read",
        }
        assert required.issubset(set(config.capabilities))

    def test_prompt_mentions_structured_tools(self, registry):
        config = registry.get_agent("meeting_debrief")
        assert config is not None
        assert "create_decision" in config.system_prompt
        assert "create_delegation" in config.system_prompt

    def test_produces_valid_tool_list(self, registry):
        config = registry.get_agent("meeting_debrief")
        assert config is not None
        tools = get_tools_for_capabilities(config.capabilities)
        assert len(tools) > 0
        tool_names = {t["name"] for t in tools}
        # Should include write tools
        assert "create_decision" in tool_names
        assert "create_delegation" in tool_names
        assert "store_memory" in tool_names
