"""Tests for connectors.graph_client — Microsoft Graph API client.

All MSAL and httpx calls are mocked; no real auth or HTTP requests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.graph_client import (
    GraphAPIError,
    GraphAuthError,
    GraphClient,
    GraphTransientError,
    _DEFAULT_SCOPES,
)


# ---------------------------------------------------------------------------
# Scope tests
# ---------------------------------------------------------------------------


def test_default_scopes_include_chat_readwrite():
    """_DEFAULT_SCOPES must include Chat.ReadWrite for chat creation."""
    assert "Chat.ReadWrite" in _DEFAULT_SCOPES


def test_default_scopes_include_user_read_basic_all():
    """_DEFAULT_SCOPES must include User.ReadBasic.All for user resolution."""
    assert "User.ReadBasic.All" in _DEFAULT_SCOPES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_msal_app():
    """Return a mock MSAL PublicClientApplication."""
    app = MagicMock()
    app.get_accounts.return_value = [{"username": "user@example.com"}]
    app.acquire_token_silent.return_value = {
        "access_token": "test-token-123",
        "id_token_claims": {"iat": 9999999999},
    }
    return app


def _make_http_client():
    """Create a mock httpx.AsyncClient with explicit request method."""
    http = MagicMock()
    http.request = AsyncMock()
    http.aclose = AsyncMock()
    return http


@pytest.fixture()
def client(mock_msal_app):
    """Create a GraphClient with mocked MSAL and httpx."""
    gc = GraphClient.__new__(GraphClient)
    gc._client_id = "test-client-id"
    gc._tenant_id = "test-tenant-id"
    gc._scopes = ["Chat.ReadWrite", "ChatMessage.Send", "Mail.Send", "User.Read", "User.ReadBasic.All"]
    gc._interactive = True
    gc._is_confidential = False
    gc._app = mock_msal_app
    gc._public_app = mock_msal_app
    gc._confidential_app = None
    gc._http = _make_http_client()
    return gc


def _make_response(
    status_code: int = 200,
    json_data: dict | None = None,
    headers: dict | None = None,
    content: bytes = b"ok",
    text: str = "",
):
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.content = content
    resp.text = text or str(json_data or "")
    return resp


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_authenticated_silent_success(client, mock_msal_app):
    """Cached token acquired via acquire_token_silent."""
    token = await client.ensure_authenticated()
    assert token == "test-token-123"
    mock_msal_app.acquire_token_silent.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_authenticated_device_code_fallback(client, mock_msal_app):
    """When silent fails, public client uses device code flow."""
    client._is_confidential = False
    mock_msal_app.acquire_token_silent.return_value = None
    mock_msal_app.initiate_device_flow.return_value = {
        "user_code": "ABC123",
        "verification_uri": "https://microsoft.com/devicelogin",
    }
    mock_msal_app.acquire_token_by_device_flow.return_value = {
        "access_token": "device-code-token",
    }

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("connectors.graph_client.asyncio.to_thread", side_effect=fake_to_thread):
        token = await client.ensure_authenticated()

    assert token == "device-code-token"
    mock_msal_app.initiate_device_flow.assert_called_once()
    mock_msal_app.acquire_token_by_device_flow.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_authenticated_auth_code_flow(client, mock_msal_app):
    """When silent fails, confidential client uses auth code flow."""
    client._is_confidential = True
    mock_msal_app.acquire_token_silent.return_value = None

    with patch.object(client, "_auth_code_flow", new_callable=AsyncMock) as mock_flow:
        mock_flow.return_value = {"access_token": "auth-code-token"}
        token = await client.ensure_authenticated()

    assert token == "auth-code-token"
    mock_flow.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_authenticated_headless_raises(client, mock_msal_app):
    """In headless mode (interactive=False), auth failure raises GraphAuthError."""
    client._interactive = False
    mock_msal_app.acquire_token_silent.return_value = None

    with pytest.raises(GraphAuthError, match="headless mode"):
        await client.ensure_authenticated()


@pytest.mark.asyncio
async def test_ensure_authenticated_confidential_headless(client, mock_msal_app):
    """Confidential client in headless mode uses client credentials grant."""
    client._interactive = False
    client._is_confidential = True
    # No cached delegated accounts
    mock_msal_app.get_accounts.return_value = []
    # Set up a separate confidential app mock for client credentials
    confidential_mock = MagicMock()
    confidential_mock.acquire_token_for_client.return_value = {
        "access_token": "client-creds-token",
    }
    client._confidential_app = confidential_mock

    token = await client.ensure_authenticated()
    assert token == "client-creds-token"
    confidential_mock.acquire_token_for_client.assert_called_once()


# ---------------------------------------------------------------------------
# _request tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_success(client):
    """200 response is parsed and returned as dict."""
    expected = {"value": [{"id": "1"}]}
    client._http.request.return_value = _make_response(200, expected)

    result = await client._request("GET", "/me/chats")
    assert result == expected


@pytest.mark.asyncio
async def test_request_401_retry(client, mock_msal_app):
    """401 clears account cache, refreshes token, and retries."""
    fail_resp = _make_response(401, text="Unauthorized")
    success_resp = _make_response(200, {"value": []})
    client._http.request.side_effect = [fail_resp, success_resp]

    # After remove_account, get_accounts returns empty, then device code flow
    account = {"username": "user@example.com"}
    mock_msal_app.get_accounts.side_effect = [
        [account],   # initial ensure_authenticated
        [account],   # 401 handler calls get_accounts to iterate & remove
        [],          # retry ensure_authenticated — no accounts
    ]
    mock_msal_app.acquire_token_silent.side_effect = [
        {"access_token": "test-token-123", "id_token_claims": {"iat": 9999999999}},
        None,  # after account removal, silent returns None
    ]
    mock_msal_app.initiate_device_flow.return_value = {
        "user_code": "ABC123",
        "verification_uri": "https://microsoft.com/devicelogin",
    }
    mock_msal_app.acquire_token_by_device_flow.return_value = {
        "access_token": "refreshed-token",
    }

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("connectors.graph_client.asyncio.to_thread", side_effect=fake_to_thread):
        result = await client._request("GET", "/me/chats")

    assert result == {"value": []}
    assert client._http.request.call_count == 2
    mock_msal_app.remove_account.assert_called_once_with(account)


@pytest.mark.asyncio
async def test_request_429_retry(client):
    """429 respects Retry-After header and retries."""
    rate_limited = _make_response(429, headers={"Retry-After": "0"}, text="Rate limited")
    success = _make_response(200, {"ok": True})
    client._http.request.side_effect = [rate_limited, success]

    with patch("connectors.graph_client.asyncio.sleep", new_callable=AsyncMock):
        result = await client._request("GET", "/me/chats")

    assert result == {"ok": True}
    assert client._http.request.call_count == 2


@pytest.mark.asyncio
async def test_request_500_transient_error(client):
    """5xx raises GraphTransientError after retries are exhausted."""
    client._http.request.return_value = _make_response(503, text="Service Unavailable")

    with patch("connectors.graph_client.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(GraphTransientError, match="503"):
            await client._request("GET", "/me/chats")
    # 1 initial + 2 retries = 3 total attempts
    assert client._http.request.call_count == 3


@pytest.mark.asyncio
async def test_request_400_api_error(client):
    """4xx (non-401/429) raises GraphAPIError."""
    client._http.request.return_value = _make_response(400, text="Bad Request")

    with pytest.raises(GraphAPIError, match="400"):
        await client._request("GET", "/me/chats")


# ---------------------------------------------------------------------------
# Teams method tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_chat_message(client):
    """send_chat_message makes correct POST call."""
    expected = {"id": "msg-1", "body": {"content": "Hello"}}
    client._http.request.return_value = _make_response(201, expected)

    result = await client.send_chat_message("chat-123", "Hello")
    assert result == expected

    # Verify the POST was made to the right path with correct body
    call_args = client._http.request.call_args
    assert call_args[0][0] == "POST"
    assert "/me/chats/chat-123/messages" in call_args[0][1]
    assert call_args[1]["json"] == {
        "body": {"content": "Hello", "contentType": "text"}
    }


# ---------------------------------------------------------------------------
# Email method tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_mail(client):
    """send_mail constructs correct recipient structure including bcc."""
    resp = _make_response(202)
    resp.content = b""
    client._http.request.return_value = resp

    result = await client.send_mail(
        to=["bob@example.com"],
        subject="Test",
        body="Hello Bob",
        cc=["alice@example.com"],
        bcc=["secret@example.com"],
    )
    assert result == {"status": "success"}

    call_args = client._http.request.call_args
    assert call_args[0][0] == "POST"
    assert "/me/sendMail" in call_args[0][1]
    payload = call_args[1]["json"]
    assert payload["message"]["subject"] == "Test"
    assert payload["message"]["toRecipients"] == [
        {"emailAddress": {"address": "bob@example.com"}}
    ]
    assert payload["message"]["ccRecipients"] == [
        {"emailAddress": {"address": "alice@example.com"}}
    ]
    assert payload["message"]["bccRecipients"] == [
        {"emailAddress": {"address": "secret@example.com"}}
    ]


@pytest.mark.asyncio
async def test_reply_mail(client):
    """reply_mail makes correct POST call."""
    resp = _make_response(202)
    resp.content = b""
    client._http.request.return_value = resp

    result = await client.reply_mail("msg-abc", "Thanks!")
    assert result == {"status": "success"}

    call_args = client._http.request.call_args
    assert call_args[0][0] == "POST"
    assert "/me/messages/msg-abc/reply" in call_args[0][1]
    assert call_args[1]["json"] == {"comment": "Thanks!"}


@pytest.mark.asyncio
async def test_reply_mail_reply_all(client):
    """reply_mail with reply_all=True uses /replyAll endpoint."""
    resp = _make_response(202)
    resp.content = b""
    client._http.request.return_value = resp

    result = await client.reply_mail(
        "msg-abc",
        "Thanks everyone!",
        reply_all=True,
        cc=["extra@example.com"],
    )
    assert result == {"status": "success"}

    call_args = client._http.request.call_args
    assert call_args[0][0] == "POST"
    assert "/me/messages/msg-abc/replyAll" in call_args[0][1]
    payload = call_args[1]["json"]
    assert payload["comment"] == "Thanks everyone!"
    assert payload["message"]["ccRecipients"] == [
        {"emailAddress": {"address": "extra@example.com"}}
    ]


@pytest.mark.asyncio
async def test_confidential_headless_uses_default_scope(client, mock_msal_app):
    """Confidential client in headless mode uses .default scope for client credentials."""
    client._interactive = False
    client._is_confidential = True
    mock_msal_app.get_accounts.return_value = []
    confidential_mock = MagicMock()
    confidential_mock.acquire_token_for_client.return_value = {
        "access_token": "client-creds-token",
    }
    client._confidential_app = confidential_mock

    token = await client.ensure_authenticated()
    assert token == "client-creds-token"
    confidential_mock.acquire_token_for_client.assert_called_once_with(
        scopes=["https://graph.microsoft.com/.default"]
    )


@pytest.mark.asyncio
async def test_request_5xx_retry_then_success(client):
    """5xx responses are retried up to 2 times with exponential backoff."""
    fail_resp = _make_response(502, text="Bad Gateway")
    success_resp = _make_response(200, {"ok": True})
    client._http.request.side_effect = [fail_resp, success_resp]

    with patch("connectors.graph_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await client._request("GET", "/me/chats")

    assert result == {"ok": True}
    assert client._http.request.call_count == 2
    # First retry waits 2^0 = 1 second
    mock_sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_request_retry_after_parse_failure(client):
    """Non-numeric Retry-After header falls back to 5 seconds."""
    rate_limited = _make_response(429, headers={"Retry-After": "not-a-number"}, text="Rate limited")
    success = _make_response(200, {"ok": True})
    client._http.request.side_effect = [rate_limited, success]

    with patch("connectors.graph_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await client._request("GET", "/me/chats")

    assert result == {"ok": True}
    mock_sleep.assert_awaited_once_with(5)


# ---------------------------------------------------------------------------
# get_authenticated_email tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_authenticated_email(client, mock_msal_app):
    """get_authenticated_email returns the cached account username."""
    result = await client.get_authenticated_email()
    assert result == "user@example.com"


@pytest.mark.asyncio
async def test_get_authenticated_email_no_accounts(client, mock_msal_app):
    """get_authenticated_email returns None when no accounts cached."""
    mock_msal_app.get_accounts.return_value = []
    result = await client.get_authenticated_email()
    assert result is None


# ---------------------------------------------------------------------------
# create_chat group/oneOnOne tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_chat_group_includes_self(client):
    """create_chat for group (2+ members) includes authenticated user."""
    client._http.request.return_value = _make_response(201, {"id": "chat-group-1"})
    client._app.get_accounts.return_value = [{"username": "me@example.com"}]

    result = await client.create_chat(["alice@example.com", "bob@example.com"])
    assert result == {"id": "chat-group-1"}

    call_args = client._http.request.call_args
    payload = call_args[1]["json"]
    assert payload["chatType"] == "group"
    member_bindings = [m["user@odata.bind"] for m in payload["members"]]
    assert "https://graph.microsoft.com/v1.0/users/me@example.com" in member_bindings
    assert "https://graph.microsoft.com/v1.0/users/alice@example.com" in member_bindings
    assert "https://graph.microsoft.com/v1.0/users/bob@example.com" in member_bindings


@pytest.mark.asyncio
async def test_create_chat_oneOnOne_does_not_duplicate_self(client):
    """create_chat for 1:1 does NOT add self - Graph handles it automatically."""
    client._http.request.return_value = _make_response(201, {"id": "chat-1on1"})

    result = await client.create_chat(["alice@example.com"])
    assert result == {"id": "chat-1on1"}

    call_args = client._http.request.call_args
    payload = call_args[1]["json"]
    assert payload["chatType"] == "oneOnOne"
    assert len(payload["members"]) == 1  # Only Alice, not self


# ---------------------------------------------------------------------------
# Lifecycle test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close(client):
    """close() calls aclose on the httpx client."""
    await client.close()
    client._http.aclose.assert_awaited_once()
