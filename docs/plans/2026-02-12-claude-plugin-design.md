# Chief of Staff — Claude Plugin (MCP Server) Design

**Date:** 2026-02-12
**Status:** Approved

## Overview

Convert the existing Chief of Staff system into an MCP (Model Context Protocol) server so it can be used as a plugin in both Claude Desktop and Claude Code. The existing CLI and all code remain untouched — a thin FastMCP wrapper is added as a new entry point.

## Tech Stack Addition

| Component | Choice |
|-----------|--------|
| MCP SDK | `mcp[cli]>=1.26,<2` (Python FastMCP) |
| Transport | stdio (universal compatibility) |
| Targets | Claude Desktop + Claude Code |

## Architecture

```
Claude Desktop/Code
    |
    | (stdio / JSON-RPC 2.0)
    |
mcp_server.py (FastMCP)
    |-- @mcp.tool: chief_of_staff_ask(message)
    |-- @mcp.tool: ingest_documents(path)
    |-- @mcp.resource: memory://facts
    |-- @mcp.resource: memory://facts/{category}
    |-- @mcp.resource: agents://list
    |
    |-- Lifespan Manager (init/cleanup)
    |       |-- MemoryStore (existing)
    |       |-- DocumentStore (existing)
    |       |-- AgentRegistry (existing)
    |       +-- ChiefOfStaff (existing)
    |
    +-- All existing modules unchanged
```

**Key principle:** The MCP server is a thin wrapper. All business logic lives in the existing modules. No changes to existing code.

## MCP Tools (2)

### 1. chief_of_staff_ask

The main interface. Claude sends a natural language request, the Chief of Staff orchestrates everything internally.

```python
@mcp.tool()
async def chief_of_staff_ask(message: str) -> str:
    """Send a request to the Chief of Staff who will orchestrate expert agents,
    search memory and documents, and return a comprehensive response.

    Use this for any task that benefits from delegation to specialized experts,
    recalling stored facts about the user, or searching ingested documents.

    Args:
        message: Your request in natural language
    """
```

### 2. ingest_documents

Ingest files into the vector store for later retrieval.

```python
@mcp.tool()
def ingest_documents(path: str) -> str:
    """Ingest documents from a file or directory into the Chief of Staff's
    knowledge base for semantic search. Supports .txt, .md, .py, .json, .yaml files.

    Args:
        path: Absolute path to a file or directory to ingest
    """
```

## MCP Resources (3)

### 1. memory://facts

All stored facts organized by category. Returns JSON.

### 2. memory://facts/{category}

Facts filtered by category (personal, preference, work, relationship). Returns JSON array.

### 3. agents://list

All available expert agents with their names, descriptions, and capabilities. Returns JSON array.

## New Files

| File | Purpose |
|------|---------|
| `mcp_server.py` | FastMCP server entry point |
| `.mcp.json` | Claude Code project-scoped config |
| `tests/test_mcp_server.py` | Unit tests for MCP tools and resources |

## Modified Files

| File | Change |
|------|--------|
| `requirements.txt` | Add `mcp[cli]>=1.26,<2` |
| `pyproject.toml` | Add mcp dependency, add `chief-mcp` script entry |
| `main.py` | Extract `ingest_path()` to a shared module (or import from main) |

## Lifespan Management

```python
@asynccontextmanager
async def app_lifespan(server: FastMCP):
    data_dir = config.DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    config.AGENT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    memory_store = MemoryStore(config.MEMORY_DB_PATH)
    document_store = DocumentStore(persist_dir=config.CHROMA_PERSIST_DIR)
    agent_registry = AgentRegistry(config.AGENT_CONFIGS_DIR)
    chief = ChiefOfStaff(
        memory_store=memory_store,
        document_store=document_store,
        agent_registry=agent_registry,
    )

    try:
        yield {
            "chief": chief,
            "memory_store": memory_store,
            "document_store": document_store,
            "agent_registry": agent_registry,
        }
    finally:
        memory_store.close()
```

## Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "chief-of-staff": {
      "command": "python3.11",
      "args": ["/Users/jasricha/Documents/GitHub/chief_of_staff/mcp_server.py"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key"
      }
    }
  }
}
```

### Claude Code

`.mcp.json` at project root:

```json
{
  "mcpServers": {
    "chief-of-staff": {
      "command": "python3.11",
      "args": ["${PROJECT_ROOT}/mcp_server.py"],
      "env": {
        "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"
      }
    }
  }
}
```

## Logging

All logging goes to stderr (mandatory for stdio transport — stdout is the JSON-RPC channel). Use Python's `logging` module configured to stderr.

## Error Handling

- Tool errors return descriptive error strings (not exceptions)
- API failures return "Chief of Staff is currently unavailable: {error}"
- Invalid paths in ingest_documents return "Path not found: {path}"

## Testing Strategy

- Unit tests for MCP tool functions (import and call directly, no transport)
- Unit tests for MCP resource functions
- Integration test: full ask flow with mocked Claude API
- All 57 existing tests remain unchanged and passing
