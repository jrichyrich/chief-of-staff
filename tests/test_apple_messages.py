import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

import apple_messages.messages as messages_mod
from apple_messages.messages import MessageStore


def _apple_ns_from_unix(unix_ts: int) -> int:
    return int((unix_ts - 978307200) * 1_000_000_000)


def _make_chat_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            guid TEXT,
            text TEXT,
            date INTEGER,
            is_from_me INTEGER,
            handle_id INTEGER
        );
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_identifier TEXT
        );
        CREATE TABLE chat_message_join (
            chat_id INTEGER,
            message_id INTEGER
        );
        """
    )
    conn.commit()
    conn.close()


def _insert_message(
    db_path: Path,
    guid: str,
    text: str,
    date_ns: int,
    is_from_me: int,
    sender: str,
    chat_id: str,
) -> None:
    conn = sqlite3.connect(db_path)
    sender_row = conn.execute("INSERT INTO handle(id) VALUES(?)", (sender,))
    handle_id = sender_row.lastrowid
    msg_row = conn.execute(
        "INSERT INTO message(guid, text, date, is_from_me, handle_id) VALUES(?, ?, ?, ?, ?)",
        (guid, text, date_ns, is_from_me, handle_id),
    )
    message_id = msg_row.lastrowid
    chat_row = conn.execute("INSERT INTO chat(chat_identifier) VALUES(?)", (chat_id,))
    chat_rowid = chat_row.lastrowid
    conn.execute(
        "INSERT INTO chat_message_join(chat_id, message_id) VALUES(?, ?)",
        (chat_rowid, message_id),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def chat_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    now = int(time.time())
    _insert_message(
        db_path=db_path,
        guid="g1",
        text="Hello from teammate",
        date_ns=_apple_ns_from_unix(now - 60),
        is_from_me=0,
        sender="+15555550123",
        chat_id="chat-team",
    )
    _insert_message(
        db_path=db_path,
        guid="g2",
        text="I sent this",
        date_ns=_apple_ns_from_unix(now - 30),
        is_from_me=1,
        sender="+15555550999",
        chat_id="chat-self",
    )
    return db_path


def test_get_messages_filters_from_me(chat_db: Path, monkeypatch):
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    monkeypatch.setattr(messages_mod, "_DEFAULT_TIMEOUT", 1)
    monkeypatch.setattr(messages_mod, "_SEND_TIMEOUT", 1)
    monkeypatch.setattr(messages_mod, "platform", messages_mod.platform)

    store = MessageStore(db_path=chat_db, communicate_script=Path("/tmp/missing"))
    rows = store.get_messages(minutes=24 * 60, limit=50, include_from_me=False)
    assert len(rows) == 1
    assert rows[0]["guid"] == "g1"
    assert rows[0]["is_from_me"] is False


def test_search_messages_matches_text_and_sender(chat_db: Path, monkeypatch):
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    store = MessageStore(db_path=chat_db, communicate_script=Path("/tmp/missing"))

    by_text = store.search_messages("teammate", minutes=24 * 60, limit=10)
    assert len(by_text) == 1
    assert by_text[0]["guid"] == "g1"

    by_sender = store.search_messages("555550999", minutes=24 * 60, limit=10)
    assert len(by_sender) == 1
    assert by_sender[0]["guid"] == "g2"


def test_list_threads_includes_profile_observations(chat_db: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    store = MessageStore(
        db_path=chat_db,
        communicate_script=Path("/tmp/missing"),
        profile_db_path=tmp_path / "thread-profiles.db",
    )

    store.get_messages(minutes=24 * 60, limit=25, include_from_me=True)
    threads = store.list_threads(minutes=24 * 60, limit=10)
    assert len(threads) == 2

    chat_team = next(t for t in threads if t["chat_identifier"] == "chat-team")
    assert "+15555550123" in chat_team["participants"]
    assert chat_team["profile"]["preferred_handle"] == "+15555550123"
    assert "+15555550123" in chat_team["profile"]["members"]


def test_get_thread_messages_and_context(chat_db: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    store = MessageStore(
        db_path=chat_db,
        communicate_script=Path("/tmp/missing"),
        profile_db_path=tmp_path / "thread-profiles.db",
    )

    rows = store.get_thread_messages(chat_identifier="chat-team", minutes=24 * 60, limit=10)
    assert len(rows) == 1
    assert rows[0]["guid"] == "g1"

    context = store.get_thread_context(chat_identifier="chat-team", minutes=24 * 60, limit=10)
    assert context["chat_identifier"] == "chat-team"
    assert context["recent_stats"]["total_messages"] == 1
    assert context["suggested_reply_target"] == "+15555550123"


def test_get_thread_messages_requires_chat_identifier(chat_db: Path, monkeypatch):
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    store = MessageStore(db_path=chat_db, communicate_script=Path("/tmp/missing"))
    rows = store.get_thread_messages(chat_identifier="", minutes=10, limit=5)
    assert rows[0]["error"] == "chat_identifier is required"


def test_send_message_preview(chat_db: Path, monkeypatch):
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    store = MessageStore(db_path=chat_db, communicate_script=Path("/tmp/missing"))
    result = store.send_message(to="+15555550123", body="Hi", confirm_send=False)
    assert result["status"] == "preview"
    assert result["requires_confirmation"] is True


def test_send_message_confirm_calls_script(chat_db: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    script = tmp_path / "communicate.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    store = MessageStore(db_path=chat_db, communicate_script=script)

    def fake_run(cmd, capture_output, text, timeout, check):
        payload = {"channel": "imessage", "status": "sent", "to": "+15555550123"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(messages_mod.subprocess, "run", fake_run)
    result = store.send_message(to="+15555550123", body="Hello", confirm_send=True)
    assert result["status"] == "sent"
    assert result["channel"] == "imessage"


def test_send_message_confirm_with_chat_identifier(chat_db: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    script = tmp_path / "communicate.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    store = MessageStore(db_path=chat_db, communicate_script=script)

    seen = {}

    def fake_run(cmd, capture_output, text, timeout, check):
        seen["cmd"] = cmd
        payload = {"channel": "imessage", "status": "sent", "chat_identifier": "chat-team"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(messages_mod.subprocess, "run", fake_run)
    result = store.send_message(body="Thread reply", confirm_send=True, chat_identifier="chat-team")
    assert result["status"] == "sent"
    assert result["chat_identifier"] == "chat-team"
    assert "--chat-id" in seen["cmd"]
