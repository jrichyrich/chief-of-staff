# agents/factory.py
import json
from datetime import datetime

import anthropic

import config as app_config
from agents.registry import AgentConfig, AgentRegistry

AGENT_CREATION_PROMPT = """You are an expert at creating AI agent configurations. Given a user's need, generate a JSON agent config.

Available capabilities (choose only what's relevant):
- memory_read: Read from shared memory (facts, locations, personal details)
- memory_write: Write to shared memory
- document_search: Search over ingested documents
- web_search: Search the web
- file_operations: Read/write local files
- code_execution: Run Python code

Respond with ONLY valid JSON (no markdown, no explanation):
{
    "name": "snake_case_name",
    "description": "One-line description of expertise",
    "system_prompt": "Detailed system prompt for the agent",
    "capabilities": ["list", "of", "capabilities"],
    "temperature": 0.3
}"""


class AgentFactory:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def create_agent(self, description: str) -> AgentConfig:
        client = anthropic.Anthropic(api_key=app_config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=app_config.CHIEF_MODEL,
            max_tokens=1024,
            system=AGENT_CREATION_PROMPT,
            messages=[{"role": "user", "content": f"I need an agent for: {description}"}],
        )

        raw = response.content[0].text
        data = json.loads(raw)

        config = AgentConfig(
            name=data["name"],
            description=data["description"],
            system_prompt=data["system_prompt"],
            capabilities=data.get("capabilities", ["memory_read"]),
            temperature=data.get("temperature", 0.3),
            max_tokens=data.get("max_tokens", 4096),
            created_by="chief_of_staff",
            created_at=datetime.now().isoformat(),
        )

        self.registry.save_agent(config)
        return config
