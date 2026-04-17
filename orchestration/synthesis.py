"""Result synthesis — optional Haiku merge pass for multi-agent dispatch."""

from __future__ import annotations

import logging
from typing import Any

from anthropic import AsyncAnthropic

import config as app_config

logger = logging.getLogger("jarvis-synthesis")

_SYNTHESIS_SYSTEM = (
    "You are the synthesis pass for a Chief of Staff briefing system. "
    "Multiple data-gathering agents have produced raw findings; your job is "
    "to produce a ranked, deduplicated brief that surfaces what matters.\n\n"
    "Ranking rules:\n"
    "1. RELEVANCE FIRST. Each input item may carry a relevance score (0.0-1.0) "
    "and category from an upstream triage pass. Respect them. Drop items below "
    "0.5 unless their category is 'escalation' or 'decision-needed'.\n"
    "2. DEDUPLICATE. If two inputs describe the same underlying event (same "
    "email thread, same incident, same meeting), merge them into one bullet "
    "with the combined context.\n"
    "3. PRIORITIZE BY CATEGORY: escalation > decision-needed > action-for-you "
    "> action-for-report > fyi. Within a category, order by relevance desc.\n"
    "4. NEVER dump raw agent output. Every line must lead with the "
    "action/implication, not the source tool.\n"
    "5. When a person is mentioned, keep any identity enrichment already "
    "attached (role, team) on first mention; drop it on repeats.\n\n"
    "Output style: executive summary tone. Outcomes over activities. "
    "Honest about yellows/reds. No hedging. If an item is a 0.9-relevance "
    "escalation, say so. Do not dump raw data under any circumstance."
)


async def synthesize_results(
    task: str,
    dispatches: list[dict[str, Any]],
    model: str = "",
    max_tokens: int = 0,
    memory_store=None,
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
    parts.append(
        "## Instructions\n"
        "Apply the ranking rules from your system prompt. Deduplicate across "
        "agents (same event → one bullet). Merge overlapping findings. Drop "
        "low-relevance items unless they are escalations or decisions. Preserve "
        "identity enrichment on first mention of each person. Produce a brief "
        "whose top line is the single most important thing the user needs to "
        "know right now; every subsequent line descends in priority.\n\n"
        "If `brief_type` context was provided (e.g. 'daily' or 'cio-weekly'), "
        "follow that format. Otherwise produce a priority-ordered bullet list."
    )

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
        try:
            if memory_store is not None:
                usage = response.usage
                memory_store.log_api_call(
                    model_id=synth_model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_input_tokens=getattr(usage, 'cache_creation_input_tokens', 0) or 0,
                    cache_read_input_tokens=getattr(usage, 'cache_read_input_tokens', 0) or 0,
                    agent_name=None,
                    caller="synthesis",
                )
        except Exception:
            pass
        return response.content[0].text
    except Exception as e:
        logger.warning("Synthesis LLM call failed, returning fallback: %s", e)
        # Fallback: concatenate results
        lines = [f"[{d['agent_name']}]: {d['result']}" for d in dispatches]
        return "\n\n".join(lines)
