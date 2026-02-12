# tests/test_dispatcher.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from chief.dispatcher import AgentDispatcher, DispatchResult


@pytest.fixture
def dispatcher():
    return AgentDispatcher(timeout_seconds=5)


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_single_agent(self, dispatcher):
        agent = MagicMock()
        agent.name = "test_agent"
        agent.execute = AsyncMock(return_value="Agent result")

        results = await dispatcher.dispatch([("test_agent", agent, "Do something")])
        assert len(results) == 1
        assert results[0].agent_name == "test_agent"
        assert results[0].result == "Agent result"
        assert results[0].error is None

    @pytest.mark.asyncio
    async def test_dispatch_multiple_agents_parallel(self, dispatcher):
        agents = []
        for i in range(3):
            agent = MagicMock()
            agent.name = f"agent_{i}"
            agent.execute = AsyncMock(return_value=f"Result {i}")
            agents.append((f"agent_{i}", agent, f"Task {i}"))

        results = await dispatcher.dispatch(agents)
        assert len(results) == 3
        result_texts = [r.result for r in results]
        assert "Result 0" in result_texts
        assert "Result 1" in result_texts
        assert "Result 2" in result_texts

    @pytest.mark.asyncio
    async def test_dispatch_handles_agent_error(self, dispatcher):
        agent = MagicMock()
        agent.name = "failing_agent"
        agent.execute = AsyncMock(side_effect=Exception("Agent crashed"))

        results = await dispatcher.dispatch([("failing_agent", agent, "Do something")])
        assert len(results) == 1
        assert results[0].error is not None
        assert "Agent crashed" in results[0].error

    @pytest.mark.asyncio
    async def test_dispatch_handles_timeout(self):
        dispatcher = AgentDispatcher(timeout_seconds=1)
        agent = MagicMock()
        agent.name = "slow_agent"

        async def slow_task(task):
            await asyncio.sleep(10)
            return "Never returns"

        agent.execute = slow_task

        results = await dispatcher.dispatch([("slow_agent", agent, "Do something")])
        assert len(results) == 1
        assert results[0].error is not None
        assert "timed out" in results[0].error.lower()

    @pytest.mark.asyncio
    async def test_dispatch_partial_failure(self, dispatcher):
        good_agent = MagicMock()
        good_agent.name = "good_agent"
        good_agent.execute = AsyncMock(return_value="Success")

        bad_agent = MagicMock()
        bad_agent.name = "bad_agent"
        bad_agent.execute = AsyncMock(side_effect=RuntimeError("Failed"))

        results = await dispatcher.dispatch([
            ("good_agent", good_agent, "Task 1"),
            ("bad_agent", bad_agent, "Task 2"),
        ])
        assert len(results) == 2
        success = [r for r in results if r.error is None]
        failures = [r for r in results if r.error is not None]
        assert len(success) == 1
        assert len(failures) == 1
