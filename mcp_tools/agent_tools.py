"""Agent management tools for the Chief of Staff MCP server."""

import json

from agents.registry import AgentConfig
from capabilities.registry import parse_capabilities_csv


def register(mcp, state):
    """Register agent tools with the FastMCP server."""

    @mcp.tool()
    async def list_agents() -> str:
        """List all available expert agent configurations."""
        agent_registry = state.agent_registry
        agents = agent_registry.list_agents()
        if not agents:
            return json.dumps({"message": "No agents configured yet.", "results": []})
        results = [
            {"name": a.name, "description": a.description, "capabilities": a.capabilities}
            for a in agents
        ]
        return json.dumps({"results": results})

    @mcp.tool()
    async def get_agent(name: str) -> str:
        """Get full details for a specific expert agent by name.

        Args:
            name: The agent name to look up
        """
        agent_registry = state.agent_registry
        agent = agent_registry.get_agent(name)
        if not agent:
            return json.dumps({"error": f"Agent '{name}' not found."})
        return json.dumps({
            "name": agent.name,
            "description": agent.description,
            "system_prompt": agent.system_prompt,
            "capabilities": agent.capabilities,
            "temperature": agent.temperature,
            "max_tokens": agent.max_tokens,
        })

    @mcp.tool()
    async def create_agent(name: str, description: str, system_prompt: str, capabilities: str = "") -> str:
        """Create or update an expert agent configuration.

        Args:
            name: Agent name (lowercase, no spaces — e.g. 'researcher', 'code_reviewer')
            description: What this agent specializes in
            system_prompt: The system prompt that defines this agent's behavior
            capabilities: Comma-separated list of capabilities (e.g. 'web_search,memory_read,document_search')
        """
        agent_registry = state.agent_registry
        try:
            caps = parse_capabilities_csv(capabilities) if capabilities else []
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        config = AgentConfig(
            name=name,
            description=description,
            system_prompt=system_prompt,
            capabilities=caps,
        )
        try:
            agent_registry.save_agent(config)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({"status": "created", "name": name, "capabilities": caps})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.list_agents = list_agents
    module.get_agent = get_agent
    module.create_agent = create_agent
