# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Chief of Staff (Jarvis) is a Python AI orchestration system where a "Chief of Staff" agent manages expert agents. It interprets user requests, routes to specialized agents, dispatches them in parallel, and synthesizes results. Three deployment modes:

- **CLI** (`chief` / `main.py`) — interactive chat loop with Rich terminal UI
- **MCP Server** (`jarvis-mcp` / `mcp_server.py`) — FastMCP stdio server for Claude Code/Desktop integration
- **Desktop Extension** (`manifest.json`) — DXT package for Claude Desktop; build with `mcpb pack . jarvis.mcpb`

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
jarvis-mcp
```

## Architecture

### Flow: User Request → Response

1. **CLI (`main.py`)** or **MCP Server (`mcp_server.py`)** receives user input
2. **ChiefOfStaff** (`chief/orchestrator.py`) calls Claude API with tools to decide what to do
3. Tool calls execute in a loop (max 25 rounds) until Claude returns a text response:
   - Memory/lifecycle tools → **MemoryStore** (SQLite)
   - Document tools → **DocumentStore** (ChromaDB)
   - Agent tools → **AgentDispatcher** runs expert agents concurrently via `asyncio.gather()`
4. Expert agents (`agents/base.py`) run their own tool-use loops with Claude, accessing capabilities granted by their YAML config

### Module Map

| Module | Purpose |
|--------|---------|
| `chief/orchestrator.py` | Decision-making loop: calls Claude API, handles tool results, maintains conversation history |
| `chief/dispatcher.py` | Async parallel agent execution with configurable timeout (60s default) |
| `agents/registry.py` | Loads/saves agent configs from YAML files in `agent_configs/` |
| `agents/base.py` | Expert agent execution: own tool-use loop with capability-gated tools |
| `agents/factory.py` | Uses Claude to dynamically generate new agent configs |
| `capabilities/registry.py` | Maps capability names (e.g. `calendar_read`) to tool schemas; validates agent configs |
| `memory/store.py` | SQLite backend: facts, locations, context, decisions, delegations, alert_rules |
| `memory/models.py` | Dataclasses: Fact, Location, ContextEntry, Decision, Delegation, AlertRule |
| `documents/store.py` | ChromaDB vector search wrapper (all-MiniLM-L6-v2 embeddings) |
| `documents/ingestion.py` | Text chunking (word-based, 500 words, 50 overlap) and SHA256 dedup |
| `tools/definitions.py` | Tool schemas (JSON Schema dicts) for the Anthropic API |
| `tools/lifecycle.py` | Execution logic for decisions, delegations, and alert rules |
| `config.py` | All paths, model names, constants, and environment variable settings |
| `mcp_server.py` | FastMCP server exposing 57+ tools and 3 resources via stdio transport |

### Apple Platform Integrations (macOS only)

| Module | Backend | Purpose |
|--------|---------|---------|
| `apple_calendar/eventkit.py` | PyObjC EventKit | Calendar CRUD — returns dicts, never raw PyObjC objects |
| `apple_reminders/eventkit.py` | PyObjC EventKit | Reminders CRUD |
| `apple_mail/mail.py` | osascript (AppleScript) | Mail read/search/send |
| `apple_messages/messages.py` | SQLite (chat.db) + osascript | iMessage history read + send |
| `apple_notifications/notifier.py` | osascript | macOS notification center |

All platform-specific imports use `try/except ImportError` guards.

### Unified Calendar System

| Module | Purpose |
|--------|---------|
| `connectors/calendar_unified.py` | Routes calendar ops across Apple Calendar and Microsoft 365 |
| `connectors/router.py` | Provider routing with ownership database (`calendar-routing.db`) |
| `connectors/providers/apple_provider.py` | Wraps `CalendarStore` |
| `connectors/providers/m365_provider.py` | Wraps `ClaudeM365Bridge` |
| `connectors/claude_m365_bridge.py` | Accesses M365 via Claude CLI subprocess with built-in M365 connector |

### OKR Tracking

| Module | Purpose |
|--------|---------|
| `okr/parser.py` | Parses Excel spreadsheet into `OKRSnapshot` |
| `okr/models.py` | Dataclasses: Objective, KeyResult, Initiative, OKRSnapshot |
| `okr/store.py` | JSON-backed persistence with query/filter support |

### Capabilities System

Agent YAML configs declare capabilities (e.g. `calendar_read`, `mail_write`, `memory_read`). The capabilities registry (`capabilities/registry.py`) maps each capability to specific tool schemas. When an agent runs, it only gets tools matching its declared capabilities. Key function: `get_tools_for_capabilities(capabilities) → list[tool_schemas]`.

22 implemented capabilities: `memory_read`, `memory_write`, `document_search`, `calendar_read`, `reminders_read`, `reminders_write`, `notifications`, `mail_read`, `mail_write`, `decision_read`, `decision_write`, `delegation_read`, `delegation_write`, `alerts_read`, `alerts_write`, and others.

### Key Patterns

- **Tool-use loop**: Both ChiefOfStaff and BaseExpertAgent loop on `response.stop_reason == "tool_use"`, executing tools and feeding results back until Claude produces a text response.
- **Dependency injection**: ChiefOfStaff and agents receive store instances via constructors. Tests use `tmp_path` fixtures for isolation.
- **MCP state management**: `mcp_server.py` uses a module-level `_state` dict populated during FastMCP lifespan for sharing stores across tool handlers.
- **API resilience**: `retry_api_call` decorator (`utils/`) with exponential backoff, max 3 retries.

## Configuration

All settings live in `config.py`:
- `ANTHROPIC_API_KEY`: from environment variable
- `DEFAULT_MODEL` / `CHIEF_MODEL`: `claude-sonnet-4-5-20250929`
- `VALID_FACT_CATEGORIES`: `personal`, `preference`, `work`, `relationship`, `backlog`
- `MAX_TOOL_ROUNDS`: 25 (orchestrator loop limit)
- `AGENT_TIMEOUT_SECONDS`: 60
- Agent configs: YAML files in `agent_configs/`
- Runtime data: `data/memory.db` (SQLite), `data/chroma/` (ChromaDB), `data/okr/` (OKR snapshots)
- Calendar routing: `data/calendar-routing.db` (event ownership tracking)
- M365 bridge: `CLAUDE_BIN`, `CLAUDE_MCP_CONFIG`, `M365_BRIDGE_MODEL`, `M365_BRIDGE_TIMEOUT_SECONDS` (all env vars)

## Memory Store Schema

SQLite (`data/memory.db`) with 6 tables:

| Table | Key Constraints | Notable Fields |
|-------|----------------|----------------|
| `facts` | `UNIQUE(category, key)` | category, key, value, confidence (0.0-1.0) |
| `locations` | `name UNIQUE` | address, latitude, longitude |
| `context` | — | session_id, topic, summary, agent |
| `decisions` | — | status: `pending_execution\|executed\|deferred\|reversed`, follow_up_date, tags |
| `delegations` | — | delegated_to, priority: `low\|medium\|high\|critical`, status: `active\|completed\|cancelled` |
| `alert_rules` | `name UNIQUE` | alert_type, condition (JSON), enabled (0/1) |

## Testing Conventions

- Async tests use `@pytest.mark.asyncio` with `asyncio_mode = "Mode.STRICT"` in pyproject.toml
- Anthropic API calls are mocked — tests never hit real APIs
- Fixtures create isolated MemoryStore, DocumentStore, AgentRegistry instances using `tmp_path`
- No shared conftest.py — fixtures are defined per test module
- Agent names must match: `^[a-z0-9][a-z0-9_-]*$`

## Package Naming Warning

**NEVER** name a package `calendar/` — it shadows Python's stdlib `calendar` module, breaking `http.cookiejar` → `httpx` → `anthropic` import chain. Use `apple_calendar/` instead.
