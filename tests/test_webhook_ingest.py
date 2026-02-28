# tests/test_webhook_ingest.py
"""Tests for the file-drop webhook inbox ingestion."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.registry import AgentConfig, AgentRegistry
from memory.store import MemoryStore
from webhook.ingest import dispatch_pending_events, ingest_events



@pytest.fixture
def agent_registry(tmp_path):
    configs_dir = tmp_path / "agent_configs"
    configs_dir.mkdir()
    registry = AgentRegistry(configs_dir)
    registry.save_agent(AgentConfig(
        name="test-agent",
        description="Test agent",
        system_prompt="You are a test agent.",
        capabilities=[],
    ))
    return registry


@pytest.fixture
def document_store():
    return MagicMock()


def _store_pending_event(memory_store, source="github", event_type="alert.fired"):
    from memory.models import WebhookEvent
    event = WebhookEvent(source=source, event_type=event_type, payload='{"test": true}')
    return memory_store.store_webhook_event(event)


def _create_dispatch_rule(memory_store, agent_name="test-agent", **overrides):
    defaults = dict(
        name="test-rule",
        event_source="github",
        event_type_pattern="alert.*",
        agent_name=agent_name,
    )
    defaults.update(overrides)
    return memory_store.create_event_rule(**defaults)


class TestIngestEvents:
    def test_valid_json_ingested(self, memory_store, inbox_dir):
        event_file = inbox_dir / "event1.json"
        event_file.write_text(
            json.dumps({
                "source": "github",
                "event_type": "push",
                "payload": {"ref": "main"},
            })
        )

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["ingested"] == 1
        assert result["failed"] == 0
        assert result["skipped"] == 0

        # Verify file moved to processed/
        assert not event_file.exists()
        assert (inbox_dir / "processed" / "event1.json").exists()

        # Verify event stored in DB
        events = memory_store.list_webhook_events(limit=10)
        assert len(events) == 1
        assert events[0].source == "github"
        assert events[0].event_type == "push"
        assert json.loads(events[0].payload) == {"ref": "main"}
        assert events[0].status == "pending"

    def test_multiple_files_ingested(self, memory_store, inbox_dir):
        for i in range(3):
            (inbox_dir / f"event{i}.json").write_text(
                json.dumps({"source": f"src{i}", "event_type": "test"})
            )

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["ingested"] == 3
        assert result["failed"] == 0
        events = memory_store.list_webhook_events(limit=10)
        assert len(events) == 3

    def test_malformed_json_moved_to_failed(self, memory_store, inbox_dir):
        bad_file = inbox_dir / "bad.json"
        bad_file.write_text("not valid json {{{")

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["ingested"] == 0
        assert result["failed"] == 1
        assert not bad_file.exists()
        assert (inbox_dir / "failed" / "bad.json").exists()

    def test_missing_source_field_fails(self, memory_store, inbox_dir):
        (inbox_dir / "nosource.json").write_text(
            json.dumps({"event_type": "test"})
        )

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["failed"] == 1
        assert result["ingested"] == 0
        assert (inbox_dir / "failed" / "nosource.json").exists()

    def test_missing_event_type_field_fails(self, memory_store, inbox_dir):
        (inbox_dir / "notype.json").write_text(
            json.dumps({"source": "test"})
        )

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["failed"] == 1
        assert result["ingested"] == 0
        assert (inbox_dir / "failed" / "notype.json").exists()

    def test_non_dict_json_fails(self, memory_store, inbox_dir):
        (inbox_dir / "array.json").write_text(json.dumps([1, 2, 3]))

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["failed"] == 1
        assert (inbox_dir / "failed" / "array.json").exists()

    def test_empty_directory_noop(self, memory_store, inbox_dir):
        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result == {"ingested": 0, "failed": 0, "skipped": 0}

    def test_string_payload_stored_as_is(self, memory_store, inbox_dir):
        (inbox_dir / "strpayload.json").write_text(
            json.dumps({
                "source": "test",
                "event_type": "ping",
                "payload": "plain text",
            })
        )

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["ingested"] == 1
        events = memory_store.list_webhook_events(limit=10)
        assert events[0].payload == "plain text"

    def test_dict_payload_serialized_to_json(self, memory_store, inbox_dir):
        (inbox_dir / "dictpayload.json").write_text(
            json.dumps({
                "source": "test",
                "event_type": "ping",
                "payload": {"key": "value"},
            })
        )

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["ingested"] == 1
        events = memory_store.list_webhook_events(limit=10)
        assert json.loads(events[0].payload) == {"key": "value"}

    def test_missing_payload_defaults_empty(self, memory_store, inbox_dir):
        (inbox_dir / "nopayload.json").write_text(
            json.dumps({"source": "test", "event_type": "ping"})
        )

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["ingested"] == 1
        events = memory_store.list_webhook_events(limit=10)
        assert events[0].payload == ""

    def test_duplicate_filename_handled(self, memory_store, inbox_dir):
        """If a file with the same name already exists in processed/, rename."""
        processed_dir = inbox_dir / "processed"
        processed_dir.mkdir()
        # Pre-existing file in processed/
        (processed_dir / "dup.json").write_text("old")

        (inbox_dir / "dup.json").write_text(
            json.dumps({"source": "test", "event_type": "ping"})
        )

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["ingested"] == 1
        # Original processed file still there
        assert (processed_dir / "dup.json").exists()
        assert (processed_dir / "dup.json").read_text() == "old"
        # New file also in processed/ with a different name
        processed_files = list(processed_dir.glob("dup*.json"))
        assert len(processed_files) == 2

    def test_non_json_files_ignored(self, memory_store, inbox_dir):
        """Only *.json files are processed; others are left in place."""
        (inbox_dir / "readme.txt").write_text("ignore me")
        (inbox_dir / "event.json").write_text(
            json.dumps({"source": "test", "event_type": "ping"})
        )

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["ingested"] == 1
        assert (inbox_dir / "readme.txt").exists()  # untouched

    def test_mixed_valid_and_invalid(self, memory_store, inbox_dir):
        (inbox_dir / "good.json").write_text(
            json.dumps({"source": "s", "event_type": "e"})
        )
        (inbox_dir / "bad.json").write_text("nope")

        result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)

        assert result["ingested"] == 1
        assert result["failed"] == 1
        assert (inbox_dir / "processed" / "good.json").exists()
        assert (inbox_dir / "failed" / "bad.json").exists()


@pytest.mark.asyncio
class TestDispatchPendingEvents:
    async def test_no_pending_events(self, memory_store, agent_registry, document_store):
        """Returns zero counts when no pending events exist."""
        result = await dispatch_pending_events(memory_store, agent_registry, document_store)
        assert result == {"dispatched": 0, "failed": 0, "skipped": 0}

    async def test_event_dispatched_and_marked_processed(self, memory_store, agent_registry, document_store):
        """Pending event with matching rule is dispatched and marked processed."""
        _store_pending_event(memory_store)
        _create_dispatch_rule(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Handled"
            MockAgent.return_value = mock_instance

            with patch("agents.triage.classify_and_resolve", side_effect=lambda cfg, _: cfg):
                result = await dispatch_pending_events(memory_store, agent_registry, document_store)

        assert result["dispatched"] == 1
        assert result["failed"] == 0
        events = memory_store.list_webhook_events(status="processed")
        assert len(events) == 1

    async def test_no_matching_rules_skipped(self, memory_store, agent_registry, document_store):
        """Event with no matching rules is skipped (stays pending)."""
        _store_pending_event(memory_store, source="unknown", event_type="no.match")

        result = await dispatch_pending_events(memory_store, agent_registry, document_store)

        assert result["skipped"] == 1
        assert result["dispatched"] == 0
        events = memory_store.list_webhook_events(status="pending")
        assert len(events) == 1

    async def test_agent_failure_marks_event_failed(self, memory_store, agent_registry, document_store):
        """When all matched agents fail, event is marked failed."""
        _store_pending_event(memory_store)
        _create_dispatch_rule(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.side_effect = RuntimeError("Agent crashed")
            MockAgent.return_value = mock_instance

            with patch("agents.triage.classify_and_resolve", side_effect=lambda cfg, _: cfg):
                result = await dispatch_pending_events(memory_store, agent_registry, document_store)

        assert result["failed"] == 1
        events = memory_store.list_webhook_events(status="failed")
        assert len(events) == 1

    async def test_dispatch_exception_marks_event_failed(self, memory_store, agent_registry, document_store):
        """If dispatcher.dispatch() raises, event is marked failed and loop continues."""
        _store_pending_event(memory_store)
        _store_pending_event(memory_store, source="github", event_type="push")
        _create_dispatch_rule(memory_store, name="rule-1")

        call_count = 0

        async def mock_dispatch(event):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Dispatch exploded")
            return [{"status": "success", "rule_name": "rule-1", "agent_name": "test-agent",
                      "result_text": "ok", "duration_seconds": 0.1, "delivery_status": None}]

        with patch("webhook.dispatcher.EventDispatcher") as MockDispatcher:
            mock_disp = AsyncMock()
            mock_disp.dispatch.side_effect = mock_dispatch
            MockDispatcher.return_value = mock_disp

            result = await dispatch_pending_events(memory_store, agent_registry, document_store)

        assert result["failed"] >= 1
        assert call_count == 2  # Both events attempted

    async def test_double_dispatch_idempotent(self, memory_store, agent_registry, document_store):
        """Second call finds no pending events after first call processes them."""
        _store_pending_event(memory_store)
        _create_dispatch_rule(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            with patch("agents.triage.classify_and_resolve", side_effect=lambda cfg, _: cfg):
                result1 = await dispatch_pending_events(memory_store, agent_registry, document_store)
                result2 = await dispatch_pending_events(memory_store, agent_registry, document_store)

        assert result1["dispatched"] == 1
        assert result2 == {"dispatched": 0, "failed": 0, "skipped": 0}


@pytest.mark.asyncio
class TestIngestToDispatchE2E:
    async def test_full_pipeline_ingest_dispatch_process(self, memory_store, agent_registry, document_store, inbox_dir):
        """E2E: file drop -> ingest -> dispatch -> agent execution -> status update."""
        # Step 1: Drop a webhook event file
        event_file = inbox_dir / "ci-alert.json"
        event_file.write_text(json.dumps({
            "source": "github",
            "event_type": "alert.fired",
            "payload": {"alert_id": 42, "severity": "critical"},
        }))

        # Step 2: Ingest
        ingest_result = ingest_events(memory_store, inbox_dir, debounce_seconds=0)
        assert ingest_result["ingested"] == 1

        # Step 3: Create a matching event rule
        _create_dispatch_rule(memory_store)

        # Step 4: Dispatch
        with patch("agents.base.BaseExpertAgent") as MockAgent:
            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Alert handled: escalated to on-call"
            MockAgent.return_value = mock_instance

            with patch("agents.triage.classify_and_resolve", side_effect=lambda cfg, _: cfg):
                dispatch_result = await dispatch_pending_events(memory_store, agent_registry, document_store)

        # Step 5: Verify
        assert dispatch_result["dispatched"] == 1
        assert dispatch_result["failed"] == 0

        events = memory_store.list_webhook_events(status="processed")
        assert len(events) == 1
        assert events[0].source == "github"

        # No more pending events
        pending = memory_store.list_webhook_events(status="pending")
        assert len(pending) == 0
