import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

import apple_messages.messages as messages_mod
from apple_messages.messages import MessageStore, decode_attributed_body


def _apple_ns_from_unix(unix_ts: int) -> int:
    return int((unix_ts - 978307200) * 1_000_000_000)


def _make_attributed_body(text: str) -> bytes:
    """Build a minimal attributedBody typedstream blob for testing."""
    text_bytes = text.encode("utf-8")
    length = len(text_bytes)
    header = b"\x04\x0bstreamtyped\x81\xe8\x03"
    ns_string = b"NSString\x01\x94\x84\x01\x2b"
    if length <= 0x7E:
        length_bytes = bytes([length])
    else:
        length_bytes = b"\x81" + length.to_bytes(2, "little")
    return header + ns_string + length_bytes + text_bytes


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
            attributedBody BLOB,
            date INTEGER,
            is_from_me INTEGER,
            handle_id INTEGER
        );
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_identifier TEXT,
            guid TEXT
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
    text: str | None,
    date_ns: int,
    is_from_me: int,
    sender: str,
    chat_id: str,
    attributed_body: bytes | None = None,
    chat_guid: str | None = None,
) -> None:
    conn = sqlite3.connect(db_path)
    sender_row = conn.execute("INSERT INTO handle(id) VALUES(?)", (sender,))
    handle_id = sender_row.lastrowid
    msg_row = conn.execute(
        "INSERT INTO message(guid, text, attributedBody, date, is_from_me, handle_id) VALUES(?, ?, ?, ?, ?, ?)",
        (guid, text, attributed_body, date_ns, is_from_me, handle_id),
    )
    message_id = msg_row.lastrowid
    chat_row = conn.execute(
        "INSERT INTO chat(chat_identifier, guid) VALUES(?, ?)",
        (chat_id, chat_guid),
    )
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
        chat_guid="iMessage;+;chat-team",
    )
    _insert_message(
        db_path=db_path,
        guid="g2",
        text="I sent this",
        date_ns=_apple_ns_from_unix(now - 30),
        is_from_me=1,
        sender="+15555550999",
        chat_id="chat-self",
        chat_guid="iMessage;+;chat-self",
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


def test_message_with_null_text_returns_empty(tmp_path: Path, monkeypatch):
    """When text is NULL and attributedBody is NULL, text should be empty string."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    now = int(time.time())
    _insert_message(
        db_path=db_path,
        guid="g-null-text",
        text=None,
        date_ns=_apple_ns_from_unix(now - 10),
        is_from_me=0,
        sender="+15555550200",
        chat_id="chat-null",
        attributed_body=None,
    )
    store = MessageStore(db_path=db_path, communicate_script=Path("/tmp/missing"))
    rows = store.get_messages(minutes=24 * 60, limit=50)
    assert len(rows) == 1
    assert rows[0]["guid"] == "g-null-text"
    assert rows[0]["text"] == ""


def test_send_message_confirm_with_chat_identifier(chat_db: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    script = tmp_path / "communicate.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    store = MessageStore(db_path=chat_db, communicate_script=script)

    seen = {}

    def fake_cleanup(cmd, timeout, **kwargs):
        seen["cmd"] = cmd
        payload = {"channel": "imessage", "status": "sent", "chat_identifier": "chat-team"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(messages_mod, "_run_with_cleanup", fake_cleanup)
    result = store.send_message(body="Thread reply", confirm_send=True, chat_identifier="chat-team")
    assert result["status"] == "sent"
    assert result["chat_identifier"] == "chat-team"
    assert "--chat-id" in seen["cmd"]


# ---------------------------------------------------------------------------
# Phase 2: attributedBody decoding tests
# ---------------------------------------------------------------------------


def test_message_with_attributed_body_fallback(tmp_path: Path, monkeypatch):
    """NULL text + valid attributedBody -> decoded text returned."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    now = int(time.time())
    blob = _make_attributed_body("Hey from attributedBody")
    _insert_message(
        db_path=db_path,
        guid="g-ab-fallback",
        text=None,
        date_ns=_apple_ns_from_unix(now - 10),
        is_from_me=0,
        sender="+15555550300",
        chat_id="chat-ab",
        attributed_body=blob,
    )
    store = MessageStore(db_path=db_path, communicate_script=Path("/tmp/missing"))
    rows = store.get_messages(minutes=24 * 60, limit=50)
    assert len(rows) == 1
    assert rows[0]["guid"] == "g-ab-fallback"
    assert rows[0]["text"] == "Hey from attributedBody"


def test_message_text_preferred_over_attributed_body(tmp_path: Path, monkeypatch):
    """Non-empty text + attributedBody -> text field used, attributedBody ignored."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    now = int(time.time())
    blob = _make_attributed_body("from attributedBody")
    _insert_message(
        db_path=db_path,
        guid="g-text-wins",
        text="from text column",
        date_ns=_apple_ns_from_unix(now - 10),
        is_from_me=0,
        sender="+15555550301",
        chat_id="chat-textpref",
        attributed_body=blob,
    )
    store = MessageStore(db_path=db_path, communicate_script=Path("/tmp/missing"))
    rows = store.get_messages(minutes=24 * 60, limit=50)
    assert len(rows) == 1
    assert rows[0]["text"] == "from text column"


def test_message_corrupt_attributed_body(tmp_path: Path, monkeypatch):
    """NULL text + corrupt attributedBody -> graceful fallback to empty string."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    now = int(time.time())
    _insert_message(
        db_path=db_path,
        guid="g-corrupt",
        text=None,
        date_ns=_apple_ns_from_unix(now - 10),
        is_from_me=0,
        sender="+15555550302",
        chat_id="chat-corrupt",
        attributed_body=b"\x00\x01\x02\x03garbage",
    )
    store = MessageStore(db_path=db_path, communicate_script=Path("/tmp/missing"))
    rows = store.get_messages(minutes=24 * 60, limit=50)
    assert len(rows) == 1
    assert rows[0]["guid"] == "g-corrupt"
    assert rows[0]["text"] == ""


def test_message_attributed_body_emoji(tmp_path: Path, monkeypatch):
    """Emoji and unicode content in attributedBody decodes correctly."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    now = int(time.time())
    emoji_text = "Hello \U0001f600 world \u2764"
    blob = _make_attributed_body(emoji_text)
    _insert_message(
        db_path=db_path,
        guid="g-emoji",
        text=None,
        date_ns=_apple_ns_from_unix(now - 10),
        is_from_me=0,
        sender="+15555550303",
        chat_id="chat-emoji",
        attributed_body=blob,
    )
    store = MessageStore(db_path=db_path, communicate_script=Path("/tmp/missing"))
    rows = store.get_messages(minutes=24 * 60, limit=50)
    assert len(rows) == 1
    assert rows[0]["text"] == emoji_text


def test_search_finds_attributed_body_content(tmp_path: Path, monkeypatch):
    """search_messages matches text decoded from attributedBody."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    now = int(time.time())
    blob = _make_attributed_body("secret rendezvous plan")
    _insert_message(
        db_path=db_path,
        guid="g-search-ab",
        text=None,
        date_ns=_apple_ns_from_unix(now - 10),
        is_from_me=0,
        sender="+15555550304",
        chat_id="chat-search",
        attributed_body=blob,
    )
    # Also insert a normal text message that should NOT match
    _insert_message(
        db_path=db_path,
        guid="g-search-normal",
        text="nothing relevant here",
        date_ns=_apple_ns_from_unix(now - 20),
        is_from_me=0,
        sender="+15555550305",
        chat_id="chat-search2",
    )
    store = MessageStore(db_path=db_path, communicate_script=Path("/tmp/missing"))
    results = store.search_messages("rendezvous", minutes=24 * 60, limit=50)
    assert len(results) == 1
    assert results[0]["guid"] == "g-search-ab"
    assert "rendezvous" in results[0]["text"]


def test_search_excludes_non_matching_attributed_body(tmp_path: Path, monkeypatch):
    """search_messages post-filter excludes attributedBody messages that don't match the query."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    now = int(time.time())
    blob = _make_attributed_body("completely unrelated content")
    _insert_message(
        db_path=db_path,
        guid="g-no-match",
        text=None,
        date_ns=_apple_ns_from_unix(now - 10),
        is_from_me=0,
        sender="+15555550306",
        chat_id="chat-nomatch",
        attributed_body=blob,
    )
    store = MessageStore(db_path=db_path, communicate_script=Path("/tmp/missing"))
    results = store.search_messages("xyznonexistent", minutes=24 * 60, limit=50)
    assert len(results) == 0


def test_decode_attributed_body_directly():
    """Unit tests for decode_attributed_body with various inputs."""
    # Valid blob
    blob = _make_attributed_body("Hello world")
    assert decode_attributed_body(blob) == "Hello world"

    # None input
    assert decode_attributed_body(None) is None

    # Empty bytes
    assert decode_attributed_body(b"") is None

    # Bytes without NSString marker
    assert decode_attributed_body(b"\x04\x0bstreamtyped\x81\xe8\x03no-marker-here") is None

    # Truncated blob (has NSString but not enough bytes after preamble)
    truncated = b"\x04\x0bstreamtyped\x81\xe8\x03NSString\x01\x94\x84\x01\x2b"
    result = decode_attributed_body(truncated)
    # Should return None or empty, not crash
    assert result is None or result == ""

    # Long text (> 0x7E bytes, uses 0x81 length encoding)
    long_text = "A" * 200
    long_blob = _make_attributed_body(long_text)
    assert decode_attributed_body(long_blob) == long_text


def test_get_thread_messages_decodes_attributed_body(tmp_path: Path, monkeypatch):
    """get_thread_messages also falls back to attributedBody."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    now = int(time.time())
    blob = _make_attributed_body("thread message from blob")
    _insert_message(
        db_path=db_path,
        guid="g-thread-ab",
        text=None,
        date_ns=_apple_ns_from_unix(now - 10),
        is_from_me=0,
        sender="+15555550307",
        chat_id="chat-thread-ab",
        attributed_body=blob,
    )
    store = MessageStore(
        db_path=db_path,
        communicate_script=Path("/tmp/missing"),
        profile_db_path=tmp_path / "thread-profiles.db",
    )
    rows = store.get_thread_messages(chat_identifier="chat-thread-ab", minutes=24 * 60, limit=10)
    assert len(rows) == 1
    assert rows[0]["text"] == "thread message from blob"


def test_list_threads_decodes_last_message_attributed_body(tmp_path: Path, monkeypatch):
    """list_threads shows decoded attributedBody as last_message_text."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    now = int(time.time())
    blob = _make_attributed_body("last msg from blob")
    _insert_message(
        db_path=db_path,
        guid="g-lt-ab",
        text=None,
        date_ns=_apple_ns_from_unix(now - 10),
        is_from_me=0,
        sender="+15555550308",
        chat_id="chat-lt-ab",
        attributed_body=blob,
    )
    store = MessageStore(
        db_path=db_path,
        communicate_script=Path("/tmp/missing"),
        profile_db_path=tmp_path / "thread-profiles.db",
    )
    threads = store.list_threads(minutes=24 * 60, limit=10)
    assert len(threads) == 1
    assert threads[0]["chat_identifier"] == "chat-lt-ab"
    assert threads[0]["last_message_text"] == "last msg from blob"


# ---------------------------------------------------------------------------
# Phase 3: chat_identifier → guid resolution tests
# ---------------------------------------------------------------------------


def test_resolve_chat_guid_found(chat_db: Path, monkeypatch):
    """_resolve_chat_guid returns the guid when chat_identifier exists."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    store = MessageStore(db_path=chat_db, communicate_script=Path("/tmp/missing"))
    guid = store._resolve_chat_guid("chat-team")
    assert guid == "iMessage;+;chat-team"


def test_resolve_chat_guid_not_found(chat_db: Path, monkeypatch):
    """_resolve_chat_guid returns None for unknown chat_identifier."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    store = MessageStore(db_path=chat_db, communicate_script=Path("/tmp/missing"))
    guid = store._resolve_chat_guid("nonexistent-chat")
    assert guid is None


def test_send_message_with_chat_identifier_resolves_guid(chat_db: Path, tmp_path: Path, monkeypatch):
    """send_message passes the resolved guid (not raw chat_identifier) to --chat-id."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    script = tmp_path / "communicate.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    store = MessageStore(db_path=chat_db, communicate_script=script)

    seen = {}

    def fake_cleanup(cmd, timeout, **kwargs):
        seen["cmd"] = cmd
        payload = {"channel": "imessage", "status": "sent", "chat_identifier": "chat-team"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(messages_mod, "_run_with_cleanup", fake_cleanup)
    result = store.send_message(body="Group reply", confirm_send=True, chat_identifier="chat-team")
    assert result["status"] == "sent"
    # The command should contain the resolved guid, not the raw chat_identifier
    chat_id_idx = seen["cmd"].index("--chat-id")
    assert seen["cmd"][chat_id_idx + 1] == "iMessage;+;chat-team"


# ---------------------------------------------------------------------------
# Phase 4: verify_handle tests
# ---------------------------------------------------------------------------


def test_verify_handle_finds_member_in_threads(chat_db: Path, tmp_path: Path, monkeypatch):
    """verify_handle returns thread info when the handle is a known thread member."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    store = MessageStore(
        db_path=chat_db,
        communicate_script=Path("/tmp/missing"),
        profile_db_path=tmp_path / "thread-profiles.db",
    )
    # Trigger observation recording so thread_members gets populated
    store.get_messages(minutes=24 * 60, limit=50, include_from_me=True)

    result = store.verify_handle("+15555550123")
    assert result["handle"] == "+15555550123"
    assert result["found_in_threads"] is True
    assert len(result["chat_identifiers"]) >= 1


def test_verify_handle_returns_empty_for_unknown(tmp_path: Path, monkeypatch):
    """verify_handle returns not-found for an unknown handle."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    store = MessageStore(
        db_path=db_path,
        communicate_script=Path("/tmp/missing"),
        profile_db_path=tmp_path / "thread-profiles.db",
    )
    result = store.verify_handle("+19999999999")
    assert result["handle"] == "+19999999999"
    assert result["found_in_threads"] is False
    assert result["chat_identifiers"] == []
    assert result["display_names"] == []


def test_verify_handle_returns_display_name(tmp_path: Path, monkeypatch):
    """verify_handle returns the display_name from thread_profiles when set."""
    monkeypatch.setattr(messages_mod, "_IS_MACOS", True)
    db_path = tmp_path / "chat.db"
    _make_chat_db(db_path)
    store = MessageStore(
        db_path=db_path,
        communicate_script=Path("/tmp/missing"),
        profile_db_path=tmp_path / "thread-profiles.db",
    )
    # Manually insert a thread profile with display_name and a member
    with store._open_profile_db() as conn:
        conn.execute(
            """INSERT INTO thread_profiles(chat_identifier, display_name, preferred_handle,
               notes, auto_reply_mode, last_seen_at, last_sender, updated_at_utc)
               VALUES(?, ?, ?, NULL, 'manual', NULL, NULL, ?)""",
            ("chat-ross", "Ross Young", "+17035551234", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO thread_members(chat_identifier, handle, last_seen_at) VALUES(?, ?, NULL)",
            ("chat-ross", "+17035551234"),
        )
        conn.commit()

    result = store.verify_handle("+17035551234")
    assert result["found_in_threads"] is True
    assert "Ross Young" in result["display_names"]
