"""Identity-graph enrichment for person mentions in briefs.

Turns raw name strings ('Shawn Farnworth') into contextual labels
('Shawn Farnworth — Director of Identity Engineering') using the
identities table + relationship facts in memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EnrichedPerson:
    canonical_name: str
    display_names: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    role: Optional[str] = None
    team: Optional[str] = None
    manager: Optional[str] = None

    def inline(self) -> str:
        """Produce a short 'Name — Role' string suitable for briefs."""
        name = self.display_names[0] if self.display_names else self.canonical_name
        if self.role:
            return f"{name} — {self.role}"
        if self.team:
            return f"{name} ({self.team})"
        return name


def _fact_field(fact, name: str) -> str:
    """Access field on Fact dataclass or dict interchangeably."""
    if isinstance(fact, dict):
        return fact.get(name) or ""
    return getattr(fact, name, "") or ""


def _facts_for(memory_store, canonical_name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for f in memory_store.list_facts(category="relationship") or []:
            key = _fact_field(f, "key")
            prefix = f"person.{canonical_name}."
            if key.startswith(prefix):
                out[key[len(prefix):]] = _fact_field(f, "value")
    except Exception:
        pass
    return out


def enrich_person_mention(
    name: str,
    memory_store,
    identity_store,
) -> Optional[EnrichedPerson]:
    """Look up an identity record by name and fold in relationship facts."""
    if not name:
        return None
    matches = identity_store.search_identity(name) if identity_store else []
    if not matches:
        return None

    canonical = matches[0].get("canonical_name", name)

    # Re-query by canonical to consolidate records across providers. The
    # initial name search may only match the provider whose display_name
    # matches the query (e.g. "Shawn Farnworth" won't substring-match a
    # record with display_name="Shawn F.").
    all_records = matches
    try:
        canonical_matches = identity_store.search_identity(canonical) or []
        if canonical_matches:
            all_records = canonical_matches
    except Exception:
        pass

    display_names: list[str] = []
    emails: list[str] = []
    providers: list[str] = []
    for r in all_records:
        if r.get("canonical_name") != canonical:
            continue
        dn = r.get("display_name") or ""
        if dn and dn not in display_names:
            display_names.append(dn)
        em = r.get("email") or ""
        if em and em not in emails:
            emails.append(em)
        pr = r.get("provider") or ""
        if pr and pr not in providers:
            providers.append(pr)

    facts = _facts_for(memory_store, canonical)
    return EnrichedPerson(
        canonical_name=canonical,
        display_names=display_names,
        emails=emails,
        providers=providers,
        role=facts.get("role"),
        team=facts.get("team"),
        manager=facts.get("manager"),
    )
