# tests/test_e2e_integration.py
"""End-to-end integration tests exercising the full pipeline with real stores.

No mocks for internal logic — only real MemoryStore (backed by tmp_path SQLite),
real webhook ingestion, real channel adapters, real proactive engine, and real
scheduler dispatch.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from channels.adapter import adapt_event
from channels.models import InboundEvent
from memory.models import (
    ScheduledTask,
    SkillSuggestion,
    WebhookEvent,
)
from memory.store import MemoryStore
from proactive.engine import ProactiveSuggestionEngine
from scheduler.engine import SchedulerEngine, execute_handler
from skills.pattern_detector import PatternDetector
from webhook.ingest import ingest_events


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "e2e_test.db")
    yield store
    store.close()


@pytest.fixture
def inbox_dir(tmp_path):
    d = tmp_path / "webhook_inbox"
    d.mkdir()
    return d


def _write_webhook_json(inbox_dir: Path, filename: str, data: dict) -> Path:
    """Helper: write a JSON file into the inbox directory."""
    filepath = inbox_dir / filename
    filepath.write_text(json.dumps(data), encoding="utf-8")
    return filepath


# =============================================================================
# 1. Webhook Ingest → MemoryStore round-trip
# =============================================================================


class TestWebhookIngestToStore:
    """Write JSON to inbox, ingest, verify stored in memory_store."""

    def test_ingest_single_event(self, memory_store, inbox_dir):
        _write_webhook_json(inbox_dir, "event1.json", {
            "source": "github",
            "event_type": "push",
            "payload": {"ref": "refs/heads/main", "commits": [{"id": "abc123"}]},
        })

        result = ingest_events(memory_store, inbox_dir)

        assert result["ingested"] == 1
        assert result["failed"] == 0

        events = memory_store.list_webhook_events()
        assert len(events) == 1
        assert events[0].source == "github"
        assert events[0].event_type == "push"
        assert events[0].status == "pending"
        # Payload is JSON-serialized
        payload = json.loads(events[0].payload)
        assert payload["ref"] == "refs/heads/main"

    def test_ingest_multiple_events(self, memory_store, inbox_dir):
        for i in range(3):
            _write_webhook_json(inbox_dir, f"event_{i}.json", {
                "source": "jira",
                "event_type": f"issue_{i}",
                "payload": {"key": f"PROJ-{i}"},
            })

        result = ingest_events(memory_store, inbox_dir)
        assert result["ingested"] == 3

        events = memory_store.list_webhook_events()
        assert len(events) == 3

    def test_ingest_moves_to_processed(self, memory_store, inbox_dir):
        filepath = _write_webhook_json(inbox_dir, "good.json", {
            "source": "slack",
            "event_type": "message",
            "payload": "hello",
        })

        ingest_events(memory_store, inbox_dir)

        # Original file moved
        assert not filepath.exists()
        processed_dir = inbox_dir / "processed"
        assert (processed_dir / "good.json").exists()

    def test_ingest_malformed_goes_to_failed(self, memory_store, inbox_dir):
        bad = inbox_dir / "bad.json"
        bad.write_text("not valid json {{{{", encoding="utf-8")

        result = ingest_events(memory_store, inbox_dir)
        assert result["failed"] == 1
        assert result["ingested"] == 0
        assert (inbox_dir / "failed" / "bad.json").exists()

    def test_ingest_missing_fields_goes_to_failed(self, memory_store, inbox_dir):
        _write_webhook_json(inbox_dir, "incomplete.json", {
            "source": "github",
            # missing event_type
        })

        result = ingest_events(memory_store, inbox_dir)
        assert result["failed"] == 1

    def test_ingest_empty_inbox(self, memory_store, inbox_dir):
        result = ingest_events(memory_store, inbox_dir)
        assert result == {"ingested": 0, "failed": 0, "skipped": 0}


# =============================================================================
# 2. Webhook → Channel Adapter normalization
# =============================================================================


class TestWebhookChannelAdapter:
    """Ingest webhook, then normalize via channel adapter."""

    def test_webhook_adapter_normalizes(self, memory_store, inbox_dir):
        _write_webhook_json(inbox_dir, "hook.json", {
            "source": "pagerduty",
            "event_type": "incident.trigger",
            "payload": {"incident_id": "P123", "title": "Server down"},
        })
        ingest_events(memory_store, inbox_dir)

        events = memory_store.list_webhook_events()
        assert len(events) == 1
        event = events[0]

        # Convert the stored event to a dict for the adapter
        raw = {
            "id": event.id,
            "source": event.source,
            "event_type": event.event_type,
            "payload": event.payload,
            "status": event.status,
            "received_at": event.received_at,
        }
        inbound = adapt_event("webhook", raw)

        assert isinstance(inbound, InboundEvent)
        assert inbound.channel == "webhook"
        assert inbound.source == "pagerduty"
        assert inbound.event_type == "webhook_event"
        assert "incident_id" in inbound.content
        assert inbound.metadata["event_type"] == "incident.trigger"
        assert inbound.metadata["status"] == "pending"

    def test_imessage_adapter(self):
        raw = {
            "sender": "+15551234567",
            "text": "Hey, meeting at 3pm?",
            "is_from_me": False,
            "chat_identifier": "iMessage;-;+15551234567",
            "date_local": "2026-02-20T14:30:00",
            "guid": "msg-001",
        }
        inbound = adapt_event("imessage", raw)
        assert inbound.channel == "imessage"
        assert inbound.source == "+15551234567"
        assert inbound.content == "Hey, meeting at 3pm?"
        assert inbound.raw_id == "msg-001"

    def test_mail_adapter(self):
        raw = {
            "sender": "boss@example.com",
            "subject": "Q1 Review",
            "body": "Please review the attached.",
            "read": False,
            "flagged": True,
            "mailbox": "INBOX",
            "account": "work",
            "to": ["me@example.com"],
            "cc": [],
            "date": "2026-02-20T09:00:00",
            "message_id": "mail-abc",
        }
        inbound = adapt_event("mail", raw)
        assert inbound.channel == "mail"
        assert inbound.source == "boss@example.com"
        assert inbound.content == "Please review the attached."
        assert inbound.metadata["subject"] == "Q1 Review"

    def test_unknown_channel_raises(self):
        with pytest.raises(ValueError, match="Unknown channel"):
            adapt_event("telegram", {"text": "hi"})


# =============================================================================
# 3. Proactive Engine detects unprocessed webhook suggestions
# =============================================================================


class TestProactiveWebhookDetection:
    """Ingest webhook events, then verify proactive engine surfaces them."""

    def test_engine_detects_pending_webhooks(self, memory_store, inbox_dir):
        _write_webhook_json(inbox_dir, "alert.json", {
            "source": "datadog",
            "event_type": "monitor.alert",
            "payload": {"monitor_id": 42, "status": "Alert"},
        })
        ingest_events(memory_store, inbox_dir)

        engine = ProactiveSuggestionEngine(memory_store)
        suggestions = engine.generate_suggestions()

        webhook_suggestions = [s for s in suggestions if s.category == "webhook"]
        assert len(webhook_suggestions) >= 1
        assert "datadog" in webhook_suggestions[0].title
        assert webhook_suggestions[0].action == "list_webhook_events"

    def test_engine_no_suggestions_when_empty(self, memory_store):
        engine = ProactiveSuggestionEngine(memory_store)
        suggestions = engine.generate_suggestions()
        # With no data, there should be no suggestions
        assert len(suggestions) == 0

    def test_engine_check_all_returns_dict(self, memory_store, inbox_dir):
        _write_webhook_json(inbox_dir, "event.json", {
            "source": "stripe",
            "event_type": "payment.succeeded",
            "payload": {"amount": 1000},
        })
        ingest_events(memory_store, inbox_dir)

        engine = ProactiveSuggestionEngine(memory_store)
        result = engine.check_all(push_enabled=False)

        assert "suggestions" in result
        assert len(result["suggestions"]) >= 1

    def test_engine_detects_skill_suggestions(self, memory_store):
        memory_store.store_skill_suggestion(SkillSuggestion(
            description="Frequently searches calendar for standup",
            suggested_name="standup_finder",
            confidence=0.85,
        ))

        engine = ProactiveSuggestionEngine(memory_store)
        suggestions = engine.generate_suggestions()

        skill_suggestions = [s for s in suggestions if s.category == "skill"]
        assert len(skill_suggestions) >= 1
        assert "standup_finder" in skill_suggestions[0].title


# =============================================================================
# 4. Scheduler dispatches webhook_poll handler
# =============================================================================


class TestSchedulerWebhookPoll:
    """Scheduler creates a webhook_poll task, executes it, and verifies ingestion."""

    def test_webhook_poll_via_scheduler(self, memory_store, inbox_dir, monkeypatch):
        # Drop a webhook JSON into the inbox
        _write_webhook_json(inbox_dir, "scheduled.json", {
            "source": "circleci",
            "event_type": "build.complete",
            "payload": {"build_num": 999, "status": "success"},
        })

        # Monkeypatch WEBHOOK_INBOX_DIR so the handler finds our inbox
        monkeypatch.setattr("config.WEBHOOK_INBOX_DIR", str(inbox_dir))

        # Create a scheduled task for webhook_poll
        task = ScheduledTask(
            name="webhook-poll-e2e",
            schedule_type="interval",
            schedule_config=json.dumps({"minutes": 15}),
            handler_type="webhook_poll",
            enabled=True,
            next_run_at="2026-02-20T09:00:00",
        )
        memory_store.store_scheduled_task(task)

        # Run the scheduler
        scheduler = SchedulerEngine(memory_store)
        now = datetime(2026, 2, 20, 10, 0, 0)
        results = scheduler.evaluate_due_tasks(now=now)

        assert len(results) == 1
        assert results[0]["status"] == "executed"
        result_data = json.loads(results[0]["result"])
        assert result_data["handler"] == "webhook_poll"
        assert result_data["ingested"] == 1

        # Verify the event actually landed in the store
        events = memory_store.list_webhook_events()
        assert len(events) == 1
        assert events[0].source == "circleci"
        assert events[0].event_type == "build.complete"

    def test_webhook_poll_empty_inbox(self, memory_store, inbox_dir, monkeypatch):
        monkeypatch.setattr("config.WEBHOOK_INBOX_DIR", str(inbox_dir))

        task = ScheduledTask(
            name="webhook-poll-empty",
            schedule_type="interval",
            schedule_config=json.dumps({"minutes": 15}),
            handler_type="webhook_poll",
            enabled=True,
            next_run_at="2026-02-20T09:00:00",
        )
        memory_store.store_scheduled_task(task)

        scheduler = SchedulerEngine(memory_store)
        results = scheduler.evaluate_due_tasks(now=datetime(2026, 2, 20, 10, 0, 0))

        assert len(results) == 1
        result_data = json.loads(results[0]["result"])
        assert result_data["status"] == "ok"
        assert result_data["ingested"] == 0


# =============================================================================
# 5. Scheduler dispatches skill_analysis handler
# =============================================================================


class TestSchedulerSkillAnalysis:
    """Scheduler creates a skill_analysis task, executes it, and verifies pattern detection."""

    def test_skill_analysis_via_scheduler(self, memory_store):
        # Seed enough usage data to trigger pattern detection
        for _ in range(10):
            memory_store.record_skill_usage("query_memory", "weekly standup notes")

        task = ScheduledTask(
            name="skill-analysis-e2e",
            schedule_type="interval",
            schedule_config=json.dumps({"hours": 24}),
            handler_type="skill_analysis",
            enabled=True,
            next_run_at="2026-02-20T06:00:00",
        )
        memory_store.store_scheduled_task(task)

        scheduler = SchedulerEngine(memory_store)
        now = datetime(2026, 2, 20, 10, 0, 0)
        results = scheduler.evaluate_due_tasks(now=now)

        assert len(results) == 1
        assert results[0]["status"] == "executed"
        result_data = json.loads(results[0]["result"])
        assert result_data["handler"] == "skill_analysis"
        assert result_data["patterns_found"] >= 1

        # Verify suggestions were stored in the DB
        suggestions = memory_store.list_skill_suggestions(status="pending")
        assert len(suggestions) >= 1
        assert any("query_memory" in s.description for s in suggestions)

    def test_skill_analysis_no_data(self, memory_store):
        task = ScheduledTask(
            name="skill-analysis-empty",
            schedule_type="interval",
            schedule_config=json.dumps({"hours": 24}),
            handler_type="skill_analysis",
            enabled=True,
            next_run_at="2026-02-20T06:00:00",
        )
        memory_store.store_scheduled_task(task)

        scheduler = SchedulerEngine(memory_store)
        results = scheduler.evaluate_due_tasks(now=datetime(2026, 2, 20, 10, 0, 0))

        assert len(results) == 1
        result_data = json.loads(results[0]["result"])
        assert result_data["patterns_found"] == 0


# =============================================================================
# 6. Full pipeline: Ingest → Store → Adapt → Proactive → Scheduler
# =============================================================================


class TestFullPipeline:
    """Complete end-to-end: webhook JSON → ingest → store → adapt → proactive detect → scheduler dispatch."""

    def test_full_webhook_lifecycle(self, memory_store, inbox_dir, monkeypatch):
        monkeypatch.setattr("config.WEBHOOK_INBOX_DIR", str(inbox_dir))

        # Step 1: Write webhook JSON to inbox
        _write_webhook_json(inbox_dir, "lifecycle.json", {
            "source": "github",
            "event_type": "pull_request.merged",
            "payload": {"pr_number": 42, "title": "Add feature X"},
        })

        # Step 2: Scheduler runs webhook_poll handler → ingests
        poll_task = ScheduledTask(
            name="poll-lifecycle",
            schedule_type="interval",
            schedule_config=json.dumps({"minutes": 15}),
            handler_type="webhook_poll",
            enabled=True,
            next_run_at="2026-02-20T09:00:00",
        )
        memory_store.store_scheduled_task(poll_task)

        scheduler = SchedulerEngine(memory_store)
        now = datetime(2026, 2, 20, 10, 0, 0)
        poll_results = scheduler.evaluate_due_tasks(now=now)
        assert poll_results[0]["status"] == "executed"

        # Step 3: Verify stored event
        events = memory_store.list_webhook_events()
        assert len(events) == 1
        event = events[0]
        assert event.source == "github"
        assert event.status == "pending"

        # Step 4: Channel adapter normalizes
        raw = {
            "id": event.id,
            "source": event.source,
            "event_type": event.event_type,
            "payload": event.payload,
            "status": event.status,
            "received_at": event.received_at,
        }
        inbound = adapt_event("webhook", raw)
        assert inbound.channel == "webhook"
        assert "pr_number" in inbound.content

        # Step 5: Proactive engine detects unprocessed webhook
        proactive = ProactiveSuggestionEngine(memory_store)
        suggestions = proactive.generate_suggestions()
        webhook_suggestions = [s for s in suggestions if s.category == "webhook"]
        assert len(webhook_suggestions) >= 1

    def test_full_skill_detection_pipeline(self, memory_store):
        """Seed usage → pattern detection → suggestion stored → proactive surfaces it."""

        # Step 1: Record repeated tool usage
        for _ in range(10):
            memory_store.record_skill_usage("search_mail", "invoice from acme")
        for _ in range(10):
            memory_store.record_skill_usage("search_mail", "invoice from globex")

        # Step 2: Run pattern detection directly
        detector = PatternDetector(memory_store)
        patterns = detector.detect_patterns()
        assert len(patterns) >= 1
        assert any("search_mail" in p["tool_name"] for p in patterns)

        # Step 3: Store suggestions (mimicking what skill_analysis handler does)
        for pattern in patterns:
            suggestion = SkillSuggestion(
                description=pattern["description"],
                suggested_name=pattern["tool_name"].replace(" ", "_") + "_specialist",
                suggested_capabilities=pattern["tool_name"],
                confidence=pattern["confidence"],
            )
            memory_store.store_skill_suggestion(suggestion)

        # Step 4: Proactive engine surfaces the skill suggestion
        proactive = ProactiveSuggestionEngine(memory_store)
        suggestions = proactive.generate_suggestions()
        skill_suggestions = [s for s in suggestions if s.category == "skill"]
        assert len(skill_suggestions) >= 1

    def test_multiple_handler_types_in_one_run(self, memory_store, inbox_dir, monkeypatch):
        """Scheduler evaluates multiple due tasks of different handler types."""
        monkeypatch.setattr("config.WEBHOOK_INBOX_DIR", str(inbox_dir))

        # Seed some data
        _write_webhook_json(inbox_dir, "multi.json", {
            "source": "jenkins",
            "event_type": "build.finished",
            "payload": {"job": "deploy"},
        })
        for _ in range(10):
            memory_store.record_skill_usage("get_calendar_events", "team meeting")

        # Create two due tasks
        memory_store.store_scheduled_task(ScheduledTask(
            name="poll-multi",
            schedule_type="interval",
            schedule_config=json.dumps({"minutes": 15}),
            handler_type="webhook_poll",
            enabled=True,
            next_run_at="2026-02-20T09:00:00",
        ))
        memory_store.store_scheduled_task(ScheduledTask(
            name="skill-multi",
            schedule_type="interval",
            schedule_config=json.dumps({"hours": 24}),
            handler_type="skill_analysis",
            enabled=True,
            next_run_at="2026-02-20T06:00:00",
        ))

        scheduler = SchedulerEngine(memory_store)
        now = datetime(2026, 2, 20, 10, 0, 0)
        results = scheduler.evaluate_due_tasks(now=now)

        assert len(results) == 2
        handlers = {r["handler_type"] for r in results}
        assert handlers == {"webhook_poll", "skill_analysis"}

        # Both should have executed
        for r in results:
            assert r["status"] == "executed"

        # Verify data from both handlers landed in store
        events = memory_store.list_webhook_events()
        assert len(events) >= 1
        suggestions = memory_store.list_skill_suggestions(status="pending")
        assert len(suggestions) >= 1
