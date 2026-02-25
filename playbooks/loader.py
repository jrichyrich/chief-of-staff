"""Playbook YAML schema, loader, and input substitution."""

import copy
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# Matches agent name pattern — prevents path traversal via names like "../etc/passwd"
VALID_PLAYBOOK_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass
class Workstream:
    """A single parallel workstream within a playbook."""

    name: str
    prompt: str
    condition: str = ""


@dataclass
class Playbook:
    """A YAML-defined playbook with parallel workstreams."""

    name: str
    description: str
    inputs: list[str]
    workstreams: list[Workstream]
    synthesis_prompt: str
    delivery_default: str = "inline"
    delivery_options: list[str] = field(default_factory=list)

    def resolve_inputs(self, values: dict[str, str]) -> "Playbook":
        """Deep copy with $variables substituted via string.Template.safe_substitute."""
        pb = copy.deepcopy(self)
        for ws in pb.workstreams:
            ws.prompt = Template(ws.prompt).safe_substitute(values)
        pb.synthesis_prompt = Template(pb.synthesis_prompt).safe_substitute(values)
        return pb

    def active_workstreams(self, context: dict | None) -> list[Workstream]:
        """Return workstreams whose conditions are met.

        No condition = always active. Conditions use simple key == value format.
        If context is None, only unconditional workstreams are returned.
        """
        result = []
        for ws in self.workstreams:
            if not ws.condition:
                result.append(ws)
            elif context is not None and _evaluate_condition(ws.condition, context):
                result.append(ws)
        return result


def _evaluate_condition(condition: str, context: dict) -> bool:
    """Evaluate a simple key == value condition against a context dict."""
    if "==" not in condition:
        return False
    parts = condition.split("==", 1)
    if len(parts) != 2:
        return False
    key = parts[0].strip()
    value = parts[1].strip()
    return context.get(key) == value


class PlaybookLoader:
    """Loads playbook YAML files from a directory."""

    def __init__(self, playbooks_dir: Path):
        self.playbooks_dir = playbooks_dir

    def list_playbooks(self) -> list[str]:
        """Return stem names of .yaml and .yml files in the directory."""
        if not self.playbooks_dir.exists():
            return []
        stems = []
        for path in sorted(self.playbooks_dir.iterdir()):
            if path.suffix in (".yaml", ".yml"):
                stems.append(path.stem)
        return stems

    def get_playbook(self, name: str) -> Optional[Playbook]:
        """Load and parse a playbook by name. Returns None if not found or invalid."""
        if not VALID_PLAYBOOK_NAME.match(name):
            logger.warning("Invalid playbook name rejected: %r", name)
            return None
        # Try .yaml first, then .yml
        for ext in (".yaml", ".yml"):
            path = self.playbooks_dir / f"{name}{ext}"
            if path.exists():
                return self._load_file(path)
        return None

    def _load_file(self, path: Path) -> Optional[Playbook]:
        """Parse YAML, validate required fields, and build a Playbook."""
        try:
            data = yaml.safe_load(path.read_text())
            if not isinstance(data, dict):
                return None

            # Validate required fields
            if "name" not in data or "workstreams" not in data:
                return None

            workstreams_data = data["workstreams"]
            if not isinstance(workstreams_data, list) or not workstreams_data:
                return None

            workstreams = []
            for ws_data in workstreams_data:
                workstreams.append(
                    Workstream(
                        name=ws_data["name"],
                        prompt=ws_data.get("prompt", ""),
                        condition=ws_data.get("condition", ""),
                    )
                )

            synthesis = data.get("synthesis", {}) or {}
            delivery = data.get("delivery", {}) or {}

            return Playbook(
                name=data["name"],
                description=data.get("description", ""),
                inputs=data.get("inputs", []),
                workstreams=workstreams,
                synthesis_prompt=synthesis.get("prompt", ""),
                delivery_default=delivery.get("default", "inline"),
                delivery_options=delivery.get("options", []),
            )
        except (yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Failed to load playbook %s: %s", path, exc)
            return None
