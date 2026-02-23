"""Dynamic complexity triage for expert agent dispatch.

Before dispatching an agent, a lightweight Haiku call classifies the task
as simple/standard/complex. Simple tasks get downgraded to haiku tier.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Optional

import anthropic

import config as app_config
from agents.registry import AgentConfig

logger = logging.getLogger("jarvis-triage")

_VALID_CLASSIFICATIONS = {"simple", "standard", "complex"}

_TRIAGE_PROMPT = (
    "Given this task and agent description, classify the reasoning depth required.\n"
    "Agent: {name} — {description}\n"
    "Task: {task}\n"
    "Reply with exactly one word: simple, standard, or complex."
)


def classify_complexity(
    task_text: str,
    agent_config: AgentConfig,
    client: Optional[anthropic.Anthropic] = None,
) -> str:
    """Classify task complexity using a Haiku pre-call.

    Returns 'simple', 'standard', or 'complex'.
    On any error, returns 'standard' (safe fallback).
    """
    if client is None:
        client = anthropic.Anthropic(api_key=app_config.ANTHROPIC_API_KEY)

    prompt = _TRIAGE_PROMPT.format(
        name=agent_config.name,
        description=agent_config.description,
        task=task_text[:1000],
    )

    try:
        response = client.messages.create(
            model=app_config.MODEL_TIERS["haiku"],
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip().lower()
        if text in _VALID_CLASSIFICATIONS:
            return text
        logger.warning("Triage returned unexpected value: %r, defaulting to standard", text)
        return "standard"
    except Exception as e:
        logger.warning("Triage classification failed: %s, defaulting to standard", e)
        return "standard"


# Tiers that should never be triaged (already cheapest, or reserved for high-stakes)
_SKIP_TRIAGE_TIERS = {"haiku", "opus"}


def classify_and_resolve(
    agent_config: AgentConfig,
    task_text: str,
    client: Optional[anthropic.Anthropic] = None,
) -> AgentConfig:
    """Classify task complexity and return a (possibly downgraded) config.

    Skips triage for haiku agents (already cheapest) and opus agents (reserved).
    Returns a copy with model overridden if downgraded; original config is never mutated.
    On error, returns the original config unchanged.
    """
    if agent_config.model in _SKIP_TRIAGE_TIERS:
        return agent_config

    classification = classify_complexity(task_text, agent_config, client=client)

    if classification == "simple":
        logger.info(
            "Triage: agent=%s classification=simple, downgrading from %s to haiku",
            agent_config.name,
            agent_config.model,
        )
        return replace(agent_config, model="haiku")

    return agent_config
