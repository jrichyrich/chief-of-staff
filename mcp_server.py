# mcp_server.py
"""Chief of Staff MCP Server -- Claude Desktop & Claude Code plugin."""

import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import config as app_config
from agents.registry import AgentRegistry
from chief.orchestrator import ChiefOfStaff
from documents.ingestion import chunk_text, content_hash, load_text_file
from documents.store import DocumentStore
from memory.store import MemoryStore

# All logging to stderr (stdout is the JSON-RPC channel for stdio transport)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("chief-of-staff-mcp")


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize shared resources on startup, clean up on shutdown."""
    app_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    app_config.AGENT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    memory_store = MemoryStore(app_config.MEMORY_DB_PATH)
    document_store = DocumentStore(persist_dir=app_config.CHROMA_PERSIST_DIR)
    agent_registry = AgentRegistry(app_config.AGENT_CONFIGS_DIR)
    chief = ChiefOfStaff(
        memory_store=memory_store,
        document_store=document_store,
        agent_registry=agent_registry,
    )

    logger.info("Chief of Staff MCP server initialized")

    try:
        yield {
            "chief": chief,
            "memory_store": memory_store,
            "document_store": document_store,
            "agent_registry": agent_registry,
        }
    finally:
        memory_store.close()
        logger.info("Chief of Staff MCP server shut down")


mcp = FastMCP(
    "chief-of-staff",
    lifespan=app_lifespan,
)


# --- Tools ---


@mcp.tool()
async def chief_of_staff_ask(message: str) -> str:
    """Send a request to the Chief of Staff who will orchestrate expert agents,
    search memory and documents, and return a comprehensive response.

    Use this for any task that benefits from delegation to specialized experts,
    recalling stored facts about the user, or searching ingested documents.

    Args:
        message: Your request in natural language (e.g., "Help me plan a team offsite")
    """
    ctx = mcp.get_context()
    chief = ctx["chief"]
    try:
        return await chief.process(message)
    except Exception as e:
        logger.error(f"Chief of Staff error: {e}")
        return f"Chief of Staff is currently unavailable: {e}"


@mcp.tool()
async def ingest_documents(path: str) -> str:
    """Ingest documents from a file or directory into the Chief of Staff's
    knowledge base for semantic search. Supports .txt, .md, .py, .json, .yaml files.

    Args:
        path: Absolute path to a file or directory to ingest
    """
    ctx = mcp.get_context()
    document_store = ctx["document_store"]
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


# --- Resources ---


@mcp.resource("memory://facts")
async def get_all_facts() -> str:
    """All stored facts about the user, organized by category."""
    ctx = mcp.get_context()
    memory_store = ctx["memory_store"]
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
    ctx = mcp.get_context()
    memory_store = ctx["memory_store"]
    facts = memory_store.get_facts_by_category(category)
    result = [{"key": f.key, "value": f.value, "confidence": f.confidence} for f in facts]
    return json.dumps(result, indent=2)


@mcp.resource("agents://list")
async def get_agents_list() -> str:
    """All available expert agents and their descriptions."""
    ctx = mcp.get_context()
    agent_registry = ctx["agent_registry"]
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
