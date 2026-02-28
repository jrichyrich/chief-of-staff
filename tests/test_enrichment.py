"""Tests for the enrich_person MCP tool."""

import json
from unittest.mock import MagicMock

import pytest

import mcp_server  # noqa: F401 — triggers register() calls
from memory.models import Delegation, Decision, Fact
from memory.store import MemoryStore
from mcp_tools.enrichment import enrich_person



@pytest.fixture(autouse=True)
def wire_state(memory_store):
    """Inject fresh stores into MCP server state."""
    mcp_server._state.memory_store = memory_store
    mcp_server._state.messages_store = None
    mcp_server._state.mail_store = None
    yield
    mcp_server._state.memory_store = None
    mcp_server._state.messages_store = None
    mcp_server._state.mail_store = None


class TestEnrichPerson:
    @pytest.mark.asyncio
    async def test_returns_valid_json_with_name(self):
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert data["name"] == "Jane Smith"

    @pytest.mark.asyncio
    async def test_identities_included(self, memory_store):
        memory_store.link_identity(
            canonical_name="Jane Smith", provider="m365_email",
            provider_id="jane@company.com", display_name="Jane", email="jane@company.com",
        )
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "identities" in data
        assert len(data["identities"]) >= 1
        assert data["identities"][0]["provider"] == "m365_email"

    @pytest.mark.asyncio
    async def test_facts_included(self, memory_store):
        memory_store.store_fact(Fact(category="relationship", key="Jane Smith/role", value="Product Manager"))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "facts" in data
        assert any("Product Manager" in f["value"] for f in data["facts"])

    @pytest.mark.asyncio
    async def test_delegations_included(self, memory_store):
        memory_store.store_delegation(Delegation(
            task="Review design doc", delegated_to="Jane Smith", priority="high",
        ))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "delegations" in data
        assert data["delegations"][0]["task"] == "Review design doc"

    @pytest.mark.asyncio
    async def test_delegations_capped_at_10(self, memory_store):
        for i in range(15):
            memory_store.store_delegation(Delegation(task=f"Task {i}", delegated_to="Jane Smith"))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert len(data["delegations"]) == 10

    @pytest.mark.asyncio
    async def test_decisions_included(self, memory_store):
        memory_store.store_decision(Decision(title="Hire Jane Smith", status="pending_execution"))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "decisions" in data
        assert data["decisions"][0]["title"] == "Hire Jane Smith"

    @pytest.mark.asyncio
    async def test_decisions_capped_at_10(self, memory_store):
        for i in range(15):
            memory_store.store_decision(Decision(title=f"Decision {i} Jane Smith", status="pending_execution"))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert len(data["decisions"]) <= 10

    @pytest.mark.asyncio
    async def test_imessages_included(self):
        mock_messages = MagicMock()
        mock_messages.search_messages.return_value = [
            {"sender": "Jane Smith", "text": "Hey!", "date": "2026-02-22T10:00:00"},
        ]
        mcp_server._state.messages_store = mock_messages
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "recent_messages" in data
        assert data["recent_messages"][0]["sender"] == "Jane Smith"

    @pytest.mark.asyncio
    async def test_imessages_capped_at_10(self):
        mock_messages = MagicMock()
        mock_messages.search_messages.return_value = [
            {"sender": "Jane", "text": f"Msg {i}", "date": "2026-02-22"} for i in range(20)
        ]
        mcp_server._state.messages_store = mock_messages
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert len(data["recent_messages"]) == 10

    @pytest.mark.asyncio
    async def test_emails_included(self):
        mock_mail = MagicMock()
        mock_mail.search_messages.return_value = [
            {"subject": "Q1 Review", "from": "jane@co.com", "date": "2026-02-22"},
        ]
        mcp_server._state.mail_store = mock_mail
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "recent_emails" in data
        assert data["recent_emails"][0]["subject"] == "Q1 Review"

    @pytest.mark.asyncio
    async def test_emails_capped_at_10(self):
        mock_mail = MagicMock()
        mock_mail.search_messages.return_value = [
            {"subject": f"Email {i}", "from": "jane@co.com", "date": "2026-02-22"} for i in range(20)
        ]
        mcp_server._state.mail_store = mock_mail
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert len(data["recent_emails"]) == 10

    @pytest.mark.asyncio
    async def test_empty_sections_omitted(self):
        result = await enrich_person("Nobody")
        data = json.loads(result)
        assert "identities" not in data
        assert "delegations" not in data
        assert "decisions" not in data
        assert "recent_messages" not in data
        assert "recent_emails" not in data
        assert "name" in data

    @pytest.mark.asyncio
    async def test_imessage_error_isolated(self, memory_store):
        mock_messages = MagicMock()
        mock_messages.search_messages.side_effect = Exception("Messages DB locked")
        mcp_server._state.messages_store = mock_messages
        memory_store.store_delegation(Delegation(task="Still works", delegated_to="Jane Smith"))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "recent_messages" not in data
        assert "delegations" in data

    @pytest.mark.asyncio
    async def test_mail_error_isolated(self, memory_store):
        mock_mail = MagicMock()
        mock_mail.search_messages.side_effect = Exception("AppleScript failed")
        mcp_server._state.mail_store = mock_mail
        memory_store.store_delegation(Delegation(task="Still works", delegated_to="Jane Smith"))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "recent_emails" not in data
        assert "delegations" in data

    @pytest.mark.asyncio
    async def test_memory_error_isolated(self):
        mock_memory = MagicMock()
        mock_memory.search_identity.return_value = []
        mock_memory.search_facts.side_effect = Exception("FTS5 error")
        mock_memory.list_delegations.return_value = []
        mock_memory.search_decisions.return_value = []
        mcp_server._state.memory_store = mock_memory
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "name" in data
        assert "facts" not in data

    @pytest.mark.asyncio
    async def test_days_back_controls_imessage_window(self):
        mock_messages = MagicMock()
        mock_messages.search_messages.return_value = []
        mcp_server._state.messages_store = mock_messages
        await enrich_person("Jane Smith", days_back=14)
        # 14 days * 1440 = 20160 minutes
        mock_messages.search_messages.assert_called_once()
        call_args = mock_messages.search_messages.call_args
        # Could be positional or keyword
        if len(call_args.args) > 1:
            assert call_args.args[1] == 20160
        else:
            assert call_args.kwargs.get("minutes") == 20160

    @pytest.mark.asyncio
    async def test_all_sections_populated(self, memory_store):
        memory_store.link_identity(
            canonical_name="Jane Smith", provider="email",
            provider_id="jane@co.com", display_name="Jane", email="jane@co.com",
        )
        memory_store.store_fact(Fact(category="work", key="Jane Smith/team", value="Platform"))
        memory_store.store_delegation(Delegation(task="Deploy v2", delegated_to="Jane Smith"))
        memory_store.store_decision(Decision(title="Promote Jane Smith", status="pending_execution"))
        mock_messages = MagicMock()
        mock_messages.search_messages.return_value = [
            {"sender": "Jane", "text": "Done!", "date": "2026-02-22"},
        ]
        mcp_server._state.messages_store = mock_messages
        mock_mail = MagicMock()
        mock_mail.search_messages.return_value = [
            {"subject": "Deployment plan", "from": "jane@co.com", "date": "2026-02-22"},
        ]
        mcp_server._state.mail_store = mock_mail
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "identities" in data
        assert "facts" in data
        assert "delegations" in data
        assert "decisions" in data
        assert "recent_messages" in data
        assert "recent_emails" in data
