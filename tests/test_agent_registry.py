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
        config = AgentConfig(
            name="researcher",
            description="Research expert",
            system_prompt="You are a researcher.",
            capabilities=["memory_read"],
        )
        registry.save_agent(config)
        assert registry.agent_exists("researcher")


class TestAgentNameValidation:
    def test_rejects_path_traversal(self, registry):
        with pytest.raises(ValueError, match="Invalid agent name"):
            registry.get_agent("../../../etc/passwd")

    def test_rejects_absolute_path(self, registry):
        with pytest.raises(ValueError, match="Invalid agent name"):
            registry.get_agent("/etc/passwd")

    def test_rejects_spaces(self, registry):
        with pytest.raises(ValueError, match="Invalid agent name"):
            registry.get_agent("my agent")

    def test_rejects_uppercase(self, registry):
        with pytest.raises(ValueError, match="Invalid agent name"):
            registry.get_agent("MyAgent")

    def test_accepts_valid_names(self, registry):
        # These should not raise (will return None since agents don't exist)
        assert registry.get_agent("researcher") is None
        assert registry.get_agent("code-reviewer") is None
        assert registry.get_agent("agent_v2") is None

    def test_save_rejects_invalid_name(self, registry):
        config = AgentConfig(
            name="../../bad_name",
            description="Bad",
            system_prompt="Bad",
        )
        with pytest.raises(ValueError, match="Invalid agent name"):
            registry.save_agent(config)
