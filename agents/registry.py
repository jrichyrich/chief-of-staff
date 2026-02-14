# agents/registry.py
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# Only allow lowercase alphanumeric, underscores, and hyphens (no path separators)
VALID_AGENT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass
class AgentConfig:
    name: str
    description: str
    system_prompt: str
    capabilities: list[str] = field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 4096
    created_by: Optional[str] = None
    created_at: Optional[str] = None


class AgentRegistry:
    def __init__(self, configs_dir: Path):
        self.configs_dir = configs_dir
        self.configs_dir.mkdir(parents=True, exist_ok=True)

    def list_agents(self) -> list[AgentConfig]:
        agents = []
        for path in sorted(self.configs_dir.glob("*.yaml")):
            config = self._load_yaml(path)
            if config:
                agents.append(config)
        return agents

    @staticmethod
    def _validate_name(name: str) -> None:
        if not VALID_AGENT_NAME.match(name):
            raise ValueError(
                f"Invalid agent name '{name}': must be lowercase alphanumeric, "
                "underscores, or hyphens, starting with a letter or digit"
            )

    def get_agent(self, name: str) -> Optional[AgentConfig]:
        self._validate_name(name)
        path = self.configs_dir / f"{name}.yaml"
        if not path.exists():
            return None
        return self._load_yaml(path)

    def save_agent(self, config: AgentConfig) -> Path:
        self._validate_name(config.name)
        path = self.configs_dir / f"{config.name}.yaml"
        data = {
            "name": config.name,
            "description": config.description,
            "system_prompt": config.system_prompt,
            "capabilities": config.capabilities,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }
        if config.created_by:
            data["created_by"] = config.created_by
        if config.created_at:
            data["created_at"] = config.created_at
        path.write_text(yaml.dump(data, default_flow_style=False))
        return path

    def agent_exists(self, name: str) -> bool:
        self._validate_name(name)
        return (self.configs_dir / f"{name}.yaml").exists()

    def _load_yaml(self, path: Path) -> Optional[AgentConfig]:
        try:
            data = yaml.safe_load(path.read_text())
            return AgentConfig(
                name=data["name"],
                description=data.get("description", ""),
                system_prompt=data.get("system_prompt", ""),
                capabilities=data.get("capabilities", []),
                temperature=data.get("temperature", 0.3),
                max_tokens=data.get("max_tokens", 4096),
                created_by=data.get("created_by"),
                created_at=data.get("created_at"),
            )
        except (yaml.YAMLError, KeyError):
            return None
