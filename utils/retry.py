# utils/retry.py
import asyncio
import logging
from functools import wraps

import anthropic

logger = logging.getLogger(__name__)

RETRYABLE_EXCEPTIONS = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
)

MAX_RETRIES = 3
BASE_DELAY = 1  # seconds


def retry_api_call(func):
    """Decorator that retries async Anthropic API calls with exponential backoff."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await func(*args, **kwargs)
            except RETRYABLE_EXCEPTIONS as exc:
                last_exception = exc
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "API call failed (attempt %d/%d): %s. Retrying in %ds...",
                        attempt + 1,
                        MAX_RETRIES + 1,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "API call failed after %d attempts: %s",
                        MAX_RETRIES + 1,
                        exc,
                    )
        raise last_exception

    return wrapper
