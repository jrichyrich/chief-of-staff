"""Local iMessage ingestion and dispatch daemon for Jarvis.

This daemon does not call LLMs directly. It:
1) polls scripts/imessage-reader for new `jarvis:` messages,
2) stores normalized events and queue jobs in SQLite,
3) hands queued work to scripts/inbox-monitor.sh,
4) reconciles completion against data/inbox-processed.json.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class DaemonConfig:
    project_dir: Path
    data_dir: Path
    reader_path: Path
    inbox_monitor_path: Path
    state_db_path: Path
    processed_file: Path
    poll_interval_seconds: int = 5
    bootstrap_lookback_minutes: int = 30
    max_lookback_minutes: int = 1440
    dispatch_batch_size: int = 25


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


class IMessageDaemon:
    def __init__(self, config: DaemonConfig):
        self.config = config
        self.store = StateStore(config.state_db_path)
        self.config.data_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.store.close()

    def run_once(self) -> dict[str, int]:
        ingested_count = self._ingest_cycle()
        dispatched_count = self._dispatch_cycle()
        return {"ingested": ingested_count, "dispatched": dispatched_count}

    def run_forever(self) -> None:
        logger.info(
            "Starting iMessage daemon (poll=%ss, db=%s)",
            self.config.poll_interval_seconds,
            self.config.state_db_path,
        )
        while True:
            try:
                result = self.run_once()
                if result["ingested"] > 0 or result["dispatched"] > 0:
                    logger.info(
                        "Cycle complete: ingested=%d dispatched=%d queued=%d failed=%d",
                        result["ingested"],
                        result["dispatched"],
                        self.store.count_jobs_by_status("queued"),
                        self.store.count_jobs_by_status("failed"),
                    )
            except Exception:
                logger.exception("Daemon cycle failed")
            time.sleep(self.config.poll_interval_seconds)

    def _ingest_cycle(self) -> int:
        now_epoch = int(time.time())
        watermark = self.store.get_watermark_epoch()
        lookback = compute_lookback_minutes(
            watermark_epoch=watermark,
            now_epoch=now_epoch,
            bootstrap_minutes=self.config.bootstrap_lookback_minutes,
            max_minutes=self.config.max_lookback_minutes,
        )

        cmd = [str(self.config.reader_path), "--minutes", str(lookback)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            logger.error("imessage-reader failed (code=%d): %s", proc.returncode, stderr)
            return 0

        raw = proc.stdout.strip() or "[]"
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("imessage-reader output was not a JSON array")

        messages: list[IngestedMessage] = []
        for row in parsed:
            if not isinstance(row, dict):
                continue
            guid = str(row.get("guid", "")).strip()
            text = str(row.get("text", "")).strip()
            date_local = str(row.get("date_local", "")).strip()
            if not guid or not date_local:
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

    def _dispatch_cycle(self) -> int:
        queued = self.store.list_queued_jobs(limit=self.config.dispatch_batch_size)
        if not queued:
            return 0

        job_ids = [int(row["id"]) for row in queued]
        guids = [str(row["message_guid"]) for row in queued]
        oldest_epoch = min(int(row["timestamp_epoch"]) for row in queued)
        lookback = compute_dispatch_lookback_minutes(
            oldest_queued_epoch=oldest_epoch,
            now_epoch=int(time.time()),
            max_minutes=self.config.max_lookback_minutes,
        )

        self.store.mark_jobs_running(job_ids)
        cmd = [str(self.config.inbox_monitor_path), "--interval", str(lookback)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "inbox-monitor failed").strip()
            for guid in guids:
                self.store.mark_job_result(guid, success=False, error=err)
            logger.error("Dispatch failed (code=%d): %s", proc.returncode, err)
            return 0

        processed_ids = self._load_processed_ids()
        dispatched = 0
        for guid in guids:
            if guid in processed_ids:
                self.store.mark_job_result(guid, success=True)
                dispatched += 1
            else:
                self.store.mark_job_result(
                    guid,
                    success=False,
                    error="guid_not_marked_processed_by_inbox_monitor",
                )
        return dispatched

    def _load_processed_ids(self) -> set[str]:
        if not self.config.processed_file.exists():
            return set()
        try:
            payload = json.loads(self.config.processed_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Processed file is not valid JSON: %s", self.config.processed_file)
            return set()
        values = payload.get("processed_ids", [])
        if not isinstance(values, list):
            return set()
        return {str(v) for v in values}
