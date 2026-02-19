import json
import logging
import platform
import sqlite3
import subprocess
from pathlib import Path
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_IS_MACOS = platform.system() == "Darwin"


def decode_attributed_body(blob: bytes) -> str | None:
    """Decode an attributedBody typedstream blob to plain text.

    Returns None if the blob cannot be decoded.
    """
    if not blob or b"NSString" not in blob:
        return None
    try:
        content = blob.split(b"NSString")[1][5:]  # Skip 5-byte preamble
        indicator = content[0]
        if indicator == 0x81:
            length = int.from_bytes(content[1:3], "little")
            start = 3
        elif indicator == 0x82:
            length = int.from_bytes(content[1:5], "little")
            start = 5
        elif indicator == 0x83:
            length = int.from_bytes(content[1:9], "little")
            start = 9
        else:
            length = indicator
            start = 1
        text = content[start : start + length].decode("utf-8", errors="replace")
        return text if text else None
    except (IndexError, ValueError):
        return None

_PLATFORM_ERROR = {"error": "Messages is only available on macOS"}
_DEFAULT_TIMEOUT = 15
_SEND_TIMEOUT = 30


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


class MessageStore:
    """Read iMessage history from chat.db and send iMessages via communicate.sh."""

    def __init__(
        self,
        db_path: Path | None = None,
        communicate_script: Path | None = None,
        profile_db_path: Path | None = None,
    ):
        self.db_path = Path(db_path) if db_path else (Path.home() / "Library" / "Messages" / "chat.db")
        self.communicate_script = (
            Path(communicate_script)
            if communicate_script
            else (_project_root() / "scripts" / "communicate.sh")
        )
        self.profile_db_path = (
            Path(profile_db_path)
            if profile_db_path
            else (_project_root() / "data" / "imessage-thread-profiles.db")
        )
        self.profile_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_profile_db()

    def _open_chat_db(self) -> sqlite3.Connection:
        if not _IS_MACOS:
            raise RuntimeError(_PLATFORM_ERROR["error"])
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        return min(max(1, int(limit)), 200)

    @staticmethod
    def _normalize_minutes(minutes: int) -> int:
        return min(max(1, int(minutes)), 60 * 24 * 14)

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _open_profile_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.profile_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_profile_db(self) -> None:
        with self._open_profile_db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS thread_profiles (
                    chat_identifier TEXT PRIMARY KEY,
                    display_name TEXT,
                    preferred_handle TEXT,
                    notes TEXT,
                    auto_reply_mode TEXT NOT NULL DEFAULT 'manual',
                    last_seen_at TEXT,
                    last_sender TEXT,
                    updated_at_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS thread_members (
                    chat_identifier TEXT NOT NULL,
                    handle TEXT NOT NULL,
                    last_seen_at TEXT,
                    PRIMARY KEY(chat_identifier, handle)
                );
                """
            )
            conn.commit()

    def _upsert_thread_observation(self, chat_identifier: str, sender: str, date_local: str) -> None:
        chat_identifier = (chat_identifier or "").strip()
        sender = (sender or "").strip()
        date_local = (date_local or "").strip()
        if not chat_identifier:
            return
        now = self._utc_now_iso()
        with self._open_profile_db() as conn:
            conn.execute(
                """
                INSERT INTO thread_profiles(
                    chat_identifier, display_name, preferred_handle, notes, auto_reply_mode,
                    last_seen_at, last_sender, updated_at_utc
                )
                VALUES(?, NULL, ?, NULL, 'manual', ?, ?, ?)
                ON CONFLICT(chat_identifier) DO UPDATE SET
                    preferred_handle = CASE
                        WHEN COALESCE(thread_profiles.preferred_handle, '') = '' THEN excluded.preferred_handle
                        ELSE thread_profiles.preferred_handle
                    END,
                    last_seen_at = CASE
                        WHEN COALESCE(thread_profiles.last_seen_at, '') <= COALESCE(excluded.last_seen_at, '')
                        THEN excluded.last_seen_at ELSE thread_profiles.last_seen_at
                    END,
                    last_sender = CASE
                        WHEN COALESCE(thread_profiles.last_seen_at, '') <= COALESCE(excluded.last_seen_at, '')
                        THEN excluded.last_sender ELSE thread_profiles.last_sender
                    END,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (chat_identifier, sender or None, date_local or None, sender or None, now),
            )
            if sender:
                conn.execute(
                    """
                    INSERT INTO thread_members(chat_identifier, handle, last_seen_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(chat_identifier, handle) DO UPDATE SET
                        last_seen_at = CASE
                            WHEN COALESCE(thread_members.last_seen_at, '') <= COALESCE(excluded.last_seen_at, '')
                            THEN excluded.last_seen_at ELSE thread_members.last_seen_at
                        END
                    """,
                    (chat_identifier, sender, date_local or None),
                )
            conn.commit()

    def _record_observations(self, rows: list[dict]) -> None:
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            chat_identifier = str(row.get("chat_identifier", "")).strip()
            sender = str(row.get("sender", "")).strip()
            date_local = str(row.get("date_local", "")).strip()
            key = (chat_identifier, sender, date_local)
            if key in seen:
                continue
            seen.add(key)
            self._upsert_thread_observation(chat_identifier, sender, date_local)

    def _load_profiles(self, chat_ids: list[str]) -> dict[str, dict]:
        chat_ids = [c for c in chat_ids if c]
        if not chat_ids:
            return {}
        placeholders = ",".join("?" for _ in chat_ids)
        with self._open_profile_db() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    p.chat_identifier,
                    COALESCE(p.display_name, '') AS display_name,
                    COALESCE(p.preferred_handle, '') AS preferred_handle,
                    COALESCE(p.notes, '') AS notes,
                    COALESCE(p.auto_reply_mode, 'manual') AS auto_reply_mode,
                    COALESCE(p.last_seen_at, '') AS last_seen_at,
                    COALESCE(p.last_sender, '') AS last_sender,
                    COALESCE(
                        (
                            SELECT group_concat(m.handle, '|||')
                            FROM thread_members m
                            WHERE m.chat_identifier = p.chat_identifier
                        ),
                        ''
                    ) AS members
                FROM thread_profiles p
                WHERE p.chat_identifier IN ({placeholders})
                """,
                tuple(chat_ids),
            ).fetchall()
        profiles: dict[str, dict] = {}
        for row in rows:
            members = [m for m in row["members"].split("|||") if m] if row["members"] else []
            profiles[row["chat_identifier"]] = {
                "display_name": row["display_name"] or "",
                "preferred_handle": row["preferred_handle"] or "",
                "notes": row["notes"] or "",
                "auto_reply_mode": row["auto_reply_mode"] or "manual",
                "last_seen_at": row["last_seen_at"] or "",
                "last_sender": row["last_sender"] or "",
                "members": members,
            }
        return profiles

    def get_messages(
        self,
        minutes: int = 60,
        limit: int = 25,
        include_from_me: bool = True,
        conversation: str = "",
    ) -> list[dict]:
        """Get recent iMessages from local chat.db."""
        if not _IS_MACOS:
            return [_PLATFORM_ERROR]
        safe_minutes = self._normalize_minutes(minutes)
        safe_limit = self._normalize_limit(limit)
        where = [
            "m.date > ((strftime('%s', 'now') - 978307200 - (? * 60)) * 1000000000)",
        ]
        params: list[object] = [safe_minutes]
        if not include_from_me:
            where.append("COALESCE(m.is_from_me, 0) = 0")
        if conversation:
            where.append(
                "("
                "lower(COALESCE(h.id, '')) LIKE ? "
                "OR lower(COALESCE(c.chat_identifier, '')) LIKE ?"
                ")"
            )
            needle = f"%{conversation.lower()}%"
            params.extend([needle, needle])
        params.append(safe_limit)

        query = f"""
            SELECT
                m.guid AS guid,
                COALESCE(m.text, '') AS text,
                m.attributedBody,
                datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime') AS date_local,
                COALESCE(m.is_from_me, 0) AS is_from_me,
                COALESCE(h.id, '') AS sender,
                COALESCE(c.chat_identifier, '') AS chat_identifier
            FROM message m
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE {" AND ".join(where)}
            GROUP BY m.ROWID
            ORDER BY m.date DESC
            LIMIT ?
        """
        try:
            with self._open_chat_db() as conn:
                rows = conn.execute(query, params).fetchall()
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as exc:
            logger.error("SQLite error in get_messages: %s", exc)
            return [{"error": str(exc)}]
        results = [
            {
                "guid": row["guid"] or "",
                "text": row["text"] or decode_attributed_body(row["attributedBody"]) or "",
                "date_local": row["date_local"] or "",
                "is_from_me": bool(row["is_from_me"]),
                "sender": row["sender"] or "",
                "chat_identifier": row["chat_identifier"] or "",
            }
            for row in rows
        ]
        self._record_observations(results)
        return results

    def search_messages(
        self,
        query: str,
        minutes: int = 24 * 60,
        limit: int = 25,
        include_from_me: bool = True,
    ) -> list[dict]:
        """Search iMessages by text, sender, or conversation identifier."""
        if not _IS_MACOS:
            return [_PLATFORM_ERROR]
        query = (query or "").strip()
        if not query:
            return []
        safe_minutes = self._normalize_minutes(minutes)
        safe_limit = self._normalize_limit(limit)
        where = [
            "m.date > ((strftime('%s', 'now') - 978307200 - (? * 60)) * 1000000000)",
            "("
            "lower(COALESCE(m.text, '')) LIKE ? "
            "OR lower(COALESCE(h.id, '')) LIKE ? "
            "OR lower(COALESCE(c.chat_identifier, '')) LIKE ? "
            "OR (m.text IS NULL AND m.attributedBody IS NOT NULL)"
            ")",
        ]
        params: list[object] = [safe_minutes]
        needle = f"%{query.lower()}%"
        params.extend([needle, needle, needle])
        if not include_from_me:
            where.append("COALESCE(m.is_from_me, 0) = 0")
        params.append(safe_limit)

        sql = f"""
            SELECT
                m.guid AS guid,
                COALESCE(m.text, '') AS text,
                m.attributedBody,
                datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime') AS date_local,
                COALESCE(m.is_from_me, 0) AS is_from_me,
                COALESCE(h.id, '') AS sender,
                COALESCE(c.chat_identifier, '') AS chat_identifier
            FROM message m
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE {" AND ".join(where)}
            GROUP BY m.ROWID
            ORDER BY m.date DESC
            LIMIT ?
        """
        try:
            with self._open_chat_db() as conn:
                rows = conn.execute(sql, params).fetchall()
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as exc:
            logger.error("SQLite error in search_messages: %s", exc)
            return [{"error": str(exc)}]
        query_lower = query.lower()
        results = []
        for row in rows:
            text = row["text"] or decode_attributed_body(row["attributedBody"]) or ""
            # If text came from attributedBody decode, verify it matches the search query
            if not row["text"] and text:
                sender = (row["sender"] or "").lower()
                chat_id = (row["chat_identifier"] or "").lower()
                if (
                    query_lower not in text.lower()
                    and query_lower not in sender
                    and query_lower not in chat_id
                ):
                    continue
            results.append(
                {
                    "guid": row["guid"] or "",
                    "text": text,
                    "date_local": row["date_local"] or "",
                    "is_from_me": bool(row["is_from_me"]),
                    "sender": row["sender"] or "",
                    "chat_identifier": row["chat_identifier"] or "",
                }
            )
        self._record_observations(results)
        return results

    def list_threads(self, minutes: int = 7 * 24 * 60, limit: int = 50) -> list[dict]:
        """List active iMessage threads with persisted profile metadata."""
        if not _IS_MACOS:
            return [_PLATFORM_ERROR]
        safe_minutes = self._normalize_minutes(minutes)
        safe_limit = self._normalize_limit(limit)
        sql = """
            SELECT
                COALESCE(c.chat_identifier, '') AS chat_identifier,
                datetime(MAX(m.date) / 1000000000 + 978307200, 'unixepoch', 'localtime') AS last_message_date_local,
                (
                    SELECT m2.text
                    FROM chat_message_join cmj2
                    JOIN message m2 ON m2.ROWID = cmj2.message_id
                    WHERE cmj2.chat_id = c.ROWID
                    ORDER BY m2.date DESC
                    LIMIT 1
                ) AS last_message_text,
                (
                    SELECT m3.attributedBody
                    FROM chat_message_join cmj3
                    JOIN message m3 ON m3.ROWID = cmj3.message_id
                    WHERE cmj3.chat_id = c.ROWID
                    ORDER BY m3.date DESC
                    LIMIT 1
                ) AS last_message_attributed_body,
                COUNT(DISTINCT m.ROWID) AS total_messages,
                SUM(CASE WHEN COALESCE(m.is_from_me, 0) = 0 THEN 1 ELSE 0 END) AS inbound_messages,
                COALESCE(group_concat(DISTINCT h.id), '') AS participants
            FROM chat c
            JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
            JOIN message m ON m.ROWID = cmj.message_id
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            WHERE m.date > ((strftime('%s', 'now') - 978307200 - (? * 60)) * 1000000000)
            GROUP BY c.ROWID
            HAVING COALESCE(c.chat_identifier, '') != ''
            ORDER BY MAX(m.date) DESC
            LIMIT ?
        """
        try:
            with self._open_chat_db() as conn:
                rows = conn.execute(sql, (safe_minutes, safe_limit)).fetchall()
        except Exception as exc:
            return [{"error": str(exc)}]
        results: list[dict] = []
        for row in rows:
            chat_identifier = row["chat_identifier"] or ""
            participants = [p for p in (row["participants"] or "").split(",") if p]
            last_text = (
                row["last_message_text"]
                or decode_attributed_body(row["last_message_attributed_body"])
                or ""
            )
            results.append(
                {
                    "chat_identifier": chat_identifier,
                    "last_message_date_local": row["last_message_date_local"] or "",
                    "last_message_text": last_text,
                    "total_messages": int(row["total_messages"] or 0),
                    "inbound_messages": int(row["inbound_messages"] or 0),
                    "participants": sorted(set(participants)),
                }
            )

        profiles = self._load_profiles([r["chat_identifier"] for r in results])
        for item in results:
            profile = profiles.get(item["chat_identifier"], {})
            item["profile"] = profile
            if profile.get("members"):
                merged = set(item["participants"])
                merged.update(profile["members"])
                item["participants"] = sorted(merged)
        return results

    def get_thread_messages(
        self,
        chat_identifier: str,
        minutes: int = 7 * 24 * 60,
        limit: int = 50,
        include_from_me: bool = True,
    ) -> list[dict]:
        """Get messages for a specific iMessage thread by chat_identifier."""
        if not _IS_MACOS:
            return [_PLATFORM_ERROR]
        chat_identifier = (chat_identifier or "").strip()
        if not chat_identifier:
            return [{"error": "chat_identifier is required"}]
        safe_minutes = self._normalize_minutes(minutes)
        safe_limit = self._normalize_limit(limit)
        where = [
            "c.chat_identifier = ?",
            "m.date > ((strftime('%s', 'now') - 978307200 - (? * 60)) * 1000000000)",
        ]
        params: list[object] = [chat_identifier, safe_minutes]
        if not include_from_me:
            where.append("COALESCE(m.is_from_me, 0) = 0")
        params.append(safe_limit)

        sql = f"""
            SELECT
                m.guid AS guid,
                COALESCE(m.text, '') AS text,
                m.attributedBody,
                datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime') AS date_local,
                COALESCE(m.is_from_me, 0) AS is_from_me,
                COALESCE(h.id, '') AS sender,
                COALESCE(c.chat_identifier, '') AS chat_identifier
            FROM chat c
            JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
            JOIN message m ON m.ROWID = cmj.message_id
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            WHERE {" AND ".join(where)}
            GROUP BY m.ROWID
            ORDER BY m.date DESC
            LIMIT ?
        """
        try:
            with self._open_chat_db() as conn:
                rows = conn.execute(sql, params).fetchall()
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as exc:
            logger.error("SQLite error in get_thread_messages: %s", exc)
            return [{"error": str(exc)}]
        results = [
            {
                "guid": row["guid"] or "",
                "text": row["text"] or decode_attributed_body(row["attributedBody"]) or "",
                "date_local": row["date_local"] or "",
                "is_from_me": bool(row["is_from_me"]),
                "sender": row["sender"] or "",
                "chat_identifier": row["chat_identifier"] or "",
            }
            for row in rows
        ]
        self._record_observations(results)
        return results

    def get_thread_context(
        self,
        chat_identifier: str,
        minutes: int = 7 * 24 * 60,
        limit: int = 20,
    ) -> dict:
        """Get thread profile + recent message context for orchestration."""
        chat_identifier = (chat_identifier or "").strip()
        if not chat_identifier:
            return {"error": "chat_identifier is required"}
        messages = self.get_thread_messages(
            chat_identifier=chat_identifier,
            minutes=minutes,
            limit=limit,
            include_from_me=True,
        )
        if messages and isinstance(messages[0], dict) and messages[0].get("error"):
            return {"error": messages[0]["error"]}
        profile = self._load_profiles([chat_identifier]).get(chat_identifier, {})
        participants = sorted(
            {
                str(m.get("sender", "")).strip()
                for m in messages
                if str(m.get("sender", "")).strip()
            }
        )
        if profile.get("members"):
            merged = set(participants)
            merged.update(profile["members"])
            participants = sorted(merged)

        inbound = sum(1 for m in messages if not m.get("is_from_me", False))
        outbound = sum(1 for m in messages if m.get("is_from_me", False))
        suggested_reply_target = profile.get("preferred_handle") or (
            next((m.get("sender", "") for m in messages if m.get("sender")), "")
        )

        return {
            "chat_identifier": chat_identifier,
            "profile": profile,
            "participants": participants,
            "recent_stats": {
                "total_messages": len(messages),
                "inbound_messages": inbound,
                "outbound_messages": outbound,
            },
            "suggested_reply_target": suggested_reply_target,
            "recent_messages": messages,
        }

    def _resolve_chat_guid(self, chat_identifier: str) -> str | None:
        """Look up the Messages.app guid for a chat_identifier.

        The AppleScript ``chat id`` property corresponds to the ``guid`` column
        in chat.db (e.g. ``iMessage;+;chat336858519315148840``), not the
        ``chat_identifier`` column.  Returns *None* when the identifier is not
        found so the caller can fall back gracefully.
        """
        try:
            with self._open_chat_db() as conn:
                row = conn.execute(
                    "SELECT guid FROM chat WHERE chat_identifier = ? LIMIT 1",
                    (chat_identifier,),
                ).fetchone()
                return row["guid"] if row else None
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as exc:
            logger.error("SQLite error resolving chat guid: %s", exc)
            return None

    def send_message(
        self,
        to: str = "",
        body: str = "",
        confirm_send: bool = False,
        chat_identifier: str = "",
    ) -> dict:
        """Send an iMessage using communicate.sh. Requires confirm_send=True."""
        if not _IS_MACOS:
            return _PLATFORM_ERROR
        to = (to or "").strip()
        body = (body or "").strip()
        chat_identifier = (chat_identifier or "").strip()
        if not to and not chat_identifier:
            return {"error": "Missing recipient: provide 'to' or 'chat_identifier'"}
        if not body:
            return {"error": "Missing message body"}
        if not confirm_send:
            route = {"chat_identifier": chat_identifier} if chat_identifier else {"to": to}
            return {
                "status": "preview",
                "channel": "imessage",
                **route,
                "body": body,
                "requires_confirmation": True,
            }
        if not self.communicate_script.exists():
            return {"error": f"communicate.sh not found: {self.communicate_script}"}
        cmd = [str(self.communicate_script), "imessage", "--body", body]
        if chat_identifier:
            # Resolve chat_identifier → guid so AppleScript can find the chat
            resolved = self._resolve_chat_guid(chat_identifier)
            cmd.extend(["--chat-id", resolved or chat_identifier])
        else:
            cmd.extend(["--to", to])
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_SEND_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"error": "iMessage send timed out"}
        except FileNotFoundError:
            return {"error": "communicate.sh not executable"}

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return {"error": stderr or stdout or "Failed to send iMessage"}
        if not stdout:
            route = {"chat_identifier": chat_identifier} if chat_identifier else {"to": to}
            return {"status": "sent", "channel": "imessage", **route}
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            data = {"status": "sent", "channel": "imessage", "to": to, "raw_output": stdout}
        return data
