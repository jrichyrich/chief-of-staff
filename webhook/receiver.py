"""Standalone entry point for the webhook inbox ingestion.

Usage:
    python -m webhook.receiver
"""

import logging
import sys

import config as app_config
from memory.store import MemoryStore
from webhook.ingest import ingest_events

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)


def main():
    app_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    inbox_dir = app_config.WEBHOOK_INBOX_DIR
    inbox_dir.mkdir(parents=True, exist_ok=True)

    memory_store = MemoryStore(app_config.MEMORY_DB_PATH)
    try:
        result = ingest_events(memory_store, inbox_dir)
        print(f"Ingest result: {result}")
    finally:
        memory_store.close()


if __name__ == "__main__":
    main()
