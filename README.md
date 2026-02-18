# Chief of Staff (Jarvis)

**Personal AI Chief of Staff with persistent memory, document search, expert agents, and native macOS integrations.**

---

## Overview

Chief of Staff (Jarvis) is a Python AI orchestration system built on Anthropic's Claude. A "Chief of Staff" agent manages a roster of expert agents, each configured with YAML and granted scoped capabilities. It interprets user requests, routes to the right specialists, dispatches them in parallel when possible, and synthesizes results.

The system exposes 57+ tools via the Model Context Protocol (MCP), covering persistent memory, semantic document search, calendar management (Apple Calendar and Microsoft 365), Apple Reminders, Apple Mail, iMessage, macOS notifications, OKR tracking, and a full decision/delegation lifecycle. All platform-specific integrations use PyObjC EventKit or AppleScript, with import guards for cross-platform safety.

Jarvis ships as both an MCP stdio server (for Claude Code) and a DXT package (for Claude Desktop), making it usable from any MCP-compatible host.

## Features

- **Persistent memory** -- facts (with categories and confidence scores), named locations, session context, decisions, delegations, and alert rules, all stored in SQLite
- **Document search** -- ChromaDB vector search with all-MiniLM-L6-v2 embeddings; ingests `.txt`, `.md`, `.py`, `.json`, `.yaml`, `.pdf`, and `.docx` files with word-based chunking and SHA256 dedup
- **Expert agent system** -- YAML-configured agents with capability-gated tool access; agents run their own tool-use loops with Claude
- **Unified calendar** -- Routes operations across Apple Calendar and Microsoft 365; provider routing with ownership tracking database
- **Apple Reminders** -- Full CRUD via PyObjC EventKit (list, create, complete, delete, search)
- **Apple Mail** -- Read, search, send, flag, and move messages via AppleScript
- **iMessage** -- Read chat history from SQLite (`chat.db`), search threads, send replies via AppleScript
- **macOS notifications** -- Push notifications to Notification Center
- **OKR tracking** -- Parse Excel spreadsheets into structured OKR snapshots with query/filter support
- **Decision and delegation lifecycle** -- Log decisions, track delegations with priorities and due dates, check for overdue items
- **Scheduled alerts** -- Configurable alert rules evaluated on a schedule (via launchd); checks for overdue delegations, stale decisions, and upcoming deadlines
- **iMessage inbox monitor** -- Autonomous daemon that processes incoming commands via iMessage

## Quick Start

### Prerequisites

- Python 3.11+
- macOS (required for Apple Calendar, Reminders, Mail, Messages, and Notifications integrations)
- An [Anthropic API key](https://console.anthropic.com/)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/chief_of_staff.git
cd chief_of_staff

# Install in development mode with test dependencies
pip install -e ".[dev]"

# Copy the example environment file and add your API key
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY
```

### First Run

```bash
# Start the MCP server
jarvis-mcp
```

The server communicates over stdio using JSON-RPC. Connect it to Claude Code or Claude Desktop (see Deployment Modes below).

## Deployment Modes

### MCP Server (Claude Code)

Add to your Claude Code MCP configuration:

```json
{
  "mcpServers": {
    "jarvis": {
      "command": "jarvis-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here"
      }
    }
  }
}
```

### DXT Package (Claude Desktop)

Build and install the desktop extension:

```bash
mcpb pack . jarvis.mcpb
```

Then install `jarvis.mcpb` in Claude Desktop via Settings > Extensions.

## Configuration

All settings are defined in `config.py` and can be overridden with environment variables. See `.env.example` for the full list.

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude |
| `CLAUDE_BIN` | No | Path to `claude` CLI binary (default: `claude`) |
| `CLAUDE_MCP_CONFIG` | No | Path to MCP config for M365 bridge |
| `M365_BRIDGE_MODEL` | No | Model for M365 bridge calls (default: `sonnet`) |
| `M365_BRIDGE_TIMEOUT_SECONDS` | No | Timeout for M365 bridge calls (default: `90`) |
| `CALENDAR_REQUIRE_DUAL_READ` | No | Require both providers for availability checks (default: `true`) |

Runtime data is stored in `data/`:
- `data/memory.db` -- SQLite database for facts, locations, decisions, delegations, alerts
- `data/chroma/` -- ChromaDB vector store for document search
- `data/okr/` -- OKR snapshot storage
- `data/calendar-routing.db` -- Calendar event ownership tracking

## Project Structure

```
chief_of_staff/
|-- mcp_server.py              # Entry point: FastMCP server (stdio transport)
|-- config.py                  # All paths, model names, constants
|-- manifest.json              # DXT package manifest for Claude Desktop
|
|-- mcp_tools/                 # MCP tool handlers, organized by domain
|   |-- state.py               # ServerState dataclass
|   |-- memory_tools.py        # Facts, locations
|   |-- document_tools.py      # Semantic search, ingestion
|   |-- agent_tools.py         # Agent CRUD
|   |-- lifecycle_tools.py     # Decisions, delegations, alerts
|   |-- calendar_tools.py      # Unified calendar operations
|   |-- reminder_tools.py      # Apple Reminders
|   |-- mail_tools.py          # Apple Mail, notifications
|   |-- imessage_tools.py      # iMessage read/send
|   |-- okr_tools.py           # OKR tracking
|   +-- resources.py           # MCP resources
|
|-- agents/                    # Expert agent framework
|   |-- base.py                # BaseExpertAgent with tool-use loop
|   |-- registry.py            # Load/save YAML agent configs
|   +-- factory.py             # Dynamic agent creation via Claude
|
|-- agent_configs/             # YAML configuration files for expert agents
|-- capabilities/              # Capability-to-tool mapping registry
|
|-- memory/                    # SQLite-backed persistent storage
|   |-- store.py               # MemoryStore (facts, locations, decisions, etc.)
|   +-- models.py              # Dataclasses for all memory entities
|
|-- documents/                 # Document ingestion and vector search
|   |-- store.py               # ChromaDB wrapper
|   +-- ingestion.py           # Text/PDF/DOCX chunking
|
|-- connectors/                # Unified calendar routing
|   |-- calendar_unified.py    # Multi-provider calendar service
|   |-- router.py              # Provider routing logic
|   |-- claude_m365_bridge.py  # Microsoft 365 via Claude CLI
|   +-- providers/             # Apple and M365 provider adapters
|
|-- apple_calendar/            # PyObjC EventKit calendar wrapper
|-- apple_reminders/           # PyObjC EventKit reminders wrapper
|-- apple_mail/                # AppleScript mail integration
|-- apple_messages/            # iMessage SQLite + AppleScript
|-- apple_notifications/       # macOS notification center
|
|-- okr/                       # OKR tracking (Excel parser, models, store)
|-- scheduler/                 # Scheduled alert evaluation
|-- tools/                     # Decision/delegation execution logic
|-- scripts/                   # Shell scripts and launchd plists
|-- tests/                     # Test suite
+-- docs/                      # Documentation
```

## Documentation

- [Architecture](docs/architecture.md) -- System design, data flow, and module interactions
- [iMessage Inbox Monitor Setup](docs/inbox-monitor-setup.md) -- Configuring the autonomous iMessage daemon

## Testing

```bash
# Run the full test suite
pytest

# Run a specific test file
pytest tests/test_mcp_server.py

# Run a single test
pytest tests/test_mcp_server.py::TestMCPTools::test_query_memory -v

# Run with coverage
pytest --cov=agents --cov=memory --cov=documents --cov=mcp_tools
```

The test suite contains 577 tests across 27+ test files. All Anthropic API calls are mocked -- tests never hit real APIs. Fixtures create isolated store instances using `tmp_path` for full test isolation.

## License

All rights reserved. License TBD.
