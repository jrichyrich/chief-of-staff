"""Unified secret retrieval: macOS Keychain first, env var fallback.

Results are cached after first lookup per key to avoid repeated subprocess calls
(e.g., when config.py reads secrets at import time).
"""

import logging
import os
import platform
import re
import subprocess

logger = logging.getLogger(__name__)

KEYCHAIN_SERVICE = "jarvis"

_IS_MACOS = platform.system() == "Darwin"

# Module-level cache: avoids subprocess overhead on repeated calls.
_cache: dict[str, str | None] = {}

_KEY_PATTERN = re.compile(r'^[a-zA-Z0-9_.-]+$')


def _validate_key(key: str) -> None:
    """Validate a secret key name."""
    if not key or not _KEY_PATTERN.match(key) or len(key) > 255:
        raise ValueError(f"Invalid secret key: {key!r}")


def clear_secret_cache() -> None:
    """Clear the in-memory secret cache, forcing fresh lookups."""
    _cache.clear()


def get_secret(key: str) -> str | None:
    """Retrieve a secret by key.

    Tries macOS Keychain first, then falls back to ``os.environ``.
    Returns ``None`` if the secret is not found in either location.
    Results are cached after first call per key (only non-None values).
    """
    _validate_key(key)

    if key in _cache:
        return _cache[key]

    value = _get_secret_uncached(key)
    if value is not None:
        _cache[key] = value
    return value


def _get_secret_uncached(key: str) -> str | None:
    """Internal: fetch secret without cache."""
    if _IS_MACOS:
        try:
            result = subprocess.run(
                [
                    "security",
                    "find-generic-password",
                    "-s", KEYCHAIN_SERVICE,
                    "-a", key,
                    "-w",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                value = result.stdout.strip()
                if value:
                    logger.debug("Secret '%s' retrieved from Keychain", key)
                    return value
        except subprocess.TimeoutExpired:
            logger.warning("Keychain lookup timed out for '%s'", key)
        except FileNotFoundError:
            logger.warning("'security' CLI not found; skipping Keychain lookup")
        except Exception:
            logger.warning("Keychain lookup failed for '%s'", key, exc_info=True)

    # Fallback to environment variable
    env_value = os.environ.get(key)
    if env_value is not None:
        logger.debug("Secret '%s' retrieved from environment", key)
    return env_value


def set_secret(key: str, value: str) -> bool:
    """Store a secret in the macOS Keychain.

    The ``-U`` flag updates the entry if it already exists.
    Returns ``True`` on success, ``False`` otherwise.
    Invalidates the cache for the given key on success.
    """
    _validate_key(key)

    if not _IS_MACOS:
        logger.warning("set_secret is only supported on macOS")
        return False

    try:
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-s", KEYCHAIN_SERVICE,
                "-a", key,
                "-w", value,
                "-U",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.debug("Secret '%s' stored in Keychain", key)
            _cache.pop(key, None)  # Invalidate cache
            return True
        logger.warning(
            "Failed to store secret '%s' in Keychain (rc=%d): %s",
            key, result.returncode, result.stderr.strip(),
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Keychain store timed out for '%s'", key)
        return False
    except FileNotFoundError:
        logger.warning("'security' CLI not found; cannot store secret")
        return False
    except Exception:
        logger.warning("Failed to store secret '%s'", key, exc_info=True)
        return False


def delete_secret(key: str) -> bool:
    """Remove a secret from the macOS Keychain.

    Returns ``True`` on success, ``False`` if the entry was not found
    or the operation failed. Invalidates the cache for the given key.
    """
    _validate_key(key)

    if not _IS_MACOS:
        logger.warning("delete_secret is only supported on macOS")
        return False

    try:
        result = subprocess.run(
            [
                "security",
                "delete-generic-password",
                "-s", KEYCHAIN_SERVICE,
                "-a", key,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.debug("Secret '%s' deleted from Keychain", key)
            _cache.pop(key, None)  # Invalidate cache
            return True
        logger.warning(
            "Failed to delete secret '%s' from Keychain (rc=%d): %s",
            key, result.returncode, result.stderr.strip(),
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Keychain delete timed out for '%s'", key)
        return False
    except FileNotFoundError:
        logger.warning("'security' CLI not found; cannot delete secret")
        return False
    except Exception:
        logger.warning("Failed to delete secret '%s'", key, exc_info=True)
        return False
