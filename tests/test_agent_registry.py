# tests/test_agent_registry.py
import pytest
import yaml
from pathlib import Path
from agents.registry import AgentRegistry, AgentConfig


@pytest.fixture
def configs_dir(tmp_path):
    return tmp_path / "agent_configs"


@pytest.fixture
def registry(configs_dir):
    configs_dir.mkdir()
    return AgentRegistry(configs_dir)


def _write_agent_yaml(configs_dir: Path, name: str, description: str, capabilities: list[str]):
    config = {
        "name": name,
        "description": description,
        "system_prompt": f"You are a {name}.",
        "capabilities": capabilities,
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    path = configs_dir / f"{name}.yaml"
    path.write_text(yaml.dump(config))
    return path


class TestAgentRegistry:
    def test_list_agents_empty(self, registry):
        agents = registry.list_agents()
        assert agents == []

    def test_load_agent(self, registry, configs_dir):
        _write_agent_yaml(configs_dir, "researcher", "Research expert", ["web_search"])
        config = registry.get_agent("researcher")
        assert config is not None
        assert config.name == "researcher"
        assert config.description == "Research expert"
        assert "web_search" in config.capabilities

    def test_list_agents(self, registry, configs_dir):
        _write_agent_yaml(configs_dir, "researcher", "Research expert", ["web_search"])
        _write_agent_yaml(configs_dir, "planner", "Event planner", ["memory_read"])
        agents = registry.list_agents()
        assert len(agents) == 2
        names = [a.name for a in agents]
        assert "researcher" in names
        assert "planner" in names

    def test_get_nonexistent_agent(self, registry):
        result = registry.get_agent("nonexistent")
        assert result is None

    def test_save_agent(self, registry, configs_dir):
        config = AgentConfig(
            name="new_agent",
            description="A new agent",
            system_prompt="You are a new agent.",
            capabilities=["memory_read", "memory_write"],
            temperature=0.5,
            max_tokens=2048,
        )
        registry.save_agent(config)
        assert (configs_dir / "new_agent.yaml").exists()

        loaded = registry.get_agent("new_agent")
        assert loaded is not None
        assert loaded.description == "A new agent"
        assert loaded.temperature == 0.5

    def test_agent_exists(self, registry, configs_dir):
        assert not registry.agent_exists("researcher")
        _write_agent_yaml(configs_dir, "researcher", "Research expert", ["web_search"])
        assert registry.agent_exists("researcher")
