"""Standalone entry point for the webhook receiver.

Usage:
    python -m webhook.receiver
"""

import asyncio
import logging
import sys

import config as app_config
from memory.store import MemoryStore
from webhook.server import run_webhook_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)


async def main():
    app_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    memory_store = MemoryStore(app_config.MEMORY_DB_PATH)

    port = app_config.WEBHOOK_PORT
    secret = app_config.WEBHOOK_SECRET

    server = await run_webhook_server(
        memory_store=memory_store,
        host="127.0.0.1",
        port=port,
        secret=secret,
    )

    try:
        await server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        await server.wait_closed()
        memory_store.close()


if __name__ == "__main__":
    asyncio.run(main())
