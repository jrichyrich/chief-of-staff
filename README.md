# Chief of Staff (Jarvis)

**Personal AI Chief of Staff with persistent memory, document search, expert agents, and native macOS integrations.**

---

## Overview

Chief of Staff (Jarvis) is a Python AI orchestration system built on Anthropic's Claude. A "Chief of Staff" agent manages a roster of expert agents, each configured with YAML and granted scoped capabilities. It interprets user requests, routes to the right specialists, dispatches them in parallel when possible, and synthesizes results.

The system exposes 105 tools across 24 modules via the Model Context Protocol (MCP), covering persistent memory (with temporal decay, FTS5, MMR reranking, and vector search), semantic document search, calendar management (Apple Calendar and Microsoft 365), Apple Reminders, Apple Mail, iMessage, macOS notifications, OKR tracking, a full decision/delegation lifecycle, webhook ingestion, event-driven agent dispatch, scheduled tasks, self-authoring skills, proactive suggestions, unified channel adapters, cross-channel identity linking, session compaction, and plugin hooks. All platform-specific integrations use PyObjC EventKit or AppleScript, with import guards for cross-platform safety.

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
- **Temporal decay + hybrid search** -- Facts scored by recency (90-day half-life); FTS5 full-text + LIKE + ChromaDB vector search merged with MMR reranking for diversity
- **Pinned facts** -- Facts marked as pinned never decay over time
- **Webhook ingestion** -- File-drop inbox pattern; external automations drop JSON, ingested on schedule
- **Event-driven agent dispatch** -- Event rules link webhook events to expert agents; matching, dispatch, and delivery in one pipeline
- **Built-in scheduler** -- SQLite-backed task scheduler with interval/cron/once types; handlers for alerts, webhooks, skill analysis
- **Autonomous scheduler daemon** -- launchd job (`com.chg.jarvis-scheduler`) runs the scheduler engine every 5 minutes
- **Self-authoring skills** -- Tracks tool usage patterns, detects clusters via Jaccard similarity, suggests and auto-creates new agent configs
- **Agent memory** -- Per-agent persistent memory (insights, preferences, context) injected into system prompts across runs; shared namespaces for cross-agent collaboration
- **Proactive suggestions** -- Engine that surfaces skill suggestions, overdue delegations, stale decisions, and upcoming deadlines
- **Unified channel adapter** -- Common InboundEvent model normalizing iMessage, Mail, and Webhook sources with EventRouter dispatch
- **Cross-channel identity linking** -- Maps provider accounts (iMessage, email, Teams, Jira, etc.) to canonical person names for unified identity resolution
- **Plugin hooks** -- YAML-configured lifecycle hooks (before/after tool call, session start/end) for extensibility
- **Session compaction** -- Session manager tracks interactions, extracts structured data (decisions, action items, facts), and flushes to long-term memory
- **Loop detection** -- Detects repeated tool-use patterns to prevent agent infinite loops
- **Session health monitoring** -- Tracks tool call count and checkpoint freshness to recommend when to persist context
- **Delivery adapters** -- Task and event results delivered via email, iMessage, or macOS notification channels
- **Scheduled alerts** -- Configurable alert rules evaluated on a schedule (via launchd); checks for overdue delegations, stale decisions, and upcoming deadlines
- **iMessage inbox monitor** -- Autonomous daemon that processes incoming commands via iMessage
- **Microsoft Teams messaging** -- Send messages to Teams channels and people via persistent Playwright browser
- **Person enrichment** -- Parallel data fetching from 6 sources for person intelligence
- **Team Playbooks** -- YAML-defined parallel workstreams dispatched via Claude Code's Task tool; built-in playbooks for meeting prep, expert research, software development, and daily briefings
- **Session Brain** -- Persistent cross-session context document carrying workstreams, action items, decisions, people context, and handoff notes
- **Channel Routing** -- Safety-tiered outbound message routing with channel selection based on recipient type, urgency, and time of day

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
|   |-- state.py               # ServerState dataclass, SessionHealth tracker
|   |-- memory_tools.py        # Facts, locations, session health
|   |-- document_tools.py      # Semantic search, ingestion
|   |-- agent_tools.py         # Agent CRUD, shared memory
|   |-- lifecycle_tools.py     # Decisions, delegations, alerts
|   |-- calendar_tools.py      # Unified calendar operations
|   |-- reminder_tools.py      # Apple Reminders
|   |-- mail_tools.py          # Apple Mail, notifications
|   |-- imessage_tools.py      # iMessage read/send
|   |-- okr_tools.py           # OKR tracking
|   |-- webhook_tools.py       # Webhook event management
|   |-- skill_tools.py         # Self-authoring skill patterns
|   |-- scheduler_tools.py     # Scheduled task management
|   |-- channel_tools.py       # Unified inbound event access
|   |-- proactive_tools.py     # Proactive suggestions
|   |-- identity_tools.py      # Cross-channel identity linking
|   |-- session_tools.py       # Session status, flush, restore
|   |-- event_rule_tools.py    # Event rules for agent dispatch
|   |-- enrichment.py          # Person data enrichment (6 sources)
|   |-- teams_browser_tools.py # Teams messaging via Playwright
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
|   |-- store.py               # MemoryStore (14 tables incl. identities, event_rules)
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
|-- scheduler/                 # Scheduler engine, alert evaluator, delivery adapters
|-- hooks/                     # Plugin hook system (YAML-configured lifecycle hooks)
|-- session/                   # Session manager (interaction tracking, flush/restore)
|-- webhook/                   # Webhook ingestion and event-driven agent dispatch
|-- channels/                  # Unified channel adapter (InboundEvent, EventRouter, routing)
|-- playbooks/                 # YAML playbook definitions for parallel workstreams
|-- proactive/                 # Proactive suggestion engine
|-- skills/                    # Tool usage pattern detection
|-- tools/                     # Decision/delegation execution logic
|-- utils/                     # Shared utilities (retry logic)
|-- scripts/                   # Shell scripts and launchd plists
|-- tests/                     # Test suite (1723 tests, 75 files)
+-- docs/                      # Documentation
```

## Documentation

- [Architecture](docs/architecture.md) -- System design, data flow, and module interactions
- [iMessage Inbox Monitor Setup](docs/inbox-monitor-setup.md) -- Configuring the autonomous iMessage daemon
- [Tools Reference](docs/tools-reference.md) -- Complete reference for all 105 MCP tools
- [Agent System](docs/agents.md) -- Agent architecture, capabilities, and configuration guide
- [Setup Guide](docs/setup-guide.md) -- Installation, environment variables, and troubleshooting
- [Project Review Team](docs/project-review-team.md) -- Running structured project reviews with specialist agents

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

The test suite contains 1723 tests across 75 test files. All Anthropic API calls are mocked -- tests never hit real APIs. Fixtures create isolated store instances using `tmp_path` for full test isolation.

## License

All rights reserved. License TBD.
