"""Tests for Graph API config settings in config.py."""

import importlib
import os
from unittest.mock import patch

import pytest


def _reload_config(**env_overrides):
    """Reload config module with the given env var overrides.

    Clears the vault.keychain cache before reloading so that
    get_secret picks up the fresh mock/env values.
    """
    try:
        from vault.keychain import clear_secret_cache
        clear_secret_cache()
    except ImportError:
        pass

    with patch.dict(os.environ, env_overrides, clear=False):
        # Remove keys not in overrides to simulate absence
        import config
        importlib.reload(config)
        return config


class TestM365GraphEnabled:
    """M365_GRAPH_ENABLED should reflect whether a client_id is available."""

    def test_disabled_when_no_client_id(self):
        """When get_secret returns None and no env var, M365_GRAPH_ENABLED is False."""
        with patch("vault.keychain.get_secret", return_value=None):
            with patch.dict(os.environ, {}, clear=False):
                # Remove any existing env vars that could provide values
                env = os.environ.copy()
                env.pop("m365_client_id", None)
                env.pop("m365_tenant_id", None)
                env.pop("TEAMS_SEND_BACKEND", None)
                env.pop("TEAMS_POSTER_BACKEND", None)
                env.pop("TEAMS_READ_BACKEND", None)
                env.pop("EMAIL_SEND_BACKEND", None)
                with patch.dict(os.environ, env, clear=True):
                    import config
                    importlib.reload(config)
                    assert config.M365_GRAPH_ENABLED is False
                    assert config.M365_CLIENT_ID == ""

    def test_enabled_when_client_id_present(self):
        """When get_secret returns a client_id, M365_GRAPH_ENABLED is True."""
        def mock_get_secret(key):
            secrets = {
                "m365_client_id": "test-client-id",
                "m365_tenant_id": "test-tenant-id",
            }
            return secrets.get(key)

        with patch("vault.keychain.get_secret", side_effect=mock_get_secret):
            env = os.environ.copy()
            env.pop("TEAMS_SEND_BACKEND", None)
            env.pop("TEAMS_POSTER_BACKEND", None)
            env.pop("TEAMS_READ_BACKEND", None)
            env.pop("EMAIL_SEND_BACKEND", None)
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.M365_GRAPH_ENABLED is True
                assert config.M365_CLIENT_ID == "test-client-id"
                assert config.M365_TENANT_ID == "test-tenant-id"


class TestTeamsSendBackend:
    """TEAMS_SEND_BACKEND defaults and env var handling."""

    def test_defaults_to_agent_browser_when_graph_disabled(self):
        """No Graph creds -> TEAMS_SEND_BACKEND defaults to 'agent-browser'."""
        with patch("vault.keychain.get_secret", return_value=None):
            env = os.environ.copy()
            env.pop("m365_client_id", None)
            env.pop("TEAMS_SEND_BACKEND", None)
            env.pop("TEAMS_POSTER_BACKEND", None)
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.TEAMS_SEND_BACKEND == "agent-browser"

    def test_defaults_to_graph_when_graph_enabled(self):
        """With Graph creds -> TEAMS_SEND_BACKEND defaults to 'graph'."""
        def mock_get_secret(key):
            return {"m365_client_id": "cid", "m365_tenant_id": "tid"}.get(key)

        with patch("vault.keychain.get_secret", side_effect=mock_get_secret):
            env = os.environ.copy()
            env.pop("TEAMS_SEND_BACKEND", None)
            env.pop("TEAMS_POSTER_BACKEND", None)
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.TEAMS_SEND_BACKEND == "graph"

    def test_env_var_overrides_default(self):
        """Explicit TEAMS_SEND_BACKEND env var takes precedence."""
        with patch("vault.keychain.get_secret", return_value=None):
            env = os.environ.copy()
            env.pop("m365_client_id", None)
            env["TEAMS_SEND_BACKEND"] = "playwright"
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.TEAMS_SEND_BACKEND == "playwright"

    def test_poster_backend_fallback(self):
        """TEAMS_POSTER_BACKEND is used as fallback when TEAMS_SEND_BACKEND is not set."""
        with patch("vault.keychain.get_secret", return_value=None):
            env = os.environ.copy()
            env.pop("m365_client_id", None)
            env.pop("TEAMS_SEND_BACKEND", None)
            env["TEAMS_POSTER_BACKEND"] = "playwright"
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.TEAMS_SEND_BACKEND == "playwright"

    def test_send_backend_wins_over_poster_backend(self):
        """TEAMS_SEND_BACKEND takes priority over TEAMS_POSTER_BACKEND."""
        with patch("vault.keychain.get_secret", return_value=None):
            env = os.environ.copy()
            env.pop("m365_client_id", None)
            env["TEAMS_SEND_BACKEND"] = "graph"
            env["TEAMS_POSTER_BACKEND"] = "playwright"
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.TEAMS_SEND_BACKEND == "graph"


class TestTeamsReadBackend:
    """TEAMS_READ_BACKEND defaults and env var handling."""

    def test_defaults_to_m365_bridge_when_graph_disabled(self):
        with patch("vault.keychain.get_secret", return_value=None):
            env = os.environ.copy()
            env.pop("m365_client_id", None)
            env.pop("TEAMS_READ_BACKEND", None)
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.TEAMS_READ_BACKEND == "m365-bridge"

    def test_defaults_to_graph_when_graph_enabled(self):
        def mock_get_secret(key):
            return {"m365_client_id": "cid", "m365_tenant_id": "tid"}.get(key)

        with patch("vault.keychain.get_secret", side_effect=mock_get_secret):
            env = os.environ.copy()
            env.pop("TEAMS_READ_BACKEND", None)
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.TEAMS_READ_BACKEND == "graph"


class TestEmailSendBackend:
    """EMAIL_SEND_BACKEND defaults and env var handling."""

    def test_defaults_to_apple_when_graph_disabled(self):
        with patch("vault.keychain.get_secret", return_value=None):
            env = os.environ.copy()
            env.pop("m365_client_id", None)
            env.pop("EMAIL_SEND_BACKEND", None)
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.EMAIL_SEND_BACKEND == "apple"

    def test_defaults_to_graph_when_graph_enabled(self):
        def mock_get_secret(key):
            return {"m365_client_id": "cid", "m365_tenant_id": "tid"}.get(key)

        with patch("vault.keychain.get_secret", side_effect=mock_get_secret):
            env = os.environ.copy()
            env.pop("EMAIL_SEND_BACKEND", None)
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.EMAIL_SEND_BACKEND == "graph"

    def test_env_var_overrides_default(self):
        with patch("vault.keychain.get_secret", return_value=None):
            env = os.environ.copy()
            env.pop("m365_client_id", None)
            env["EMAIL_SEND_BACKEND"] = "graph"
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.EMAIL_SEND_BACKEND == "graph"


class TestGraphScopes:
    """M365_GRAPH_SCOPES should contain the expected permissions."""

    def test_scopes_value(self):
        import config
        importlib.reload(config)
        assert config.M365_GRAPH_SCOPES == [
            "Calendars.ReadWrite",
            "Channel.ReadBasic.All",
            "ChannelMessage.Send",
            "Chat.Create",
            "Chat.Read",
            "Chat.ReadWrite",
            "ChatMessage.Send",
            "Mail.Send",
            "Team.ReadBasic.All",
            "User.Read",
            "User.ReadBasic.All",
        ]


class TestGetSecretFallback:
    """When vault.keychain is not importable, config falls back to env vars."""

    def test_env_var_fallback_for_client_id(self):
        """If get_secret returns None, M365_CLIENT_ID stays empty."""
        with patch("vault.keychain.get_secret", return_value=None):
            env = os.environ.copy()
            env.pop("m365_client_id", None)
            with patch.dict(os.environ, env, clear=True):
                import config
                importlib.reload(config)
                assert config.M365_CLIENT_ID == ""
                assert config.M365_GRAPH_ENABLED is False
