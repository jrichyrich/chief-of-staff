"""Tests for session/context_config.py."""

from session.context_config import ContextLoaderConfig


class TestContextLoaderConfig:
    def test_default_config_values(self):
        """Verify ContextLoaderConfig has correct defaults."""
        config = ContextLoaderConfig()

        assert config.enabled is True
        assert config.per_source_timeout_seconds == 10
        assert config.ttl_minutes == 15
        assert config.sources == {
            "calendar": True,
            "mail": True,
            "delegations": True,
            "decisions": True,
            "reminders": True,
            "brain": True,
        }

    def test_config_custom_values(self):
        """Custom values override defaults."""
        config = ContextLoaderConfig(
            enabled=False,
            per_source_timeout_seconds=5,
            ttl_minutes=30,
            sources={"calendar": True, "mail": False},
        )

        assert config.enabled is False
        assert config.per_source_timeout_seconds == 5
        assert config.ttl_minutes == 30
        assert config.sources == {"calendar": True, "mail": False}

    def test_config_from_env_vars(self, monkeypatch):
        """Verify config.py picks up SESSION_CONTEXT_* env vars."""
        monkeypatch.setenv("SESSION_CONTEXT_ENABLED", "false")
        monkeypatch.setenv("SESSION_CONTEXT_TIMEOUT", "5")
        monkeypatch.setenv("SESSION_CONTEXT_TTL", "30")
        monkeypatch.setenv("SESSION_CONTEXT_SOURCES", "calendar,brain")

        # Re-import config to pick up env vars
        import importlib
        import config as app_config
        importlib.reload(app_config)

        try:
            assert app_config.SESSION_CONTEXT_ENABLED is False
            assert app_config.SESSION_CONTEXT_TIMEOUT == 5
            assert app_config.SESSION_CONTEXT_TTL == 30
            assert app_config.SESSION_CONTEXT_SOURCES == frozenset(["calendar", "brain"])
        finally:
            # Restore defaults
            monkeypatch.delenv("SESSION_CONTEXT_ENABLED")
            monkeypatch.delenv("SESSION_CONTEXT_TIMEOUT")
            monkeypatch.delenv("SESSION_CONTEXT_TTL")
            monkeypatch.delenv("SESSION_CONTEXT_SOURCES")
            importlib.reload(app_config)

    def test_config_env_invalid_timeout(self, monkeypatch):
        """Invalid timeout env var falls back to default."""
        monkeypatch.setenv("SESSION_CONTEXT_TIMEOUT", "not_a_number")

        import importlib
        import config as app_config
        importlib.reload(app_config)

        try:
            assert app_config.SESSION_CONTEXT_TIMEOUT == 10
        finally:
            monkeypatch.delenv("SESSION_CONTEXT_TIMEOUT")
            importlib.reload(app_config)

    def test_config_env_invalid_ttl(self, monkeypatch):
        """Invalid TTL env var falls back to default."""
        monkeypatch.setenv("SESSION_CONTEXT_TTL", "bad")

        import importlib
        import config as app_config
        importlib.reload(app_config)

        try:
            assert app_config.SESSION_CONTEXT_TTL == 15
        finally:
            monkeypatch.delenv("SESSION_CONTEXT_TTL")
            importlib.reload(app_config)
