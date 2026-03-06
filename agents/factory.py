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
    def __init__(self, registry: AgentRegistry, memory_store=None):
        self.registry = registry
        self.memory_store = memory_store

    def create_agent(self, description: str) -> AgentConfig:
        client = anthropic.Anthropic(api_key=app_config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=app_config.MODEL_TIERS["haiku"],
            max_tokens=1024,
            system=AGENT_CREATION_PROMPT,
            messages=[{"role": "user", "content": f"I need an agent for: {description}"}],
        )
        try:
            if self.memory_store is not None:
                usage = response.usage
                self.memory_store.log_api_call(
                    model_id=app_config.MODEL_TIERS["haiku"],
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_input_tokens=getattr(usage, 'cache_creation_input_tokens', 0) or 0,
                    cache_read_input_tokens=getattr(usage, 'cache_read_input_tokens', 0) or 0,
                    agent_name=None,
                    caller="factory",
                )
        except Exception:
            pass

        raw = response.content[0].text
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"AgentFactory: LLM returned invalid JSON: {exc}. Raw output: {raw[:500]}"
            ) from exc
        for required_key in ("name", "description", "system_prompt"):
            if required_key not in data:
                raise ValueError(
                    f"AgentFactory: LLM output missing required key '{required_key}'. "
                    f"Got keys: {list(data.keys())}"
                )
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
