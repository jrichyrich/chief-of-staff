# tests/test_retry.py
import asyncio
import logging
from unittest.mock import AsyncMock, patch

import anthropic
import httpx
import pytest

from utils.retry import retry_api_call, MAX_RETRIES, BASE_DELAY


# --- Helpers ---

def _make_rate_limit_error():
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com"))
    return anthropic.RateLimitError(message="rate limited", response=response, body=None)


def _make_internal_server_error():
    response = httpx.Response(500, request=httpx.Request("POST", "https://api.anthropic.com"))
    return anthropic.InternalServerError(message="internal error", response=response, body=None)


def _make_connection_error():
    return anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))


def _make_auth_error():
    response = httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com"))
    return anthropic.AuthenticationError(message="auth failed", response=response, body=None)


def _make_bad_request_error():
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com"))
    return anthropic.BadRequestError(message="bad request", response=response, body=None)


# --- Tests ---

@pytest.mark.asyncio
async def test_succeeds_without_retry():
    """Call succeeds on first attempt — no retries needed."""
    mock_fn = AsyncMock(return_value="ok")

    @retry_api_call
    async def fn():
        return await mock_fn()

    result = await fn()
    assert result == "ok"
    assert mock_fn.call_count == 1


@pytest.mark.asyncio
async def test_retries_on_rate_limit_then_succeeds():
    """RateLimitError triggers retry; succeeds on second attempt."""
    mock_fn = AsyncMock(side_effect=[_make_rate_limit_error(), "ok"])

    @retry_api_call
    async def fn():
        return await mock_fn()

    with patch("utils.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await fn()

    assert result == "ok"
    assert mock_fn.call_count == 2
    mock_sleep.assert_awaited_once_with(BASE_DELAY)


@pytest.mark.asyncio
async def test_retries_on_internal_server_error():
    """InternalServerError triggers retry."""
    mock_fn = AsyncMock(side_effect=[_make_internal_server_error(), "ok"])

    @retry_api_call
    async def fn():
        return await mock_fn()

    with patch("utils.retry.asyncio.sleep", new_callable=AsyncMock):
        result = await fn()

    assert result == "ok"
    assert mock_fn.call_count == 2


@pytest.mark.asyncio
async def test_retries_on_connection_error():
    """APIConnectionError triggers retry."""
    mock_fn = AsyncMock(side_effect=[_make_connection_error(), "ok"])

    @retry_api_call
    async def fn():
        return await mock_fn()

    with patch("utils.retry.asyncio.sleep", new_callable=AsyncMock):
        result = await fn()

    assert result == "ok"
    assert mock_fn.call_count == 2


@pytest.mark.asyncio
async def test_exhausts_retries_then_raises():
    """All retries fail — raises the last exception."""
    errors = [_make_rate_limit_error() for _ in range(MAX_RETRIES + 1)]
    mock_fn = AsyncMock(side_effect=errors)

    @retry_api_call
    async def fn():
        return await mock_fn()

    with patch("utils.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(anthropic.RateLimitError):
            await fn()

    assert mock_fn.call_count == MAX_RETRIES + 1
    assert mock_sleep.await_count == MAX_RETRIES


@pytest.mark.asyncio
async def test_exponential_backoff_delays():
    """Backoff delays double each attempt: 1s, 2s, 4s."""
    errors = [_make_rate_limit_error() for _ in range(MAX_RETRIES)]
    mock_fn = AsyncMock(side_effect=[*errors, "ok"])

    @retry_api_call
    async def fn():
        return await mock_fn()

    with patch("utils.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await fn()

    assert result == "ok"
    delays = [call.args[0] for call in mock_sleep.await_args_list]
    assert delays == [1, 2, 4]


@pytest.mark.asyncio
async def test_no_retry_on_auth_error():
    """AuthenticationError is NOT retried — raises immediately."""
    mock_fn = AsyncMock(side_effect=_make_auth_error())

    @retry_api_call
    async def fn():
        return await mock_fn()

    with pytest.raises(anthropic.AuthenticationError):
        await fn()

    assert mock_fn.call_count == 1


@pytest.mark.asyncio
async def test_no_retry_on_bad_request_error():
    """BadRequestError is NOT retried — raises immediately."""
    mock_fn = AsyncMock(side_effect=_make_bad_request_error())

    @retry_api_call
    async def fn():
        return await mock_fn()

    with pytest.raises(anthropic.BadRequestError):
        await fn()

    assert mock_fn.call_count == 1


@pytest.mark.asyncio
async def test_retry_logs_warnings(caplog):
    """Each retry attempt logs a warning."""
    mock_fn = AsyncMock(side_effect=[_make_rate_limit_error(), "ok"])

    @retry_api_call
    async def fn():
        return await mock_fn()

    with caplog.at_level(logging.WARNING, logger="utils.retry"):
        with patch("utils.retry.asyncio.sleep", new_callable=AsyncMock):
            await fn()

    assert any("Retrying in" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_retry_logs_error_on_final_failure(caplog):
    """Final failure logs an error."""
    errors = [_make_rate_limit_error() for _ in range(MAX_RETRIES + 1)]
    mock_fn = AsyncMock(side_effect=errors)

    @retry_api_call
    async def fn():
        return await mock_fn()

    with caplog.at_level(logging.ERROR, logger="utils.retry"):
        with patch("utils.retry.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(anthropic.RateLimitError):
                await fn()

    assert any("failed after" in record.message for record in caplog.records)
