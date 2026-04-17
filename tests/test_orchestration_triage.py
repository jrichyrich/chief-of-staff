"""Tests for orchestration triage: heuristic filter + LLM scoring."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestration.triage import (
    FilterConfig,
    TriageContext,
    TriagedItem,
    heuristic_filter,
)


def test_filter_drops_noreply_senders():
    items = [
        {"kind": "email", "from_email": "noreply@domain.com", "subject": "Deploy OK"},
        {"kind": "email", "from_email": "shawn@chg.com", "subject": "PST fix"},
    ]
    config = FilterConfig()
    out = heuristic_filter(items, config)
    assert len(out) == 1
    assert out[0]["from_email"] == "shawn@chg.com"


def test_filter_drops_common_newsletters():
    items = [
        {"kind": "email", "from_email": "digest@substack.com", "subject": "Weekly"},
        {"kind": "email", "from_email": "notifications@github.com", "subject": "PR x"},
        {"kind": "email", "from_email": "shawn@chg.com", "subject": "Real"},
    ]
    config = FilterConfig(noise_senders_contains=("substack.com", "notifications@github.com"))
    out = heuristic_filter(items, config)
    assert [x["from_email"] for x in out] == ["shawn@chg.com"]


def test_filter_keeps_item_from_key_person_even_if_older():
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    items = [
        {"kind": "email", "from_email": "random@x.com", "subject": "stale", "timestamp": old},
        {"kind": "email", "from_email": "theresa@chg.com", "subject": "old ask", "timestamp": old},
        {"kind": "email", "from_email": "random@x.com", "subject": "fresh", "timestamp": recent},
    ]
    config = FilterConfig(max_age_days=14, key_people_emails=("theresa@chg.com",))
    out = heuristic_filter(items, config)
    subjects = {x["subject"] for x in out}
    assert "stale" not in subjects
    assert "old ask" in subjects
    assert "fresh" in subjects


def test_filter_preserves_unknown_kinds():
    items = [{"kind": "delegation", "task": "x"}]
    out = heuristic_filter(items, FilterConfig())
    assert out == items


def test_filter_drops_self_sent():
    items = [
        {"kind": "email", "from_email": "jason@chg.com", "subject": "self"},
        {"kind": "email", "from_email": "shawn@chg.com", "subject": "other"},
    ]
    config = FilterConfig(user_email="jason@chg.com")
    out = heuristic_filter(items, config)
    assert len(out) == 1 and out[0]["from_email"] == "shawn@chg.com"


from orchestration.triage import build_triage_context


class FakeMemory:
    def __init__(self, facts):
        self._facts = facts

    def list_facts(self, category=None, limit=None):
        if category:
            return [f for f in self._facts if f["category"] == category]
        return self._facts


class FakeBrain:
    def __init__(self, text):
        self._text = text

    def get_current_focus(self):
        return self._text


def test_build_triage_context_pulls_user_role():
    mem = FakeMemory([
        {"category": "personal", "key": "role", "value": "VP/Chief of Staff to the CIO"},
    ])
    ctx = build_triage_context(memory_store=mem, brain=FakeBrain(""))
    assert "VP" in ctx.user_role or "Chief of Staff" in ctx.user_role


def test_build_triage_context_includes_active_projects():
    mem = FakeMemory([
        {"category": "work", "key": "project.pst_remediation", "value": "Active — sev-0 rollback"},
        {"category": "work", "key": "project.dmo_conf_2026", "value": "Panel co-owner"},
        {"category": "personal", "key": "role", "value": "VP"},
    ])
    ctx = build_triage_context(memory_store=mem, brain=FakeBrain(""))
    joined = " ".join(ctx.active_projects).lower()
    assert "pst" in joined
    assert "dmo" in joined


def test_build_triage_context_pulls_current_focus_from_brain():
    mem = FakeMemory([])
    brain = FakeBrain("## Focus\n- Ship CIO weekly brief Friday\n- Close PST rollback")
    ctx = build_triage_context(memory_store=mem, brain=brain)
    joined = " ".join(ctx.current_focus).lower()
    assert "cio weekly" in joined or "pst rollback" in joined


def test_build_triage_context_tolerates_empty_sources():
    ctx = build_triage_context(memory_store=FakeMemory([]), brain=FakeBrain(""))
    assert ctx.user_role  # falls back to default
    assert ctx.active_projects == []
    assert ctx.current_focus == []


def test_build_triage_context_accepts_fact_dataclasses():
    """Real MemoryStore.list_facts returns list[Fact] dataclasses, not dicts."""
    from memory.models import Fact

    class DataclassFakeMemory:
        def __init__(self, facts):
            self._facts = facts

        def list_facts(self, category=None, limit=None):
            if category:
                return [f for f in self._facts if f.category == category]
            return self._facts

    mem = DataclassFakeMemory([
        Fact(category="personal", key="role", value="VP/CoS"),
        Fact(category="work", key="project.pst", value="active"),
    ])
    ctx = build_triage_context(memory_store=mem, brain=FakeBrain(""))
    assert "VP" in ctx.user_role
    assert any("pst" in p.lower() for p in ctx.active_projects)


@pytest.mark.asyncio
async def test_llm_triage_parses_haiku_json_response():
    from orchestration import triage as t
    import json

    items = [
        {"kind": "email", "subject": "PST rollback decision", "from_email": "shawn@chg.com"},
        {"kind": "email", "subject": "Lunch menu", "from_email": "cafe@chg.com"},
    ]
    ctx = TriageContext(
        user_role="VP/CoS",
        active_projects=["pst_remediation"],
        current_focus=["close PST rollback"],
        key_people=["shawn.farnworth"],
    )

    fake_response_text = json.dumps([
        {"index": 0, "relevance": 0.95, "category": "decision-needed",
         "why": "Blocks PST rollback close; aligns with current focus"},
        {"index": 1, "relevance": 0.1, "category": "fyi",
         "why": "Cafe menu, no action"},
    ])

    async def fake_create(**kwargs):
        mock = MagicMock()
        mock.content = [MagicMock(text=fake_response_text)]
        mock.usage = MagicMock(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        return mock

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch.object(t, "AsyncAnthropic", return_value=mock_client):
        results = await t.llm_triage(items, ctx)

    assert len(results) == 2
    assert results[0].relevance == 0.95
    assert results[0].category == "decision-needed"
    assert "PST" in results[0].why
    assert results[0].relevance >= results[1].relevance


@pytest.mark.asyncio
async def test_llm_triage_empty_input_skips_llm_call():
    from orchestration import triage as t

    ctx = TriageContext(user_role="VP/CoS")
    with patch.object(t, "AsyncAnthropic") as mock_client_cls:
        results = await t.llm_triage([], ctx)
    assert results == []
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_llm_triage_falls_back_gracefully_on_bad_json():
    from orchestration import triage as t

    items = [{"kind": "email", "subject": "X"}]
    ctx = TriageContext(user_role="VP/CoS")

    async def fake_create(**kwargs):
        mock = MagicMock()
        mock.content = [MagicMock(text="not json at all")]
        mock.usage = MagicMock(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        return mock

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch.object(t, "AsyncAnthropic", return_value=mock_client):
        results = await t.llm_triage(items, ctx)

    assert len(results) == 1
    assert results[0].category == "fyi"
    assert 0 <= results[0].relevance <= 1
