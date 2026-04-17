"""Tests for email/Teams thread reconstruction."""

import pytest

from orchestration.thread_reconstruction import (
    EmailThread,
    TeamsThread,
    reconstruct_email_threads,
    reconstruct_teams_threads,
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


SAMPLE_TEAMS = [
    {
        "id": "1713292800000",
        "chatId": "19:abc@thread.v2",
        "chatType": "oneOnOne",
        "from": {"user": {"id": "shawn-id", "displayName": "Shawn F"}},
        "createdDateTime": "2026-04-17T10:00:00Z",
        "body": {"content": "<p>Can you own PST rollback?</p>", "contentType": "html"},
        "webUrl": "https://teams.microsoft.com/l/message/19:abc/1713292800000",
        "replyToId": None,
    },
    {
        "id": "1713292860000",
        "chatId": "19:abc@thread.v2",
        "chatType": "oneOnOne",
        "from": {"user": {"id": "jason-id", "displayName": "Jason R"}},
        "createdDateTime": "2026-04-17T10:01:00Z",
        "body": {"content": "<p>Yes. Ship tonight.</p>", "contentType": "html"},
        "webUrl": "https://teams.microsoft.com/l/message/19:abc/1713292860000",
        "replyToId": "1713292800000",
    },
    {
        "id": "1713293000000",
        "chatId": "19:xyz@thread.v2",
        "chatType": "group",
        "from": {"user": {"id": "theresa-id", "displayName": "Theresa O"}},
        "createdDateTime": "2026-04-17T09:00:00Z",
        "body": {"content": "<p>Weekly roll-up due Friday</p>", "contentType": "html"},
        "webUrl": "https://teams.microsoft.com/l/message/19:xyz/1713293000000",
        "replyToId": None,
    },
]


def test_reconstruct_teams_threads_groups_by_chat_id():
    threads = reconstruct_teams_threads(SAMPLE_TEAMS)
    assert len(threads) == 2


def test_teams_thread_exposes_latest_message_text():
    threads = reconstruct_teams_threads(SAMPLE_TEAMS)
    abc = next(t for t in threads if t.chat_id == "19:abc@thread.v2")
    assert "Ship tonight" in abc.latest_preview


def test_teams_thread_strips_html():
    threads = reconstruct_teams_threads(SAMPLE_TEAMS)
    abc = next(t for t in threads if t.chat_id == "19:abc@thread.v2")
    assert "<p>" not in abc.latest_preview
    assert "</p>" not in abc.latest_preview


def test_teams_thread_chat_type_preserved():
    threads = reconstruct_teams_threads(SAMPLE_TEAMS)
    abc = next(t for t in threads if t.chat_id == "19:abc@thread.v2")
    xyz = next(t for t in threads if t.chat_id == "19:xyz@thread.v2")
    assert abc.chat_type == "oneOnOne"
    assert xyz.chat_type == "group"
