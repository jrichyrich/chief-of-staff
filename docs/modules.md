# Module Reference

Detailed documentation for every module in the Chief of Staff (Jarvis) system, organized by subsystem.

---

## Table of Contents

1. [Entry Points](#entry-points)
2. [MCP Tool Modules](#mcp-tool-modules)
3. [Agent System](#agent-system)
4. [Memory System](#memory-system)
5. [Document System](#document-system)
6. [Calendar Connectors](#calendar-connectors)
7. [Apple Platform Integrations](#apple-platform-integrations)
8. [Scheduler System](#scheduler-system)
9. [Delivery System](#delivery-system)
10. [Session System](#session-system)
11. [Webhook System](#webhook-system)
12. [Channel System](#channel-system)
13. [Proactive System](#proactive-system)
14. [Skills System](#skills-system)
15. [Browser Automation](#browser-automation)
16. [Hooks System](#hooks-system)
17. [Humanizer](#humanizer)
18. [Formatter](#formatter)
19. [Playbooks](#playbooks)
20. [OKR Tracking](#okr-tracking)
21. [Utilities](#utilities)

---

## Entry Points

### `mcp_server.py`

The main entry point for the MCP server. A slim module (~278 lines) that:

1. Creates the `FastMCP` server instance with a lifespan manager
2. Initializes all stores (memory, documents, calendar, reminders, mail, messages, OKR, hooks, session brain, session manager)
3. Registers all 26 tool modules by calling their `register(mcp, state)` functions
4. Seeds default scheduled tasks (alert_eval, webhook_poll, webhook_dispatch, skill_analysis)
5. Installs the automatic usage tracker middleware
6. Provides the `main()` entry point that runs the server with stdio transport

Exposed as the `jarvis-mcp` console script via `pyproject.toml`.

### `config.py`

Central configuration module. All paths, model names, constants, and environment variable settings. Key settings:

| Setting | Default | Source |
|---------|---------|--------|
| `DEFAULT_MODEL` | `claude-sonnet-4-5-20250929` | Hardcoded |
| `MODEL_TIERS` | haiku, sonnet, opus | Hardcoded |
| `MAX_TOOL_ROUNDS` | 25 | Hardcoded |
| `AGENT_TIMEOUT_SECONDS` | 60 | Hardcoded |
| `DATA_DIR` | `./data` | Hardcoded |
| `DAEMON_TICK_INTERVAL_SECONDS` | 60 | Env var |
| `SCHEDULER_HANDLER_TIMEOUT_SECONDS` | 300 | Env var |
| `MAX_CONCURRENT_AGENT_DISPATCHES` | 5 | Env var |
| `SKILL_SUGGESTION_THRESHOLD` | 0.7 | Hardcoded |
| `DISPATCH_AGENTS_MAX_AGENTS` | 10 | Hardcoded |

---

## MCP Tool Modules

All modules in `mcp_tools/` follow the same pattern: export a `register(mcp, state)` function that defines tools inside using `@mcp.tool()` decorators. Tool functions are also exposed at module level via `sys.modules` for test imports.

### `mcp_tools/state.py`

Defines `ServerState` (a dataclass holding references to all stores) and `SessionHealth` (tracks tool call count and checkpoint timing). Also provides `_retry_on_transient()` for SQLite retry logic.

`ServerState` supports dict-style access (`state["memory_store"]`) for backward compatibility with tests.

### `mcp_tools/decorators.py`

Provides the `@tool_errors(context, expected)` decorator for standardized MCP tool error handling. Catches expected exceptions with a context prefix, and unexpected exceptions with full logging.

### `mcp_tools/usage_tracker.py`

Middleware that wraps `FastMCP._tool_manager.call_tool` to automatically record every tool invocation. Extracts a query pattern from tool arguments (checking keys like `query`, `name`, `title`, etc. in priority order). Records both aggregated `skill_usage` counts and individual `tool_usage_log` entries with timing. Self-referential skill tools are excluded from tracking.

### `mcp_tools/memory_tools.py` (7 tools)

- `store_fact` -- Store a fact with category, key, value, confidence, and optional pinning
- `delete_fact` -- Delete a fact by category and key
- `query_memory` -- Hybrid search (FTS5 + LIKE + vector) with MMR reranking
- `store_location` -- Store a named location with coordinates
- `list_locations` -- List all stored locations
- `checkpoint_session` -- Persist session context to memory
- `get_session_health` -- Return tool call count and checkpoint status

### `mcp_tools/document_tools.py` (2 tools)

- `search_documents` -- Semantic search over ingested documents via ChromaDB
- `ingest_documents` -- Ingest files (txt, md, py, json, yaml, pdf, docx) with word-based chunking (500 words, 50 overlap) and SHA256 dedup

### `mcp_tools/agent_tools.py` (7 tools)

- `list_agents` -- List all registered agents with descriptions and capabilities
- `get_agent` -- Get full agent config by name
- `create_agent` -- Create a new agent via AgentFactory (Claude generates YAML)
- `get_agent_memory` -- Get all memories for a specific agent
- `clear_agent_memory` -- Delete all memories for an agent
- `store_shared_memory` -- Store a memory in a shared namespace
- `get_shared_memory` -- Retrieve shared namespace memories

### `mcp_tools/lifecycle_tools.py` (14 tools)

Decisions: `create_decision`, `search_decisions`, `update_decision`, `delete_decision`, `list_pending_decisions`

Delegations: `create_delegation`, `list_delegations`, `update_delegation`, `delete_delegation`, `check_overdue_delegations`

Alerts: `create_alert_rule`, `list_alert_rules`, `check_alerts`, `dismiss_alert`

### `mcp_tools/calendar_tools.py` (8 tools)

- `list_calendars` -- List calendars across providers
- `get_calendar_events` -- Get events in a date range with provider routing
- `create_calendar_event` -- Create an event (auto-routes to appropriate provider)
- `update_calendar_event` -- Update an event (resolves provider from ownership DB)
- `delete_calendar_event` -- Delete an event
- `search_calendar_events` -- Search by title text
- `find_my_open_slots` -- Find available time slots (defaults to provider_preference="both")
- `find_group_availability` -- Guidance for multi-person scheduling

### `mcp_tools/reminder_tools.py` (6 tools)

- `list_reminder_lists`, `list_reminders`, `create_reminder`, `complete_reminder`, `delete_reminder`, `search_reminders`

### `mcp_tools/mail_tools.py` (10 tools)

- `send_notification`, `list_mailboxes`, `get_mail_messages`, `get_mail_message`, `search_mail`, `mark_mail_read`, `mark_mail_flagged`, `move_mail_message`, `reply_to_email`, `send_email`

### `mcp_tools/imessage_tools.py` (6 tools)

- `get_imessages`, `list_imessage_threads`, `get_imessage_thread_messages`, `get_thread_context`, `search_imessages`, `send_imessage_reply`

### `mcp_tools/okr_tools.py` (3 tools)

- `refresh_okr_data` -- Parse Excel spreadsheet into OKR snapshot
- `query_okr_status` -- Query OKR data with filters
- `refresh_okr_from_sharepoint` -- Download OKR spreadsheet from SharePoint and parse

### `mcp_tools/webhook_tools.py` (3 tools)

- `list_webhook_events`, `get_webhook_event`, `process_webhook_event`

### `mcp_tools/skill_tools.py` (6 tools)

- `record_tool_usage`, `analyze_skill_patterns`, `list_skill_suggestions`, `auto_create_skill`, `auto_execute_skills`, `get_tool_statistics`

### `mcp_tools/scheduler_tools.py` (6 tools)

- `create_scheduled_task`, `list_scheduled_tasks`, `update_scheduled_task`, `delete_scheduled_task`, `run_scheduled_task`, `get_scheduler_status`

### `mcp_tools/channel_tools.py` (2 tools)

- `list_inbound_events` -- List normalized events across iMessage, Mail, and Webhook channels
- `get_event_summary` -- Count events by channel

### `mcp_tools/proactive_tools.py` (2 tools)

- `get_proactive_suggestions` -- Generate and return prioritized suggestions
- `dismiss_suggestion` -- Dismiss a suggestion so it does not reappear

### `mcp_tools/identity_tools.py` (4 tools)

- `link_identity`, `unlink_identity`, `get_identity`, `search_identity`

### `mcp_tools/session_tools.py` (3 tools)

- `get_session_status` -- Return session interaction count, token estimate, and extracted data summary
- `flush_session_memory` -- Persist decisions, actions, and facts to long-term memory
- `restore_session` -- Load previous session context from a checkpoint

### `mcp_tools/event_rule_tools.py` (5 tools)

- `create_event_rule`, `update_event_rule`, `delete_event_rule`, `list_event_rules`, `process_webhook_event_with_agents`

### `mcp_tools/enrichment.py` (1 tool)

- `enrich_person` -- Parallel data fetching from 6 sources (identities, facts, delegations, decisions, iMessages, emails)

### `mcp_tools/teams_browser_tools.py` (5 tools)

- `open_teams_browser`, `post_teams_message`, `confirm_teams_post`, `cancel_teams_post`, `close_teams_browser`

### `mcp_tools/brain_tools.py` (2 tools)

- `get_session_brain` -- Return the session brain as a dict
- `update_session_brain` -- Add/update workstreams, action items, decisions, people, and handoff notes

### `mcp_tools/routing_tools.py` (1 tool)

- `route_message` -- Determine safety tier and channel for an outbound message

### `mcp_tools/playbook_tools.py` (2 tools)

- `list_playbooks` -- List available playbook definitions
- `get_playbook` -- Get a playbook with input substitution applied

### `mcp_tools/formatter_tools.py` (4 tools)

- `format_brief` -- Render a daily brief
- `format_table` -- Render data as a table
- `format_card` -- Render a card-style display
- `format_dashboard` -- Render a multi-section dashboard

**Note**: Formatter tools are for delivery channels only (email, iMessage, notification). Do NOT call them during interactive Claude Code sessions -- ANSI escape codes display as raw garbage.

### `mcp_tools/dispatch_tools.py` (1 tool)

- `dispatch_agents` -- Parallel multi-agent orchestrator. Selects agents by name, capability, or auto-detection, runs them concurrently with semaphore-bounded `asyncio.gather`, applies triage for model tier selection, and returns consolidated results.

### `mcp_tools/sharepoint_tools.py` (1 tool)

- `download_from_sharepoint` -- Download a file from any SharePoint URL via Playwright browser

### `mcp_tools/resources.py` (4 resources)

MCP resources exposing read-only views:
- `facts://all` -- All stored facts
- `memory://facts/{category}` -- Facts filtered by category
- `agents://list` -- All registered agents
- `memory://session-brain` -- Current session brain content

---

## Agent System

### `agents/base.py`

`BaseExpertAgent` -- The core agent class. Inherits from 5 domain mixins (LifecycleMixin, CalendarMixin, ReminderMixin, NotificationMixin, MailMixin). Key features:

- **Tool-use loop**: Iterates up to `MAX_TOOL_ROUNDS` (25) with Claude API
- **Capability gating**: Only receives tool schemas matching declared capabilities
- **Dispatch table**: Cached dict mapping tool names to handler functions
- **Hook integration**: Fires `before_tool_call` and `after_tool_call` hooks with arg transformation support
- **Loop detection**: Uses `LoopDetector` to prevent infinite tool-call loops
- **Agent memory injection**: System prompt includes agent-specific memories and shared namespace memories
- **Retry logic**: `@retry_api_call` decorator with exponential backoff for API calls

`AgentResult` -- String subclass with `.status`, `.is_success`, `.is_error`, `.metadata` properties. Status values: `success`, `loop_detected`, `max_rounds_reached`, `error`.

### `agents/registry.py`

`AgentRegistry` -- Loads and caches YAML agent configs from `agent_configs/`. Validates agent names against `^[a-z0-9][a-z0-9_-]*$`. Cache is invalidated on save operations.

`AgentConfig` dataclass: name, description, system_prompt, capabilities, namespaces, temperature, max_tokens, model, created_by, created_at.

### `agents/factory.py`

`AgentFactory` -- Uses Claude to dynamically generate new agent configurations from natural-language descriptions. Produces YAML configs saved to `agent_configs/`.

### `agents/triage.py`

`classify_and_resolve()` -- Pre-flight complexity classification. Uses a Haiku pre-call to classify tasks as simple/standard/complex. Simple tasks get downgraded from sonnet to haiku tier. Skips triage for agents already at haiku or opus tiers.

### `agents/loop_detector.py`

`LoopDetector` -- Tracks tool calls using a hash of (name, args). Detects:
- Same call repeated >= 3 times (warning) or >= 5 times (break)
- A-B-A-B alternation pattern (warning after 4 entries)

### `agents/mixins.py`

Domain-specific tool handler mixins providing `_handle_*` methods for calendar, reminders, notifications, mail, and lifecycle operations. These are mixed into `BaseExpertAgent`.

---

## Memory System

### `memory/store.py`

`MemoryStore` -- Facade class that:
1. Creates the SQLite connection (WAL mode, busy_timeout=30s, foreign_keys=ON)
2. Creates all 14 tables via `_create_tables()`
3. Runs schema migrations (pinned column, namespace column, delivery columns)
4. Instantiates 7 domain stores (FactStore, LifecycleStore, WebhookStore, SchedulerStore, SkillStore, AgentMemoryStore, IdentityStore)
5. Delegates all public methods to domain stores via attribute assignment

All domain stores share the same SQLite connection and `threading.RLock`.

### `memory/models.py`

Dataclasses and enums for all memory entities:

**Enums (StrEnum)**: FactCategory, DecisionStatus, DelegationStatus, DelegationPriority, WebhookStatus, HandlerType, DeliveryChannel, ScheduleType, SkillSuggestionStatus, AgentMemoryType, IdentityProvider, AlertType, AgentResultStatus

**Dataclasses**: Fact, Location, ContextEntry, Decision, Delegation, AlertRule, WebhookEvent, ScheduledTask, SkillUsage, SkillSuggestion, Identity, EventRule, AgentMemory

### `memory/fact_store.py`

`FactStore` -- Manages facts, locations, and context entries. Search capabilities:
- **FTS5 full-text search** with BM25 ranking
- **LIKE search** for simple text matching
- **ChromaDB vector search** (all-MiniLM-L6-v2 embeddings)
- **Hybrid search** combining FTS5 + LIKE + vector with MMR (Maximal Marginal Relevance) reranking for diversity
- **Temporal decay** with 90-day half-life (pinned facts exempt)

### `memory/lifecycle_store.py`

Manages decisions, delegations, and alert rules with full CRUD + status filtering.

### `memory/webhook_store.py`

Manages webhook events and event rules. Provides `match_event_rules()` for pattern-based event-to-rule matching.

### `memory/scheduler_store.py`

Manages scheduled tasks with `get_due_tasks()` for the scheduler engine.

### `memory/skill_store.py`

Manages skill usage aggregation, individual tool invocation logging, and skill suggestions.

### `memory/agent_memory_store.py`

Per-agent persistent memory with namespace support for cross-agent collaboration.

### `memory/identity_store.py`

Cross-channel identity linking with `resolve_sender()` and `resolve_handle_to_name()`.

---

## Document System

### `documents/store.py`

`DocumentStore` -- ChromaDB wrapper using `all-MiniLM-L6-v2` embeddings with cosine similarity. Handles legacy collection name migration.

### `documents/ingestion.py`

Word-based document chunking (500 words, 50 word overlap) with SHA256 dedup. Supports: `.txt`, `.md`, `.py`, `.json`, `.yaml`, `.pdf` (via pypdf), `.docx` (via python-docx).

---

## Calendar Connectors

### `connectors/calendar_unified.py`

`UnifiedCalendarService` -- Facade that routes operations across multiple calendar providers. Features:
- Event deduplication by iCal UID (or title+start+end fallback)
- Event ownership tracking in a separate SQLite database
- Source filtering
- Dual-read policy enforcement (both providers must succeed)
- Provider-prefixed UIDs (`provider:native_id`) for write routing

### `connectors/router.py`

`ProviderRouter` -- Policy engine for read/write provider selection with alias normalization. Read policy defaults to querying both providers. Write policy routes work calendars to M365 and defaults to Apple for personal.

### `connectors/provider_base.py`

`CalendarProvider` -- Abstract base class for calendar provider adapters.

### `connectors/claude_m365_bridge.py`

`ClaudeM365Bridge` -- Accesses Microsoft 365 calendar data via Claude CLI subprocess with the built-in M365 MCP connector. Supports listing calendars, getting/creating/updating/deleting events, and searching.

### `connectors/providers/apple_provider.py`

Wraps `CalendarStore` (EventKit) as a `CalendarProvider`.

### `connectors/providers/m365_provider.py`

Wraps `ClaudeM365Bridge` as a `CalendarProvider`.

---

## Apple Platform Integrations

All platform-specific imports use `try/except ImportError` guards for cross-platform safety.

### `apple_calendar/eventkit.py`

`CalendarStore` -- PyObjC EventKit wrapper for macOS Calendar. All methods return plain Python dicts/lists (never raw PyObjC objects).

### `apple_reminders/eventkit.py`

`ReminderStore` -- PyObjC EventKit wrapper for macOS Reminders. Full CRUD operations.

### `apple_mail/mail.py`

`MailStore` -- AppleScript-based integration with Apple Mail. Read, search, send, flag, and move messages.

### `apple_messages/messages.py`

`MessageStore` -- Reads iMessage history from SQLite (`~/Library/Messages/chat.db`) and sends replies via AppleScript. Supports GUID resolution for group chats.

### `apple_notifications/notifier.py`

`Notifier` -- Sends macOS notifications via osascript (Notification Center).

---

## Scheduler System

### `scheduler/engine.py`

`SchedulerEngine` -- Evaluates due tasks from the `scheduled_tasks` table. Features:
- `CronExpression` parser (5-field: minute hour day month weekday) with wildcards, ranges, lists, and steps
- `calculate_next_run()` for interval, cron, and once schedule types
- Optimistic locking: advances `next_run_at` before execution to prevent double-runs

### `scheduler/daemon.py`

`JarvisDaemon` -- Persistent asyncio process wrapping `SchedulerEngine` in a tick loop. SIGTERM/SIGINT trigger graceful shutdown. Tick errors are caught and logged, never crashing the loop.

### `scheduler/handlers.py`

Handler dispatch for scheduled tasks. Maps handler types (alert_eval, webhook_poll, webhook_dispatch, skill_analysis, morning_brief, proactive_push, custom) to execution functions.

### `scheduler/alert_evaluator.py`

Standalone alert rule evaluator. Checks for overdue delegations, stale decisions, and upcoming deadlines.

### `scheduler/availability.py`

Calendar availability analysis for finding open time slots.

### `scheduler/morning_brief.py`

Morning brief generator for scheduled delivery.

---

## Delivery System

### `delivery/service.py`

`deliver_result()` -- Entry point for delivering task/event results. Routes to appropriate adapter, applies humanizer text transforms, and auto-detects daily brief JSON for formatting.

Adapters:
- `EmailDeliveryAdapter` -- Via Apple Mail (`MailStore.send_message()`)
- `IMessageDeliveryAdapter` -- Via AppleScript (`MessageStore.send_message()`)
- `NotificationDeliveryAdapter` -- Via osascript (`Notifier.send()`)
- `TeamsDeliveryAdapter` -- Via Playwright (`PlaywrightTeamsPoster`)

All adapters support `string.Template` substitution with `$result`, `$task_name`, `$timestamp` variables.

---

## Session System

### `session/manager.py`

`SessionManager` -- Manages session lifecycle:
- **Tracking**: Records interactions (role, content, tool name/args, timestamp) in a buffer
- **Token estimation**: `word_count * 1.3`
- **Structured extraction**: Keyword matching to classify buffer contents as decisions, action items, key facts, or general
- **Flush**: Persists extracted data to facts table (work category) with confidence scores, plus context checkpoint. Updates Session Brain.
- **Restore**: Loads previous session context and related facts

### `session/brain.py`

`SessionBrain` -- Persistent markdown file (`data/session_brain.md`) carrying context across sessions. Sections: Active Workstreams, Open Action Items, Recent Decisions, Key People Context, Session Handoff Notes. Uses `atomic_write()` with fcntl file locking for safe concurrent access.

---

## Webhook System

### `webhook/ingest.py`

Scans `data/webhook-inbox/` for JSON files, validates payloads, and stores them to the `webhook_events` table.

### `webhook/dispatcher.py`

`EventDispatcher` -- Matches webhook events against event rules, executes corresponding agents, and delivers results. Supports parallel dispatch via `asyncio.gather` with semaphore-bounded concurrency.

### `webhook/receiver.py`

Standalone entry point for running ingestion outside the MCP server.

---

## Channel System

### `channels/models.py`

`InboundEvent` -- Normalized event dataclass with channel, source, event_type, content, sender, timestamp, metadata.

### `channels/adapter.py`

`ChannelAdapter` ABC with concrete adapters: `IMessageAdapter`, `MailAdapter`, `WebhookAdapter`. Each adapter's `normalize()` method converts raw data to `InboundEvent`.

### `channels/router.py`

`EventRouter` -- Thread-safe handler dispatch by event type. Handlers are registered via `register_handler()` and fired via `route()`.

### `channels/consumers.py`

Built-in handlers: `log_event_handler` (logs events), `priority_filter` (detects urgent keywords).

### `channels/routing.py`

Outbound channel routing with safety tiers:
- `determine_safety_tier()` -- AUTO_SEND (self), CONFIRM (internal), DRAFT_ONLY (external/sensitive/first-contact)
- `select_channel()` -- Routes based on recipient type, urgency, and work hours
- `is_sensitive_topic()` -- Keyword-based detection of HR/legal/financial content
- `is_work_hours()` -- Monday-Friday, 09:00-17:59

---

## Proactive System

### `proactive/engine.py`

`ProactiveSuggestionEngine` -- Generates prioritized suggestions by checking: skill suggestions, unprocessed webhooks, overdue delegations, stale decisions, upcoming deadlines, session checkpoint needs, token limits, unflushed items, and session brain items.

### `proactive/models.py`

`Suggestion` dataclass with category, priority, title, description, action, created_at.

---

## Skills System

### `skills/pattern_detector.py`

`PatternDetector` -- Clusters tool usage rows by tool name and Jaccard similarity to find repeated patterns. Generates skill suggestions when confidence exceeds threshold.

---

## Browser Automation

### `browser/manager.py`

`TeamsBrowserManager` -- Launches and manages a persistent Chromium process with a cached profile directory. Supports launching, connecting, and graceful shutdown.

### `browser/teams_poster.py`

`PlaywrightTeamsPoster` -- Connects to the running browser, searches Teams for targets by name, prepares and sends messages. Two-phase flow (prepare + confirm) prevents accidental sends.

### `browser/navigator.py`

Navigation helpers for Teams chat/channel resolution.

### `browser/okta_auth.py`

Okta authentication flow for Teams browser sessions.

### `browser/sharepoint_download.py`

SharePoint file download via Playwright browser.

### `browser/constants.py`

Browser-related constants (URLs, timeouts, selectors).

---

## Hooks System

### `hooks/registry.py`

`HookRegistry` -- Manages lifecycle hooks by event type (before_tool_call, after_tool_call, session_start, session_end). Hooks are YAML-configured, priority-sorted, and error-isolated.

Helper functions:
- `build_tool_context()` -- Standard context dict for tool-related events
- `extract_transformed_args()` -- Extract arg transformations from hook results

### `hooks/builtin.py`

Built-in hook implementations (audit logging, etc.).

### `hooks/hook_configs/`

YAML hook configuration files: `builtin.yaml`, `humanizer.yaml`.

---

## Humanizer

### `humanizer/rules.py`

Rule-based text transformer with 60+ rules removing AI writing patterns: em dashes, vocabulary swaps (utilize->use, leverage->use), filler phrases, sycophantic patterns, copula avoidance, and hedging reduction.

### `humanizer/hook.py`

Hook integration for applying humanizer rules to tool outputs.

---

## Formatter

### `formatter/brief.py`

`render_daily()` -- Renders daily briefing data into formatted text.

### `formatter/cards.py`, `formatter/tables.py`, `formatter/dashboard.py`

Card, table, and dashboard rendering for delivery channels.

### `formatter/text.py`, `formatter/console.py`

Text and console output helpers.

### `formatter/styles.py`, `formatter/types.py`, `formatter/data_helpers.py`

Styling definitions, type aliases, and data preparation utilities.

---

## Playbooks

### `playbooks/loader.py`

`PlaybookLoader` -- YAML parsing with `string.Template` input substitution and condition evaluation. Conditions support `$input_name` references for dynamic workstream selection.

### Built-in Playbooks

- `playbooks/daily_briefing.yaml` -- Calendar, email, messages, delegations, reminders
- `playbooks/meeting_prep.yaml` -- Attendee research, topic prep, agenda drafting
- `playbooks/expert_research.yaml` -- Web, documents, memory, synthesis
- `playbooks/software_dev_team.yaml` -- Architecture, implementation, testing, review

---

## OKR Tracking

### `okr/parser.py`

Parses Excel spreadsheets (via openpyxl) into `OKRSnapshot` structures.

### `okr/models.py`

Dataclasses: `Objective`, `KeyResult`, `Initiative`, `OKRSnapshot`.

### `okr/store.py`

`OKRStore` -- JSON-backed persistence with query and filter support.

---

## Utilities

### `utils/retry.py`

`@retry_api_call` -- Async decorator that retries Anthropic API calls (RateLimitError, InternalServerError, APIConnectionError) with exponential backoff (1s, 2s, 4s, up to 3 retries).

### `utils/atomic.py`

`atomic_write()` -- Writes files atomically using fcntl file locking and `os.replace()`.

`locked_read()` -- Reads files under a shared flock for safe concurrent access.

### `utils/subprocess.py`

Subprocess execution helpers.

### `utils/text.py`

Text processing utilities.
