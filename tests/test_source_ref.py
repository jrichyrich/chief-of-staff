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
    assert ref.provider == "m365_teams"
    assert ref.thread_id == "19:abc@thread.v2"
    assert ref.message_id == "1713292800000"
    assert ref.url.endswith("...")
    assert ref.quote.startswith("Can you own")
    assert ref.timestamp == "2026-04-17T14:00:00Z"
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


def test_source_ref_from_json_ignores_unknown_keys():
    """Forward-compat: older code must load newer JSON that has extra fields."""
    raw = '{"provider": "m365_email", "future_field": "ignored", "thread_id": "x"}'
    ref = SourceRef.from_json(raw)
    assert ref.provider == "m365_email"
    assert ref.thread_id == "x"


def test_source_ref_from_json_handles_partial_json():
    """Backward-compat: tolerate JSON with only a subset of known fields."""
    raw = '{"provider": "manual"}'
    ref = SourceRef.from_json(raw)
    assert ref.provider == "manual"
    assert ref.thread_id is None


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


# ---------------------------------------------------------------------------
# Persistence tests (SQLite round-trip via MemoryStore)
# ---------------------------------------------------------------------------

import tempfile
from pathlib import Path

from memory.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test.db"
    return MemoryStore(db_path=str(db))


def test_delegation_source_ref_persists(store):
    ref = SourceRef(
        provider="m365_teams",
        thread_id="19:abc@thread.v2",
        url="https://teams.microsoft.com/l/message/x",
        quote="Own PST remediation",
    )
    d = Delegation(task="PST remediation", delegated_to="shawn", source_ref=ref)
    saved = store.store_delegation(d)
    assert saved.id is not None
    reloaded = store.get_delegation(saved.id)
    assert reloaded.source_ref == ref


def test_decision_source_ref_persists(store):
    ref = SourceRef(provider="m365_email", quote="Going with option B")
    dec = Decision(title="Adopt option B", source_ref=ref)
    saved = store.store_decision(dec)
    reloaded = store.get_decision(saved.id)
    assert reloaded.source_ref == ref


def test_legacy_delegation_without_source_ref_still_loads(store):
    """Existing rows (no source_ref column value) must load with source_ref=None."""
    d = Delegation(task="t", delegated_to="x")  # source_ref defaults to None
    saved = store.store_delegation(d)
    reloaded = store.get_delegation(saved.id)
    assert reloaded.source_ref is None


# ---------------------------------------------------------------------------
# Update-path serialization tests — the TEXT column must receive JSON, not a
# SourceRef or dict repr. Mirrors the pattern scheduler_store uses for
# delivery_config on update_scheduled_task.
# ---------------------------------------------------------------------------


def test_update_delegation_source_ref_round_trips(store):
    d = Delegation(task="t", delegated_to="x")
    saved = store.store_delegation(d)
    ref = SourceRef(provider="m365_teams", thread_id="19:abc@thread.v2", quote="Own it")
    store.update_delegation(saved.id, source_ref=ref)
    reloaded = store.get_delegation(saved.id)
    assert reloaded.source_ref == ref


def test_update_delegation_source_ref_accepts_dict(store):
    d = Delegation(task="t", delegated_to="x")
    saved = store.store_delegation(d)
    store.update_delegation(saved.id, source_ref={"provider": "m365_email", "quote": "sure"})
    reloaded = store.get_delegation(saved.id)
    assert reloaded.source_ref == SourceRef(provider="m365_email", quote="sure")


def test_update_decision_source_ref_round_trips(store):
    dec = Decision(title="x")
    saved = store.store_decision(dec)
    ref = SourceRef(provider="m365_email", quote="Going with B")
    store.update_decision(saved.id, source_ref=ref)
    reloaded = store.get_decision(saved.id)
    assert reloaded.source_ref == ref


# ---------------------------------------------------------------------------
# from_dict defends the MCP boundary against LLM-produced dicts with unknown
# keys (same forward-compat behavior SourceRef.from_json already has).
# ---------------------------------------------------------------------------


def test_from_dict_filters_unknown_keys():
    ref = SourceRef.from_dict({"provider": "m365_teams", "foo": "bar", "quote": "hi"})
    assert ref.provider == "m365_teams"
    assert ref.quote == "hi"
