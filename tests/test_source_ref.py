"""Tests for SourceRef dataclass and its integration on Delegation/Decision."""

import json
import pytest

from memory.models import Decision, Delegation, SourceRef


def test_source_ref_minimum_construction():
    ref = SourceRef(provider="m365_email")
    assert ref.provider == "m365_email"
    assert ref.thread_id is None
    assert ref.url is None


def test_source_ref_full_construction():
    ref = SourceRef(
        provider="m365_teams",
        thread_id="19:abc@thread.v2",
        message_id="1713292800000",
        url="https://teams.microsoft.com/l/message/...",
        quote="Can you own the PST remediation?",
        timestamp="2026-04-17T14:00:00Z",
        from_identity="shawn.farnworth",
    )
    assert ref.quote.startswith("Can you own")
    assert ref.from_identity == "shawn.farnworth"


def test_source_ref_json_roundtrip():
    ref = SourceRef(
        provider="m365_email",
        thread_id="AAMkAD...",
        quote="Need decision on Okta rollback",
    )
    as_json = ref.to_json()
    assert isinstance(as_json, str)
    restored = SourceRef.from_json(as_json)
    assert restored == ref


def test_delegation_accepts_source_ref():
    ref = SourceRef(provider="m365_teams", thread_id="19:abc", url="https://...")
    d = Delegation(
        task="Own PST remediation rollback",
        delegated_to="shawn.farnworth",
        source_ref=ref,
    )
    assert d.source_ref.provider == "m365_teams"


def test_decision_accepts_source_ref():
    ref = SourceRef(provider="m365_email", quote="We're going with option B.")
    dec = Decision(title="Adopt Option B for Okta rollback", source_ref=ref)
    assert dec.source_ref.quote == "We're going with option B."


def test_delegation_source_ref_defaults_none():
    """Backward-compat: existing code creating Delegation without source_ref still works."""
    d = Delegation(task="t", delegated_to="x")
    assert d.source_ref is None
    assert d.source == ""  # legacy string field unchanged


def test_decision_source_ref_defaults_none():
    dec = Decision(title="t")
    assert dec.source_ref is None
    assert dec.source == ""
