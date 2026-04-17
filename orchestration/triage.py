"""Triage: rank and filter brief inputs before synthesis.

Two passes:
  1. heuristic_filter — drop obvious noise (newsletters, self-sent, stale)
  2. llm_triage — Haiku scores each surviving item 0.0-1.0 with category + why

Synthesis consumes the output of llm_triage; this replaces the current
'synthesis sees raw dump' behavior that yields low-signal briefs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

logger = logging.getLogger("jarvis-triage")


_DEFAULT_NOISE_SENDERS = (
    "noreply@", "no-reply@", "donotreply@",
    "notifications@github.com", "notifications@",
    "substack.com", "mailchimp.com", "mailgun",
)


@dataclass
class FilterConfig:
    user_email: str = ""
    max_age_days: int = 14
    key_people_emails: tuple[str, ...] = ()
    noise_senders_contains: tuple[str, ...] = _DEFAULT_NOISE_SENDERS


@dataclass
class TriageContext:
    user_role: str
    active_projects: list[str] = field(default_factory=list)
    current_focus: list[str] = field(default_factory=list)
    key_people: list[str] = field(default_factory=list)


@dataclass
class TriagedItem:
    item: dict[str, Any]
    relevance: float
    category: str
    why: str


def _is_noise_sender(email_addr: str, config: FilterConfig) -> bool:
    addr = (email_addr or "").lower()
    if not addr:
        return False
    return any(token.lower() in addr for token in config.noise_senders_contains)


def _is_stale(item: dict[str, Any], config: FilterConfig) -> bool:
    ts = item.get("timestamp") or item.get("receivedDateTime") or item.get("createdDateTime")
    if not ts:
        return False
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.max_age_days)
    return when < cutoff


def _is_key_person(email_addr: str, config: FilterConfig) -> bool:
    return email_addr.lower() in {e.lower() for e in config.key_people_emails}


def heuristic_filter(
    items: Sequence[dict[str, Any]],
    config: FilterConfig,
) -> list[dict[str, Any]]:
    """Drop obvious noise. Keeps anything whose kind we don't know how to filter."""
    kept: list[dict[str, Any]] = []
    for item in items:
        kind = item.get("kind", "")
        if kind not in {"email", "teams"}:
            kept.append(item)
            continue
        sender = item.get("from_email") or item.get("latest_sender_email") or ""
        if config.user_email and sender.lower() == config.user_email.lower():
            continue
        if _is_noise_sender(sender, config):
            continue
        if _is_stale(item, config) and not _is_key_person(sender, config):
            continue
        kept.append(item)
    return kept


_DEFAULT_ROLE = "VP / Chief of Staff"


def _fact_field(fact, name: str) -> str:
    """Access field on Fact dataclass or dict interchangeably."""
    if isinstance(fact, dict):
        return fact.get(name) or ""
    return getattr(fact, name, "") or ""


def _extract_focus_bullets(brain_text: str) -> list[str]:
    lines = [ln.strip() for ln in (brain_text or "").splitlines()]
    bullets: list[str] = []
    for ln in lines:
        if ln.startswith("- ") or ln.startswith("* "):
            bullets.append(ln[2:].strip())
    return bullets


def build_triage_context(
    memory_store,
    brain=None,
    key_people: list[str] | None = None,
) -> TriageContext:
    """Assemble the TriageContext from memory + session brain.

    Expects memory_store to have a list_facts(category=...) method that
    returns iterables of dicts with 'category', 'key', 'value'.
    """
    role = _DEFAULT_ROLE
    active_projects: list[str] = []
    try:
        for f in memory_store.list_facts(category="personal") or []:
            if _fact_field(f, "key") == "role":
                role = _fact_field(f, "value") or role
                break
    except Exception as exc:
        logger.debug("triage: failed to load role fact: %s", exc)

    try:
        for f in memory_store.list_facts(category="work") or []:
            key = _fact_field(f, "key")
            if key.startswith("project."):
                label = key[len("project."):].replace("_", " ")
                val = _fact_field(f, "value")
                active_projects.append(f"{label}: {val}" if val else label)
    except Exception as exc:
        logger.debug("triage: failed to load work facts: %s", exc)

    current_focus: list[str] = []
    if brain is not None:
        try:
            text = brain.get_current_focus() if hasattr(brain, "get_current_focus") else str(brain)
            current_focus = _extract_focus_bullets(text)
        except Exception as exc:
            logger.debug("triage: failed to pull brain focus: %s", exc)

    return TriageContext(
        user_role=role,
        active_projects=active_projects,
        current_focus=current_focus,
        key_people=list(key_people or []),
    )


from anthropic import AsyncAnthropic
import config as app_config


_TRIAGE_SYSTEM = (
    "You are the triage pass for a Chief of Staff briefing system. You will "
    "receive a JSON array of inbound items (emails, Teams messages, delegation "
    "updates, calendar items) and a JSON context object describing the user's "
    "role, active projects, current focus, and key people.\n\n"
    "Your job: return a JSON array, one object per input (preserving index), "
    "each with: index (int), relevance (float 0.0-1.0), category (one of: "
    "'escalation','decision-needed','action-for-you','action-for-report','fyi'), "
    "why (one sentence citing which context signal drove the score).\n\n"
    "Scoring rubric:\n"
    "- 0.9-1.0: directly blocks or advances an active project / current focus item\n"
    "- 0.7-0.9: from a key person, or directly tied to a project without blocking it\n"
    "- 0.5-0.7: tangentially relevant; action-for-report or dependency visibility\n"
    "- 0.2-0.5: fyi\n"
    "- 0.0-0.2: noise; would not be missed if dropped\n\n"
    "Return ONLY the JSON array — no prose, no markdown fences."
)


def _default_triaged(items: Sequence[dict[str, Any]]) -> list[TriagedItem]:
    """Safe default when the LLM fails: everything is fyi at 0.5."""
    return [
        TriagedItem(item=dict(it), relevance=0.5, category="fyi",
                    why="triage unavailable; defaulted")
        for it in items
    ]


async def llm_triage(
    items: Sequence[dict[str, Any]],
    context: TriageContext,
    model: str = "",
    memory_store=None,
) -> list[TriagedItem]:
    """Score each item 0.0-1.0 using Haiku. Sorted by relevance desc."""
    if not items:
        return []

    from dataclasses import asdict
    payload = {
        "context": asdict(context),
        "items": [
            {"index": i, **{k: v for k, v in item.items() if k != "raw"}}
            for i, item in enumerate(items)
        ],
    }
    user_content = json.dumps(payload, default=str)

    triage_model = model or getattr(app_config, "TRIAGE_MODEL", "claude-haiku-4-5-20251001")

    try:
        client = AsyncAnthropic(api_key=app_config.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=triage_model,
            max_tokens=2048,
            system=_TRIAGE_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        if memory_store is not None:
            try:
                usage = response.usage
                memory_store.log_api_call(
                    model_id=triage_model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                    agent_name=None,
                    caller="triage",
                )
            except Exception:
                pass
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        scored_rows = json.loads(raw)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("llm_triage failed, using defaults: %s", exc)
        return _default_triaged(items)

    by_index = {int(row.get("index", -1)): row for row in scored_rows}
    out: list[TriagedItem] = []
    for i, item in enumerate(items):
        row = by_index.get(i) or {}
        out.append(TriagedItem(
            item=dict(item),
            relevance=float(row.get("relevance", 0.5)),
            category=str(row.get("category", "fyi")),
            why=str(row.get("why", "")),
        ))
    out.sort(key=lambda r: r.relevance, reverse=True)
    return out
