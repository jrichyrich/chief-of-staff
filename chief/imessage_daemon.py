"""Local iMessage ingestion and dispatch daemon for Jarvis.

This daemon:
1) polls MessageStore for new iMessages,
2) stores normalized events and queue jobs in SQLite,
3) executes queued instructions via IMessageExecutor (Claude API),
4) replies via iMessage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("imessage-daemon")


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_local_date_to_epoch(date_local: str) -> int:
    """Parse `YYYY-MM-DD HH:MM:SS` in local tz to epoch seconds."""
    dt = datetime.strptime(date_local, "%Y-%m-%d %H:%M:%S")
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is None:
        raise ValueError("Could not resolve local timezone")
    return int(dt.replace(tzinfo=local_tz).timestamp())


def compute_lookback_minutes(
    watermark_epoch: int,
    now_epoch: int,
    bootstrap_minutes: int,
    max_minutes: int,
) -> int:
    if watermark_epoch <= 0:
        return bootstrap_minutes
    age_seconds = max(0, now_epoch - watermark_epoch)
    minutes = int(age_seconds / 60) + 2
    if minutes < 1:
        minutes = 1
    if minutes > max_minutes:
        minutes = max_minutes
    return minutes


def compute_dispatch_lookback_minutes(
    oldest_queued_epoch: int,
    now_epoch: int,
    max_minutes: int,
) -> int:
    if oldest_queued_epoch <= 0:
        return 5
    age_seconds = max(0, now_epoch - oldest_queued_epoch)
    minutes = int(age_seconds / 60) + 3
    if minutes < 1:
        minutes = 1
    if minutes > max_minutes:
        minutes = max_minutes
    return minutes


DISPATCH_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class DaemonConfig:
    project_dir: Path
    data_dir: Path
    state_db_path: Path
    poll_interval_seconds: int = 5
    bootstrap_lookback_minutes: int = 30
    max_lookback_minutes: int = 1440
    dispatch_batch_size: int = 25
    chat_db_path: Path | None = None  # defaults to ~/Library/Messages/chat.db
    profile_db_path: Path | None = None  # defaults to data/imessage-thread-profiles.db
    monitored_conversation: str = ""  # filter to specific chat_identifier
    include_from_me: bool = True  # whether to process own messages
    allowed_senders: tuple[str, ...] = ()  # if non-empty, only process from these senders
    command_prefix: str = ""  # if set, only process messages starting with this prefix


@dataclass(frozen=True)
class IngestedMessage:
    guid: str
    text: str
    date_local: str
    timestamp_epoch: int
    raw_json: str


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS message_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guid TEXT NOT NULL UNIQUE,
                text TEXT NOT NULL,
                date_local TEXT NOT NULL,
                timestamp_epoch INTEGER NOT NULL,
                raw_json TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS processing_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_guid TEXT NOT NULL UNIQUE REFERENCES message_events(guid),
                status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outbound_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_guid TEXT,
                channel TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS watermarks (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def get_watermark_epoch(self) -> int:
        row = self.conn.execute(
            "SELECT value FROM watermarks WHERE key = 'last_message_epoch'"
        ).fetchone()
        if not row:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0

    def set_watermark_epoch(self, epoch: int) -> None:
        self.conn.execute(
            """
            INSERT INTO watermarks(key, value, updated_at_utc)
            VALUES('last_message_epoch', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at_utc = excluded.updated_at_utc
            """,
            (str(epoch), utc_now_iso()),
        )
        self.conn.commit()

    def ingest_messages(self, messages: list[IngestedMessage]) -> tuple[int, int]:
        inserted = 0
        max_epoch = 0
        now = utc_now_iso()
        for msg in messages:
            cur = self.conn.execute(
                """
                INSERT OR IGNORE INTO message_events
                (guid, text, date_local, timestamp_epoch, raw_json, created_at_utc)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (msg.guid, msg.text, msg.date_local, msg.timestamp_epoch, msg.raw_json, now),
            )
            if cur.rowcount == 1:
                inserted += 1
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO processing_jobs
                    (message_guid, status, attempts, last_error, created_at_utc, updated_at_utc)
                    VALUES (?, 'queued', 0, NULL, ?, ?)
                    """,
                    (msg.guid, now, now),
                )
            if msg.timestamp_epoch > max_epoch:
                max_epoch = msg.timestamp_epoch
        self.conn.commit()
        return inserted, max_epoch

    def list_queued_jobs(self, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                j.id,
                j.message_guid,
                j.status,
                j.attempts,
                e.timestamp_epoch,
                e.date_local,
                e.text
            FROM processing_jobs j
            JOIN message_events e ON e.guid = j.message_guid
            WHERE j.status = 'queued'
            ORDER BY e.timestamp_epoch ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_jobs_running(self, job_ids: list[int]) -> None:
        if not job_ids:
            return
        now = utc_now_iso()
        placeholders = ",".join("?" for _ in job_ids)
        params: list[Any] = [now]
        params.extend(job_ids)
        self.conn.execute(
            f"""
            UPDATE processing_jobs
            SET status = 'running',
                attempts = attempts + 1,
                updated_at_utc = ?
            WHERE id IN ({placeholders})
            """,
            tuple(params),
        )
        self.conn.commit()

    def mark_job_result(self, message_guid: str, success: bool, error: str = "") -> None:
        status = "succeeded" if success else "failed"
        now = utc_now_iso()
        err_val: Any = None if success else error[:1000]
        self.conn.execute(
            """
            UPDATE processing_jobs
            SET status = ?, last_error = ?, updated_at_utc = ?
            WHERE message_guid = ?
            """,
            (status, err_val, now, message_guid),
        )
        self.conn.commit()

    def count_jobs_by_status(self, status: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM processing_jobs WHERE status = ?",
            (status,),
        ).fetchone()
        return int(row["c"]) if row else 0

    def recover_stale_running_jobs(self, max_age_seconds: int = 300, max_attempts: int = 3) -> int:
        """Reset jobs stuck in 'running' state back to 'queued' for retry.

        Jobs that have exceeded max_attempts are marked as 'failed' instead.
        Returns the number of jobs recovered.
        """
        now = utc_now_iso()
        # SQLite datetime comparison: jobs running longer than max_age_seconds
        cursor = self.conn.execute(
            """
            UPDATE processing_jobs
            SET status = CASE WHEN attempts >= ? THEN 'failed' ELSE 'queued' END,
                last_error = CASE WHEN attempts >= ? THEN 'max_attempts_exceeded' ELSE 'recovered_stale' END,
                updated_at_utc = ?
            WHERE status = 'running'
              AND julianday(?) - julianday(updated_at_utc) > ? / 86400.0
            """,
            (max_attempts, max_attempts, now, now, max_age_seconds),
        )
        recovered = cursor.rowcount
        self.conn.commit()
        if recovered > 0:
            logger.info("Recovered %d stale running jobs", recovered)
        return recovered


class IMessageDaemon:
    def __init__(
        self,
        config: DaemonConfig,
        message_store: Any | None = None,
        executor: Any | None = None,
        reply_fn: Callable[..., Any] | None = None,
    ):
        self.config = config
        self.store = StateStore(config.state_db_path)
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        if message_store is not None:
            self.message_store = message_store
        else:
            from apple_messages.messages import MessageStore

            self.message_store = MessageStore(
                db_path=config.chat_db_path,
                profile_db_path=config.profile_db_path
                or config.data_dir / "imessage-thread-profiles.db",
            )
        self.executor = executor
        self.reply_fn = reply_fn

    def close(self) -> None:
        self.store.close()

    async def run_once(self) -> dict[str, int]:
        self.store.recover_stale_running_jobs()
        ingested_count = self._ingest_cycle()
        dispatched_count = await self._dispatch_cycle()
        return {"ingested": ingested_count, "dispatched": dispatched_count}

    def _ingest_cycle(self) -> int:
        now_epoch = int(time.time())
        watermark = self.store.get_watermark_epoch()
        lookback = compute_lookback_minutes(
            watermark_epoch=watermark,
            now_epoch=now_epoch,
            bootstrap_minutes=self.config.bootstrap_lookback_minutes,
            max_minutes=self.config.max_lookback_minutes,
        )

        raw_messages = self.message_store.get_messages(
            minutes=lookback,
            limit=200,
            include_from_me=self.config.include_from_me,
            conversation=self.config.monitored_conversation,
        )

        messages: list[IngestedMessage] = []
        allowed = self.config.allowed_senders
        prefix = self.config.command_prefix
        for row in raw_messages:
            guid = str(row.get("guid", "")).strip()
            text = str(row.get("text", "")).strip()
            date_local = str(row.get("date_local", "")).strip()
            if not guid or not date_local:
                continue
            # Sender allowlist filtering
            if allowed:
                sender = str(row.get("sender", "")).strip()
                is_from_me = row.get("is_from_me", False)
                if not is_from_me and sender not in allowed:
                    continue
            # Command prefix filtering
            if prefix and not text.lower().startswith(prefix.lower()):
                continue
            ts = parse_local_date_to_epoch(date_local)
            messages.append(
                IngestedMessage(
                    guid=guid,
                    text=text,
                    date_local=date_local,
                    timestamp_epoch=ts,
                    raw_json=json.dumps(row, separators=(",", ":"), sort_keys=True),
                )
            )

        inserted, max_epoch = self.store.ingest_messages(messages)
        if max_epoch > watermark:
            self.store.set_watermark_epoch(max_epoch)
        return inserted

    async def _dispatch_cycle(self) -> int:
        """Process queued messages: execute via Claude API and reply via iMessage."""
        queued = self.store.list_queued_jobs(limit=self.config.dispatch_batch_size)
        if not queued:
            return 0

        dispatched = 0
        for job in queued:
            guid = str(job["message_guid"])
            text = str(job.get("text", "")).strip()
            self.store.mark_jobs_running([int(job["id"])])

            if not text:
                self.store.mark_job_result(guid, success=False, error="empty_message_text")
                continue

            if self.executor is None:
                self.store.mark_job_result(guid, success=False, error="no_executor_configured")
                continue

            try:
                result_text = await asyncio.wait_for(
                    self.executor.execute(text),
                    timeout=DISPATCH_TIMEOUT_SECONDS,
                )
                # Mark execution as succeeded regardless of reply outcome
                self.store.mark_job_result(guid, success=True)
                dispatched += 1
                # Reply via iMessage (separate from execution success)
                if self.reply_fn and result_text:
                    try:
                        self.reply_fn(body=result_text)
                    except Exception as reply_err:
                        logger.error("Reply failed for guid=%s: %s", guid, reply_err)
            except asyncio.TimeoutError:
                self.store.mark_job_result(guid, success=False, error="execution_timeout")
                logger.error("Dispatch timeout for guid=%s", guid)
            except Exception as e:
                self.store.mark_job_result(guid, success=False, error=str(e))
                logger.error("Dispatch error for guid=%s: %s", guid, e)

        return dispatched
