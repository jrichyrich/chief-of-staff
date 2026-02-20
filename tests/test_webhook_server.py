# tests/test_webhook_server.py
"""Tests for the webhook HTTP server."""

import asyncio
import hashlib
import hmac
import json
import socket

import pytest

from memory.store import MemoryStore
from webhook.server import (
    WebhookHandler,
    _make_response,
    _verify_signature,
    run_webhook_server,
)


@pytest.fixture
def memory_store(tmp_path):
    db_path = tmp_path / "test_webhook.db"
    store = MemoryStore(db_path)
    yield store
    store.close()


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _send_request(host, port, method, path, body=None, headers=None):
    """Send a raw HTTP request and return (status_code, response_body_dict)."""
    reader, writer = await asyncio.open_connection(host, port)

    body_bytes = json.dumps(body).encode() if body else b""
    header_lines = [f"{method} {path} HTTP/1.1", f"Host: {host}:{port}"]
    if body_bytes:
        header_lines.append(f"Content-Length: {len(body_bytes)}")
        header_lines.append("Content-Type: application/json")
    if headers:
        for key, value in headers.items():
            header_lines.append(f"{key}: {value}")
    header_lines.append("")
    header_lines.append("")
    request = "\r\n".join(header_lines).encode() + body_bytes

    writer.write(request)
    await writer.drain()

    response = await reader.read(4096)
    writer.close()
    await writer.wait_closed()

    # Parse response
    response_text = response.decode("utf-8", errors="replace")
    parts = response_text.split("\r\n\r\n", 1)
    status_line = parts[0].split("\r\n")[0]
    status_code = int(status_line.split(" ")[1])
    response_body = json.loads(parts[1]) if len(parts) > 1 and parts[1] else {}
    return status_code, response_body


class TestSignatureVerification:
    def test_valid_signature(self):
        body = b'{"source": "test", "event_type": "ping"}'
        secret = "mysecret"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert _verify_signature(body, sig, secret) is True

    def test_invalid_signature(self):
        body = b'{"source": "test", "event_type": "ping"}'
        assert _verify_signature(body, "bad_signature", "mysecret") is False

    def test_wrong_secret(self):
        body = b'{"source": "test", "event_type": "ping"}'
        sig = hmac.new(b"wrong_secret", body, hashlib.sha256).hexdigest()
        assert _verify_signature(body, sig, "mysecret") is False


class TestMakeResponse:
    def test_200_response(self):
        resp = _make_response(200, {"status": "ok"})
        assert b"HTTP/1.1 200 OK" in resp
        assert b"application/json" in resp
        assert b'"status": "ok"' in resp

    def test_404_response(self):
        resp = _make_response(404, {"error": "Not found"})
        assert b"HTTP/1.1 404 Not Found" in resp


@pytest.mark.asyncio
class TestWebhookServer:
    async def test_post_webhook_success(self, memory_store):
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret="")
        try:
            status, body = await _send_request(
                "127.0.0.1", port, "POST", "/webhook",
                body={"source": "github", "event_type": "push", "payload": {"ref": "main"}},
            )
            assert status == 200
            assert body["status"] == "received"
            assert body["event_id"] is not None

            # Verify event stored in DB
            event = memory_store.get_webhook_event(body["event_id"])
            assert event is not None
            assert event.source == "github"
            assert event.event_type == "push"
            assert json.loads(event.payload) == {"ref": "main"}
            assert event.status == "pending"
        finally:
            server.close()
            await server.wait_closed()

    async def test_post_webhook_with_valid_signature(self, memory_store):
        secret = "test_secret_key"
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret=secret)
        try:
            payload = json.dumps({"source": "slack", "event_type": "message"}).encode()
            sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

            status, body = await _send_request(
                "127.0.0.1", port, "POST", "/webhook",
                body={"source": "slack", "event_type": "message"},
                headers={"X-Webhook-Signature": sig},
            )
            assert status == 200
            assert body["status"] == "received"
        finally:
            server.close()
            await server.wait_closed()

    async def test_post_webhook_with_invalid_signature(self, memory_store):
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret="real_secret")
        try:
            status, body = await _send_request(
                "127.0.0.1", port, "POST", "/webhook",
                body={"source": "test", "event_type": "ping"},
                headers={"X-Webhook-Signature": "bad_sig"},
            )
            assert status == 401
            assert "Invalid signature" in body["error"]
        finally:
            server.close()
            await server.wait_closed()

    async def test_post_webhook_missing_signature(self, memory_store):
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret="real_secret")
        try:
            status, body = await _send_request(
                "127.0.0.1", port, "POST", "/webhook",
                body={"source": "test", "event_type": "ping"},
            )
            assert status == 401
            assert "Missing" in body["error"]
        finally:
            server.close()
            await server.wait_closed()

    async def test_post_webhook_missing_fields(self, memory_store):
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret="")
        try:
            status, body = await _send_request(
                "127.0.0.1", port, "POST", "/webhook",
                body={"source": "test"},
            )
            assert status == 400
            assert "Missing required fields" in body["error"]
        finally:
            server.close()
            await server.wait_closed()

    async def test_post_webhook_invalid_json(self, memory_store):
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret="")
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            bad_body = b"not json"
            request = (
                f"POST /webhook HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Content-Length: {len(bad_body)}\r\n"
                f"\r\n"
            ).encode() + bad_body
            writer.write(request)
            await writer.drain()
            response = await reader.read(4096)
            writer.close()
            await writer.wait_closed()

            resp_text = response.decode()
            assert "400" in resp_text
            assert "Invalid JSON" in resp_text
        finally:
            server.close()
            await server.wait_closed()

    async def test_wrong_method(self, memory_store):
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret="")
        try:
            status, body = await _send_request(
                "127.0.0.1", port, "GET", "/webhook",
            )
            assert status == 404
        finally:
            server.close()
            await server.wait_closed()

    async def test_wrong_path(self, memory_store):
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret="")
        try:
            status, body = await _send_request(
                "127.0.0.1", port, "POST", "/other",
                body={"source": "test", "event_type": "ping"},
            )
            assert status == 404
        finally:
            server.close()
            await server.wait_closed()

    async def test_health_check(self, memory_store):
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret="")
        try:
            status, body = await _send_request(
                "127.0.0.1", port, "GET", "/health",
            )
            assert status == 200
            assert body["status"] == "ok"
        finally:
            server.close()
            await server.wait_closed()

    async def test_string_payload_stored_as_is(self, memory_store):
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret="")
        try:
            status, body = await _send_request(
                "127.0.0.1", port, "POST", "/webhook",
                body={"source": "test", "event_type": "ping", "payload": "plain text"},
            )
            assert status == 200
            event = memory_store.get_webhook_event(body["event_id"])
            assert event.payload == "plain text"
        finally:
            server.close()
            await server.wait_closed()

    async def test_no_signature_required_when_no_secret(self, memory_store):
        port = _find_free_port()
        server = await run_webhook_server(memory_store, port=port, secret="")
        try:
            status, body = await _send_request(
                "127.0.0.1", port, "POST", "/webhook",
                body={"source": "test", "event_type": "ping"},
            )
            assert status == 200
        finally:
            server.close()
            await server.wait_closed()
