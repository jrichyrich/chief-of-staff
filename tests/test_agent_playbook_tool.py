# tests/test_agent_playbook_tool.py
"""Tests for get_agent_as_playbook MCP tool and get_mcp_alternatives registry function."""

import json

import pytest

from agents.registry import AgentConfig, AgentRegistry
from capabilities.registry import (
    CAPABILITY_DEFINITIONS,
    MCP_ALTERNATIVES,
    get_mcp_alternatives,
)
from documents.store import DocumentStore
from memory.models import AgentMemory
from memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def shared_state(tmp_path):
    """Create the shared state dict that lifespan would provide."""
    memory_store = MemoryStore(tmp_path / "test.db")
    document_store = DocumentStore(persist_dir=tmp_path / "chroma")
    configs_dir = tmp_path / "agent_configs"
    configs_dir.mkdir()
    agent_registry = AgentRegistry(configs_dir)

    state = {
        "memory_store": memory_store,
        "document_store": document_store,
        "agent_registry": agent_registry,
    }

    yield state
    memory_store.close()


def _create_test_agent(registry: AgentRegistry, **overrides) -> AgentConfig:
    """Helper to create and save a test agent with sensible defaults."""
    defaults = {
        "name": "test-agent",
        "description": "A test agent",
        "system_prompt": "You are a test agent. Follow these steps:\n1. Do thing A\n2. Do thing B",
        "capabilities": ["memory_read", "calendar_read"],
        "namespaces": [],
        "temperature": 0.3,
        "max_tokens": 4096,
        "model": "sonnet",
    }
    defaults.update(overrides)
    config = AgentConfig(**defaults)
    registry.save_agent(config)
    return config


# ---------------------------------------------------------------------------
# Tests: get_mcp_alternatives
# ---------------------------------------------------------------------------


class TestGetMcpAlternatives:
    """Tests for the get_mcp_alternatives registry function."""

    def test_known_capability_returns_mapping(self):
        result = get_mcp_alternatives("calendar_read")
        assert result is not None
        assert "primary" in result
        assert "note" in result

    def test_unknown_capability_returns_none(self):
        result = get_mcp_alternatives("nonexistent_capability")
        assert result is None

    def test_all_entries_have_required_keys(self):
        """Every entry in MCP_ALTERNATIVES must have 'primary' and 'note'."""
        for cap_name, mapping in MCP_ALTERNATIVES.items():
            assert "primary" in mapping, f"{cap_name} missing 'primary'"
            assert "note" in mapping, f"{cap_name} missing 'note'"
            assert isinstance(mapping["primary"], str), f"{cap_name} 'primary' must be str"
            assert isinstance(mapping["note"], str), f"{cap_name} 'note' must be str"

    def test_all_mapped_capabilities_exist_in_definitions(self):
        """Every capability in MCP_ALTERNATIVES should be a real capability."""
        for cap_name in MCP_ALTERNATIVES:
            assert cap_name in CAPABILITY_DEFINITIONS, (
                f"MCP_ALTERNATIVES references unknown capability: {cap_name}"
            )

    @pytest.mark.parametrize("cap_name", list(MCP_ALTERNATIVES.keys()))
    def test_each_alternative_has_primary(self, cap_name):
        result = get_mcp_alternatives(cap_name)
        assert result is not None
        assert result["primary"]  # Non-empty string


# ---------------------------------------------------------------------------
# Tests: get_agent_as_playbook
# ---------------------------------------------------------------------------


class TestGetAgentAsPlaybook:
    """Tests for the get_agent_as_playbook MCP tool."""

    @pytest.mark.asyncio
    async def test_valid_agent_returns_playbook_structure(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        _create_test_agent(shared_state["agent_registry"])

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["mode"] == "playbook"
        assert data["name"] == "test-agent"
        assert data["description"] == "A test agent"
        assert "instructions" in data
        assert "You are a test agent" in data["instructions"]
        assert "capabilities_needed" in data
        assert "tool_guidance" in data
        assert "output_settings" in data
        assert "agent_memory" in data
        assert "note" in data

    @pytest.mark.asyncio
    async def test_nonexistent_agent_returns_error(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("nonexistent-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data
        assert "nonexistent-agent" in data["error"]

    @pytest.mark.asyncio
    async def test_tool_guidance_includes_mcp_alternatives(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        # Create agent with calendar_read — which has MCP alternatives
        _create_test_agent(
            shared_state["agent_registry"],
            capabilities=["calendar_read"],
        )

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        guidance = data["tool_guidance"]
        assert len(guidance) >= 1

        cal_entry = next(g for g in guidance if g["capability"] == "calendar_read")
        assert "mcp_alternatives" in cal_entry
        assert "primary" in cal_entry["mcp_alternatives"]
        assert cal_entry["mcp_alternatives"]["primary"] == MCP_ALTERNATIVES["calendar_read"]["primary"]

    @pytest.mark.asyncio
    async def test_tool_guidance_handles_no_mcp_alternative(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        # memory_read has no MCP alternative defined
        _create_test_agent(
            shared_state["agent_registry"],
            capabilities=["memory_read"],
        )

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        guidance = data["tool_guidance"]
        mem_entry = next(g for g in guidance if g["capability"] == "memory_read")
        assert "mcp_alternatives" not in mem_entry
        assert "jarvis_tools" in mem_entry
        assert len(mem_entry["jarvis_tools"]) > 0

    @pytest.mark.asyncio
    async def test_agent_memory_included_when_present(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        _create_test_agent(shared_state["agent_registry"])

        # Store some agent memories
        memory_store = shared_state["memory_store"]
        memory_store.store_agent_memory(AgentMemory(
            agent_name="test-agent", memory_type="insight", key="key1", value="value1", confidence=0.9
        ))
        memory_store.store_agent_memory(AgentMemory(
            agent_name="test-agent", memory_type="context", key="key2", value="value2", confidence=1.0
        ))

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert len(data["agent_memory"]) == 2
        keys = {m["key"] for m in data["agent_memory"]}
        assert keys == {"key1", "key2"}

    @pytest.mark.asyncio
    async def test_agent_memory_empty_when_none(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        _create_test_agent(shared_state["agent_registry"])

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["agent_memory"] == []

    @pytest.mark.asyncio
    async def test_shared_namespace_memories_included(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        # Create agent with namespaces
        _create_test_agent(
            shared_state["agent_registry"],
            namespaces=["research-team"],
        )

        # Store shared memory in that namespace
        memory_store = shared_state["memory_store"]
        memory_store.store_shared_memory(
            "research-team", "insight", "finding1", "Important finding", confidence=0.8
        )

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "shared_memories" in data
        assert "research-team" in data["shared_memories"]
        ns_mems = data["shared_memories"]["research-team"]
        assert len(ns_mems) == 1
        assert ns_mems[0]["key"] == "finding1"
        assert ns_mems[0]["value"] == "Important finding"

    @pytest.mark.asyncio
    async def test_shared_memories_omitted_when_empty(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        _create_test_agent(
            shared_state["agent_registry"],
            namespaces=["empty-ns"],
        )

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "shared_memories" not in data

    @pytest.mark.asyncio
    async def test_output_settings_reflect_config(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        _create_test_agent(
            shared_state["agent_registry"],
            temperature=0.7,
            max_tokens=8192,
            model="opus",
        )

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        settings = data["output_settings"]
        assert settings["model_tier"] == "opus"
        assert settings["temperature"] == 0.7
        assert settings["max_tokens"] == 8192

    @pytest.mark.asyncio
    async def test_capabilities_needed_matches_config(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        _create_test_agent(
            shared_state["agent_registry"],
            capabilities=["memory_read", "mail_read", "calendar_read"],
        )

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert set(data["capabilities_needed"]) == {"memory_read", "mail_read", "calendar_read"}

    @pytest.mark.asyncio
    async def test_tool_guidance_has_jarvis_tools(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        _create_test_agent(
            shared_state["agent_registry"],
            capabilities=["calendar_read"],
        )

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        guidance = data["tool_guidance"]
        cal_entry = next(g for g in guidance if g["capability"] == "calendar_read")
        assert "jarvis_tools" in cal_entry
        # calendar_read should have get_calendar_events and search_calendar_events
        assert "get_calendar_events" in cal_entry["jarvis_tools"]

    @pytest.mark.asyncio
    async def test_invalid_agent_name_returns_error(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("INVALID NAME!")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_multiple_capabilities_all_have_guidance(self, shared_state):
        import mcp_server
        from mcp_tools.agent_tools import get_agent_as_playbook

        _create_test_agent(
            shared_state["agent_registry"],
            capabilities=["memory_read", "calendar_read", "mail_read"],
        )

        mcp_server._state.update(shared_state)
        try:
            result = await get_agent_as_playbook("test-agent")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        guidance_caps = {g["capability"] for g in data["tool_guidance"]}
        assert "memory_read" in guidance_caps
        assert "calendar_read" in guidance_caps
        assert "mail_read" in guidance_caps


# ---------------------------------------------------------------------------
# Tests: MCP registration
# ---------------------------------------------------------------------------


class TestPlaybookToolRegistration:
    """Verify get_agent_as_playbook is registered as an MCP tool."""

    def test_tool_registered(self):
        import mcp_server
        tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
        assert "get_agent_as_playbook" in tool_names
