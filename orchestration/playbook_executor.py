"""Playbook executor — runs playbook workstreams in parallel, synthesizes results."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from playbooks.loader import Playbook, Workstream

logger = logging.getLogger("jarvis-playbook-executor")


async def _dispatch_workstream(
    workstream: Workstream,
    agent_registry: Any,
    state: Any,
) -> str:
    """Dispatch a single workstream by finding a matching agent or using a fallback.

    Returns JSON string with dispatches list.
    """
    from agents.base import BaseExpertAgent

    # Find an agent whose name matches the workstream
    config = None
    try:
        config = agent_registry.get_agent(workstream.name)
    except (ValueError, AttributeError):
        pass

    if config is None:
        # Fallback: use first agent with non-empty capabilities
        all_agents = agent_registry.list_agents()
        for a in all_agents:
            if a.capabilities:
                config = a
                break

    if config is None:
        return json.dumps({
            "dispatches": [{"agent_name": workstream.name, "status": "error", "result": "No suitable agent found"}],
            "summary": "No agent available",
        })

    agent = BaseExpertAgent(
        config=config,
        memory_store=getattr(state, "memory_store", None),
        document_store=getattr(state, "document_store", None),
        calendar_store=getattr(state, "calendar_store", None),
        reminder_store=getattr(state, "reminder_store", None),
        mail_store=getattr(state, "mail_store", None),
        hook_registry=getattr(state, "hook_registry", None),
        agent_browser=getattr(state, "agent_browser", None),
    )

    result = await agent.execute(workstream.prompt)
    return json.dumps({
        "dispatches": [{"agent_name": config.name, "status": "success", "result": str(result)}],
        "summary": f"Workstream {workstream.name} completed",
    })


async def execute_playbook(
    playbook: Playbook,
    agent_registry: Any,
    state: Any,
    context: Optional[dict] = None,
    max_concurrent: int = 5,
) -> dict:
    """Execute a playbook: run active workstreams in parallel, then synthesize.

    Args:
        playbook: Resolved Playbook instance (inputs already substituted).
        agent_registry: AgentRegistry for looking up agents.
        state: ServerState with store references.
        context: Optional dict for evaluating workstream conditions.
        max_concurrent: Max concurrent workstream executions.

    Returns:
        Dict with workstream_results, synthesized_summary, and status.
    """
    active = playbook.active_workstreams(context)

    if not active:
        return {
            "playbook": playbook.name,
            "status": "completed",
            "workstream_results": [],
            "message": "No active workstreams (all conditions unmet)",
        }

    start = time.monotonic()
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _run(ws: Workstream) -> dict:
        async with semaphore:
            try:
                raw = await _dispatch_workstream(ws, agent_registry, state)
                parsed = json.loads(raw)
                dispatches = parsed.get("dispatches", [])
                result_text = "\n".join(d.get("result", "") for d in dispatches)
                status = "success" if all(d.get("status") == "success" for d in dispatches) else "partial"
                return {"workstream": ws.name, "status": status, "result": result_text}
            except Exception as e:
                logger.error("Workstream %s failed: %s", ws.name, e)
                return {"workstream": ws.name, "status": "error", "result": str(e)}

    workstream_results = await asyncio.gather(*[_run(ws) for ws in active])
    duration = round(time.monotonic() - start, 3)

    result = {
        "playbook": playbook.name,
        "status": "completed",
        "workstream_results": list(workstream_results),
        "duration_seconds": duration,
    }

    # Synthesize if a synthesis prompt is provided and at least one workstream succeeded
    if playbook.synthesis_prompt:
        successful_dispatches = [
            {"agent_name": r["workstream"], "status": r["status"], "result": r["result"]}
            for r in workstream_results
        ]
        if any(r["status"] == "success" for r in workstream_results):
            try:
                from orchestration.synthesis import synthesize_results
                synthesis = await synthesize_results(
                    task=playbook.synthesis_prompt,
                    dispatches=successful_dispatches,
                )
                result["synthesized_summary"] = synthesis
            except Exception as e:
                logger.warning("Playbook synthesis failed: %s", e)
                result["synthesis_error"] = str(e)

    return result
