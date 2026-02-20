# agents/registry.py
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from capabilities.registry import validate_capabilities

# Only allow lowercase alphanumeric, underscores, and hyphens (no path separators)
VALID_AGENT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass
class AgentConfig:
    name: str
    description: str
    system_prompt: str
    capabilities: list[str] = field(default_factory=list)
    namespaces: list[str] = field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 4096
    created_by: Optional[str] = None
    created_at: Optional[str] = None


class AgentRegistry:
    def __init__(self, configs_dir: Path):
        self.configs_dir = configs_dir
        self.configs_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, AgentConfig] = {}
        self._cache_loaded = False

    def _ensure_cache(self) -> None:
        """Load all configs into cache on first access."""
        if self._cache_loaded:
            return
        self._cache.clear()
        for path in sorted(self.configs_dir.glob("*.yaml")):
            config = self._load_yaml(path)
            if config:
                self._cache[config.name] = config
        self._cache_loaded = True

    def _invalidate_cache(self) -> None:
        self._cache_loaded = False
        self._cache.clear()

    def list_agents(self) -> list[AgentConfig]:
        self._ensure_cache()
        return list(self._cache.values())

    @staticmethod
    def _validate_name(name: str) -> None:
        if not VALID_AGENT_NAME.match(name):
            raise ValueError(
                f"Invalid agent name '{name}': must be lowercase alphanumeric, "
                "underscores, or hyphens, starting with a letter or digit"
            )

    def get_agent(self, name: str) -> Optional[AgentConfig]:
        self._validate_name(name)
        self._ensure_cache()
        return self._cache.get(name)

    def save_agent(self, config: AgentConfig) -> Path:
        self._validate_name(config.name)
        normalized_capabilities = validate_capabilities(config.capabilities)
        config.capabilities = normalized_capabilities
        path = self.configs_dir / f"{config.name}.yaml"
        data = {
            "name": config.name,
            "description": config.description,
            "system_prompt": config.system_prompt,
            "capabilities": normalized_capabilities,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }
        if config.namespaces:
            data["namespaces"] = config.namespaces
        if config.created_by:
            data["created_by"] = config.created_by
        if config.created_at:
            data["created_at"] = config.created_at
        path.write_text(yaml.dump(data, default_flow_style=False))
        self._invalidate_cache()
        return path

    def agent_exists(self, name: str) -> bool:
        self._validate_name(name)
        self._ensure_cache()
        return name in self._cache

    def _load_yaml(self, path: Path) -> Optional[AgentConfig]:
        try:
            data = yaml.safe_load(path.read_text())
            capabilities = validate_capabilities(data.get("capabilities", []))
            return AgentConfig(
                name=data["name"],
                description=data.get("description", ""),
                system_prompt=data.get("system_prompt", ""),
                capabilities=capabilities,
                namespaces=data.get("namespaces", []),
                temperature=data.get("temperature", 0.3),
                max_tokens=data.get("max_tokens", 4096),
                created_by=data.get("created_by"),
                created_at=data.get("created_at"),
            )
        except (yaml.YAMLError, KeyError, ValueError):
            return None
