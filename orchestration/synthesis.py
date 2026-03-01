"""Result synthesis — optional Haiku merge pass for multi-agent dispatch."""

from __future__ import annotations

import logging
from typing import Any

from anthropic import AsyncAnthropic

import config as app_config

logger = logging.getLogger("jarvis-synthesis")

_SYNTHESIS_SYSTEM = (
    "You are a synthesis agent. You receive outputs from multiple expert agents "
    "that worked on the same task in parallel. Your job is to merge their findings "
    "into a single, coherent, concise summary. Preserve key facts from each agent. "
    "Note any contradictions. Do not add information the agents did not provide."
)


async def synthesize_results(
    task: str,
    dispatches: list[dict[str, Any]],
    model: str = "",
    max_tokens: int = 0,
) -> str:
    """Synthesize multiple agent results into a single coherent summary.

    Args:
        task: The original task description.
        dispatches: List of dispatch result dicts with agent_name, status, result.
        model: Override model (default: config DISPATCH_SYNTHESIS_MODEL).
        max_tokens: Override max_tokens (default: config DISPATCH_SYNTHESIS_MAX_TOKENS).

    Returns:
        Synthesized summary string.
    """
    successful = [d for d in dispatches if d.get("status") == "success"]
    failed = [d for d in dispatches if d.get("status") != "success"]

    # All errors — no synthesis possible
    if not successful:
        error_lines = [f"- {d['agent_name']}: {d['result']}" for d in failed]
        return "All agents failed:\n" + "\n".join(error_lines)

    # Single success — return directly, no LLM call needed
    if len(successful) == 1 and not failed:
        return successful[0]["result"]

    # Build synthesis prompt
    parts = [f"## Original Task\n{task}\n"]
    for d in successful:
        parts.append(f"## Agent: {d['agent_name']} (success)\n{d['result']}\n")
    for d in failed:
        parts.append(f"## Agent: {d['agent_name']} (FAILED)\n{d['result']}\n")
    parts.append("## Instructions\nSynthesize the above into a unified summary.")

    user_content = "\n".join(parts)
    synth_model = model or getattr(app_config, "DISPATCH_SYNTHESIS_MODEL", "claude-haiku-4-5-20251001")
    synth_max = max_tokens or getattr(app_config, "DISPATCH_SYNTHESIS_MAX_TOKENS", 1024)

    try:
        client = AsyncAnthropic(api_key=app_config.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=synth_model,
            max_tokens=synth_max,
            system=_SYNTHESIS_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Synthesis LLM call failed, returning fallback: %s", e)
        # Fallback: concatenate results
        lines = [f"[{d['agent_name']}]: {d['result']}" for d in dispatches]
        return "\n\n".join(lines)
