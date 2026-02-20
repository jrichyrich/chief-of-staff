# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Chief of Staff (Jarvis) is a Python AI orchestration system where a "Chief of Staff" agent manages expert agents. It interprets user requests, routes to specialized agents, dispatches them in parallel, and synthesizes results. Two deployment modes:

- **MCP Server** (`jarvis-mcp` / `mcp_server.py`) — FastMCP stdio server for Claude Code/Desktop integration
- **Desktop Extension** (`manifest.json`) — DXT package for Claude Desktop; build with `mcpb pack . jarvis.mcpb`

## Development Commands

```bash
# Install (dev mode with test deps)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_mcp_server.py

# Run a specific test
pytest tests/test_mcp_server.py::TestMCPTools::test_query_memory -v

# Run with coverage
pytest --cov=agents --cov=memory --cov=documents --cov=mcp_tools

# Start MCP server
jarvis-mcp
```

## Architecture

### Flow: User Request → Response

1. **MCP Server** (`mcp_server.py`) receives tool calls from Claude Code/Desktop
2. Tool handlers in `mcp_tools/` modules execute directly — memory, calendar, reminders, mail, agents, etc.
3. Expert agents (`agents/base.py`) run their own tool-use loops with Claude, accessing capabilities granted by their YAML config

### MCP Server Structure

`mcp_server.py` is a slim entry point (~170 lines) that initializes stores and registers tool modules. All tool handlers live in the `mcp_tools/` package:

| Module | Tools |
|--------|-------|
| `mcp_tools/state.py` | `ServerState` dataclass, `_retry_on_transient` helper |
| `mcp_tools/memory_tools.py` | store_fact, delete_fact, query_memory, store_location, list_locations, checkpoint_session |
| `mcp_tools/document_tools.py` | search_documents, ingest_documents (supports .txt, .md, .py, .json, .yaml, .pdf, .docx) |
| `mcp_tools/agent_tools.py` | list_agents, get_agent, create_agent |
| `mcp_tools/lifecycle_tools.py` | create_decision, search_decisions, update_decision, delete_decision, list_pending_decisions, create_delegation, list_delegations, update_delegation, delete_delegation, check_overdue_delegations, create_alert_rule, list_alert_rules, check_alerts, dismiss_alert |
| `mcp_tools/calendar_tools.py` | list_calendars, get_calendar_events, create/update/delete_calendar_event, search_calendar_events, find_my_open_slots, find_group_availability |
| `mcp_tools/reminder_tools.py` | list_reminder_lists, list_reminders, create_reminder, complete_reminder, delete_reminder, search_reminders |
| `mcp_tools/mail_tools.py` | send_notification, list_mailboxes, get_mail_messages, get_mail_message, search_mail, mark_mail_read, mark_mail_flagged, move_mail_message, send_email |
| `mcp_tools/imessage_tools.py` | get_imessages, list_imessage_threads, get_imessage_threads, get_imessage_thread_messages, get_thread_context, search_imessages, send_imessage_reply |
| `mcp_tools/okr_tools.py` | refresh_okr_data, query_okr_status |
| `mcp_tools/webhook_tools.py` | list_webhook_events, get_webhook_event, process_webhook_event |
| `mcp_tools/skill_tools.py` | record_tool_usage, analyze_skill_patterns, list_skill_suggestions, auto_create_skill |
| `mcp_tools/scheduler_tools.py` | create_scheduled_task, list_scheduled_tasks, update_scheduled_task, delete_scheduled_task, run_scheduled_task, get_scheduler_status |
| `mcp_tools/resources.py` | MCP resources: facts://all, memory://facts/{category}, agents://list |

Each module exports a `register(mcp, state)` function. Tools are defined inside `register()` using `@mcp.tool()` decorators and access stores via `state.memory_store`, `state.calendar_store`, etc. Tool functions are also exposed at module level via `sys.modules` for test imports.

### Module Map

| Module | Purpose |
|--------|---------|
| `mcp_server.py` | Slim entry point: store initialization (lifespan), tool module registration |
| `mcp_tools/` | All MCP tool handlers, organized by domain (see table above) |
| `agents/base.py` | Expert agent execution: own tool-use loop with capability-gated tools |
| `agents/registry.py` | Loads/saves agent configs from YAML files in `agent_configs/` |
| `agents/factory.py` | Uses Claude to dynamically generate new agent configs |
| `capabilities/registry.py` | Maps capability names (e.g. `calendar_read`) to tool schemas; validates agent configs |
| `memory/store.py` | SQLite backend: facts (with FTS5 full-text index), locations, context, decisions, delegations, alert_rules, webhook_events, scheduled_tasks, skill_usage, skill_suggestions |
| `memory/models.py` | Dataclasses: Fact, Location, ContextEntry, Decision, Delegation, AlertRule, WebhookEvent, ScheduledTask, SkillUsage, SkillSuggestion |
| `documents/store.py` | ChromaDB vector search wrapper (all-MiniLM-L6-v2 embeddings) |
| `documents/ingestion.py` | Text/PDF/DOCX chunking (word-based, 500 words, 50 overlap) and SHA256 dedup |
| `tools/lifecycle.py` | Execution logic for decisions, delegations, and alert rules |
| `scheduler/alert_evaluator.py` | Standalone alert rule evaluator (runs via launchd every 2 hours) |
| `scheduler/engine.py` | Built-in scheduler engine with cron parser, evaluates due tasks from SQLite |
| `skills/pattern_detector.py` | Detects repeated usage patterns and suggests new agent configurations |
| `webhook/server.py` | Async HTTP webhook receiver with HMAC-SHA256 signature verification |
| `config.py` | All paths, model names, constants, and environment variable settings |

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

**Important**: `find_my_open_slots` defaults to `provider_preference="both"` to pull events from ALL providers. Never rely on a single provider for availability checks.

### OKR Tracking

| Module | Purpose |
|--------|---------|
| `okr/parser.py` | Parses Excel spreadsheet into `OKRSnapshot` |
| `okr/models.py` | Dataclasses: Objective, KeyResult, Initiative, OKRSnapshot |
| `okr/store.py` | JSON-backed persistence with query/filter support |

### Capabilities System

Agent YAML configs declare capabilities (e.g. `calendar_read`, `mail_write`, `memory_read`). The capabilities registry (`capabilities/registry.py`) maps each capability to specific tool schemas. When an agent runs, it only gets tools matching its declared capabilities. Key function: `get_tools_for_capabilities(capabilities) → list[tool_schemas]`.

### Key Patterns

- **Tool module registration**: Each `mcp_tools/` module defines tools inside a `register(mcp, state)` function. The `mcp_server.py` entry point calls all register functions at module level.
- **Typed state management**: `ServerState` dataclass (`mcp_tools/state.py`) with typed fields for each store. Populated during FastMCP lifespan. Supports dict-style access for backward compatibility with tests.
- **Tool-use loop**: BaseExpertAgent loops on `response.stop_reason == "tool_use"`, executing tools and feeding results back until Claude produces a text response. Capped at `MAX_TOOL_ROUNDS` (25).
- **Dependency injection**: Agents receive store instances via constructors. Tests use `tmp_path` fixtures for isolation.
- **Retry logic**: `_retry_on_transient` in `mcp_tools/state.py` retries on `sqlite3.OperationalError` and `OSError` with exponential backoff. `retry_api_call` in `utils/` handles Anthropic API retries.

## Configuration

All settings live in `config.py`:
- `ANTHROPIC_API_KEY`: from environment variable
- `DEFAULT_MODEL`: `claude-sonnet-4-5-20250929`
- `VALID_FACT_CATEGORIES`: `personal`, `preference`, `work`, `relationship`, `backlog`
- `MAX_TOOL_ROUNDS`: 25 (agent loop limit)
- `AGENT_TIMEOUT_SECONDS`: 60
- Agent configs: YAML files in `agent_configs/`
- Runtime data: `data/memory.db` (SQLite), `data/chroma/` (ChromaDB), `data/okr/` (OKR snapshots)
- Calendar routing: `data/calendar-routing.db` (event ownership tracking)
- M365 bridge: `CLAUDE_BIN`, `CLAUDE_MCP_CONFIG`, `M365_BRIDGE_MODEL`, `M365_BRIDGE_TIMEOUT_SECONDS` (all env vars)

## Memory Store Schema

SQLite (`data/memory.db`) with 10 tables:

| Table | Key Constraints | Notable Fields |
|-------|----------------|----------------|
| `facts` | `UNIQUE(category, key)` | category, key, value, confidence (0.0-1.0) |
| `facts_fts` | FTS5 virtual table | Synced via triggers, BM25 ranking |
| `locations` | `name UNIQUE` | address, latitude, longitude |
| `context` | — | session_id, topic, summary, agent |
| `decisions` | — | status: `pending_execution\|executed\|deferred\|reversed`, follow_up_date, tags |
| `delegations` | — | delegated_to, priority: `low\|medium\|high\|critical`, status: `active\|completed\|cancelled` |
| `alert_rules` | `name UNIQUE` | alert_type, condition (JSON), enabled (0/1) |
| `webhook_events` | — | source, event_type, payload (JSON), status: `pending\|processed\|failed` |
| `scheduled_tasks` | `name UNIQUE` | schedule_type: `interval\|cron\|once`, handler_type, enabled, next_run_at |
| `skill_usage` | `UNIQUE(tool_name, query_pattern)` | count, last_used |
| `skill_suggestions` | — | suggested_name, confidence, status: `pending\|accepted\|rejected` |

## Testing Conventions

- 825 tests across 44 test files
- Async tests use `@pytest.mark.asyncio` with `asyncio_mode = "Mode.STRICT"` in pyproject.toml
- Anthropic API calls are mocked — tests never hit real APIs
- Fixtures create isolated MemoryStore, DocumentStore, AgentRegistry instances using `tmp_path`
- No shared conftest.py — fixtures are defined per test module
- Agent names must match: `^[a-z0-9][a-z0-9_-]*$`
- Tool functions are imported from `mcp_tools.*` modules (e.g. `from mcp_tools.calendar_tools import list_calendars`)
- Tests must `import mcp_server` first to trigger `register()` calls before importing tool functions

## Agent Teams

When a task involves 3+ independent subtasks that can run in parallel (e.g., multi-source research, OKR analysis, meeting prep, daily briefs, code analysis across multiple files), **proactively create a team of agents**. Do not wait for explicit user instruction to parallelize — default to spinning up teams whenever there is a clear parallelization opportunity.

## Package Naming Warning

**NEVER** name a package `calendar/` — it shadows Python's stdlib `calendar` module, breaking `http.cookiejar` → `httpx` → `anthropic` import chain. Use `apple_calendar/` instead.
