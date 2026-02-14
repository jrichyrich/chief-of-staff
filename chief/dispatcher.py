# chief/dispatcher.py
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("dispatcher")


@dataclass
class DispatchResult:
    agent_name: str
    result: Optional[str] = None
    error: Optional[str] = None


class AgentDispatcher:
    def __init__(self, timeout_seconds: int = 60):
        self.timeout_seconds = timeout_seconds

    async def dispatch(
        self, tasks: list[tuple[str, Any, str]]
    ) -> list[DispatchResult]:
        """Dispatch tasks to agents in parallel.

        Args:
            tasks: List of (agent_name, agent_instance, task_description) tuples

        Returns:
            List of DispatchResult with results or errors
        """
        agent_names = [name for name, _, _ in tasks]
        logger.info("Dispatching %d agent(s): %s", len(tasks), ", ".join(agent_names))
        coroutines = [
            self._run_agent(name, agent, task)
            for name, agent, task in tasks
        ]
        results = await asyncio.gather(*coroutines)
        succeeded = sum(1 for r in results if r.error is None)
        failed = len(results) - succeeded
        logger.info("Dispatch complete: %d succeeded, %d failed", succeeded, failed)
        return results

    async def _run_agent(
        self, name: str, agent: Any, task: str
    ) -> DispatchResult:
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                agent.execute(task), timeout=self.timeout_seconds
            )
            elapsed = time.monotonic() - start
            logger.info("Agent '%s' completed in %.2fs", name, elapsed)
            return DispatchResult(agent_name=name, result=result)
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            logger.warning("Agent '%s' timed out after %.2fs", name, elapsed)
            return DispatchResult(
                agent_name=name, error=f"Agent '{name}' timed out after {self.timeout_seconds}s"
            )
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error("Agent '%s' failed after %.2fs: %s", name, elapsed, e)
            return DispatchResult(agent_name=name, error=str(e))
