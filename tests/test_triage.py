"""Tests for dynamic complexity triage."""

from unittest.mock import MagicMock, patch

import pytest

from agents.registry import AgentConfig
from agents.triage import classify_complexity, classify_and_resolve


def _make_agent_config(model="sonnet", name="test-agent", description="A test agent"):
    return AgentConfig(
        name=name,
        description=description,
        system_prompt="You are a test agent.",
        capabilities=["memory_read"],
        model=model,
    )


def _mock_response(text):
    """Create a mock Anthropic response with the given text."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


class TestClassifyComplexity:
    def test_returns_simple(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config()
        result = classify_complexity("Check status", config, client=client)
        assert result == "simple"

    def test_returns_standard(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("standard")
        config = _make_agent_config()
        result = classify_complexity("Analyze the incident report", config, client=client)
        assert result == "standard"

    def test_returns_complex(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("complex")
        config = _make_agent_config()
        result = classify_complexity("Deep security audit", config, client=client)
        assert result == "complex"

    def test_strips_whitespace(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("  simple\n")
        config = _make_agent_config()
        result = classify_complexity("task", config, client=client)
        assert result == "simple"

    def test_api_error_returns_standard(self):
        client = MagicMock()
        client.messages.create.side_effect = Exception("API down")
        config = _make_agent_config()
        result = classify_complexity("task", config, client=client)
        assert result == "standard"

    def test_unexpected_response_returns_standard(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("I think this is medium difficulty")
        config = _make_agent_config()
        result = classify_complexity("task", config, client=client)
        assert result == "standard"

    def test_uses_haiku_model(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config()
        classify_complexity("task", config, client=client)
        call_kwargs = client.messages.create.call_args.kwargs
        import config as app_config
        assert call_kwargs["model"] == app_config.MODEL_TIERS["haiku"]

    def test_max_tokens_is_small(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config()
        classify_complexity("task", config, client=client)
        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] <= 10

    def test_task_text_truncated(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config()
        long_task = "x" * 5000
        classify_complexity(long_task, config, client=client)
        call_kwargs = client.messages.create.call_args.kwargs
        prompt_text = call_kwargs["messages"][0]["content"]
        assert len(prompt_text) < 1500

    def test_prompt_includes_agent_info(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config(name="incident-responder", description="Handles incidents")
        classify_complexity("Server is down", config, client=client)
        call_kwargs = client.messages.create.call_args.kwargs
        prompt_text = call_kwargs["messages"][0]["content"]
        assert "incident-responder" in prompt_text
        assert "Handles incidents" in prompt_text
        assert "Server is down" in prompt_text

    def test_creates_client_if_none(self):
        config = _make_agent_config()
        with patch("agents.triage.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _mock_response("simple")
            mock_anthropic.Anthropic.return_value = mock_client
            result = classify_complexity("task", config)
            assert result == "simple"
            mock_anthropic.Anthropic.assert_called_once()


class TestClassifyAndResolve:
    def test_simple_downgrades_sonnet_to_haiku(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config(model="sonnet")
        result = classify_and_resolve(config, "Check status", client=client)
        assert result.model == "haiku"
        assert config.model == "sonnet"

    def test_standard_keeps_sonnet(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("standard")
        config = _make_agent_config(model="sonnet")
        result = classify_and_resolve(config, "Analyze incident", client=client)
        assert result.model == "sonnet"

    def test_complex_keeps_sonnet(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("complex")
        config = _make_agent_config(model="sonnet")
        result = classify_and_resolve(config, "Deep audit", client=client)
        assert result.model == "sonnet"

    def test_haiku_agent_skips_triage(self):
        client = MagicMock()
        config = _make_agent_config(model="haiku")
        result = classify_and_resolve(config, "task", client=client)
        assert result.model == "haiku"
        client.messages.create.assert_not_called()

    def test_opus_agent_never_downgraded(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config(model="opus")
        result = classify_and_resolve(config, "task", client=client)
        assert result.model == "opus"
        client.messages.create.assert_not_called()

    def test_returns_copy_not_original(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config(model="sonnet")
        result = classify_and_resolve(config, "task", client=client)
        assert result is not config
        assert result.model == "haiku"
        assert config.model == "sonnet"

    def test_preserves_all_other_fields(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = AgentConfig(
            name="my-agent",
            description="Does stuff",
            system_prompt="You do stuff.",
            capabilities=["memory_read", "calendar_read"],
            namespaces=["team-a"],
            temperature=0.5,
            max_tokens=2048,
            model="sonnet",
        )
        result = classify_and_resolve(config, "task", client=client)
        assert result.model == "haiku"
        assert result.name == "my-agent"
        assert result.description == "Does stuff"
        assert result.system_prompt == "You do stuff."
        assert result.capabilities == ["memory_read", "calendar_read"]
        assert result.namespaces == ["team-a"]
        assert result.temperature == 0.5
        assert result.max_tokens == 2048

    def test_api_error_keeps_original_model(self):
        client = MagicMock()
        client.messages.create.side_effect = Exception("API down")
        config = _make_agent_config(model="sonnet")
        result = classify_and_resolve(config, "task", client=client)
        assert result.model == "sonnet"
