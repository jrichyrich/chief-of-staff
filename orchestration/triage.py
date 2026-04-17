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
