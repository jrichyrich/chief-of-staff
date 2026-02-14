# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Chief of Staff is a Python AI orchestration system where a "Chief of Staff" agent manages expert agents. It interprets user requests, routes to specialized agents, dispatches them in parallel, and synthesizes results. Three deployment modes:

- **CLI** (`chief` / `main.py`) — interactive chat loop with Rich terminal UI
- **MCP Server** (`jarvis-mcp` / `mcp_server.py`) — FastMCP stdio server for Claude Code integration
- **Desktop Extension** (`manifest.json`) — DXT package for Claude Desktop distribution; build with `mcpb pack . jarvis.mcpb` and install by dragging into Claude Desktop Settings

## Development Commands

```bash
# Install (dev mode with test deps)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_orchestrator.py

# Run a specific test
pytest tests/test_orchestrator.py::test_process_text_response -v

# Run with coverage
pytest --cov=chief --cov=agents --cov=memory --cov=documents

# Start CLI chat loop
chief

# Start MCP server
chief-mcp
```

## Architecture

### Flow: User Request → Response

1. **CLI (`main.py`)** or **MCP Server (`mcp_server.py`)** receives user input
2. **ChiefOfStaff** (`chief/orchestrator.py`) calls Claude API with 7 tools to decide what to do
3. Tool calls execute in a loop until Claude returns a text response:
   - Memory tools → **MemoryStore** (SQLite)
   - Document tools → **DocumentStore** (ChromaDB)
   - Agent tools → **AgentDispatcher** runs expert agents concurrently via `asyncio.gather()`
4. Expert agents (`agents/base.py`) also run their own tool-use loops with Claude, accessing memory and documents

### Module Map

| Module | Purpose |
|--------|---------|
| `chief/orchestrator.py` | Decision-making loop: calls Claude API, handles tool results, maintains conversation history |
| `chief/dispatcher.py` | Async parallel agent execution with configurable timeout (60s default) |
| `agents/registry.py` | Loads/saves agent configs from YAML files in `agent_configs/` |
| `agents/base.py` | Expert agent execution: own tool-use loop with memory_read, memory_write, document_search |
| `agents/factory.py` | Uses Claude to dynamically generate new agent configs |
| `memory/store.py` | SQLite backend with three tables: facts (category+key unique), locations, context |
| `memory/models.py` | Dataclasses: Fact, Location, ContextEntry |
| `documents/store.py` | ChromaDB vector search wrapper (all-MiniLM-L6-v2 embeddings) |
| `documents/ingestion.py` | Text chunking (word-based, 500 words, 50 overlap) and SHA256 dedup |
| `tools/definitions.py` | Tool schemas for the Anthropic API |
| `config.py` | All paths, model names, and constants in one place |
| `mcp_server.py` | FastMCP server exposing tools and resources via stdio transport |

### Key Patterns

- **Tool-use loop**: Both ChiefOfStaff and BaseExpertAgent loop on `response.stop_reason == "tool_use"`, executing tools and feeding results back until Claude produces a text response.
- **Dependency injection**: ChiefOfStaff and agents receive MemoryStore, DocumentStore, and AgentRegistry instances. Tests use `tmp_path` fixtures for isolation.
- **MCP state management**: `mcp_server.py` uses a module-level `_state` dict populated during FastMCP lifespan for sharing stores across tool handlers.

## Configuration

All settings live in `config.py`. Key values:
- `ANTHROPIC_API_KEY`: from environment variable
- `DEFAULT_MODEL` / `CHIEF_MODEL`: `claude-sonnet-4-5-20250929`
- Agent configs: YAML files in `agent_configs/`
- Runtime data: `data/memory.db` (SQLite), `data/chroma/` (ChromaDB)

## Testing Conventions

- Async tests use `@pytest.mark.asyncio` with pytest-asyncio
- Anthropic API calls are mocked — tests never hit real APIs
- Fixtures create isolated MemoryStore, DocumentStore, AgentRegistry instances using `tmp_path`
- No conftest.py — fixtures are defined per test module
