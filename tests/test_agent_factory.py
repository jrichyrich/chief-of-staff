# tests/test_agent_factory.py
import pytest
from unittest.mock import MagicMock, patch
from agents.factory import AgentFactory
from agents.registry import AgentRegistry, AgentConfig


@pytest.fixture
def registry(agent_registry):
    return agent_registry


@pytest.fixture
def factory(registry):
    return AgentFactory(registry)


class TestAgentFactory:
    def test_create_agent_from_description(self, factory, registry):
        """Factory should generate an AgentConfig from a natural language description."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(
            type="text",
            text="""{
                "name": "event_planner",
                "description": "Expert at planning events, venues, catering, and logistics",
                "system_prompt": "You are an event planning expert. You help organize events by finding venues, coordinating logistics, and managing timelines.",
                "capabilities": ["memory_read", "memory_write", "web_search"],
                "temperature": 0.4
            }""",
        )]

        with patch("agents.factory.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            config = factory.create_agent("I need help planning a company offsite event")

        assert config.name == "event_planner"
        assert "event" in config.description.lower()
        assert len(config.capabilities) > 0
        # Should be saved to registry
        assert registry.agent_exists("event_planner")

    def test_create_agent_saves_to_registry(self, factory, registry):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(
            type="text",
            text="""{
                "name": "budget_analyst",
                "description": "Expert at financial analysis and budgeting",
                "system_prompt": "You are a budget analyst.",
                "capabilities": ["memory_read"],
                "temperature": 0.2
            }""",
        )]

        with patch("agents.factory.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            factory.create_agent("Help me analyze my budget")

        loaded = registry.get_agent("budget_analyst")
        assert loaded is not None
        assert loaded.name == "budget_analyst"

    def test_factory_uses_haiku_model(self, factory):
        """Factory should use haiku tier for generating agent configs."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(
            type="text",
            text="""{
                "name": "test_agent",
                "description": "Test",
                "system_prompt": "Test.",
                "capabilities": ["memory_read"],
                "temperature": 0.3
            }""",
        )]

        with patch("agents.factory.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            factory.create_agent("test agent")

            call_kwargs = mock_client.messages.create.call_args.kwargs
            import config as app_config
            assert call_kwargs["model"] == app_config.MODEL_TIERS["haiku"]
