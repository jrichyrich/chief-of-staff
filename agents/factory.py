# agents/factory.py
import json
from datetime import datetime

import anthropic

import config as app_config
from agents.registry import AgentConfig, AgentRegistry
from capabilities.registry import capability_prompt_lines, validate_capabilities

MAX_AUTO_CAPABILITIES = 8
RESTRICTED_CAPABILITIES = {"mail_write", "notifications", "alerts_write"}

_CAPABILITY_LINES = "\n".join(f"- {line}" for line in capability_prompt_lines(include_unimplemented=True))

AGENT_CREATION_PROMPT = """You are an expert at creating AI agent configurations. Given a user's need, generate a JSON agent config.

Available capabilities (choose only what's relevant):
%s

Respond with ONLY valid JSON (no markdown, no explanation):
{
    "name": "snake_case_name",
    "description": "One-line description of expertise",
    "system_prompt": "Detailed system prompt for the agent",
    "capabilities": ["list", "of", "capabilities"],
    "temperature": 0.3
}""" % _CAPABILITY_LINES


class AgentFactory:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def create_agent(self, description: str) -> AgentConfig:
        client = anthropic.Anthropic(api_key=app_config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=app_config.MODEL_TIERS["haiku"],
            max_tokens=1024,
            system=AGENT_CREATION_PROMPT,
            messages=[{"role": "user", "content": f"I need an agent for: {description}"}],
        )

        raw = response.content[0].text
        data = json.loads(raw)
        capabilities = validate_capabilities(data.get("capabilities", ["memory_read"]))
        # Filter out restricted capabilities and cap count for auto-generated agents
        capabilities = [c for c in capabilities if c not in RESTRICTED_CAPABILITIES]
        capabilities = capabilities[:MAX_AUTO_CAPABILITIES]

        config = AgentConfig(
            name=data["name"],
            description=data["description"],
            system_prompt=data["system_prompt"],
            capabilities=capabilities,
            temperature=data.get("temperature", 0.3),
            max_tokens=data.get("max_tokens", 4096),
            created_by="chief_of_staff",
            created_at=datetime.now().isoformat(),
        )

        self.registry.save_agent(config)
        return config
