"""Tests for channels/adapter.py — adapter normalization."""

import pytest

from channels.adapter import (
    IMessageAdapter,
    MailAdapter,
    WebhookAdapter,
    adapt_event,
)
from channels.models import InboundEvent


# --- IMessageAdapter ---


class TestIMessageAdapter:
    def test_normalizes_basic_message(self):
        raw = {
            "guid": "msg-001",
            "text": "Hello there!",
            "date_local": "2026-02-20T10:00:00",
            "is_from_me": False,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        }
        event = IMessageAdapter().normalize(raw)
        assert isinstance(event, InboundEvent)
        assert event.channel == "imessage"
        assert event.source == "+15551234567"
        assert event.event_type == "message"
        assert event.content == "Hello there!"
        assert event.received_at == "2026-02-20T10:00:00"
        assert event.raw_id == "msg-001"
        assert event.metadata["is_from_me"] is False
        assert event.metadata["chat_identifier"] == "+15551234567"

    def test_normalizes_from_me_message(self):
        raw = {
            "guid": "msg-002",
            "text": "Reply",
            "date_local": "2026-02-20T10:01:00",
            "is_from_me": True,
            "sender": "",
            "chat_identifier": "+15551234567",
        }
        event = IMessageAdapter().normalize(raw)
        assert event.metadata["is_from_me"] is True
        assert event.source == ""

    def test_handles_missing_fields(self):
        event = IMessageAdapter().normalize({})
        assert event.channel == "imessage"
        assert event.source == ""
        assert event.content == ""
        assert event.raw_id == ""


# --- MailAdapter ---


class TestMailAdapter:
    def test_normalizes_header_only_message(self):
        raw = {
            "message_id": "mail-abc-123",
            "subject": "Quarterly Report",
            "sender": "alice@example.com",
            "date": "2026-02-20 09:30:00",
            "read": False,
            "flagged": True,
            "mailbox": "INBOX",
            "account": "work",
        }
        event = MailAdapter().normalize(raw)
        assert event.channel == "mail"
        assert event.source == "alice@example.com"
        assert event.event_type == "email"
        assert event.content == "Quarterly Report"  # falls back to subject
        assert event.received_at == "2026-02-20 09:30:00"
        assert event.raw_id == "mail-abc-123"
        assert event.metadata["subject"] == "Quarterly Report"
        assert event.metadata["read"] is False
        assert event.metadata["flagged"] is True

    def test_normalizes_full_message_with_body(self):
        raw = {
            "message_id": "mail-xyz-789",
            "subject": "Hello",
            "sender": "bob@example.com",
            "date": "2026-02-20 08:00:00",
            "read": True,
            "flagged": False,
            "body": "Full email body text here.",
            "to": ["me@example.com"],
            "cc": ["cc@example.com"],
        }
        event = MailAdapter().normalize(raw)
        assert event.content == "Full email body text here."
        assert event.metadata["to"] == ["me@example.com"]
        assert event.metadata["cc"] == ["cc@example.com"]

    def test_handles_missing_fields(self):
        event = MailAdapter().normalize({})
        assert event.channel == "mail"
        assert event.source == ""
        assert event.content == ""


# --- WebhookAdapter ---


class TestWebhookAdapter:
    def test_normalizes_webhook_event(self):
        raw = {
            "id": 42,
            "source": "github",
            "event_type": "push",
            "payload": '{"ref": "refs/heads/main"}',
            "status": "pending",
            "received_at": "2026-02-20T12:00:00",
        }
        event = WebhookAdapter().normalize(raw)
        assert event.channel == "webhook"
        assert event.source == "github"
        assert event.event_type == "webhook_event"
        assert event.content == '{"ref": "refs/heads/main"}'
        assert event.received_at == "2026-02-20T12:00:00"
        assert event.raw_id == "42"
        assert event.metadata["status"] == "pending"
        assert event.metadata["event_type"] == "push"

    def test_handles_missing_fields(self):
        event = WebhookAdapter().normalize({})
        assert event.channel == "webhook"
        assert event.source == ""
        assert event.content == ""


# --- adapt_event factory ---


class TestAdaptEvent:
    def test_dispatches_to_imessage_adapter(self):
        raw = {"guid": "g1", "text": "hi", "sender": "+1555", "date_local": "", "is_from_me": False, "chat_identifier": ""}
        event = adapt_event("imessage", raw)
        assert event.channel == "imessage"
        assert event.content == "hi"

    def test_dispatches_to_mail_adapter(self):
        raw = {"message_id": "m1", "subject": "Test", "sender": "a@b.com", "date": ""}
        event = adapt_event("mail", raw)
        assert event.channel == "mail"

    def test_dispatches_to_webhook_adapter(self):
        raw = {"id": 1, "source": "s", "event_type": "e", "payload": "p", "received_at": ""}
        event = adapt_event("webhook", raw)
        assert event.channel == "webhook"

    def test_raises_for_unknown_channel(self):
        with pytest.raises(ValueError, match="Unknown channel"):
            adapt_event("slack", {})
