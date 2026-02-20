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

    @mcp.tool()
    async def get_agent_memory(agent_name: str) -> str:
        """Get all memories stored by a specific agent.

        Args:
            agent_name: The agent name to retrieve memories for
        """
        memory_store = state.memory_store
        memories = memory_store.get_agent_memories(agent_name)
        if not memories:
            return json.dumps({"message": f"No memories found for agent '{agent_name}'.", "results": []})
        results = [
            {
                "memory_type": m.memory_type,
                "key": m.key,
                "value": m.value,
                "confidence": m.confidence,
                "updated_at": m.updated_at,
            }
            for m in memories
        ]
        return json.dumps({"agent_name": agent_name, "results": results})

    @mcp.tool()
    async def clear_agent_memory(agent_name: str) -> str:
        """Delete all memories for a specific agent.

        Args:
            agent_name: The agent name whose memories should be cleared
        """
        memory_store = state.memory_store
        count = memory_store.clear_agent_memories(agent_name)
        return json.dumps({"agent_name": agent_name, "deleted_count": count})

    @mcp.tool()
    async def store_shared_memory(
        namespace: str, memory_type: str, key: str, value: str, confidence: float = 1.0
    ) -> str:
        """Store a memory in a shared namespace for cross-agent collaboration.

        Args:
            namespace: The shared namespace (e.g. 'research-team', 'onboarding')
            memory_type: Type of memory ('insight', 'preference', 'context')
            key: A short label for this memory
            value: The memory content
            confidence: Confidence score from 0.0 to 1.0 (default 1.0)
        """
        memory_store = state.memory_store
        result = memory_store.store_shared_memory(namespace, memory_type, key, value, confidence)
        return json.dumps({
            "status": "stored",
            "namespace": namespace,
            "memory_type": result.memory_type,
            "key": result.key,
            "value": result.value,
            "confidence": result.confidence,
        })

    @mcp.tool()
    async def get_shared_memory(namespace: str, memory_type: str = "") -> str:
        """Retrieve shared memories from a namespace.

        Args:
            namespace: The shared namespace to query
            memory_type: Optional filter by memory type ('insight', 'preference', 'context')
        """
        memory_store = state.memory_store
        memories = memory_store.get_shared_memories(namespace, memory_type)
        if not memories:
            return json.dumps({"message": f"No shared memories in namespace '{namespace}'.", "results": []})
        results = [
            {
                "memory_type": m.memory_type,
                "key": m.key,
                "value": m.value,
                "confidence": m.confidence,
                "updated_at": m.updated_at,
            }
            for m in memories
        ]
        return json.dumps({"namespace": namespace, "results": results})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.list_agents = list_agents
    module.get_agent = get_agent
    module.create_agent = create_agent
    module.get_agent_memory = get_agent_memory
    module.clear_agent_memory = clear_agent_memory
    module.store_shared_memory = store_shared_memory
    module.get_shared_memory = get_shared_memory
