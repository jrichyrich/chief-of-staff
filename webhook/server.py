"""Lightweight HTTP webhook receiver using asyncio.

Accepts POST /webhook with JSON body and optional HMAC-SHA256 signature verification.
Stores events in the memory.db webhook_events table.
"""

import asyncio
import hashlib
import hmac
import json
import logging
from http import HTTPStatus
from typing import Optional

from memory.models import WebhookEvent
from memory.store import MemoryStore

logger = logging.getLogger("jarvis-webhook")


def _verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature. Returns True if valid."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _make_response(status: int, body: dict) -> bytes:
    """Build a minimal HTTP response."""
    payload = json.dumps(body).encode()
    reason = HTTPStatus(status).phrase
    headers = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )
    return headers.encode() + payload


class WebhookHandler(asyncio.Protocol):
    """asyncio protocol that handles one HTTP request per connection."""

    def __init__(self, memory_store: MemoryStore, secret: str):
        self.memory_store = memory_store
        self.secret = secret
        self.transport: Optional[asyncio.Transport] = None
        self._buffer = b""

    def connection_made(self, transport: asyncio.Transport):
        self.transport = transport

    def data_received(self, data: bytes):
        self._buffer += data
        # Wait until we have the full request (headers + body based on Content-Length)
        if b"\r\n\r\n" not in self._buffer:
            return

        header_end = self._buffer.index(b"\r\n\r\n")
        header_bytes = self._buffer[:header_end]
        body_start = header_end + 4

        # Parse Content-Length
        content_length = 0
        for line in header_bytes.decode("utf-8", errors="replace").split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
                break

        # Wait for full body
        if len(self._buffer) - body_start < content_length:
            return

        body = self._buffer[body_start:body_start + content_length]
        headers_text = header_bytes.decode("utf-8", errors="replace")
        self._handle_request(headers_text, body)

    def _parse_headers(self, headers_text: str) -> tuple[str, str, dict]:
        """Parse HTTP headers, returning (method, path, headers_dict)."""
        lines = headers_text.split("\r\n")
        request_line = lines[0]
        parts = request_line.split(" ", 2)
        method = parts[0] if len(parts) > 0 else ""
        path = parts[1] if len(parts) > 1 else ""
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        return method, path, headers

    def _handle_request(self, headers_text: str, body: bytes):
        method, path, headers = self._parse_headers(headers_text)

        # Health check endpoint
        if method == "GET" and path == "/health":
            self._send_response(200, {"status": "ok"})
            return

        # Only accept POST /webhook
        if method != "POST" or path != "/webhook":
            self._send_response(404, {"error": "Not found"})
            return

        # Verify signature if secret is configured
        if self.secret:
            signature = headers.get("x-webhook-signature", "")
            if not signature:
                self._send_response(401, {"error": "Missing X-Webhook-Signature header"})
                return
            if not _verify_signature(body, signature, self.secret):
                self._send_response(401, {"error": "Invalid signature"})
                return

        # Parse JSON body
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_response(400, {"error": "Invalid JSON body"})
            return

        # Validate required fields
        source = data.get("source")
        event_type = data.get("event_type")
        if not source or not event_type:
            self._send_response(400, {"error": "Missing required fields: source, event_type"})
            return

        # Store the event
        payload = data.get("payload", {})
        if not isinstance(payload, str):
            payload = json.dumps(payload)

        event = WebhookEvent(
            source=source,
            event_type=event_type,
            payload=payload,
        )
        stored = self.memory_store.store_webhook_event(event)
        logger.info("Webhook event stored: id=%s source=%s type=%s", stored.id, source, event_type)

        self._send_response(200, {
            "status": "received",
            "event_id": stored.id,
        })

    def _send_response(self, status: int, body: dict):
        if self.transport:
            self.transport.write(_make_response(status, body))
            self.transport.close()


async def run_webhook_server(
    memory_store: MemoryStore,
    host: str = "127.0.0.1",
    port: int = 8765,
    secret: str = "",
) -> asyncio.Server:
    """Start the webhook HTTP server. Returns the asyncio.Server instance."""
    loop = asyncio.get_running_loop()
    server = await loop.create_server(
        lambda: WebhookHandler(memory_store, secret),
        host,
        port,
    )
    logger.info("Webhook server listening on %s:%s", host, port)
    return server
