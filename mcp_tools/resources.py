"""MCP resources for exposing data endpoints."""

import json


def register(mcp, state):
    """Register MCP resources with the server."""

    @mcp.resource("memory://facts")
    async def get_all_facts() -> str:
        """All stored facts about the user, organized by category."""
        memory_store = state.memory_store
        categories = ["personal", "preference", "work", "relationship"]
        result = {}
        for cat in categories:
            facts = memory_store.get_facts_by_category(cat)
            if facts:
                result[cat] = [{"key": f.key, "value": f.value, "confidence": f.confidence} for f in facts]
        return json.dumps(result, indent=2) if result else json.dumps({"message": "No facts stored yet."})

    @mcp.resource("memory://facts/{category}")
    async def get_facts_by_category(category: str) -> str:
        """Facts for a specific category (personal, preference, work, relationship)."""
        memory_store = state.memory_store
        facts = memory_store.get_facts_by_category(category)
        result = [{"key": f.key, "value": f.value, "confidence": f.confidence} for f in facts]
        return json.dumps(result, indent=2)

    @mcp.resource("agents://list")
    async def get_agents_list() -> str:
        """All available expert agents and their descriptions."""
        agent_registry = state.agent_registry
        agents = agent_registry.list_agents()
        result = [
            {"name": a.name, "description": a.description, "capabilities": a.capabilities}
            for a in agents
        ]
        return json.dumps(result, indent=2) if result else json.dumps({"message": "No agents configured yet."})

    # Expose resource functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.get_all_facts = get_all_facts
    module.get_facts_by_category = get_facts_by_category
    module.get_agents_list = get_agents_list
