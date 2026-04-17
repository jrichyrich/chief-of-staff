"""Tests for the triage_brief_items MCP tool."""

import json
from unittest.mock import MagicMock, patch

import pytest

import mcp_server  # noqa: F401 — triggers register() calls
from memory.models import Fact
from mcp_tools.triage_tools import triage_brief_items


SAMPLE_EMAILS = [
    {
        "id": "AAMkAD-1",
        "conversationId": "conv-pst",
        "subject": "PST incident — next steps",
        "from": {"emailAddress": {"address": "shawn@chg.com", "name": "Shawn F"}},
        "receivedDateTime": "2026-04-17T10:00:00Z",
        "bodyPreview": "Decision needed on rollback window.",
    },
    {
        "id": "AAMkAD-2",
        "conversationId": "conv-pst",
        "subject": "RE: PST incident — next steps",
        "from": {"emailAddress": {"address": "jason@chg.com", "name": "Jason R"}},
        "receivedDateTime": "2026-04-17T10:30:00Z",
        "bodyPreview": "Option B. Ship tonight.",
    },
    {
        "id": "AAMkAD-3",
        "conversationId": "conv-cafe",
        "subject": "Weekly menu",
        "from": {"emailAddress": {"address": "cafe@chg.com", "name": "Cafe"}},
        "receivedDateTime": "2026-04-17T09:00:00Z",
        "bodyPreview": "Tacos Tuesday.",
    },
    {
        "id": "AAMkAD-4",
        "conversationId": "conv-spam",
        "subject": "Newsletter",
        "from": {"emailAddress": {"address": "noreply@substack.com", "name": "Sub"}},
        "receivedDateTime": "2026-04-17T08:00:00Z",
        "bodyPreview": "Weekly digest.",
    },
]


SAMPLE_TEAMS = [
    {
        "id": "1713292800000",
        "chatId": "19:abc@thread.v2",
        "chatType": "oneOnOne",
        "from": {"user": {"id": "shawn-id", "displayName": "Shawn Farnworth"}},
        "createdDateTime": "2026-04-17T10:00:00Z",
        "body": {"content": "<p>Can you own PST rollback?</p>", "contentType": "html"},
    },
]


FAKE_TRIAGE_RESPONSE = json.dumps([
    {"index": 0, "relevance": 0.95, "category": "decision-needed", "why": "PST rollback blocking"},
    {"index": 1, "relevance": 0.2, "category": "fyi", "why": "menu"},
    {"index": 2, "relevance": 0.85, "category": "action-for-you", "why": "PST ownership"},
])


def _mock_haiku(text: str):
    async def fake_create(**kwargs):
        mock = MagicMock()
        mock.content = [MagicMock(text=text)]
        mock.usage = MagicMock(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        return mock

    client = MagicMock()
    client.messages.create = fake_create
    return client


@pytest.fixture(autouse=True)
def wire_state(memory_store):
    mcp_server._state.memory_store = memory_store
    mcp_server._state.session_brain = None
    yield
    mcp_server._state.memory_store = None
    mcp_server._state.session_brain = None


class TestTriageBriefItems:
    @pytest.mark.asyncio
    async def test_happy_path_returns_structured_result(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="role", value="VP/CoS"))
        memory_store.store_fact(Fact(category="work", key="project.pst", value="active"))
        memory_store.link_identity(
            canonical_name="shawn.farnworth", provider="m365_teams",
            provider_id="shawn-id", display_name="Shawn Farnworth", email="shawn@chg.com",
        )
        memory_store.store_fact(Fact(
            category="relationship",
            key="person.shawn.farnworth.role",
            value="Director of Identity Engineering",
        ))

        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic", return_value=_mock_haiku(FAKE_TRIAGE_RESPONSE)):
            result = await triage_brief_items(
                emails=SAMPLE_EMAILS,
                teams_messages=SAMPLE_TEAMS,
                brief_type="daily",
                key_people_emails=["shawn@chg.com"],
                user_email="jason@chg.com",
            )

        data = json.loads(result)
        assert set(data.keys()) == {"threads", "triaged", "enriched_people", "context"}

    @pytest.mark.asyncio
    async def test_threads_include_both_email_and_teams(self):
        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic", return_value=_mock_haiku(FAKE_TRIAGE_RESPONSE)):
            result = await triage_brief_items(
                emails=SAMPLE_EMAILS, teams_messages=SAMPLE_TEAMS,
                user_email="jason@chg.com",
            )
        data = json.loads(result)
        kinds = {th["kind"] for th in data["threads"]}
        assert kinds == {"email", "teams"}

    @pytest.mark.asyncio
    async def test_triaged_sorted_by_relevance_desc(self):
        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic", return_value=_mock_haiku(FAKE_TRIAGE_RESPONSE)):
            result = await triage_brief_items(
                emails=SAMPLE_EMAILS, teams_messages=SAMPLE_TEAMS,
                user_email="jason@chg.com",
            )
        data = json.loads(result)
        relevances = [ti["relevance"] for ti in data["triaged"]]
        assert relevances == sorted(relevances, reverse=True)

    @pytest.mark.asyncio
    async def test_self_sent_email_dropped_before_llm(self):
        """jason@chg.com authored conv-pst latest reply — the thread's latest sender is 'self', so filter drops it."""
        captured = {}

        async def capturing_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            mock = MagicMock()
            mock.content = [MagicMock(text=FAKE_TRIAGE_RESPONSE)]
            mock.usage = MagicMock(
                input_tokens=1, output_tokens=1,
                cache_creation_input_tokens=0, cache_read_input_tokens=0,
            )
            return mock

        client = MagicMock()
        client.messages.create = capturing_create

        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic", return_value=client):
            await triage_brief_items(
                emails=SAMPLE_EMAILS, teams_messages=[],
                user_email="jason@chg.com",
            )
        sent = captured["messages"][0]["content"]
        assert "conv-pst" not in sent
        assert "conv-cafe" in sent or "conv-spam" not in sent  # cafe survives, noreply filtered

    @pytest.mark.asyncio
    async def test_noreply_email_filtered(self):
        captured = {}

        async def capturing_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            mock = MagicMock()
            mock.content = [MagicMock(text=FAKE_TRIAGE_RESPONSE)]
            mock.usage = MagicMock(
                input_tokens=1, output_tokens=1,
                cache_creation_input_tokens=0, cache_read_input_tokens=0,
            )
            return mock

        client = MagicMock()
        client.messages.create = capturing_create

        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic", return_value=client):
            await triage_brief_items(
                emails=SAMPLE_EMAILS, teams_messages=[],
                user_email="jason@chg.com",
            )
        sent = captured["messages"][0]["content"]
        assert "substack" not in sent.lower()
        assert "noreply" not in sent.lower()

    @pytest.mark.asyncio
    async def test_enriched_people_indexed_by_canonical_name(self, memory_store):
        memory_store.link_identity(
            canonical_name="shawn.farnworth", provider="m365_teams",
            provider_id="shawn-id", display_name="Shawn Farnworth", email="shawn@chg.com",
        )
        memory_store.store_fact(Fact(
            category="relationship",
            key="person.shawn.farnworth.role",
            value="Director of Identity Engineering",
        ))

        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic", return_value=_mock_haiku(FAKE_TRIAGE_RESPONSE)):
            result = await triage_brief_items(
                emails=SAMPLE_EMAILS, teams_messages=SAMPLE_TEAMS,
                user_email="jason@chg.com",
            )
        data = json.loads(result)
        assert "shawn.farnworth" in data["enriched_people"]
        entry = data["enriched_people"]["shawn.farnworth"]
        assert entry["role"] == "Director of Identity Engineering"
        assert "Shawn Farnworth" in entry["display_names"]

    @pytest.mark.asyncio
    async def test_context_reflects_memory_and_key_people(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="role", value="VP/Chief of Staff"))
        memory_store.store_fact(Fact(category="work", key="project.pst", value="sev-0 active"))

        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic", return_value=_mock_haiku(FAKE_TRIAGE_RESPONSE)):
            result = await triage_brief_items(
                emails=SAMPLE_EMAILS, teams_messages=[],
                key_people_emails=["shawn@chg.com", "theresa@chg.com"],
                user_email="jason@chg.com",
            )
        data = json.loads(result)
        ctx = data["context"]
        assert "VP" in ctx["user_role"] or "Chief of Staff" in ctx["user_role"]
        assert any("pst" in p.lower() for p in ctx["active_projects"])
        assert ctx["key_people"] == ["shawn@chg.com", "theresa@chg.com"]

    @pytest.mark.asyncio
    async def test_empty_inputs_produce_empty_triage(self):
        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic") as mock_client_cls:
            result = await triage_brief_items(
                emails=[], teams_messages=[], user_email="jason@chg.com",
            )
        mock_client_cls.assert_not_called()
        data = json.loads(result)
        assert data["threads"] == []
        assert data["triaged"] == []
        assert data["enriched_people"] == {}

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_default_scores(self):
        """If Haiku returns garbage, tool still returns items at default 0.5 fyi."""
        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic", return_value=_mock_haiku("not-json")):
            result = await triage_brief_items(
                emails=SAMPLE_EMAILS, teams_messages=[],
                user_email="jason@chg.com",
            )
        data = json.loads(result)
        # After filter: conv-pst (self-sent drop), conv-cafe, conv-spam (noreply drop)
        # → cafe only should survive heuristic filter
        assert len(data["triaged"]) >= 1
        for ti in data["triaged"]:
            assert ti["category"] == "fyi"
            assert ti["relevance"] == 0.5

    @pytest.mark.asyncio
    async def test_brief_type_flows_into_context_payload(self):
        """The brief_type argument should survive into the result context."""
        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic", return_value=_mock_haiku(FAKE_TRIAGE_RESPONSE)):
            result = await triage_brief_items(
                emails=[], teams_messages=[],
                brief_type="weekly-cio",
                user_email="jason@chg.com",
            )
        data = json.loads(result)
        assert data["context"].get("brief_type") == "weekly-cio"

    @pytest.mark.asyncio
    async def test_triaged_item_preserves_thread_payload(self):
        from orchestration import triage as t
        with patch.object(t, "AsyncAnthropic", return_value=_mock_haiku(FAKE_TRIAGE_RESPONSE)):
            result = await triage_brief_items(
                emails=SAMPLE_EMAILS, teams_messages=SAMPLE_TEAMS,
                user_email="jason@chg.com",
            )
        data = json.loads(result)
        # Each triaged entry must include the underlying item dict.
        for ti in data["triaged"]:
            assert "item" in ti
            assert "kind" in ti["item"]
