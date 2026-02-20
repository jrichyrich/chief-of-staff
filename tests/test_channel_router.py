"""Tests for channels/router.py and channels/consumers.py."""

import threading

import pytest

from channels.consumers import log_event_handler, priority_filter
from channels.models import InboundEvent
from channels.router import EventRouter


def _make_event(**overrides) -> InboundEvent:
    """Helper to create an InboundEvent with sensible defaults."""
    defaults = {
        "channel": "imessage",
        "source": "+15551234567",
        "event_type": "message",
        "content": "Hello world",
        "metadata": {},
        "received_at": "2026-02-20T10:00:00",
        "raw_id": "test-001",
    }
    defaults.update(overrides)
    return InboundEvent(**defaults)


# --- EventRouter ---


class TestEventRouter:
    def test_register_and_route_single_handler(self):
        router = EventRouter()
        results_seen = []

        def handler(event: InboundEvent) -> dict:
            results_seen.append(event.raw_id)
            return {"handled": True}

        router.register_handler("message", handler)
        results = router.route(_make_event())
        assert len(results) == 1
        assert results[0] == {"handled": True}
        assert results_seen == ["test-001"]

    def test_multiple_handlers_for_same_event_type(self):
        router = EventRouter()

        def handler_a(event: InboundEvent) -> dict:
            return {"handler": "a"}

        def handler_b(event: InboundEvent) -> dict:
            return {"handler": "b"}

        router.register_handler("message", handler_a)
        router.register_handler("message", handler_b)
        results = router.route(_make_event())
        assert len(results) == 2
        assert results[0] == {"handler": "a"}
        assert results[1] == {"handler": "b"}

    def test_no_handlers_returns_empty(self):
        router = EventRouter()
        results = router.route(_make_event(event_type="email"))
        assert results == []

    def test_handler_for_different_event_type_not_called(self):
        router = EventRouter()
        called = []

        def handler(event: InboundEvent) -> dict:
            called.append(True)
            return {}

        router.register_handler("email", handler)
        results = router.route(_make_event(event_type="message"))
        assert results == []
        assert called == []

    def test_handler_exception_is_caught(self):
        router = EventRouter()

        def bad_handler(event: InboundEvent) -> dict:
            raise RuntimeError("boom")

        def good_handler(event: InboundEvent) -> dict:
            return {"ok": True}

        router.register_handler("message", bad_handler)
        router.register_handler("message", good_handler)
        results = router.route(_make_event())
        assert len(results) == 2
        assert "error" in results[0]
        assert "boom" in results[0]["error"]
        assert results[1] == {"ok": True}

    def test_thread_safety(self):
        """Concurrent registration and routing should not crash."""
        router = EventRouter()
        errors = []

        def register_handlers():
            try:
                for i in range(50):
                    router.register_handler("message", lambda e, i=i: {"i": i})
            except Exception as exc:
                errors.append(exc)

        def route_events():
            try:
                for _ in range(50):
                    router.route(_make_event())
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=register_handlers),
            threading.Thread(target=route_events),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []


# --- Built-in consumers ---


class TestLogEventHandler:
    def test_returns_summary(self):
        event = _make_event(content="Test message body here")
        result = log_event_handler(event)
        assert result["action"] == "logged"
        assert result["channel"] == "imessage"
        assert result["source"] == "+15551234567"
        assert result["raw_id"] == "test-001"
        assert "Test message body" in result["content_preview"]

    def test_truncates_long_content(self):
        event = _make_event(content="x" * 500)
        result = log_event_handler(event)
        assert len(result["content_preview"]) == 120

    def test_handles_empty_content(self):
        event = _make_event(content="")
        result = log_event_handler(event)
        assert result["content_preview"] == ""


class TestPriorityFilter:
    def test_detects_urgent_keyword(self):
        event = _make_event(content="This is URGENT please respond")
        result = priority_filter(event)
        assert result["is_priority"] is True
        assert "urgent" in result["matched_keywords"]

    def test_detects_multiple_keywords(self):
        event = _make_event(content="CRITICAL emergency: action required ASAP")
        result = priority_filter(event)
        assert result["is_priority"] is True
        assert set(result["matched_keywords"]) == {"critical", "emergency", "asap"}

    def test_no_keywords_not_priority(self):
        event = _make_event(content="Just a normal message")
        result = priority_filter(event)
        assert result["is_priority"] is False
        assert result["matched_keywords"] == []

    def test_empty_content_not_priority(self):
        event = _make_event(content="")
        result = priority_filter(event)
        assert result["is_priority"] is False

    def test_blocking_keyword(self):
        event = _make_event(content="This issue is blocking the release")
        result = priority_filter(event)
        assert result["is_priority"] is True
        assert "blocking" in result["matched_keywords"]


# --- Router + consumers integration ---


class TestRouterWithConsumers:
    def test_wired_together(self):
        router = EventRouter()
        router.register_handler("message", log_event_handler)
        router.register_handler("message", priority_filter)

        event = _make_event(content="This is urgent!")
        results = router.route(event)
        assert len(results) == 2
        assert results[0]["action"] == "logged"
        assert results[1]["action"] == "priority_check"
        assert results[1]["is_priority"] is True
