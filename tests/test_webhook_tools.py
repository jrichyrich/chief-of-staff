# tests/test_webhook_tools.py
"""Tests for the webhook MCP tools."""

import json

import pytest

import mcp_server  # noqa: F401 — triggers tool registrations
from memory.models import WebhookEvent
from memory.store import MemoryStore
from mcp_tools import webhook_tools


@pytest.fixture
def memory_store(tmp_path):
    db_path = tmp_path / "test_webhook_tools.db"
    store = MemoryStore(db_path)
    yield store
    store.close()


@pytest.fixture(autouse=True)
def setup_state(memory_store):
    """Inject test memory store into MCP server state."""
    from mcp_server import _state
    original = _state.memory_store
    _state.memory_store = memory_store
    yield
    _state.memory_store = original


def _seed_events(memory_store, count=3):
    """Insert sample webhook events and return their IDs."""
    ids = []
    for i in range(count):
        event = WebhookEvent(
            source=f"source_{i}",
            event_type=f"type_{i}",
            payload=json.dumps({"index": i}),
        )
        stored = memory_store.store_webhook_event(event)
        ids.append(stored.id)
    return ids


@pytest.mark.asyncio
class TestListWebhookEvents:
    async def test_empty_list(self):
        result = json.loads(await webhook_tools.list_webhook_events())
        assert result["results"] == []
        assert "No webhook events" in result["message"]

    async def test_list_all(self, memory_store):
        _seed_events(memory_store, 3)
        result = json.loads(await webhook_tools.list_webhook_events())
        assert result["count"] == 3
        assert len(result["results"]) == 3

    async def test_filter_by_source(self, memory_store):
        _seed_events(memory_store, 3)
        result = json.loads(await webhook_tools.list_webhook_events(source="source_1"))
        assert result["count"] == 1
        assert result["results"][0]["source"] == "source_1"

    async def test_filter_by_status(self, memory_store):
        ids = _seed_events(memory_store, 3)
        memory_store.update_webhook_event_status(ids[0], "processed")
        result = json.loads(await webhook_tools.list_webhook_events(status="pending"))
        assert result["count"] == 2

    async def test_limit(self, memory_store):
        _seed_events(memory_store, 5)
        result = json.loads(await webhook_tools.list_webhook_events(limit=2))
        assert result["count"] == 2


@pytest.mark.asyncio
class TestGetWebhookEvent:
    async def test_get_existing(self, memory_store):
        ids = _seed_events(memory_store, 1)
        result = json.loads(await webhook_tools.get_webhook_event(ids[0]))
        assert result["id"] == ids[0]
        assert result["source"] == "source_0"
        assert result["event_type"] == "type_0"
        assert result["payload"] == {"index": 0}
        assert result["status"] == "pending"

    async def test_get_nonexistent(self):
        result = json.loads(await webhook_tools.get_webhook_event(9999))
        assert "error" in result
        assert "not found" in result["error"]

    async def test_get_with_string_payload(self, memory_store):
        event = WebhookEvent(source="test", event_type="ping", payload="plain text")
        stored = memory_store.store_webhook_event(event)
        result = json.loads(await webhook_tools.get_webhook_event(stored.id))
        assert result["payload"] == "plain text"


@pytest.mark.asyncio
class TestProcessWebhookEvent:
    async def test_process_pending_event(self, memory_store):
        ids = _seed_events(memory_store, 1)
        result = json.loads(await webhook_tools.process_webhook_event(ids[0]))
        assert result["status"] == "processed"
        assert result["processed_at"] is not None

        # Verify in DB
        event = memory_store.get_webhook_event(ids[0])
        assert event.status == "processed"
        assert event.processed_at is not None

    async def test_process_already_processed(self, memory_store):
        ids = _seed_events(memory_store, 1)
        memory_store.update_webhook_event_status(ids[0], "processed")
        result = json.loads(await webhook_tools.process_webhook_event(ids[0]))
        assert result["status"] == "already_processed"

    async def test_process_nonexistent(self):
        result = json.loads(await webhook_tools.process_webhook_event(9999))
        assert "error" in result


@pytest.mark.asyncio
class TestWebhookStoreIntegration:
    async def test_store_and_retrieve(self, memory_store):
        event = WebhookEvent(
            source="jira",
            event_type="issue_created",
            payload=json.dumps({"key": "PROJ-123", "summary": "New bug"}),
        )
        stored = memory_store.store_webhook_event(event)
        assert stored.id is not None
        assert stored.status == "pending"
        assert stored.received_at is not None

        retrieved = memory_store.get_webhook_event(stored.id)
        assert retrieved.source == "jira"
        assert retrieved.event_type == "issue_created"
        assert json.loads(retrieved.payload)["key"] == "PROJ-123"

    async def test_update_status(self, memory_store):
        event = WebhookEvent(source="test", event_type="ping")
        stored = memory_store.store_webhook_event(event)

        updated = memory_store.update_webhook_event_status(stored.id, "processed")
        assert updated.status == "processed"
        assert updated.processed_at is not None

    async def test_update_status_failed(self, memory_store):
        event = WebhookEvent(source="test", event_type="ping")
        stored = memory_store.store_webhook_event(event)

        updated = memory_store.update_webhook_event_status(stored.id, "failed")
        assert updated.status == "failed"
        assert updated.processed_at is not None

    async def test_list_with_multiple_filters(self, memory_store):
        for src in ["github", "github", "slack"]:
            event = WebhookEvent(source=src, event_type="push")
            memory_store.store_webhook_event(event)

        all_events = memory_store.list_webhook_events()
        assert len(all_events) == 3

        github_events = memory_store.list_webhook_events(source="github")
        assert len(github_events) == 2

        slack_events = memory_store.list_webhook_events(source="slack")
        assert len(slack_events) == 1
