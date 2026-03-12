"""Tests for vault.keychain — macOS Keychain integration with env var fallback."""

import subprocess
from unittest.mock import patch

import pytest

from vault.keychain import clear_secret_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the secret cache before and after each test."""
    clear_secret_cache()
    yield
    clear_secret_cache()


# ---------------------------------------------------------------------------
# get_secret
# ---------------------------------------------------------------------------

class TestGetSecret:
    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_get_secret_from_keychain(self, mock_run):
        """Keychain has the value — return it without checking env."""
        mock_run.return_value = _make_completed(stdout="my-secret-value\n")

        from vault.keychain import get_secret
        result = get_secret("m365_client_id")

        assert result == "my-secret-value"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "find-generic-password" in args
        assert "m365_client_id" in args

    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_get_secret_fallback_to_env(self, mock_run, monkeypatch):
        """Keychain lookup fails — fall back to environment variable."""
        mock_run.return_value = _make_completed(returncode=44, stderr="not found")
        monkeypatch.setenv("m365_client_id", "env-value")

        from vault.keychain import get_secret
        result = get_secret("m365_client_id")

        assert result == "env-value"

    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_get_secret_not_found(self, mock_run, monkeypatch):
        """Neither Keychain nor env has the secret — return None."""
        mock_run.return_value = _make_completed(returncode=44, stderr="not found")
        monkeypatch.delenv("m365_client_id", raising=False)

        from vault.keychain import get_secret
        result = get_secret("m365_client_id")

        assert result is None

    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_get_secret_cached(self, mock_run):
        """Second call for the same key uses cache, no subprocess."""
        mock_run.return_value = _make_completed(stdout="cached-value\n")

        from vault.keychain import get_secret
        result1 = get_secret("test_key")
        result2 = get_secret("test_key")

        assert result1 == result2 == "cached-value"
        mock_run.assert_called_once()  # Only one subprocess call

    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_get_secret_none_not_cached(self, mock_run, monkeypatch):
        """None results are NOT cached — second call retries subprocess."""
        mock_run.return_value = _make_completed(returncode=44, stderr="not found")
        monkeypatch.delenv("test_key", raising=False)

        from vault.keychain import get_secret
        result1 = get_secret("test_key")
        assert result1 is None

        result2 = get_secret("test_key")
        assert result2 is None

        assert mock_run.call_count == 2  # Called subprocess both times

    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_get_secret_timeout(self, mock_run, monkeypatch):
        """TimeoutExpired is caught, falls back to env, returns None if no env."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="security", timeout=10)
        monkeypatch.delenv("test_key", raising=False)

        from vault.keychain import get_secret
        result = get_secret("test_key")

        assert result is None

    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_get_secret_timeout_with_env_fallback(self, mock_run, monkeypatch):
        """TimeoutExpired is caught and falls back to env value."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="security", timeout=10)
        monkeypatch.setenv("test_key", "fallback-value")

        from vault.keychain import get_secret
        result = get_secret("test_key")

        assert result == "fallback-value"


# ---------------------------------------------------------------------------
# set_secret
# ---------------------------------------------------------------------------

class TestSetSecret:
    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_set_secret_success(self, mock_run):
        """Subprocess exits 0 — return True."""
        mock_run.return_value = _make_completed(returncode=0)

        from vault.keychain import set_secret
        result = set_secret("m365_client_id", "new-value")

        assert result is True
        args = mock_run.call_args[0][0]
        assert "add-generic-password" in args
        assert "-U" in args
        assert "new-value" in args

    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_set_secret_failure(self, mock_run):
        """Subprocess exits non-zero — return False."""
        mock_run.return_value = _make_completed(returncode=1, stderr="some error")

        from vault.keychain import set_secret
        result = set_secret("m365_client_id", "new-value")

        assert result is False

    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_set_secret_timeout(self, mock_run):
        """TimeoutExpired is caught — return False."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="security", timeout=10)

        from vault.keychain import set_secret
        result = set_secret("m365_client_id", "new-value")

        assert result is False


# ---------------------------------------------------------------------------
# delete_secret
# ---------------------------------------------------------------------------

class TestDeleteSecret:
    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_delete_secret_success(self, mock_run):
        """Subprocess exits 0 — return True."""
        mock_run.return_value = _make_completed(returncode=0)

        from vault.keychain import delete_secret
        result = delete_secret("m365_client_id")

        assert result is True
        args = mock_run.call_args[0][0]
        assert "delete-generic-password" in args

    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_delete_secret_not_found(self, mock_run):
        """Entry doesn't exist — subprocess returns non-zero, return False."""
        mock_run.return_value = _make_completed(returncode=44, stderr="not found")

        from vault.keychain import delete_secret
        result = delete_secret("m365_client_id")

        assert result is False

    @patch("vault.keychain._IS_MACOS", True)
    @patch("vault.keychain.subprocess.run")
    def test_delete_secret_timeout(self, mock_run):
        """TimeoutExpired is caught — return False."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="security", timeout=10)

        from vault.keychain import delete_secret
        result = delete_secret("m365_client_id")

        assert result is False


# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------

class TestKeyValidation:
    def test_empty_key_raises(self):
        """Empty key string raises ValueError."""
        from vault.keychain import get_secret, set_secret, delete_secret
        with pytest.raises(ValueError, match="Invalid secret key"):
            get_secret("")
        with pytest.raises(ValueError, match="Invalid secret key"):
            set_secret("", "value")
        with pytest.raises(ValueError, match="Invalid secret key"):
            delete_secret("")

    def test_special_chars_key_raises(self):
        """Keys with special characters raise ValueError."""
        from vault.keychain import get_secret, set_secret, delete_secret
        for bad_key in ["foo bar", "key;drop", "a/b", "x@y", "k=v", "$(cmd)"]:
            with pytest.raises(ValueError, match="Invalid secret key"):
                get_secret(bad_key)
            with pytest.raises(ValueError, match="Invalid secret key"):
                set_secret(bad_key, "value")
            with pytest.raises(ValueError, match="Invalid secret key"):
                delete_secret(bad_key)

    def test_too_long_key_raises(self):
        """Keys longer than 255 characters raise ValueError."""
        from vault.keychain import get_secret
        with pytest.raises(ValueError, match="Invalid secret key"):
            get_secret("a" * 256)

    def test_valid_keys_accepted(self):
        """Valid key patterns do not raise."""
        from vault.keychain import _validate_key
        for good_key in ["m365_client_id", "API.KEY", "my-secret", "KEY123", "a.b_c-d"]:
            _validate_key(good_key)  # Should not raise


# ---------------------------------------------------------------------------
# Non-macOS platform
# ---------------------------------------------------------------------------

class TestNonMacOS:
    @patch("vault.keychain._IS_MACOS", False)
    def test_non_macos_skips_keychain(self, monkeypatch):
        """On non-macOS, only check env — never call subprocess."""
        monkeypatch.setenv("m365_client_id", "linux-env-value")

        from vault.keychain import get_secret
        with patch("vault.keychain.subprocess.run") as mock_run:
            result = get_secret("m365_client_id")

        assert result == "linux-env-value"
        mock_run.assert_not_called()

    @patch("vault.keychain._IS_MACOS", False)
    def test_non_macos_set_secret_returns_false(self):
        """set_secret returns False on non-macOS without calling subprocess."""
        from vault.keychain import set_secret
        with patch("vault.keychain.subprocess.run") as mock_run:
            result = set_secret("m365_client_id", "value")

        assert result is False
        mock_run.assert_not_called()

    @patch("vault.keychain._IS_MACOS", False)
    def test_non_macos_delete_secret_returns_false(self):
        """delete_secret returns False on non-macOS without calling subprocess."""
        from vault.keychain import delete_secret
        with patch("vault.keychain.subprocess.run") as mock_run:
            result = delete_secret("m365_client_id")

        assert result is False
        mock_run.assert_not_called()
