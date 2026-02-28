"""Tests for session management: SessionManager, MCP tools, and proactive integration."""

import json

import pytest

from memory.store import MemoryStore
from mcp_tools.state import ServerState, SessionHealth
from proactive.engine import ProactiveSuggestionEngine
from session.brain import SessionBrain
from session.manager import SessionManager


# --- Fixtures ---



@pytest.fixture
def session_mgr(memory_store):
    return SessionManager(memory_store, session_id="test-session-001")


@pytest.fixture
def state(memory_store, session_mgr):
    s = ServerState()
    s.memory_store = memory_store
    s.session_manager = session_mgr
    return s


# --- SessionManager Core Tests ---


class TestSessionManagerInit:
    def test_auto_generates_session_id(self, memory_store):
        mgr = SessionManager(memory_store)
        assert mgr.session_id  # not empty
        assert len(mgr.session_id) == 36  # UUID format

    def test_custom_session_id(self, memory_store):
        mgr = SessionManager(memory_store, session_id="custom-123")
        assert mgr.session_id == "custom-123"

    def test_initial_state_empty(self, session_mgr):
        assert session_mgr.interaction_count == 0
        assert session_mgr.estimate_tokens() == 0


class TestTrackInteraction:
    def test_basic_tracking(self, session_mgr):
        session_mgr.track_interaction("user", "Hello world")
        assert session_mgr.interaction_count == 1

    def test_multiple_interactions(self, session_mgr):
        session_mgr.track_interaction("user", "First message")
        session_mgr.track_interaction("assistant", "Response")
        session_mgr.track_interaction("user", "Follow up")
        assert session_mgr.interaction_count == 3

    def test_with_tool_info(self, session_mgr):
        session_mgr.track_interaction(
            "assistant", "Using tool",
            tool_name="query_memory", tool_args={"query": "test"},
        )
        assert session_mgr.interaction_count == 1

    def test_empty_content(self, session_mgr):
        session_mgr.track_interaction("user", "")
        assert session_mgr.interaction_count == 1


class TestEstimateTokens:
    def test_empty_buffer(self, session_mgr):
        assert session_mgr.estimate_tokens() == 0

    def test_single_word(self, session_mgr):
        session_mgr.track_interaction("user", "hello")
        # 1 word * 1.3 = 1.3 -> int = 1
        assert session_mgr.estimate_tokens() == 1

    def test_multiple_words(self, session_mgr):
        session_mgr.track_interaction("user", "hello world foo bar baz")
        # 5 words * 1.3 = 6.5 -> int = 6
        assert session_mgr.estimate_tokens() == 6

    def test_includes_tool_name(self, session_mgr):
        session_mgr.track_interaction(
            "assistant", "result",
            tool_name="query_memory",
        )
        # "result" = 1 word, "query_memory" = 1 word -> 2 * 1.3 = 2.6 -> 2
        assert session_mgr.estimate_tokens() == 2

    def test_includes_tool_args(self, session_mgr):
        session_mgr.track_interaction(
            "assistant", "result",
            tool_name="store_fact",
            tool_args={"category": "work", "key": "test"},
        )
        # Content "result" = 1, tool_name "store_fact" = 1
        # tool_args str repr words count
        tokens = session_mgr.estimate_tokens()
        assert tokens > 2  # more than just content + tool_name

    def test_accumulates_across_interactions(self, session_mgr):
        session_mgr.track_interaction("user", "one two three")  # 3 words
        session_mgr.track_interaction("assistant", "four five")  # 2 words
        # 5 * 1.3 = 6.5 -> 6
        assert session_mgr.estimate_tokens() == 6


class TestExtractStructuredData:
    def test_empty_buffer(self, session_mgr):
        result = session_mgr.extract_structured_data()
        assert result == {"decisions": [], "action_items": [], "key_facts": [], "general": []}

    def test_detects_decisions(self, session_mgr):
        session_mgr.track_interaction("user", "We decided to use Python for the backend")
        session_mgr.track_interaction("user", "The decision was unanimous")
        session_mgr.track_interaction("user", "We agreed on the timeline")
        session_mgr.track_interaction("user", "We will do the migration next week")
        result = session_mgr.extract_structured_data()
        assert len(result["decisions"]) == 4

    def test_detects_action_items(self, session_mgr):
        session_mgr.track_interaction("user", "TODO: update the docs")
        session_mgr.track_interaction("user", "We need to fix the bug")
        session_mgr.track_interaction("user", "I should write tests first")
        session_mgr.track_interaction("user", "action item: deploy to staging")
        result = session_mgr.extract_structured_data()
        assert len(result["action_items"]) == 4

    def test_detects_key_facts(self, session_mgr):
        session_mgr.track_interaction("user", "This is important for the project")
        session_mgr.track_interaction("user", "Note that the API rate limit is 100/min")
        session_mgr.track_interaction("user", "Remember to check the credentials")
        result = session_mgr.extract_structured_data()
        assert len(result["key_facts"]) == 3

    def test_general_catchall(self, session_mgr):
        session_mgr.track_interaction("user", "Just a regular message")
        session_mgr.track_interaction("user", "Another plain message")
        result = session_mgr.extract_structured_data()
        assert len(result["general"]) == 2
        assert result["decisions"] == []
        assert result["action_items"] == []
        assert result["key_facts"] == []

    def test_priority_decision_over_action(self, session_mgr):
        """When content matches both decision and action patterns, decision wins."""
        session_mgr.track_interaction("user", "We decided we need to rewrite the module")
        result = session_mgr.extract_structured_data()
        # "decided" matches decision pattern, "need to" matches action — decision wins
        assert len(result["decisions"]) == 1
        assert len(result["action_items"]) == 0

    def test_skips_empty_content(self, session_mgr):
        session_mgr.track_interaction("user", "")
        session_mgr.track_interaction("user", "   ")
        result = session_mgr.extract_structured_data()
        assert result == {"decisions": [], "action_items": [], "key_facts": [], "general": []}

    def test_mixed_content(self, session_mgr):
        session_mgr.track_interaction("user", "We decided on approach A")
        session_mgr.track_interaction("user", "TODO: implement approach A")
        session_mgr.track_interaction("user", "Note that it requires Python 3.12")
        session_mgr.track_interaction("user", "Let's move forward")
        result = session_mgr.extract_structured_data()
        assert len(result["decisions"]) == 1
        assert len(result["action_items"]) == 1
        assert len(result["key_facts"]) == 1
        assert len(result["general"]) == 1

    def test_case_insensitive_matching(self, session_mgr):
        session_mgr.track_interaction("user", "DECIDED to go with option B")
        session_mgr.track_interaction("user", "todo: check the logs")
        session_mgr.track_interaction("user", "IMPORTANT: deadline is Friday")
        result = session_mgr.extract_structured_data()
        assert len(result["decisions"]) == 1
        assert len(result["action_items"]) == 1
        assert len(result["key_facts"]) == 1


class TestFlush:
    def test_flush_all(self, session_mgr, memory_store):
        session_mgr.track_interaction("user", "We decided to migrate")
        session_mgr.track_interaction("user", "TODO: write migration script")
        session_mgr.track_interaction("user", "Note that prod DB is on RDS")

        result = session_mgr.flush(priority_threshold="all")
        assert result["decisions_stored"] == 1
        assert result["actions_stored"] == 1
        assert result["facts_stored"] == 1
        assert result["summary_length"] > 0

        # Verify facts were persisted
        facts = memory_store.search_facts("session_decision")
        assert len(facts) >= 1
        facts = memory_store.search_facts("session_action")
        assert len(facts) >= 1
        facts = memory_store.search_facts("session_fact")
        assert len(facts) >= 1

    def test_flush_decisions_only(self, session_mgr, memory_store):
        session_mgr.track_interaction("user", "We decided to use Redis")
        session_mgr.track_interaction("user", "TODO: set up Redis cluster")
        session_mgr.track_interaction("user", "Note that Redis is in-memory")

        result = session_mgr.flush(priority_threshold="decisions")
        assert result["decisions_stored"] == 1
        assert result["actions_stored"] == 0
        assert result["facts_stored"] == 0

    def test_flush_action_items_includes_decisions(self, session_mgr):
        session_mgr.track_interaction("user", "We decided on X")
        session_mgr.track_interaction("user", "TODO: implement X")
        session_mgr.track_interaction("user", "Note that X is complex")

        result = session_mgr.flush(priority_threshold="action_items")
        assert result["decisions_stored"] == 1
        assert result["actions_stored"] == 1
        assert result["facts_stored"] == 0

    def test_flush_key_facts_includes_all_except_general(self, session_mgr):
        session_mgr.track_interaction("user", "We decided on Y")
        session_mgr.track_interaction("user", "TODO: implement Y")
        session_mgr.track_interaction("user", "Note that Y has side effects")
        session_mgr.track_interaction("user", "Just chatting")

        result = session_mgr.flush(priority_threshold="key_facts")
        assert result["decisions_stored"] == 1
        assert result["actions_stored"] == 1
        assert result["facts_stored"] == 1

    def test_flush_creates_context_entry(self, session_mgr, memory_store):
        session_mgr.track_interaction("user", "Some context here")
        session_mgr.flush()

        entries = memory_store.list_context(session_id="test-session-001")
        assert len(entries) == 1
        assert "[Session Flush]" in entries[0].summary

    def test_flush_empty_session(self, session_mgr):
        result = session_mgr.flush()
        assert result["decisions_stored"] == 0
        assert result["actions_stored"] == 0
        assert result["facts_stored"] == 0
        assert result["summary_length"] > 0  # still generates "empty session" summary

    def test_flush_stores_with_correct_source(self, session_mgr, memory_store):
        session_mgr.track_interaction("user", "We decided to go")
        session_mgr.flush()

        facts = memory_store.search_facts("session_decision")
        assert len(facts) >= 1
        assert facts[0].source == "session_flush"


class TestGetSessionSummary:
    def test_empty_session(self, session_mgr):
        summary = session_mgr.get_session_summary()
        assert "Empty session" in summary

    def test_summary_includes_counts(self, session_mgr):
        session_mgr.track_interaction("user", "We decided on A")
        session_mgr.track_interaction("user", "TODO: implement B")
        session_mgr.track_interaction("user", "Regular chat")

        summary = session_mgr.get_session_summary()
        assert "3 interactions" in summary
        assert "1 decision" in summary
        assert "1 action item" in summary
        assert "tokens" in summary

    def test_summary_includes_key_decision(self, session_mgr):
        session_mgr.track_interaction("user", "We decided to use PostgreSQL for storage")
        summary = session_mgr.get_session_summary()
        assert "Key decision:" in summary
        assert "PostgreSQL" in summary

    def test_summary_truncates_long_content(self, session_mgr):
        long_text = "We decided to " + "x" * 200
        session_mgr.track_interaction("user", long_text)
        summary = session_mgr.get_session_summary()
        assert "..." in summary

    def test_summary_shows_action_when_no_decisions(self, session_mgr):
        session_mgr.track_interaction("user", "TODO: fix the auth bug in login flow")
        summary = session_mgr.get_session_summary()
        assert "Key action:" in summary
        assert "auth bug" in summary


class TestRestoreFromCheckpoint:
    def test_restore_empty(self, session_mgr):
        result = session_mgr.restore_from_checkpoint("nonexistent-session")
        assert result["session_id"] == "nonexistent-session"
        assert result["context_entries"] == []

    def test_restore_after_flush(self, session_mgr, memory_store):
        session_mgr.track_interaction("user", "We decided to use caching")
        session_mgr.flush()

        # Create a new manager and restore
        new_mgr = SessionManager(memory_store)
        result = new_mgr.restore_from_checkpoint("test-session-001")
        assert result["session_id"] == "test-session-001"
        assert len(result["context_entries"]) >= 1
        assert len(result["related_facts"]) >= 1

    def test_restore_includes_context_summaries(self, session_mgr, memory_store):
        session_mgr.track_interaction("user", "Some important work")
        session_mgr.flush()

        result = session_mgr.restore_from_checkpoint("test-session-001")
        entry = result["context_entries"][0]
        assert "topic" in entry
        assert "summary" in entry
        assert "created_at" in entry


# --- MCP Tool Tests ---


class TestSessionMCPTools:
    """Test the MCP tool functions for session management."""

    @pytest.fixture(autouse=True)
    def setup_mcp(self, state):
        """Import mcp_server to trigger registration, then set up state."""
        import mcp_server
        from mcp_tools import session_tools

        # Store references before registration
        self._state = state

        # Re-register with our test state
        from unittest.mock import MagicMock
        mock_mcp = MagicMock()
        # Capture the tool decorator calls
        mock_mcp.tool.return_value = lambda fn: fn
        session_tools.register(mock_mcp, state)

    @pytest.mark.asyncio
    async def test_get_session_status(self, state):
        from mcp_tools.session_tools import get_session_status
        state.session_manager.track_interaction("user", "We decided to refactor")
        state.session_manager.track_interaction("user", "TODO: write tests")

        result_json = await get_session_status()
        result = json.loads(result_json)
        assert result["session_id"] == "test-session-001"
        assert result["interaction_count"] == 2
        assert result["token_estimate"] > 0
        assert result["extracted_items_preview"]["decisions"] == 1
        assert result["extracted_items_preview"]["action_items"] == 1
        assert "context_window_usage" in result

    @pytest.mark.asyncio
    async def test_get_session_status_no_manager(self, state):
        from mcp_tools.session_tools import get_session_status
        state.session_manager = None
        result_json = await get_session_status()
        result = json.loads(result_json)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_flush_session_memory(self, state):
        from mcp_tools.session_tools import flush_session_memory
        state.session_manager.track_interaction("user", "We decided to deploy Friday")

        result_json = await flush_session_memory(priority="all")
        result = json.loads(result_json)
        assert result["status"] == "flushed"
        assert result["decisions_stored"] == 1
        assert result["session_id"] == "test-session-001"

    @pytest.mark.asyncio
    async def test_flush_session_memory_invalid_priority(self, state):
        from mcp_tools.session_tools import flush_session_memory
        result_json = await flush_session_memory(priority="invalid")
        result = json.loads(result_json)
        assert "error" in result
        assert "Invalid priority" in result["error"]

    @pytest.mark.asyncio
    async def test_flush_session_memory_no_manager(self, state):
        from mcp_tools.session_tools import flush_session_memory
        state.session_manager = None
        result_json = await flush_session_memory()
        result = json.loads(result_json)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_restore_session(self, state, memory_store):
        from mcp_tools.session_tools import restore_session
        # First, flush some data
        state.session_manager.track_interaction("user", "We decided on approach A")
        state.session_manager.flush()

        result_json = await restore_session(session_id="test-session-001")
        result = json.loads(result_json)
        assert result["status"] == "restored"
        assert result["session_id"] == "test-session-001"
        assert len(result["context_entries"]) >= 1

    @pytest.mark.asyncio
    async def test_restore_session_no_manager(self, state):
        from mcp_tools.session_tools import restore_session
        state.session_manager = None
        result_json = await restore_session(session_id="any")
        result = json.loads(result_json)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_flush_records_checkpoint_on_health(self, state):
        from mcp_tools.session_tools import flush_session_memory
        assert not state.session_health.last_checkpoint
        state.session_manager.track_interaction("user", "Some content")
        await flush_session_memory()
        assert state.session_health.last_checkpoint


# --- Proactive Engine Integration Tests ---


class TestProactiveSessionIntegration:
    def test_token_limit_suggestion_not_triggered_below_threshold(self, memory_store):
        mgr = SessionManager(memory_store)
        # Add a few interactions (well below 120k tokens)
        for i in range(10):
            mgr.track_interaction("user", f"Message number {i}")

        engine = ProactiveSuggestionEngine(memory_store, session_manager=mgr)
        suggestions = engine._check_session_token_limit()
        assert suggestions == []

    def test_token_limit_suggestion_triggered_above_threshold(self, memory_store):
        mgr = SessionManager(memory_store)
        # Each word is roughly 1.3 tokens; we need ~120k tokens
        # So ~92,308 words. Let's simulate that with large interactions.
        big_content = " ".join(["word"] * 10000)
        for _ in range(10):  # 10 * 10000 = 100,000 words -> ~130,000 tokens
            mgr.track_interaction("user", big_content)

        engine = ProactiveSuggestionEngine(memory_store, session_manager=mgr)
        suggestions = engine._check_session_token_limit()
        assert len(suggestions) == 1
        assert suggestions[0].category == "session"
        assert suggestions[0].priority == "high"
        assert suggestions[0].action == "flush_session_memory"
        assert "context limit" in suggestions[0].title

    def test_no_session_manager_returns_empty(self, memory_store):
        engine = ProactiveSuggestionEngine(memory_store, session_manager=None)
        assert engine._check_session_token_limit() == []
        assert engine._check_session_unflushed_items() == []

    def test_unflushed_decisions_suggestion(self, memory_store):
        mgr = SessionManager(memory_store)
        mgr.track_interaction("user", "We decided to use approach X")

        engine = ProactiveSuggestionEngine(memory_store, session_manager=mgr)
        suggestions = engine._check_session_unflushed_items()
        assert len(suggestions) == 1
        assert suggestions[0].priority == "medium"
        assert "1 decision" in suggestions[0].title

    def test_unflushed_actions_suggestion(self, memory_store):
        mgr = SessionManager(memory_store)
        mgr.track_interaction("user", "TODO: fix the login bug")
        mgr.track_interaction("user", "We need to update the docs")

        engine = ProactiveSuggestionEngine(memory_store, session_manager=mgr)
        suggestions = engine._check_session_unflushed_items()
        assert len(suggestions) == 1
        assert "2 action item(s)" in suggestions[0].title

    def test_unflushed_mixed_suggestion(self, memory_store):
        mgr = SessionManager(memory_store)
        mgr.track_interaction("user", "We decided on plan B")
        mgr.track_interaction("user", "TODO: execute plan B")

        engine = ProactiveSuggestionEngine(memory_store, session_manager=mgr)
        suggestions = engine._check_session_unflushed_items()
        assert len(suggestions) == 1
        assert "decision" in suggestions[0].title
        assert "action" in suggestions[0].title

    def test_no_unflushed_items_returns_empty(self, memory_store):
        mgr = SessionManager(memory_store)
        mgr.track_interaction("user", "Just a regular message")

        engine = ProactiveSuggestionEngine(memory_store, session_manager=mgr)
        suggestions = engine._check_session_unflushed_items()
        assert suggestions == []

    def test_session_suggestions_in_generate_suggestions(self, memory_store):
        mgr = SessionManager(memory_store)
        mgr.track_interaction("user", "We decided on the approach")
        mgr.track_interaction("user", "TODO: implement it")

        engine = ProactiveSuggestionEngine(memory_store, session_manager=mgr)
        all_suggestions = engine.generate_suggestions()
        session_suggestions = [s for s in all_suggestions if s.category == "session"]
        assert len(session_suggestions) >= 1  # at least unflushed items


# --- Checkpoint Integration Tests ---


class TestCheckpointSessionEnrichment:
    """Test that checkpoint_session uses SessionManager for richer extraction."""

    @pytest.fixture(autouse=True)
    def setup_mcp(self, state):
        import mcp_server
        from mcp_tools import memory_tools
        from unittest.mock import MagicMock
        mock_mcp = MagicMock()
        mock_mcp.tool.return_value = lambda fn: fn
        memory_tools.register(mock_mcp, state)

    @pytest.mark.asyncio
    async def test_checkpoint_with_session_manager_extracts_decisions(self, state, memory_store):
        from mcp_tools.memory_tools import checkpoint_session
        state.session_manager.track_interaction("user", "We decided to use Redis")
        state.session_manager.track_interaction("user", "TODO: set up Redis cluster")

        result_json = await checkpoint_session(summary="Test checkpoint")
        result = json.loads(result_json)
        assert result["status"] == "checkpoint_saved"
        assert result["enriched_facts"] >= 1

        # Verify decision was stored
        facts = memory_store.search_facts("checkpoint_decision")
        decision_facts = [f for f in facts if "Redis" in f.value]
        assert len(decision_facts) >= 1

    @pytest.mark.asyncio
    async def test_checkpoint_without_session_manager(self, state, memory_store):
        from mcp_tools.memory_tools import checkpoint_session
        state.session_manager = None

        result_json = await checkpoint_session(
            summary="Plain checkpoint", key_facts="fact1, fact2"
        )
        result = json.loads(result_json)
        assert result["status"] == "checkpoint_saved"
        assert result["enriched_facts"] == 0
        assert result["facts_stored"] == 2

    @pytest.mark.asyncio
    async def test_checkpoint_with_empty_session(self, state):
        from mcp_tools.memory_tools import checkpoint_session
        # Session manager exists but has no interactions
        result_json = await checkpoint_session(summary="Empty session checkpoint")
        result = json.loads(result_json)
        assert result["status"] == "checkpoint_saved"
        assert result["enriched_facts"] == 0


# --- Session Brain Integration Tests ---


class TestFlushUpdatesSessionBrain:
    def test_flush_stores_decisions_in_brain(self, tmp_path):
        store = MemoryStore(tmp_path / "test.db")
        brain = SessionBrain(tmp_path / "brain.md")
        mgr = SessionManager(store, session_brain=brain)
        mgr.track_interaction("assistant", "We decided to use Python 3.11")
        mgr.flush()
        assert len(brain.decisions) >= 1
        store.close()

    def test_flush_stores_action_items_in_brain(self, tmp_path):
        store = MemoryStore(tmp_path / "test.db")
        brain = SessionBrain(tmp_path / "brain.md")
        mgr = SessionManager(store, session_brain=brain)
        mgr.track_interaction("assistant", "TODO: file the IC3 report")
        mgr.flush()
        assert len(brain.action_items) >= 1
        store.close()

    def test_flush_saves_brain_to_disk(self, tmp_path):
        store = MemoryStore(tmp_path / "test.db")
        brain_path = tmp_path / "brain.md"
        brain = SessionBrain(brain_path)
        mgr = SessionManager(store, session_brain=brain)
        mgr.track_interaction("assistant", "We decided to use Python")
        mgr.flush()
        assert brain_path.exists()
        store.close()

    def test_flush_without_brain_works(self, tmp_path):
        """Ensure backward compatibility when no brain is provided."""
        store = MemoryStore(tmp_path / "test.db")
        mgr = SessionManager(store)
        mgr.track_interaction("assistant", "We decided something")
        result = mgr.flush()
        assert result["decisions_stored"] >= 1
        store.close()
