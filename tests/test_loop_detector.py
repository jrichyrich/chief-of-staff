# tests/test_loop_detector.py
"""Tests for agents/loop_detector.py — LoopDetector."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents.loop_detector import LoopDetector
from agents.base import BaseExpertAgent
from agents.registry import AgentConfig
from documents.store import DocumentStore
from memory.store import MemoryStore


# ---------------------------------------------------------------------------
# LoopDetector unit tests
# ---------------------------------------------------------------------------

class TestLoopDetectorBasic:
    def test_first_call_returns_ok(self):
        d = LoopDetector()
        assert d.record("query_memory", {"query": "test"}) == "ok"

    def test_same_call_under_threshold_returns_ok(self):
        d = LoopDetector(warn_threshold=3, break_threshold=5)
        assert d.record("query_memory", {"query": "x"}) == "ok"
        assert d.record("query_memory", {"query": "x"}) == "ok"

    def test_same_call_at_warn_threshold(self):
        d = LoopDetector(warn_threshold=3, break_threshold=5)
        d.record("query_memory", {"query": "x"})
        d.record("query_memory", {"query": "x"})
        assert d.record("query_memory", {"query": "x"}) == "warning"

    def test_same_call_between_warn_and_break(self):
        d = LoopDetector(warn_threshold=3, break_threshold=5)
        for _ in range(3):
            d.record("query_memory", {"query": "x"})
        assert d.record("query_memory", {"query": "x"}) == "warning"

    def test_same_call_at_break_threshold(self):
        d = LoopDetector(warn_threshold=3, break_threshold=5)
        for _ in range(4):
            d.record("query_memory", {"query": "x"})
        assert d.record("query_memory", {"query": "x"}) == "break"

    def test_same_call_above_break_threshold(self):
        d = LoopDetector(warn_threshold=3, break_threshold=5)
        for _ in range(5):
            d.record("query_memory", {"query": "x"})
        assert d.record("query_memory", {"query": "x"}) == "break"

    def test_different_args_are_separate(self):
        d = LoopDetector(warn_threshold=2, break_threshold=3)
        assert d.record("query_memory", {"query": "a"}) == "ok"
        assert d.record("query_memory", {"query": "b"}) == "ok"
        assert d.record("query_memory", {"query": "a"}) == "warning"
        assert d.record("query_memory", {"query": "b"}) == "warning"

    def test_different_tools_are_separate(self):
        d = LoopDetector(warn_threshold=3, break_threshold=5)
        for _ in range(2):
            d.record("query_memory", {"query": "x"})
            d.record("search_documents", {"query": "x"})
        # Each tool called only 2 times — under warn_threshold
        assert d.record("query_memory", {"query": "x"}) == "warning"
        assert d.record("search_documents", {"query": "x"}) == "warning"

    def test_varied_usage_does_not_trigger(self):
        d = LoopDetector(warn_threshold=3, break_threshold=5)
        assert d.record("query_memory", {"query": "a"}) == "ok"
        assert d.record("search_documents", {"query": "b"}) == "ok"
        assert d.record("store_memory", {"category": "personal", "key": "k", "value": "v"}) == "ok"
        assert d.record("query_memory", {"query": "c"}) == "ok"
        assert d.record("search_documents", {"query": "d"}) == "ok"


class TestLoopDetectorAlternation:
    def test_ab_alternation_detected(self):
        d = LoopDetector(warn_threshold=10, break_threshold=20)  # high thresholds
        d.record("tool_a", {"x": 1})  # A
        d.record("tool_b", {"y": 2})  # B
        d.record("tool_a", {"x": 1})  # A
        result = d.record("tool_b", {"y": 2})  # B — A-B-A-B
        assert result == "warning"

    def test_ab_alternation_with_different_tools(self):
        d = LoopDetector(warn_threshold=10, break_threshold=20)
        d.record("query_memory", {"query": "test"})
        d.record("search_documents", {"query": "test"})
        d.record("query_memory", {"query": "test"})
        result = d.record("search_documents", {"query": "test"})
        assert result == "warning"

    def test_no_false_alternation_aab(self):
        """A-A-B should not trigger alternation."""
        d = LoopDetector(warn_threshold=10, break_threshold=20)
        d.record("tool_a", {"x": 1})
        d.record("tool_a", {"x": 1})
        d.record("tool_b", {"y": 2})
        result = d.record("tool_a", {"x": 1})  # A-A-B-A, not A-B-A-B
        assert result == "ok"

    def test_no_false_alternation_same_tool(self):
        """A-A-A-A is same-tool repetition, not alternation."""
        d = LoopDetector(warn_threshold=10, break_threshold=20)
        d.record("tool_a", {"x": 1})
        d.record("tool_a", {"x": 1})
        d.record("tool_a", {"x": 1})
        # This is same tool repeated — alternation requires h[-1] != h[-2]
        result = d.record("tool_a", {"x": 1})
        assert result == "ok"  # Under warn_threshold=10


class TestLoopDetectorReset:
    def test_reset_clears_state(self):
        d = LoopDetector(warn_threshold=2, break_threshold=3)
        d.record("query_memory", {"query": "x"})
        d.record("query_memory", {"query": "x"})
        d.reset()
        # After reset, counter is back to zero
        assert d.record("query_memory", {"query": "x"}) == "ok"

    def test_reset_clears_history(self):
        d = LoopDetector(warn_threshold=10, break_threshold=20)
        d.record("tool_a", {"x": 1})
        d.record("tool_b", {"y": 2})
        d.record("tool_a", {"x": 1})
        d.reset()
        # After reset, alternation detection starts fresh
        result = d.record("tool_b", {"y": 2})
        assert result == "ok"


class TestLoopDetectorEdgeCases:
    def test_empty_args(self):
        d = LoopDetector(warn_threshold=2, break_threshold=3)
        d.record("list_reminders", {})
        assert d.record("list_reminders", {}) == "warning"

    def test_arg_order_does_not_matter(self):
        """json.dumps with sort_keys normalizes arg order."""
        d = LoopDetector(warn_threshold=2, break_threshold=3)
        d.record("query_memory", {"query": "x", "category": "work"})
        result = d.record("query_memory", {"category": "work", "query": "x"})
        assert result == "warning"

    def test_custom_thresholds(self):
        d = LoopDetector(warn_threshold=1, break_threshold=2)
        assert d.record("tool", {"a": 1}) == "warning"  # 1st call hits warn=1
        assert d.record("tool", {"a": 1}) == "break"    # 2nd call hits break=2


# ---------------------------------------------------------------------------
# Integration: LoopDetector in BaseExpertAgent.execute()
# ---------------------------------------------------------------------------



def _make_tool_use_response(tool_name, tool_input, tool_id="toolu_123"):
    block = SimpleNamespace(type="tool_use", name=tool_name, input=tool_input, id=tool_id)
    return SimpleNamespace(stop_reason="tool_use", content=[block])


def _make_text_response(text):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(stop_reason="end_turn", content=[block])


class TestLoopDetectorIntegration:
    @pytest.mark.asyncio
    async def test_loop_break_terminates_early(self, memory_store, document_store):
        """Agent should stop early when loop detector signals break."""
        config = AgentConfig(
            name="loop-test",
            description="Test",
            system_prompt="Test.",
            capabilities=["memory_read"],
        )
        agent = BaseExpertAgent(config, memory_store, document_store, client=AsyncMock())

        # Same tool call every round — should hit break at round 5
        tool_resp = _make_tool_use_response("query_memory", {"query": "stuck"}, "toolu_loop")
        agent.client.messages.create = AsyncMock(return_value=tool_resp)

        with patch.object(agent, "_handle_tool_call", return_value={"result": []}):
            result = await agent.execute("Loop forever")

        assert "repetitive tool call loop detected" in result.lower()
        # Should have called API 5 times (break_threshold=5)
        assert agent.client.messages.create.call_count == 5

    @pytest.mark.asyncio
    async def test_warning_injects_system_message(self, memory_store, document_store):
        """At warning threshold, a system hint is appended to the tool result."""
        config = AgentConfig(
            name="warn-test",
            description="Test",
            system_prompt="Test.",
            capabilities=["memory_read"],
        )
        agent = BaseExpertAgent(config, memory_store, document_store, client=AsyncMock())

        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                return _make_tool_use_response("query_memory", {"query": "same"}, f"toolu_{call_count}")
            return _make_text_response("I changed approach.")

        agent.client.messages.create = AsyncMock(side_effect=mock_create)

        with patch.object(agent, "_handle_tool_call", return_value={"result": []}):
            result = await agent.execute("Do something")

        assert result == "I changed approach."

        # Check that the 3rd tool result (warning at count=3) had the system hint
        third_call_messages = agent.client.messages.create.call_args_list[3].kwargs["messages"]
        tool_result_content = third_call_messages[-1]["content"][0]["content"]
        assert "repeating the same tool call" in tool_result_content.lower()

    @pytest.mark.asyncio
    async def test_normal_execution_not_affected(self, memory_store, document_store):
        """Normal varied tool usage should not trigger loop detection."""
        config = AgentConfig(
            name="normal-test",
            description="Test",
            system_prompt="Test.",
            capabilities=["memory_read", "memory_write"],
        )
        agent = BaseExpertAgent(config, memory_store, document_store, client=AsyncMock())

        tool_resp_1 = _make_tool_use_response("query_memory", {"query": "a"}, "toolu_1")
        tool_resp_2 = _make_tool_use_response("query_memory", {"query": "b"}, "toolu_2")
        text_resp = _make_text_response("Done with varied queries.")

        agent.client.messages.create = AsyncMock(
            side_effect=[tool_resp_1, tool_resp_2, text_resp]
        )

        with patch.object(agent, "_handle_tool_call", return_value={"result": []}):
            result = await agent.execute("Search for stuff")

        assert result == "Done with varied queries."
        assert agent.client.messages.create.call_count == 3
