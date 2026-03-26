"""Tests for GraphClient.get_schedule — free/busy schedule retrieval.

All MSAL and httpx calls are mocked; no real auth or HTTP requests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from connectors.graph_client import GraphAPIError, GraphClient


# ---------------------------------------------------------------------------
# Fixtures & helpers
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
    gc._scopes = ["Calendars.ReadWrite"]
    gc._interactive = True
    gc._app = mock_msal_app
    gc._public_app = mock_msal_app
    gc._confidential_app = None
    gc._http = _make_http_client()
    gc._calendar_name_cache = {}
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
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_schedule_single_user(client):
    """Single user schedule: verify POST payload and normalized response."""
    graph_response = {
        "value": [
            {
                "scheduleId": "alice@example.com",
                "availabilityView": "0220000",
                "scheduleItems": [
                    {
                        "status": "busy",
                        "start": {
                            "dateTime": "2026-03-20T10:00:00",
                            "timeZone": "America/Denver",
                        },
                        "end": {
                            "dateTime": "2026-03-20T11:00:00",
                            "timeZone": "America/Denver",
                        },
                    }
                ],
            }
        ]
    }
    client._http.request.return_value = _make_response(json_data=graph_response)

    result = await client.get_schedule(
        schedules=["alice@example.com"],
        start="2026-03-20T08:00:00",
        end="2026-03-20T17:00:00",
    )

    # Verify the POST was called with correct payload
    call_args = client._http.request.call_args
    assert call_args[0][0] == "POST"
    assert "/me/calendar/getSchedule" in call_args[0][1]

    payload = call_args[1]["json"]
    assert payload["schedules"] == ["alice@example.com"]
    assert payload["startTime"]["dateTime"] == "2026-03-20T08:00:00"
    assert payload["startTime"]["timeZone"] == "America/Denver"
    assert payload["endTime"]["dateTime"] == "2026-03-20T17:00:00"
    assert payload["availabilityViewInterval"] == 30

    # Verify normalized response
    assert len(result) == 1
    assert result[0]["email"] == "alice@example.com"
    assert result[0]["availability_view"] == "0220000"
    assert len(result[0]["schedule_items"]) == 1
    assert result[0]["schedule_items"][0]["status"] == "busy"
    assert result[0]["schedule_items"][0]["start"] == "2026-03-20T10:00:00"
    assert result[0]["schedule_items"][0]["end"] == "2026-03-20T11:00:00"


@pytest.mark.asyncio
async def test_get_schedule_multiple_users(client):
    """Three users in a single batch — all returned in one API call."""
    graph_response = {
        "value": [
            {
                "scheduleId": "alice@example.com",
                "availabilityView": "0000",
                "scheduleItems": [],
            },
            {
                "scheduleId": "bob@example.com",
                "availabilityView": "2200",
                "scheduleItems": [
                    {
                        "status": "busy",
                        "start": {"dateTime": "2026-03-20T09:00:00", "timeZone": "America/Denver"},
                        "end": {"dateTime": "2026-03-20T10:00:00", "timeZone": "America/Denver"},
                    },
                ],
            },
            {
                "scheduleId": "carol@example.com",
                "availabilityView": "0020",
                "scheduleItems": [
                    {
                        "status": "tentative",
                        "start": {"dateTime": "2026-03-20T14:00:00", "timeZone": "America/Denver"},
                        "end": {"dateTime": "2026-03-20T15:00:00", "timeZone": "America/Denver"},
                    },
                ],
            },
        ]
    }
    client._http.request.return_value = _make_response(json_data=graph_response)

    result = await client.get_schedule(
        schedules=["alice@example.com", "bob@example.com", "carol@example.com"],
        start="2026-03-20T08:00:00",
        end="2026-03-20T17:00:00",
    )

    # Single API call for 3 users (under batch limit of 20)
    assert client._http.request.call_count == 1

    assert len(result) == 3
    assert result[0]["email"] == "alice@example.com"
    assert result[1]["email"] == "bob@example.com"
    assert result[2]["email"] == "carol@example.com"
    assert result[1]["schedule_items"][0]["status"] == "busy"
    assert result[2]["schedule_items"][0]["status"] == "tentative"


@pytest.mark.asyncio
async def test_get_schedule_batching(client):
    """25 users should result in 2 API calls (20 + 5)."""

    def make_batch_response(emails):
        return _make_response(json_data={
            "value": [
                {
                    "scheduleId": email,
                    "availabilityView": "0000",
                    "scheduleItems": [],
                }
                for email in emails
            ]
        })

    all_emails = [f"user{i}@example.com" for i in range(25)]

    # Return different responses for each batch call
    client._http.request.side_effect = [
        make_batch_response(all_emails[:20]),
        make_batch_response(all_emails[20:]),
    ]

    result = await client.get_schedule(
        schedules=all_emails,
        start="2026-03-20T08:00:00",
        end="2026-03-20T17:00:00",
    )

    # Verify 2 API calls were made
    assert client._http.request.call_count == 2

    # First batch: 20 users
    first_call_payload = client._http.request.call_args_list[0][1]["json"]
    assert len(first_call_payload["schedules"]) == 20

    # Second batch: 5 users
    second_call_payload = client._http.request.call_args_list[1][1]["json"]
    assert len(second_call_payload["schedules"]) == 5

    # All 25 results returned
    assert len(result) == 25
    assert result[0]["email"] == "user0@example.com"
    assert result[24]["email"] == "user24@example.com"


@pytest.mark.asyncio
async def test_get_schedule_empty_items(client):
    """User with no schedule items returns empty schedule_items list."""
    graph_response = {
        "value": [
            {
                "scheduleId": "free@example.com",
                "availabilityView": "0000000000",
                "scheduleItems": [],
            }
        ]
    }
    client._http.request.return_value = _make_response(json_data=graph_response)

    result = await client.get_schedule(
        schedules=["free@example.com"],
        start="2026-03-20T08:00:00",
        end="2026-03-20T17:00:00",
    )

    assert len(result) == 1
    assert result[0]["email"] == "free@example.com"
    assert result[0]["availability_view"] == "0000000000"
    assert result[0]["schedule_items"] == []


@pytest.mark.asyncio
async def test_get_schedule_api_error_403(client):
    """403 response (e.g., external user) raises GraphAPIError."""
    error_response = _make_response(
        status_code=403,
        json_data={
            "error": {
                "code": "ErrorAccessDenied",
                "message": "Access is denied. Check credentials and try again.",
            }
        },
        text="ErrorAccessDenied: Access is denied. Check credentials and try again.",
    )
    client._http.request.return_value = error_response

    with pytest.raises(GraphAPIError, match="403"):
        await client.get_schedule(
            schedules=["external@other.org"],
            start="2026-03-20T08:00:00",
            end="2026-03-20T17:00:00",
        )
