"""File-drop inbox ingestion for webhook events.

External automations drop JSON files into the inbox directory.
This module scans, validates, and ingests them into the webhook_events table.

Usage:
    python -m webhook.ingest
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("jarvis-webhook-ingest")


def ingest_events(
    memory_store,
    inbox_dir: Path,
) -> dict:
    """Scan inbox_dir for *.json files and ingest valid events.

    Each JSON file must contain:
        {"source": "...", "event_type": "...", "payload": {...}}

    Valid events are stored via memory_store.store_webhook_event().
    Processed files move to inbox_dir/processed/.
    Malformed files move to inbox_dir/failed/.

    Returns dict with counts: {"ingested": N, "failed": N, "skipped": N}
    """
    from memory.models import WebhookEvent

    inbox_dir = Path(inbox_dir)
    processed_dir = inbox_dir / "processed"
    failed_dir = inbox_dir / "failed"

    processed_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    counts = {"ingested": 0, "failed": 0, "skipped": 0}

    json_files = sorted(inbox_dir.glob("*.json"))
    if not json_files:
        logger.info("No JSON files found in %s", inbox_dir)
        return counts

    for filepath in json_files:
        try:
            raw = filepath.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            logger.warning("Malformed file %s: %s", filepath.name, exc)
            _move_file(filepath, failed_dir)
            counts["failed"] += 1
            continue

        # Validate required fields
        source = data.get("source") if isinstance(data, dict) else None
        event_type = data.get("event_type") if isinstance(data, dict) else None
        if not source or not event_type:
            logger.warning(
                "Missing required fields (source, event_type) in %s", filepath.name
            )
            _move_file(filepath, failed_dir)
            counts["failed"] += 1
            continue

        # Normalize payload to string
        payload = data.get("payload", "")
        if not isinstance(payload, str):
            payload = json.dumps(payload)

        event = WebhookEvent(
            source=source,
            event_type=event_type,
            payload=payload,
        )
        stored = memory_store.store_webhook_event(event)
        logger.info(
            "Ingested event id=%s source=%s type=%s from %s",
            stored.id,
            source,
            event_type,
            filepath.name,
        )
        _move_file(filepath, processed_dir)
        counts["ingested"] += 1

    logger.info(
        "Ingest complete: %d ingested, %d failed, %d skipped",
        counts["ingested"],
        counts["failed"],
        counts["skipped"],
    )
    return counts


def _move_file(src: Path, dest_dir: Path) -> Path:
    """Move file to dest_dir, appending timestamp if name collides."""
    dest = dest_dir / src.name
    if dest.exists():
        stem = src.stem
        suffix = src.suffix
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        dest = dest_dir / f"{stem}_{timestamp}{suffix}"
    shutil.move(str(src), str(dest))
    return dest


def _setup_logging(log_path: Path):
    """Configure logging to file and stderr."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stderr),
        ],
    )


if __name__ == "__main__":
    # Add parent dir to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from config import DATA_DIR, MEMORY_DB_PATH, WEBHOOK_INBOX_DIR
    from memory.store import MemoryStore

    _setup_logging(DATA_DIR / "webhook-ingest.log")

    if not MEMORY_DB_PATH.exists():
        logger.error("Memory DB not found at %s", MEMORY_DB_PATH)
        sys.exit(1)

    WEBHOOK_INBOX_DIR.mkdir(parents=True, exist_ok=True)

    store = MemoryStore(MEMORY_DB_PATH)
    try:
        result = ingest_events(store, WEBHOOK_INBOX_DIR)
        logger.info("Result: %s", result)
    finally:
        store.close()
