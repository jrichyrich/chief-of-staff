"""Tests for email/Teams thread reconstruction."""

import pytest

from orchestration.thread_reconstruction import (
    EmailThread,
    reconstruct_email_threads,
)


SAMPLE_EMAILS = [
    {
        "id": "AAMkAD-1",
        "conversationId": "conv-abc",
        "subject": "PST incident — next steps",
        "from": {"emailAddress": {"address": "shawn@chg.com", "name": "Shawn F"}},
        "receivedDateTime": "2026-04-17T10:00:00Z",
        "bodyPreview": "We need a decision on the rollback window.",
        "webLink": "https://outlook.office.com/mail/id/AAMkAD-1",
    },
    {
        "id": "AAMkAD-2",
        "conversationId": "conv-abc",
        "subject": "RE: PST incident — next steps",
        "from": {"emailAddress": {"address": "jason@chg.com", "name": "Jason R"}},
        "receivedDateTime": "2026-04-17T10:30:00Z",
        "bodyPreview": "Going with option B. Ship tonight.",
        "webLink": "https://outlook.office.com/mail/id/AAMkAD-2",
    },
    {
        "id": "AAMkAD-3",
        "conversationId": "conv-xyz",
        "subject": "Weekly roll-up",
        "from": {"emailAddress": {"address": "theresa@chg.com", "name": "Theresa O"}},
        "receivedDateTime": "2026-04-17T09:00:00Z",
        "bodyPreview": "Send the CIO weekly by Friday.",
        "webLink": "https://outlook.office.com/mail/id/AAMkAD-3",
    },
]


def test_reconstruct_email_threads_groups_by_conversation_id():
    threads = reconstruct_email_threads(SAMPLE_EMAILS)
    assert len(threads) == 2
    by_id = {t.conversation_id: t for t in threads}
    assert len(by_id["conv-abc"].messages) == 2
    assert len(by_id["conv-xyz"].messages) == 1


def test_thread_orders_messages_by_received_date():
    threads = reconstruct_email_threads(SAMPLE_EMAILS)
    abc = next(t for t in threads if t.conversation_id == "conv-abc")
    assert abc.messages[0]["id"] == "AAMkAD-1"
    assert abc.messages[1]["id"] == "AAMkAD-2"


def test_thread_latest_message_properties():
    threads = reconstruct_email_threads(SAMPLE_EMAILS)
    abc = next(t for t in threads if t.conversation_id == "conv-abc")
    assert abc.latest_received == "2026-04-17T10:30:00Z"
    assert abc.latest_sender_email == "jason@chg.com"
    assert "option B" in abc.latest_preview


def test_thread_participants_unique():
    threads = reconstruct_email_threads(SAMPLE_EMAILS)
    abc = next(t for t in threads if t.conversation_id == "conv-abc")
    emails = {p["email"] for p in abc.participants}
    assert emails == {"shawn@chg.com", "jason@chg.com"}


def test_empty_input_returns_empty_list():
    assert reconstruct_email_threads([]) == []


def test_missing_conversation_id_falls_back_to_subject():
    """Some tenants don't return conversationId; fall back to normalized subject."""
    items = [
        {
            "id": "1",
            "subject": "RE: Foo",
            "from": {"emailAddress": {"address": "a@x.com"}},
            "receivedDateTime": "2026-04-17T10:00:00Z",
            "bodyPreview": "",
        },
        {
            "id": "2",
            "subject": "FW: Foo",
            "from": {"emailAddress": {"address": "b@x.com"}},
            "receivedDateTime": "2026-04-17T11:00:00Z",
            "bodyPreview": "",
        },
    ]
    threads = reconstruct_email_threads(items)
    assert len(threads) == 1
    assert len(threads[0].messages) == 2
