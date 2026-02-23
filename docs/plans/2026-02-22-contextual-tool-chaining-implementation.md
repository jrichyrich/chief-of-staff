# Contextual Tool Chaining (Person Enrichment) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an `enrich_person` MCP tool that fetches identity, facts, delegations, decisions, iMessage, and email data for a person in parallel — one tool call instead of six.

**Architecture:** New `mcp_tools/enrichment.py` module with a single `enrich_person` tool. Uses `asyncio.gather` to fetch from 6 data sources in parallel. Each source is error-isolated. Empty sections omitted. Registered in `mcp_server.py` alongside existing tool modules.

**Tech Stack:** Python, asyncio, FastMCP, pytest

---

### Task 1: Create enrichment module with enrich_person

**Files:**
- Create: `mcp_tools/enrichment.py`
- Create: `tests/test_enrichment.py`

**Step 1: Write the tests**

Create `tests/test_enrichment.py`:

```python
"""Tests for the enrich_person MCP tool."""

import json
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

import mcp_server  # noqa: F401 — triggers register() calls
from memory.models import Delegation, Decision
from memory.store import MemoryStore
from mcp_tools.enrichment import enrich_person


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test_enrichment.db")
    yield store
    store.close()


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
        """Result always contains the queried name."""
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert data["name"] == "Jane Smith"

    @pytest.mark.asyncio
    async def test_identities_included(self, memory_store):
        """Linked identities appear in result."""
        memory_store.link_identity(
            canonical_name="Jane Smith",
            provider="m365_email",
            provider_id="jane@company.com",
            display_name="Jane",
            email="jane@company.com",
        )
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "identities" in data
        assert len(data["identities"]) >= 1
        assert data["identities"][0]["provider"] == "m365_email"

    @pytest.mark.asyncio
    async def test_facts_included(self, memory_store):
        """Memory facts about the person appear."""
        from memory.models import Fact
        memory_store.store_fact(Fact(category="relationship", key="Jane Smith/role", value="Product Manager"))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "facts" in data
        assert any("Product Manager" in f["value"] for f in data["facts"])

    @pytest.mark.asyncio
    async def test_delegations_included(self, memory_store):
        """Delegations to the person appear."""
        memory_store.store_delegation(Delegation(
            task="Review design doc", delegated_to="Jane Smith", priority="high",
        ))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "delegations" in data
        assert data["delegations"][0]["task"] == "Review design doc"

    @pytest.mark.asyncio
    async def test_delegations_capped_at_10(self, memory_store):
        """Delegations are capped at 10."""
        for i in range(15):
            memory_store.store_delegation(Delegation(
                task=f"Task {i}", delegated_to="Jane Smith",
            ))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert len(data["delegations"]) == 10

    @pytest.mark.asyncio
    async def test_decisions_included(self, memory_store):
        """Decisions mentioning the person appear."""
        memory_store.store_decision(Decision(
            title="Hire Jane Smith", status="pending_execution",
        ))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "decisions" in data
        assert data["decisions"][0]["title"] == "Hire Jane Smith"

    @pytest.mark.asyncio
    async def test_decisions_capped_at_10(self, memory_store):
        """Decisions are capped at 10."""
        for i in range(15):
            memory_store.store_decision(Decision(
                title=f"Decision {i} Jane Smith", status="pending_execution",
            ))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert len(data["decisions"]) <= 10

    @pytest.mark.asyncio
    async def test_imessages_included(self):
        """iMessage search results appear when messages_store is available."""
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
        """iMessage results are capped at 10."""
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
        """Mail search results appear when mail_store is available."""
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
        """Email results are capped at 10."""
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
        """Sections with no data are not in the output."""
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
        """iMessage failure does not break other sections."""
        mock_messages = MagicMock()
        mock_messages.search_messages.side_effect = Exception("Messages DB locked")
        mcp_server._state.messages_store = mock_messages
        memory_store.store_delegation(Delegation(
            task="Still works", delegated_to="Jane Smith",
        ))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "recent_messages" not in data
        assert "delegations" in data

    @pytest.mark.asyncio
    async def test_mail_error_isolated(self, memory_store):
        """Mail failure does not break other sections."""
        mock_mail = MagicMock()
        mock_mail.search_messages.side_effect = Exception("AppleScript failed")
        mcp_server._state.mail_store = mock_mail
        memory_store.store_delegation(Delegation(
            task="Still works", delegated_to="Jane Smith",
        ))
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "recent_emails" not in data
        assert "delegations" in data

    @pytest.mark.asyncio
    async def test_memory_error_isolated(self):
        """Memory store failure for one section doesn't break others."""
        mock_memory = MagicMock()
        mock_memory.search_identity.return_value = []
        mock_memory.query_memory.side_effect = Exception("FTS5 error")
        mock_memory.list_delegations.return_value = []
        mock_memory.search_decisions.return_value = []
        mcp_server._state.memory_store = mock_memory
        result = await enrich_person("Jane Smith")
        data = json.loads(result)
        assert "name" in data
        assert "facts" not in data

    @pytest.mark.asyncio
    async def test_days_back_controls_imessage_window(self):
        """days_back parameter controls how far back iMessage searches."""
        mock_messages = MagicMock()
        mock_messages.search_messages.return_value = []
        mcp_server._state.messages_store = mock_messages
        await enrich_person("Jane Smith", days_back=14)
        call_kwargs = mock_messages.search_messages.call_args
        # 14 days = 14 * 1440 = 20160 minutes
        assert call_kwargs[1].get("minutes", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None) == 20160 or \
               mock_messages.search_messages.call_args.kwargs.get("minutes") == 20160

    @pytest.mark.asyncio
    async def test_all_sections_populated(self, memory_store):
        """Full enrichment with all sources returning data."""
        from memory.models import Fact
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
```

**Step 2: Write the implementation**

Create `mcp_tools/enrichment.py`:

```python
"""Contextual tool chaining — person enrichment via parallel data fetching."""

import asyncio
import json
import logging

logger = logging.getLogger("jarvis-enrichment")


def register(mcp, state):
    """Register enrichment tools with the MCP server."""

    @mcp.tool()
    async def enrich_person(name: str, days_back: int = 7) -> str:
        """Get a consolidated profile for a person: identities, facts, delegations, decisions, recent messages, and emails.

        Fetches from 6 data sources in parallel. Much faster than calling each tool separately.
        Empty sections are omitted. If a data source is unavailable, that section is silently skipped.

        Args:
            name: Person's name to search for (canonical name or partial match)
            days_back: How many days back to search communications (default 7)
        """
        context = {"name": name}
        minutes = days_back * 1440

        async def fetch_identities():
            try:
                results = state.memory_store.search_identity(name)
                if results:
                    return ("identities", results[:10])
            except Exception as e:
                logger.debug("enrich_person: identities failed: %s", e)
            return None

        async def fetch_facts():
            try:
                results = state.memory_store.query_memory(name)
                if results:
                    facts = [
                        {"category": f.category, "key": f.key, "value": f.value, "confidence": f.confidence}
                        for f in results[:10]
                    ]
                    if facts:
                        return ("facts", facts)
            except Exception as e:
                logger.debug("enrich_person: facts failed: %s", e)
            return None

        async def fetch_delegations():
            try:
                results = state.memory_store.list_delegations(delegated_to=name)
                if results:
                    delegations = [
                        {"task": d.task, "delegated_to": d.delegated_to, "due_date": d.due_date or "", "priority": d.priority, "status": d.status}
                        for d in results[:10]
                    ]
                    if delegations:
                        return ("delegations", delegations)
            except Exception as e:
                logger.debug("enrich_person: delegations failed: %s", e)
            return None

        async def fetch_decisions():
            try:
                results = state.memory_store.search_decisions(name)
                if results:
                    decisions = [
                        {"title": d["title"], "status": d["status"], "created_at": d.get("created_at", "")}
                        for d in results[:10]
                    ]
                    if decisions:
                        return ("decisions", decisions)
            except Exception as e:
                logger.debug("enrich_person: decisions failed: %s", e)
            return None

        async def fetch_imessages():
            try:
                messages_store = state.messages_store
                if messages_store is None:
                    return None
                results = messages_store.search_messages(name, minutes=minutes)
                if results:
                    return ("recent_messages", results[:10])
            except Exception as e:
                logger.debug("enrich_person: imessages failed: %s", e)
            return None

        async def fetch_emails():
            try:
                mail_store = state.mail_store
                if mail_store is None:
                    return None
                results = mail_store.search_messages(name, limit=10)
                if results:
                    return ("recent_emails", results[:10])
            except Exception as e:
                logger.debug("enrich_person: emails failed: %s", e)
            return None

        results = await asyncio.gather(
            fetch_identities(),
            fetch_facts(),
            fetch_delegations(),
            fetch_decisions(),
            fetch_imessages(),
            fetch_emails(),
        )

        for result in results:
            if result is not None:
                key, value = result
                context[key] = value

        return json.dumps(context, indent=2, default=str)

    # Expose at module level for testing
    import sys
    module = sys.modules[__name__]
    module.enrich_person = enrich_person
```

**Step 3: Run tests to verify they pass**

Run: `pytest tests/test_enrichment.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add mcp_tools/enrichment.py tests/test_enrichment.py
git commit -m "feat: add enrich_person MCP tool for parallel person data fetching"
```

---

### Task 2: Register enrichment module in mcp_server.py

**Files:**
- Modify: `mcp_server.py:194-233`

**Step 1: Add import**

In `mcp_server.py`, add `enrichment` to the import block (after `resources` on line 212):

```python
from mcp_tools import (
    memory_tools,
    document_tools,
    agent_tools,
    lifecycle_tools,
    calendar_tools,
    reminder_tools,
    mail_tools,
    imessage_tools,
    okr_tools,
    webhook_tools,
    skill_tools,
    scheduler_tools,
    proactive_tools,
    channel_tools,
    identity_tools,
    event_rule_tools,
    session_tools,
    resources,
    enrichment,
)
```

**Step 2: Add registration call**

After `resources.register(mcp, _state)` (line 233), add:

```python
enrichment.register(mcp, _state)
```

**Step 3: Run tests**

Run: `pytest tests/test_enrichment.py -v`
Expected: ALL PASS (tool still works with registration)

Run: `pytest`
Expected: ALL 1435+ tests pass

**Step 4: Commit**

```bash
git add mcp_server.py
git commit -m "feat: register enrichment module in MCP server"
```

---

### Task 3: Run full test suite and verify no regressions

**Files:** None (verification only)

**Step 1: Run full test suite**

Run: `pytest`
Expected: All 1435+ tests pass, zero failures

**Step 2: Commit (final)**

```bash
git add -A
git commit -m "feat: contextual tool chaining — enrich_person for parallel person data fetching

New enrich_person MCP tool fetches identity, facts, delegations, decisions,
iMessage, and email data for a person in parallel via asyncio.gather. One
tool call replaces 5-6 sequential calls. Each data source error-isolated.
Empty sections omitted. Results capped at 10 per section."
```
