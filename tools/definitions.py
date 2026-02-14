# tools/definitions.py

CHIEF_TOOLS = [
    {
        "name": "query_memory",
        "description": "Look up facts, locations, or personal details from shared memory. Use this to recall things about the user or context from previous conversations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term to look up"},
                "category": {
                    "type": "string",
                    "description": "Optional category filter",
                    "enum": ["personal", "preference", "work", "relationship", "location"],
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "store_memory",
        "description": "Save a new fact or detail to shared memory so it can be recalled later.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Fact category",
                    "enum": ["personal", "preference", "work", "relationship"],
                },
                "key": {"type": "string", "description": "Fact key (e.g., 'name', 'favorite_food')"},
                "value": {"type": "string", "description": "Fact value"},
            },
            "required": ["category", "key", "value"],
        },
    },
    {
        "name": "search_documents",
        "description": "Search over ingested documents using semantic similarity. Returns relevant passages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "top_k": {"type": "integer", "description": "Number of results", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_agents",
        "description": "List all available expert agents and their descriptions.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "dispatch_agent",
        "description": "Send a task to a specific expert agent and get their response.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Name of the expert agent to dispatch"},
                "task": {"type": "string", "description": "The task description for the agent"},
            },
            "required": ["agent_name", "task"],
        },
    },
    {
        "name": "create_agent",
        "description": "Create a new expert agent when no existing agent has the right expertise. Provide explicit config fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent name (lowercase, underscores, e.g. 'event_planner')"},
                "description": {"type": "string", "description": "One-line description of expertise"},
                "system_prompt": {"type": "string", "description": "Detailed system prompt for the agent"},
                "capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of capabilities: memory_read, memory_write, document_search",
                },
            },
            "required": ["name", "description", "system_prompt"],
        },
    },
    {
        "name": "dispatch_parallel",
        "description": "Send tasks to multiple expert agents simultaneously. Use when a request benefits from multiple perspectives or specialties.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "List of agent-task pairs to dispatch in parallel",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent_name": {"type": "string"},
                            "task": {"type": "string"},
                        },
                        "required": ["agent_name", "task"],
                    },
                },
            },
            "required": ["tasks"],
        },
    },
]


def get_chief_tools() -> list[dict]:
    return CHIEF_TOOLS
