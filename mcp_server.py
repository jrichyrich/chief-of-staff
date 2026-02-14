# mcp_server.py
"""Chief of Staff MCP Server -- Claude Desktop & Claude Code plugin.

Exposes granular tools for memory, document search, and agent management.
No internal LLM calls — the host Claude handles all reasoning.
"""

import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import config as app_config
from agents.registry import AgentConfig, AgentRegistry
from documents.ingestion import chunk_text, content_hash, load_text_file
from documents.store import DocumentStore
from memory.models import Fact, Location
from memory.store import MemoryStore

# All logging to stderr (stdout is the JSON-RPC channel for stdio transport)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("jarvis-mcp")

# Module-level state populated by the lifespan manager.
_state: dict = {}


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize shared resources on startup, clean up on shutdown."""
    app_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    app_config.AGENT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    memory_store = MemoryStore(app_config.MEMORY_DB_PATH)
    document_store = DocumentStore(persist_dir=app_config.CHROMA_PERSIST_DIR)
    agent_registry = AgentRegistry(app_config.AGENT_CONFIGS_DIR)

    _state.update({
        "memory_store": memory_store,
        "document_store": document_store,
        "agent_registry": agent_registry,
    })

    logger.info("Jarvis MCP server initialized")

    try:
        yield
    finally:
        _state.clear()
        memory_store.close()
        logger.info("Jarvis MCP server shut down")


mcp = FastMCP(
    "jarvis",
    lifespan=app_lifespan,
)


# --- Memory Tools ---


@mcp.tool()
async def store_fact(category: str, key: str, value: str, confidence: float = 1.0) -> str:
    """Store a fact about the user in long-term memory. Overwrites if category+key already exists.

    Args:
        category: One of 'personal', 'preference', 'work', 'relationship'
        key: Short label for the fact (e.g. 'name', 'favorite_color', 'job_title')
        value: The fact value
        confidence: Confidence score from 0.0 to 1.0 (default 1.0)
    """
    memory_store = _state["memory_store"]
    fact = Fact(category=category, key=key, value=value, confidence=confidence)
    stored = memory_store.store_fact(fact)
    return json.dumps({
        "status": "stored",
        "category": stored.category,
        "key": stored.key,
        "value": stored.value,
    })


@mcp.tool()
async def query_memory(query: str, category: str = "") -> str:
    """Search stored facts about the user. Returns matching facts.

    Args:
        query: Search term to match against fact keys and values
        category: Optional — filter to a specific category (personal, preference, work, relationship). Leave empty to search all.
    """
    memory_store = _state["memory_store"]

    if category:
        facts = memory_store.get_facts_by_category(category)
    else:
        facts = memory_store.search_facts(query)

    if not facts:
        return json.dumps({"message": f"No facts found for query '{query}'.", "results": []})

    results = [{"category": f.category, "key": f.key, "value": f.value, "confidence": f.confidence} for f in facts]
    return json.dumps({"results": results})


@mcp.tool()
async def store_location(name: str, address: str = "", notes: str = "",
                         latitude: float = 0.0, longitude: float = 0.0) -> str:
    """Store a named location in memory.

    Args:
        name: Location name (e.g. 'home', 'office', 'favorite_restaurant')
        address: Street address
        notes: Additional notes about this location
        latitude: GPS latitude (optional, 0.0 if unknown)
        longitude: GPS longitude (optional, 0.0 if unknown)
    """
    memory_store = _state["memory_store"]
    loc = Location(
        name=name,
        address=address or None,
        notes=notes or None,
        latitude=latitude if latitude != 0.0 else None,
        longitude=longitude if longitude != 0.0 else None,
    )
    stored = memory_store.store_location(loc)
    return json.dumps({"status": "stored", "name": stored.name, "address": stored.address})


@mcp.tool()
async def list_locations() -> str:
    """List all stored locations."""
    memory_store = _state["memory_store"]
    locations = memory_store.list_locations()
    if not locations:
        return json.dumps({"message": "No locations stored yet.", "results": []})
    results = [{"name": l.name, "address": l.address, "notes": l.notes} for l in locations]
    return json.dumps({"results": results})


# --- Document Tools ---


@mcp.tool()
async def search_documents(query: str, top_k: int = 5) -> str:
    """Semantic search over ingested documents. Returns the most relevant chunks.

    Args:
        query: Natural language search query
        top_k: Number of results to return (default 5)
    """
    document_store = _state["document_store"]
    results = document_store.search(query, top_k=top_k)

    if not results:
        return json.dumps({"message": "No documents found. Ingest documents first.", "results": []})

    return json.dumps({"results": results})


@mcp.tool()
async def ingest_documents(path: str) -> str:
    """Ingest documents from a file or directory into the knowledge base for semantic search.
    Supports .txt, .md, .py, .json, .yaml files.

    Args:
        path: Absolute path to a file or directory to ingest
    """
    document_store = _state["document_store"]
    target = Path(path)

    if not target.exists():
        return f"Path not found: {path}"

    supported = {".txt", ".md", ".py", ".json", ".yaml", ".yml"}
    files = []

    if target.is_file():
        files = [target]
    elif target.is_dir():
        for ext in supported:
            files.extend(target.glob(f"**/*{ext}"))

    if not files:
        return f"No supported files found at {path}"

    total_chunks = 0
    for file in files:
        text = load_text_file(file)
        chunks = chunk_text(text)
        file_hash = content_hash(text)

        texts = []
        metadatas = []
        ids = []
        for i, chunk in enumerate(chunks):
            texts.append(chunk)
            metadatas.append({"source": str(file.name), "chunk_index": i})
            ids.append(f"{file_hash}_{i}")

        document_store.add_documents(texts=texts, metadatas=metadatas, ids=ids)
        total_chunks += len(chunks)

    logger.info(f"Ingested {len(files)} file(s), {total_chunks} chunks from {path}")
    return f"Ingested {len(files)} file(s), {total_chunks} chunks."


# --- Agent Tools ---


@mcp.tool()
async def list_agents() -> str:
    """List all available expert agent configurations."""
    agent_registry = _state["agent_registry"]
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
    agent_registry = _state["agent_registry"]
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
    agent_registry = _state["agent_registry"]
    caps = [c.strip() for c in capabilities.split(",") if c.strip()] if capabilities else []
    config = AgentConfig(
        name=name,
        description=description,
        system_prompt=system_prompt,
        capabilities=caps,
    )
    agent_registry.save_agent(config)
    return json.dumps({"status": "created", "name": name, "capabilities": caps})


# --- Resources ---


@mcp.resource("memory://facts")
async def get_all_facts() -> str:
    """All stored facts about the user, organized by category."""
    memory_store = _state["memory_store"]
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
    memory_store = _state["memory_store"]
    facts = memory_store.get_facts_by_category(category)
    result = [{"key": f.key, "value": f.value, "confidence": f.confidence} for f in facts]
    return json.dumps(result, indent=2)


@mcp.resource("agents://list")
async def get_agents_list() -> str:
    """All available expert agents and their descriptions."""
    agent_registry = _state["agent_registry"]
    agents = agent_registry.list_agents()
    result = [
        {"name": a.name, "description": a.description, "capabilities": a.capabilities}
        for a in agents
    ]
    return json.dumps(result, indent=2) if result else json.dumps({"message": "No agents configured yet."})


# --- Entry point ---


def main():
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
