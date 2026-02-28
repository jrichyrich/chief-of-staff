# Chief of Staff (Jarvis)

**Personal AI Chief of Staff with persistent memory, document search, expert agents, and native macOS integrations.**

---

## Overview

Chief of Staff (Jarvis) is a Python AI orchestration system built on Anthropic's Claude. A "Chief of Staff" agent manages a roster of expert agents, each configured with YAML and granted scoped capabilities. It interprets user requests, routes to the right specialists, dispatches them in parallel when possible, and synthesizes results.

The system exposes **112 tools** and **4 resources** across **26 modules** via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/), covering:

- **Persistent memory** with temporal decay, FTS5 full-text search, MMR reranking, and ChromaDB vector search
- **Semantic document search** with word-based chunking and SHA256 dedup
- **Unified calendar** across Apple Calendar and Microsoft 365 with provider routing and ownership tracking
- **Apple Reminders, Mail, iMessage, and macOS notifications** via PyObjC EventKit and AppleScript
- **OKR tracking** from Excel spreadsheets
- **Decision/delegation lifecycle** with alerts and due-date tracking
- **Webhook ingestion** with event-driven agent dispatch
- **Built-in scheduler** with interval, cron, and one-shot task types
- **Self-authoring skills** via tool usage pattern detection
- **Proactive suggestions** surfacing overdue items and session health
- **Unified channel adapters** and cross-channel identity linking
- **Session management** with compaction, brain persistence, and checkpoint/restore
- **Plugin hooks** for lifecycle extensibility
- **Microsoft Teams messaging** via persistent Playwright browser automation
- **Person enrichment** from 6 parallel data sources
- **Outbound channel routing** with safety tiers and work-hours awareness
- **Team playbooks** for YAML-defined parallel workstreams
- **Humanizer** text post-processing to remove AI writing patterns

Jarvis ships as both an MCP stdio server (for Claude Code) and a DXT package (for Claude Desktop).

## Quick Start

### Prerequisites

- Python 3.11+
- macOS (required for Apple Calendar, Reminders, Mail, Messages, and Notifications integrations)
- An [Anthropic API key](https://console.anthropic.com/)

### Installation

```bash
# Clone the repository
git clone https://github.com/jrichyrich/chief-of-staff.git
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
| `SCHEDULER_ENABLED` | No | Enable the built-in scheduler (default: `true`) |
| `DAEMON_TICK_INTERVAL_SECONDS` | No | Daemon tick interval (default: `60`) |
| `SCHEDULER_HANDLER_TIMEOUT_SECONDS` | No | Per-handler execution timeout (default: `300`) |
| `MAX_CONCURRENT_AGENT_DISPATCHES` | No | Parallel agent dispatch limit (default: `5`) |
| `SKILL_AUTO_EXECUTE_ENABLED` | No | Auto-execute skill suggestions (default: `false`) |
| `PROACTIVE_PUSH_ENABLED` | No | Push proactive notifications (default: `false`) |
| `WEBHOOK_AUTO_DISPATCH_ENABLED` | No | Auto-dispatch webhook events (default: `false`) |

### Runtime Data

All runtime data is stored in `data/`:

| Path | Purpose |
|------|---------|
| `data/memory.db` | SQLite database (14 tables: facts, locations, decisions, delegations, alerts, identities, and more) |
| `data/chroma/` | ChromaDB vector store for document search (all-MiniLM-L6-v2 embeddings) |
| `data/okr/` | OKR snapshot storage (JSON) |
| `data/calendar-routing.db` | Calendar event ownership tracking (SQLite) |
| `data/session_brain.md` | Persistent cross-session context document |
| `data/webhook-inbox/` | File-drop inbox for webhook event ingestion |

## Project Structure

```
chief_of_staff/
|-- mcp_server.py              # Entry point: FastMCP server (stdio transport)
|-- config.py                  # All paths, model names, constants
|-- manifest.json              # DXT package manifest for Claude Desktop
|
|-- mcp_tools/                 # MCP tool handlers (26 modules, 112 tools + 4 resources)
|   |-- state.py               # ServerState dataclass, SessionHealth tracker
|   |-- decorators.py          # @tool_errors standardized error handling
|   |-- usage_tracker.py       # Automatic tool invocation tracking middleware
|   |-- memory_tools.py        # Facts, locations, session health (7 tools)
|   |-- document_tools.py      # Semantic search, ingestion (2 tools)
|   |-- agent_tools.py         # Agent CRUD, shared memory (7 tools)
|   |-- lifecycle_tools.py     # Decisions, delegations, alerts (14 tools)
|   |-- calendar_tools.py      # Unified calendar operations (8 tools)
|   |-- reminder_tools.py      # Apple Reminders (6 tools)
|   |-- mail_tools.py          # Apple Mail, notifications (10 tools)
|   |-- imessage_tools.py      # iMessage read/send (6 tools)
|   |-- okr_tools.py           # OKR tracking (3 tools)
|   |-- webhook_tools.py       # Webhook event management (3 tools)
|   |-- skill_tools.py         # Self-authoring skill patterns (6 tools)
|   |-- scheduler_tools.py     # Scheduled task management (6 tools)
|   |-- channel_tools.py       # Unified inbound event access (2 tools)
|   |-- proactive_tools.py     # Proactive suggestions (2 tools)
|   |-- identity_tools.py      # Cross-channel identity linking (4 tools)
|   |-- session_tools.py       # Session status, flush, restore (3 tools)
|   |-- event_rule_tools.py    # Event rules for agent dispatch (5 tools)
|   |-- enrichment.py          # Person data enrichment (1 tool)
|   |-- teams_browser_tools.py # Teams messaging via Playwright (5 tools)
|   |-- brain_tools.py         # Session brain read/update (2 tools)
|   |-- routing_tools.py       # Outbound channel routing (1 tool)
|   |-- playbook_tools.py      # Team playbooks (2 tools)
|   |-- formatter_tools.py     # Output formatting (4 tools)
|   |-- dispatch_tools.py      # Parallel multi-agent dispatch (1 tool)
|   |-- sharepoint_tools.py    # SharePoint file download (1 tool)
|   +-- resources.py           # MCP resources (4 resources)
|
|-- agents/                    # Expert agent framework
|   |-- base.py                # BaseExpertAgent with tool-use loop and hook integration
|   |-- registry.py            # Load/save YAML agent configs
|   |-- factory.py             # Dynamic agent creation via Claude
|   |-- triage.py              # Complexity classification for model tier selection
|   |-- loop_detector.py       # Repetitive tool-call detection
|   +-- mixins.py              # Domain-specific tool handler mixins
|
|-- agent_configs/             # 34 YAML configuration files for expert agents
|-- capabilities/              # Capability-to-tool mapping registry (34 capabilities)
|
|-- memory/                    # SQLite-backed persistent storage (facade + domain stores)
|   |-- store.py               # MemoryStore facade (14 tables)
|   |-- models.py              # Dataclasses and enums for all memory entities
|   |-- fact_store.py          # Facts, locations, context (FTS5 + vector search)
|   |-- lifecycle_store.py     # Decisions, delegations, alert rules
|   |-- webhook_store.py       # Webhook events, event rules
|   |-- scheduler_store.py     # Scheduled tasks
|   |-- skill_store.py         # Skill usage, tool usage log, suggestions
|   |-- agent_memory_store.py  # Per-agent and shared memory
|   +-- identity_store.py      # Cross-channel identity links
|
|-- documents/                 # Document ingestion and vector search
|   |-- store.py               # ChromaDB wrapper
|   +-- ingestion.py           # Text/PDF/DOCX chunking (500 words, 50 overlap)
|
|-- connectors/                # Unified calendar routing
|   |-- calendar_unified.py    # Multi-provider calendar service with dedup and ownership
|   |-- router.py              # Provider routing logic (read/write policies)
|   |-- provider_base.py       # CalendarProvider abstract base
|   |-- claude_m365_bridge.py  # Microsoft 365 via Claude CLI subprocess
|   +-- providers/             # Apple and M365 provider adapters
|
|-- apple_calendar/            # PyObjC EventKit calendar wrapper
|-- apple_reminders/           # PyObjC EventKit reminders wrapper
|-- apple_mail/                # AppleScript mail integration
|-- apple_messages/            # iMessage SQLite (chat.db) + AppleScript
|-- apple_notifications/       # macOS notification center
|
|-- okr/                       # OKR tracking (Excel parser, models, JSON store)
|-- scheduler/                 # Scheduler engine, daemon, handlers, delivery, availability
|-- delivery/                  # Delivery service with adapters (email, iMessage, notification, Teams)
|-- hooks/                     # Plugin hook system (YAML-configured lifecycle hooks)
|-- session/                   # Session manager + Session Brain (persistent context)
|-- webhook/                   # Webhook ingestion, receiver, and event-driven agent dispatch
|-- channels/                  # Unified channel adapter (InboundEvent, EventRouter, routing)
|-- playbooks/                 # YAML playbook definitions for parallel workstreams
|-- proactive/                 # Proactive suggestion engine
|-- skills/                    # Tool usage pattern detection
|-- browser/                   # Playwright browser manager, Teams poster, Okta auth, SharePoint
|-- humanizer/                 # AI writing pattern removal (rule-based text transforms)
|-- formatter/                 # Output formatting (brief, cards, tables, dashboard)
|-- tools/                     # Tool executor and lifecycle execution logic
|-- utils/                     # Shared utilities (retry, atomic file ops, subprocess, text)
|-- scripts/                   # Shell scripts, launchd plists, setup
|-- tests/                     # Test suite (2172 tests, 102 files)
+-- docs/                      # Documentation
```

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | Full system architecture with Mermaid diagrams |
| [Module Reference](docs/modules.md) | Detailed documentation for every module |
| [Tools Reference](docs/tools-reference.md) | Complete reference for all 112 MCP tools |
| [Agent System](docs/agents.md) | Agent architecture, capabilities, and configuration |
| [Setup Guide](docs/setup-guide.md) | Installation, environment variables, and troubleshooting |
| [How-To Guides](docs/how-to-guides.md) | Task-oriented guides for common operations |
| [iMessage Inbox Monitor](docs/inbox-monitor-setup.md) | Configuring the autonomous iMessage daemon |
| [Project Review Team](docs/project-review-team.md) | Running structured project reviews with specialist agents |

### Architectural Decision Records

| ADR | Decision |
|-----|----------|
| [ADR-001](docs/adrs/001-mcp-over-rest.md) | MCP over REST API for Claude integration |
| [ADR-002](docs/adrs/002-sqlite-memory-store.md) | SQLite as the primary data store |
| [ADR-003](docs/adrs/003-capability-gated-agents.md) | Capability-gated agent tool access |
| [ADR-004](docs/adrs/004-facade-memory-store.md) | Facade pattern for MemoryStore decomposition |
| [ADR-005](docs/adrs/005-unified-calendar-routing.md) | Unified calendar with provider routing |
| [ADR-006](docs/adrs/006-persistent-daemon.md) | Persistent daemon replacing launchd agents |
| [ADR-007](docs/adrs/007-safety-tiered-routing.md) | Safety-tiered outbound message routing |

### Design Documents

Historical design and implementation plans are archived in [docs/plans/](docs/plans/).

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

The test suite contains **2172 tests across 102 test files**. All Anthropic API calls are mocked -- tests never hit real APIs. Fixtures create isolated store instances using `tmp_path` for full test isolation. CI runs on Python 3.11 and 3.12 via GitHub Actions.

## Key Design Principles

1. **No internal LLM calls from the MCP server** -- The host Claude instance handles all reasoning. The MCP server is a thin tool layer.
2. **Capability-gated agents** -- Expert agents only receive tool schemas matching their declared YAML capabilities, enforcing least-privilege access.
3. **Dependency injection everywhere** -- Stores are passed to constructors, never imported globally. Tests use `tmp_path` fixtures for full isolation.
4. **Platform safety via import guards** -- All macOS-specific imports use `try/except ImportError`, enabling the core system to run on non-macOS platforms.
5. **Fail-safe delivery** -- Delivery failures never propagate or block task execution. Each adapter catches its own exceptions.
6. **One agent failure never blocks others** -- Parallel dispatch via `asyncio.gather` with per-agent error isolation.

## License

All rights reserved. License TBD.
