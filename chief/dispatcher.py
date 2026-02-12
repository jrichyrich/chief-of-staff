# chief/dispatcher.py
import asyncio
from dataclasses import dataclass
from typing import Any, Optional


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
        coroutines = [
            self._run_agent(name, agent, task)
            for name, agent, task in tasks
        ]
        return await asyncio.gather(*coroutines)

    async def _run_agent(
        self, name: str, agent: Any, task: str
    ) -> DispatchResult:
        try:
            result = await asyncio.wait_for(
                agent.execute(task), timeout=self.timeout_seconds
            )
            return DispatchResult(agent_name=name, result=result)
        except asyncio.TimeoutError:
            return DispatchResult(
                agent_name=name, error=f"Agent '{name}' timed out after {self.timeout_seconds}s"
            )
        except Exception as e:
            return DispatchResult(agent_name=name, error=str(e))
