# tests/test_checkpoint_session.py
import json

import pytest

from memory.models import Fact
from memory.store import MemoryStore


@pytest.fixture
def shared_state(tmp_path):
    """Create the shared state dict that lifespan would provide."""
    memory_store = MemoryStore(tmp_path / "test.db")
    state = {"memory_store": memory_store}
    yield state
    memory_store.close()


class TestCheckpointSession:
    @pytest.mark.asyncio
    async def test_stores_context_entry(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import checkpoint_session

        mcp_server._state.update(shared_state)
        try:
            result = await checkpoint_session("Discussed project architecture decisions")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "checkpoint_saved"
        assert data["context_id"] is not None
        assert data["facts_stored"] == 0

        # Verify the context entry was stored with correct topic
        entries = shared_state["memory_store"].list_context()
        assert len(entries) == 1
        assert entries[0].topic == "session_checkpoint"
        assert entries[0].summary == "Discussed project architecture decisions"
        assert entries[0].agent == "jarvis"

    @pytest.mark.asyncio
    async def test_stores_key_facts(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import checkpoint_session

        mcp_server._state.update(shared_state)
        try:
            result = await checkpoint_session(
                "Session with key decisions",
                key_facts="User prefers dark mode, Project deadline is March 1, Use Python 3.12",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "checkpoint_saved"
        assert data["facts_stored"] == 3

        # Verify facts were stored in the database
        facts = shared_state["memory_store"].search_facts("checkpoint_")
        assert len(facts) == 3

    @pytest.mark.asyncio
    async def test_empty_summary_returns_error(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import checkpoint_session

        mcp_server._state.update(shared_state)
        try:
            result = await checkpoint_session("")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data
        assert "Summary must not be empty" in data["error"]

    @pytest.mark.asyncio
    async def test_whitespace_only_summary_returns_error(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import checkpoint_session

        mcp_server._state.update(shared_state)
        try:
            result = await checkpoint_session("   ")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_empty_key_facts_stores_only_context(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import checkpoint_session

        mcp_server._state.update(shared_state)
        try:
            result = await checkpoint_session("Just a summary", key_facts="")
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "checkpoint_saved"
        assert data["facts_stored"] == 0

        # No facts should be stored
        facts = shared_state["memory_store"].search_facts("checkpoint_")
        assert len(facts) == 0

        # But context entry should exist
        entries = shared_state["memory_store"].list_context()
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_facts_have_correct_attributes(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import checkpoint_session

        mcp_server._state.update(shared_state)
        try:
            result = await checkpoint_session(
                "Test session",
                key_facts="Important fact",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["facts_stored"] == 1

        facts = shared_state["memory_store"].search_facts("checkpoint_")
        assert len(facts) == 1
        fact = facts[0]
        assert fact.category == "work"
        assert fact.confidence == 0.8
        assert fact.source == "session_checkpoint"
        assert fact.value == "Important fact"
        assert fact.key.startswith("checkpoint_")

    @pytest.mark.asyncio
    async def test_session_id_passed_to_context(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import checkpoint_session

        mcp_server._state.update(shared_state)
        try:
            result = await checkpoint_session(
                "Session summary",
                session_id="session-abc-123",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        assert data["status"] == "checkpoint_saved"

        entries = shared_state["memory_store"].list_context(session_id="session-abc-123")
        assert len(entries) == 1
        assert entries[0].session_id == "session-abc-123"

    @pytest.mark.asyncio
    async def test_skips_empty_facts_in_comma_list(self, shared_state):
        import mcp_server
        from mcp_tools.memory_tools import checkpoint_session

        mcp_server._state.update(shared_state)
        try:
            result = await checkpoint_session(
                "Test session",
                key_facts="fact one, , fact two, ",
            )
        finally:
            mcp_server._state.clear()

        data = json.loads(result)
        # Should only store 2 non-empty facts
        assert data["facts_stored"] == 2
