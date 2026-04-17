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
            if (f.get("key") or "") == "role":
                role = f.get("value") or role
                break
    except Exception as exc:
        logger.debug("triage: failed to load role fact: %s", exc)

    try:
        for f in memory_store.list_facts(category="work") or []:
            key = f.get("key") or ""
            if key.startswith("project."):
                label = key[len("project."):].replace("_", " ")
                val = f.get("value") or ""
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
