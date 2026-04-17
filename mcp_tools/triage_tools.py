"""MCP wrapper exposing the brief relevance pipeline to subagents.

Subagents can't directly import orchestration/* Python modules; they can
only invoke MCP tools. This module wraps thread reconstruction, heuristic
filtering, Haiku triage, and identity-graph enrichment behind one tool so
the daily-briefing / weekly-cio-briefing subagents can actually rank
their inputs instead of dumping raw data into synthesis.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

from orchestration.person_enrichment import enrich_person_mention
from orchestration.thread_reconstruction import (
    reconstruct_email_threads,
    reconstruct_teams_threads,
)
from orchestration.triage import (
    FilterConfig,
    build_triage_context,
    heuristic_filter,
    llm_triage,
)

from .decorators import tool_errors

logger = logging.getLogger("jarvis-triage-tools")


def _distinct_names_from_items(items: list[dict[str, Any]]) -> list[str]:
    """Pull unique person display names out of triaged item payloads."""
    seen: set[str] = set()
    ordered: list[str] = []
    for it in items:
        candidates: list[str] = []
        fn = (it.get("from_name") or "").strip()
        if fn:
            candidates.append(fn)
        for p in it.get("participants") or []:
            name = (p.get("name") or "").strip() if isinstance(p, dict) else ""
            if name:
                candidates.append(name)
        for name in candidates:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
    return ordered


def register(mcp, state):
    """Register triage tools with the MCP server."""

    @mcp.tool()
    @tool_errors("Triage error")
    async def triage_brief_items(
        emails: list[dict[str, Any]] = [],
        teams_messages: list[dict[str, Any]] = [],
        brief_type: str = "daily",
        key_people_emails: list[str] = [],
        user_email: str = "",
    ) -> str:
        """Reconstruct threads, rank by relevance, and enrich people for a brief.

        Wraps the orchestration pipeline so subagents don't have to (and can't)
        import orchestration.* directly. Given raw Graph-shaped email + Teams
        payloads, returns scored threads plus identity-graph enrichment for the
        people mentioned.

        Args:
            emails: Graph-shaped email message dicts (as returned by outlook_email_search).
            teams_messages: Graph-shaped Teams chat message dicts.
            brief_type: 'daily' or 'weekly-cio' — flows into the context payload.
            key_people_emails: Stakeholder emails that bypass stale-age filtering.
            user_email: The user's own email (for self-sent drop).

        Returns:
            JSON with keys: threads, triaged, enriched_people, context.
        """
        email_threads = reconstruct_email_threads(emails)
        teams_threads = reconstruct_teams_threads(teams_messages)
        thread_dicts = [t.to_triage_dict() for t in email_threads] + [
            t.to_triage_dict() for t in teams_threads
        ]

        context = build_triage_context(
            memory_store=state.memory_store,
            brain=state.session_brain,
            key_people=list(key_people_emails),
        )
        context_payload = asdict(context)
        context_payload["brief_type"] = brief_type

        if not thread_dicts:
            return json.dumps({
                "threads": [],
                "triaged": [],
                "enriched_people": {},
                "context": context_payload,
            }, default=str)

        filter_config = FilterConfig(
            user_email=user_email,
            key_people_emails=tuple(key_people_emails),
        )
        filtered = heuristic_filter(thread_dicts, filter_config)

        triaged = await llm_triage(filtered, context, memory_store=state.memory_store)
        triaged_payload = [
            {
                "item": ti.item,
                "relevance": ti.relevance,
                "category": ti.category,
                "why": ti.why,
            }
            for ti in triaged
        ]

        names = _distinct_names_from_items([ti.item for ti in triaged])
        enriched: dict[str, dict[str, Any]] = {}
        identity_store = getattr(state.memory_store, "identity_store", state.memory_store)

        def _enrich(name: str):
            try:
                return enrich_person_mention(name, state.memory_store, identity_store)
            except Exception as exc:
                logger.debug("enrich_person_mention(%s) failed: %s", name, exc)
                return None

        results = await asyncio.gather(
            *(asyncio.to_thread(_enrich, n) for n in names)
        ) if names else []

        for person in results:
            if person is None:
                continue
            if person.canonical_name in enriched:
                continue
            enriched[person.canonical_name] = {
                "canonical_name": person.canonical_name,
                "display_names": person.display_names,
                "emails": person.emails,
                "providers": person.providers,
                "role": person.role,
                "team": person.team,
                "manager": person.manager,
                "inline": person.inline(),
            }

        return json.dumps(
            {
                "threads": thread_dicts,
                "triaged": triaged_payload,
                "enriched_people": enriched,
                "context": context_payload,
            },
            default=str,
        )

    import sys
    module = sys.modules[__name__]
    module.triage_brief_items = triage_brief_items
