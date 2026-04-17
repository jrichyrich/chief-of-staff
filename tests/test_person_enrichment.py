"""Tests for person enrichment using the identity graph."""

import pytest

from orchestration.person_enrichment import (
    EnrichedPerson,
    enrich_person_mention,
)


class FakeMemory:
    def __init__(self, facts):
        self._facts = facts

    def list_facts(self, category=None, limit=None):
        if category:
            return [f for f in self._facts if f["category"] == category]
        return self._facts


class FakeIdentity:
    def __init__(self, records):
        self._records = records

    def search_identity(self, q: str):
        ql = q.lower()
        return [
            r for r in self._records
            if ql in (r.get("canonical_name") or "").lower()
            or ql in (r.get("display_name") or "").lower()
        ]


def test_enrich_person_returns_none_when_not_found():
    mem = FakeMemory([])
    idents = FakeIdentity([])
    assert enrich_person_mention("Unknown Person", mem, idents) is None


def test_enrich_person_consolidates_across_providers():
    idents = FakeIdentity([
        {"canonical_name": "shawn.farnworth", "provider": "m365_email",
         "display_name": "Shawn Farnworth", "email": "shawn@chg.com"},
        {"canonical_name": "shawn.farnworth", "provider": "m365_teams",
         "display_name": "Shawn F.", "email": ""},
        {"canonical_name": "shawn.farnworth", "provider": "imessage",
         "display_name": "Shawn", "email": ""},
    ])
    mem = FakeMemory([])
    enriched = enrich_person_mention("Shawn Farnworth", mem, idents)
    assert enriched is not None
    assert enriched.canonical_name == "shawn.farnworth"
    assert set(enriched.providers) == {"m365_email", "m365_teams", "imessage"}
    assert "shawn@chg.com" in enriched.emails


def test_enrich_person_pulls_role_fact():
    idents = FakeIdentity([
        {"canonical_name": "shawn.farnworth", "provider": "m365_email",
         "display_name": "Shawn Farnworth", "email": "shawn@chg.com"},
    ])
    mem = FakeMemory([
        {"category": "relationship", "key": "person.shawn.farnworth.role",
         "value": "Director of Identity Engineering"},
        {"category": "relationship", "key": "person.shawn.farnworth.manager",
         "value": "Jason Richards"},
    ])
    enriched = enrich_person_mention("Shawn Farnworth", mem, idents)
    assert enriched.role == "Director of Identity Engineering"
    assert enriched.manager == "Jason Richards"


def test_enrich_person_accepts_fact_dataclasses():
    """Real MemoryStore returns list[Fact] dataclasses, not dicts."""
    from memory.models import Fact

    class DataclassFakeMemory:
        def __init__(self, facts):
            self._facts = facts

        def list_facts(self, category=None, limit=None):
            if category:
                return [f for f in self._facts if f.category == category]
            return self._facts

    idents = FakeIdentity([
        {"canonical_name": "shawn.farnworth", "provider": "m365_email",
         "display_name": "Shawn Farnworth", "email": "shawn@chg.com"},
    ])
    mem = DataclassFakeMemory([
        Fact(category="relationship", key="person.shawn.farnworth.role", value="Director"),
    ])
    enriched = enrich_person_mention("Shawn Farnworth", mem, idents)
    assert enriched.role == "Director"


def test_enrich_person_inline_rendering():
    enriched = EnrichedPerson(
        canonical_name="shawn.farnworth",
        display_names=["Shawn Farnworth"],
        emails=["shawn@chg.com"],
        providers=["m365_email"],
        role="Director of Identity Engineering",
    )
    rendered = enriched.inline()
    assert "Shawn Farnworth" in rendered
    assert "Director of Identity Engineering" in rendered
