# Architecture

This document provides a comprehensive architectural overview of the Chief of Staff (Jarvis) system with Mermaid diagrams for visual reference.

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Request Flow](#2-request-flow)
3. [Data Model](#3-data-model)
4. [Agent Execution](#4-agent-execution)
5. [Unified Calendar System](#5-unified-calendar-system)
6. [Scheduler and Daemon](#6-scheduler-and-daemon)
7. [Webhook and Event-Driven Dispatch](#7-webhook-and-event-driven-dispatch)
8. [Session Management](#8-session-management)
9. [Channel Routing](#9-channel-routing)
10. [Self-Authoring Skills](#10-self-authoring-skills)
11. [Proactive Suggestion Engine](#11-proactive-suggestion-engine)
12. [Identity Linking](#12-identity-linking)
13. [Plugin Hooks](#13-plugin-hooks)
14. [Person Enrichment](#14-person-enrichment)
15. [Teams Browser Integration](#15-teams-browser-integration)
16. [iMessage Inbox Monitor](#16-imessage-inbox-monitor)
17. [Team Playbooks](#17-team-playbooks)
18. [Delivery System](#18-delivery-system)
19. [Humanizer](#19-humanizer)

---

## 1. System Architecture

High-level component map showing all modules, data stores, platform integrations, and their interconnections.

```mermaid
graph TB
    %% ── Clients ──────────────────────────────────────────────────
    subgraph Clients["Clients"]
        CC["Claude Code"]
        CD["Claude Desktop"]
        IM["iMessage<br/>(inbox-monitor)"]
        DAEMON["JarvisDaemon<br/>(scheduler/daemon.py)"]
    end

    %% ── MCP Server ──────────────────────────────────────────────
    subgraph MCP["MCP Server (mcp_server.py)"]
        direction TB
        EP["FastMCP Entry Point<br/><i>stdio JSON-RPC transport</i>"]
        SS["ServerState<br/><i>mcp_tools/state.py</i>"]
        UT["UsageTracker<br/><i>call_tool middleware</i>"]
        EP -->|populates| SS
        EP -->|installs| UT
    end

    %% ── Tool Modules ────────────────────────────────────────────
    subgraph Tools["Tool Modules (112 tools + 4 resources)"]
        direction TB
        TM["memory_tools<br/><i>7 tools</i>"]
        TD["document_tools<br/><i>2 tools</i>"]
        TA["agent_tools<br/><i>7 tools</i>"]
        TL["lifecycle_tools<br/><i>14 tools</i>"]
        TC["calendar_tools<br/><i>8 tools</i>"]
        TR["reminder_tools<br/><i>6 tools</i>"]
        TMA["mail_tools<br/><i>10 tools</i>"]
        TI["imessage_tools<br/><i>6 tools</i>"]
        TO["okr_tools<br/><i>3 tools</i>"]
        TWH["webhook_tools<br/><i>3 tools</i>"]
        TSK["skill_tools<br/><i>6 tools</i>"]
        TSCHED["scheduler_tools<br/><i>6 tools</i>"]
        TCH["channel_tools<br/><i>2 tools</i>"]
        TPR["proactive_tools<br/><i>2 tools</i>"]
        TSES["session_tools<br/><i>3 tools</i>"]
        TER["event_rule_tools<br/><i>5 tools</i>"]
        TID["identity_tools<br/><i>4 tools</i>"]
        TEN["enrichment<br/><i>1 tool</i>"]
        TTB["teams_browser_tools<br/><i>5 tools</i>"]
        TRT["routing_tools<br/><i>1 tool</i>"]
        TBR["brain_tools<br/><i>2 tools</i>"]
        TPB["playbook_tools<br/><i>2 tools</i>"]
        TFM["formatter_tools<br/><i>4 tools</i>"]
        TDP["dispatch_tools<br/><i>1 tool</i>"]
        TSP["sharepoint_tools<br/><i>1 tool</i>"]
        TRES["resources<br/><i>4 resources</i>"]
    end

    %% ── Data Stores ─────────────────────────────────────────────
    subgraph DataStores["Data Stores"]
        MS["MemoryStore<br/><i>SQLite (memory.db)</i><br/>14 tables"]
        DS["DocumentStore<br/><i>ChromaDB (data/chroma/)</i><br/>all-MiniLM-L6-v2"]
        OS["OKRStore<br/><i>JSON (data/okr/)</i>"]
        RDB["OwnershipDB<br/><i>SQLite (calendar-routing.db)</i>"]
        SB["SessionBrain<br/><i>Markdown (session_brain.md)</i>"]
    end

    %% ── Agent System ────────────────────────────────────────────
    subgraph AgentSystem["Agent System"]
        direction TB
        AR["AgentRegistry<br/><i>34 YAML configs</i>"]
        BE["BaseExpertAgent<br/><i>Tool-use loop</i>"]
        AF["AgentFactory<br/><i>Claude-generated configs</i>"]
        CR["CapabilitiesRegistry<br/><i>34 capabilities</i>"]
        TR2["Triage<br/><i>Complexity classifier</i>"]
        LD["LoopDetector<br/><i>Repetition guard</i>"]
        AR --> BE
        AF --> AR
        CR --> BE
        TR2 --> BE
        LD --> BE
    end

    %% ── Unified Calendar ────────────────────────────────────────
    subgraph Calendar["Unified Calendar"]
        direction TB
        UCS["UnifiedCalendarService<br/><i>Facade + dedup + ownership</i>"]
        PR["ProviderRouter<br/><i>Read/write routing</i>"]
        AP["AppleCalendarProvider"]
        MP["Microsoft365Provider"]
        UCS --> PR
        PR --> AP
        PR --> MP
    end

    %% ── Apple Platform ──────────────────────────────────────────
    subgraph Apple["Apple Platform"]
        direction TB
        ACS["CalendarStore<br/><i>PyObjC EventKit</i>"]
        ARS["ReminderStore<br/><i>PyObjC EventKit</i>"]
        AMS["MailStore<br/><i>AppleScript</i>"]
        MSGS["MessageStore<br/><i>chat.db + AppleScript</i>"]
        NOT["Notifier<br/><i>osascript</i>"]
    end

    %% ── Infrastructure ──────────────────────────────────────────
    subgraph Infra["Infrastructure"]
        direction TB
        HR["HookRegistry<br/><i>YAML lifecycle hooks</i>"]
        SM["SessionManager<br/><i>Tracking + flush</i>"]
        PSE["ProactiveEngine<br/><i>Suggestion generation</i>"]
        ED["EventDispatcher<br/><i>Agent dispatch</i>"]
        DL["DeliveryService<br/><i>4 channel adapters</i>"]
        HM["Humanizer<br/><i>Text post-processing</i>"]
    end

    %% ── External Services ───────────────────────────────────────
    subgraph External["External Services"]
        CLAUDE_API["Claude API<br/><i>Anthropic Messages</i>"]
        M365["Microsoft 365<br/><i>Claude CLI bridge</i>"]
        EK["EventKit<br/><i>macOS framework</i>"]
        CHATDB["chat.db<br/><i>iMessage database</i>"]
        CHROMIUM["Chromium<br/><i>Playwright browser</i>"]
    end

    %% ── Client connections ──────────────────────────────────────
    CC -->|"stdio JSON-RPC"| EP
    CD -->|"stdio JSON-RPC"| EP
    IM -->|"claude CLI"| CLAUDE_API
    DAEMON -->|"direct"| MS

    %% ── Tool module wiring (via ServerState) ────────────────────
    SS --> Tools

    %% ── Tool to Store connections ───────────────────────────────
    TM --> MS
    TD --> DS
    TA --> AR
    TL --> MS
    TC --> UCS
    TR --> ARS
    TMA --> AMS & NOT
    TI --> MSGS
    TO --> OS
    TWH --> MS
    TSK --> MS
    TSCHED --> MS
    TCH --> MSGS & AMS & MS
    TPR --> PSE
    PSE --> MS
    TSES --> SM
    SM --> MS & SB
    TER --> MS & ED
    ED --> AR & DL
    TID --> MS
    TEN --> MS & MSGS & AMS
    TTB --> CHROMIUM
    TBR --> SB
    TDP --> AR & BE
    TSP --> CHROMIUM
    DL --> AMS & MSGS & NOT & CHROMIUM
    DL --> HM

    %% ── Calendar connections ────────────────────────────────────
    AP --> ACS
    ACS --> EK
    MP -->|"ClaudeM365Bridge"| M365
    UCS --> RDB

    %% ── Agent to Claude API ─────────────────────────────────────
    BE --> CLAUDE_API

    %% ── Apple backends ──────────────────────────────────────────
    MSGS --> CHATDB
    ARS --> EK

    %% ── Styling ─────────────────────────────────────────────────
    classDef client fill:#4a9eff,stroke:#2d6cc0,color:#fff
    classDef server fill:#2d2d2d,stroke:#555,color:#fff
    classDef tool fill:#6c5ce7,stroke:#4834d4,color:#fff
    classDef store fill:#00b894,stroke:#00816a,color:#fff
    classDef agent fill:#e17055,stroke:#b33939,color:#fff
    classDef calendar fill:#fdcb6e,stroke:#d4a017,color:#333
    classDef apple fill:#a29bfe,stroke:#6c5ce7,color:#fff
    classDef external fill:#636e72,stroke:#2d3436,color:#fff
    classDef infra fill:#55efc4,stroke:#00b894,color:#333

    class CC,CD,IM,DAEMON client
    class EP,SS,UT server
    class TM,TD,TA,TL,TC,TR,TMA,TI,TO,TWH,TSK,TSCHED,TCH,TPR,TSES,TER,TID,TEN,TTB,TRT,TBR,TPB,TFM,TDP,TSP,TRES tool
    class MS,DS,OS,RDB,SB store
    class AR,BE,AF,CR,TR2,LD agent
    class UCS,PR,AP,MP calendar
    class ACS,ARS,AMS,MSGS,NOT apple
    class CLAUDE_API,M365,EK,CHATDB,CHROMIUM external
    class HR,SM,PSE,ED,DL,HM infra
```

---

## 2. Request Flow

### Standard MCP Tool Call

How a single tool call flows from client through the MCP server to a data store and back.

```mermaid
sequenceDiagram
    participant Client as Claude Code / Desktop
    participant FastMCP as FastMCP Server
    participant Tracker as UsageTracker
    participant Handler as Tool Handler<br/>(mcp_tools/*.py)
    participant State as ServerState
    participant Store as Data Store<br/>(SQLite / ChromaDB)

    Client->>FastMCP: JSON-RPC tool call<br/>(stdio transport)
    activate FastMCP

    FastMCP->>Tracker: Intercept via wrapped call_tool
    activate Tracker
    Tracker->>Tracker: Extract query pattern

    Tracker->>Handler: Forward to @mcp.tool() handler
    activate Handler

    Handler->>State: Access state.memory_store<br/>or state.calendar_store, etc.
    State-->>Handler: Store instance

    Handler->>Store: Execute operation<br/>(e.g. store_fact, search, get_events)
    activate Store
    Store-->>Handler: Result (dict / list)
    deactivate Store

    Handler->>Handler: json.dumps(result)
    Handler-->>Tracker: JSON string response
    deactivate Handler

    Tracker->>Tracker: Record invocation<br/>(tool_usage_log table)
    Tracker-->>FastMCP: Response
    deactivate Tracker

    FastMCP-->>Client: JSON-RPC response
    deactivate FastMCP
```

### Lifespan Initialization

Before any tool call is processed, the `app_lifespan` context manager initializes all stores and populates `ServerState`:

```mermaid
sequenceDiagram
    participant FastMCP as FastMCP
    participant Lifespan as app_lifespan()
    participant State as ServerState

    FastMCP->>Lifespan: Server startup
    activate Lifespan

    Lifespan->>Lifespan: Create MemoryStore (SQLite + ChromaDB)
    Lifespan->>Lifespan: Create DocumentStore (ChromaDB)
    Lifespan->>Lifespan: Create AgentRegistry (YAML)
    Lifespan->>Lifespan: Create CalendarStore (EventKit)
    Lifespan->>Lifespan: Create ClaudeM365Bridge
    Lifespan->>Lifespan: Create ProviderRouter + UnifiedCalendarService
    Lifespan->>Lifespan: Create ReminderStore, MailStore,<br/>MessageStore, OKRStore
    Lifespan->>Lifespan: Create HookRegistry (YAML hooks)
    Lifespan->>Lifespan: Create SessionBrain + SessionManager

    Lifespan->>State: Populate all store references
    State-->>Lifespan: Ready

    Lifespan->>Lifespan: Seed default scheduled tasks<br/>(alert_eval, webhook_poll,<br/>webhook_dispatch, skill_analysis)
    Lifespan->>Lifespan: Fire session_start hooks

    Lifespan-->>FastMCP: yield (server running)
    deactivate Lifespan

    Note over FastMCP: Server accepts tool calls

    FastMCP->>Lifespan: Server shutdown
    activate Lifespan
    Lifespan->>Lifespan: Fire session_end hooks
    Lifespan->>State: Reset all references to None
    Lifespan->>Lifespan: memory_store.close()
    deactivate Lifespan
```

---

## 3. Data Model

### SQLite Schema (memory.db)

The MemoryStore manages 14 tables via a facade pattern that delegates to 7 domain stores sharing a single connection and lock.

```mermaid
erDiagram
    facts {
        int id PK
        text category "personal|preference|work|relationship|backlog"
        text key "UNIQUE with category"
        text value
        real confidence "0.0 to 1.0"
        text source
        int pinned "0 or 1"
        timestamp created_at
        timestamp updated_at
    }

    facts_fts {
        text key
        text value
        text category
    }

    locations {
        int id PK
        text name "UNIQUE"
        text address
        real latitude
        real longitude
        text notes
        timestamp created_at
    }

    context {
        int id PK
        text session_id
        text topic
        text summary
        text agent
        timestamp created_at
    }

    decisions {
        int id PK
        text title
        text description
        text context
        text status "pending_execution|executed|deferred|reversed"
        text follow_up_date
        text tags
        text owner
        timestamp created_at
    }

    delegations {
        int id PK
        text task
        text delegated_to
        text due_date
        text priority "low|medium|high|critical"
        text status "active|completed|cancelled"
        timestamp created_at
    }

    alert_rules {
        int id PK
        text name "UNIQUE"
        text alert_type
        text condition "JSON"
        int enabled "0 or 1"
        timestamp last_triggered_at
    }

    webhook_events {
        int id PK
        text source
        text event_type
        text payload "JSON"
        text status "pending|processed|failed"
        timestamp received_at
    }

    event_rules {
        int id PK
        text name "UNIQUE"
        text event_source
        text event_type_pattern
        text agent_name
        text agent_input_template
        text delivery_channel
        int priority
    }

    scheduled_tasks {
        int id PK
        text name "UNIQUE"
        text schedule_type "interval|cron|once"
        text schedule_config "JSON"
        text handler_type
        text handler_config "JSON"
        int enabled
        timestamp next_run_at
        timestamp last_run_at
        text delivery_channel
    }

    skill_usage {
        int id PK
        text tool_name
        text query_pattern "UNIQUE with tool_name"
        int count
        timestamp last_used
    }

    tool_usage_log {
        int id PK
        text tool_name
        text query_pattern
        int success
        int duration_ms
        text session_id
        timestamp created_at
    }

    skill_suggestions {
        int id PK
        text description
        text suggested_name
        real confidence
        text status "pending|accepted|rejected"
    }

    agent_memory {
        int id PK
        text agent_name
        text memory_type "insight|preference|context"
        text key "UNIQUE with agent_name+memory_type"
        text value
        real confidence
        text namespace
    }

    identities {
        int id PK
        text canonical_name
        text provider "UNIQUE with provider_id"
        text provider_id
        text display_name
        text email
    }
```

### MemoryStore Facade Pattern

```mermaid
graph TB
    MS["MemoryStore<br/><i>Facade</i>"]

    FS["FactStore<br/><i>facts, locations, context</i><br/><i>FTS5 + vector search</i>"]
    LS["LifecycleStore<br/><i>decisions, delegations, alert_rules</i>"]
    WS["WebhookStore<br/><i>webhook_events, event_rules</i>"]
    SS["SchedulerStore<br/><i>scheduled_tasks</i>"]
    SKS["SkillStore<br/><i>skill_usage, tool_usage_log,<br/>skill_suggestions</i>"]
    AMS["AgentMemoryStore<br/><i>agent_memory (private + shared)</i>"]
    IS["IdentityStore<br/><i>identities</i>"]

    CONN["SQLite Connection<br/><i>WAL mode, busy_timeout=30s</i>"]
    LOCK["RLock<br/><i>Thread-safe writes</i>"]

    MS --> FS & LS & WS & SS & SKS & AMS & IS
    FS & LS & WS & SS & SKS & AMS & IS --> CONN
    FS & LS & WS & SS & SKS & AMS & IS --> LOCK

    classDef facade fill:#e17055,stroke:#b33939,color:#fff
    classDef store fill:#6c5ce7,stroke:#4834d4,color:#fff
    classDef infra fill:#636e72,stroke:#2d3436,color:#fff

    class MS facade
    class FS,LS,WS,SS,SKS,AMS,IS store
    class CONN,LOCK infra
```

---

## 4. Agent Execution

### Tool-Use Loop

The `BaseExpertAgent` runs an autonomous tool-use loop with the Claude API. Each agent is gated by the capabilities declared in its YAML config.

```mermaid
sequenceDiagram
    participant Caller as Caller<br/>(dispatch_tools, event_rule_tools)
    participant Agent as BaseExpertAgent
    participant CapReg as CapabilitiesRegistry
    participant Hooks as HookRegistry
    participant Claude as Claude API
    participant Dispatch as Dispatch Table

    Caller->>Agent: agent.execute(task)
    activate Agent

    Agent->>CapReg: get_tools_for_capabilities(config.capabilities)
    CapReg-->>Agent: Filtered tool schemas

    Agent->>Agent: Build system prompt<br/>(YAML prompt + agent memory<br/>+ shared namespaces + date)

    loop Tool-use loop (max 25 rounds)
        Agent->>Claude: messages.create(system, messages, tools)
        activate Claude
        Note over Agent,Claude: retry_api_call decorator:<br/>3 retries with exponential backoff
        Claude-->>Agent: Response
        deactivate Claude

        alt stop_reason == "tool_use"
            Agent->>Agent: LoopDetector.record(name, args)

            alt Loop detected (break signal)
                Agent-->>Caller: AgentResult(status=loop_detected)
            end

            loop For each tool_use block
                Agent->>Hooks: fire before_tool_call
                Hooks-->>Agent: Optional arg transforms

                Agent->>Agent: Check capability boundary
                alt Tool not in allowed set
                    Agent->>Agent: Return error dict
                else Tool allowed
                    Agent->>Dispatch: _dispatch_tool(name, input)
                    Dispatch-->>Agent: Result dict
                end

                Agent->>Hooks: fire after_tool_call
            end

            Agent->>Agent: Append to conversation
            Note over Agent: Continue loop

        else stop_reason == "end_turn"
            Agent-->>Caller: AgentResult(status=success, text)
        end
    end

    Note over Agent: Max rounds reached
    Agent-->>Caller: AgentResult(status=max_rounds_reached)
    deactivate Agent
```

### Capability Gating

```mermaid
graph LR
    subgraph AgentYAML["Agent YAML Config"]
        CAP["capabilities:<br/>- memory_read<br/>- calendar_read<br/>- mail_read"]
    end

    subgraph CapRegistry["Capabilities Registry (34 capabilities)"]
        C1["memory_read<br/><i>query_memory</i>"]
        C2["calendar_read<br/><i>get_calendar_events</i><br/><i>search_calendar_events</i>"]
        C3["mail_read<br/><i>get_mail_messages</i><br/><i>get_mail_message</i><br/><i>search_mail</i><br/><i>get_unread_count</i>"]
    end

    subgraph ToolSchemas["Granted Tool Schemas"]
        T1["query_memory"]
        T2["get_calendar_events"]
        T3["search_calendar_events"]
        T4["get_mail_messages"]
        T5["get_mail_message"]
        T6["search_mail"]
        T7["get_unread_count"]
    end

    CAP --> C1 & C2 & C3
    C1 --> T1
    C2 --> T2 & T3
    C3 --> T4 & T5 & T6 & T7

    classDef yaml fill:#fdcb6e,stroke:#d4a017,color:#333
    classDef cap fill:#6c5ce7,stroke:#4834d4,color:#fff
    classDef tool fill:#00b894,stroke:#00816a,color:#fff

    class CAP yaml
    class C1,C2,C3 cap
    class T1,T2,T3,T4,T5,T6,T7 tool
```

### Dynamic Complexity Triage

Before dispatching an agent, a lightweight Haiku pre-call classifies task complexity. Simple tasks get downgraded to the Haiku model tier for cost savings.

```mermaid
flowchart TD
    START["Agent dispatch requested"] --> CHECK_TIER{"Agent model<br/>== haiku or opus?"}
    CHECK_TIER -->|Yes| SKIP["Skip triage<br/>(already cheapest or reserved)"]
    CHECK_TIER -->|No| CLASSIFY["Haiku pre-call:<br/>classify_complexity()"]
    CLASSIFY --> RESULT{"Classification?"}
    RESULT -->|simple| DOWNGRADE["Downgrade to haiku tier<br/>(copy config, override model)"]
    RESULT -->|standard| KEEP["Keep original model tier"]
    RESULT -->|complex| KEEP
    RESULT -->|error| KEEP
    SKIP --> EXECUTE["Execute agent"]
    DOWNGRADE --> EXECUTE
    KEEP --> EXECUTE
```

### Capabilities Reference

| Capability | Tools | Status |
|-----------|-------|--------|
| `memory_read` | query_memory | Implemented |
| `memory_write` | store_memory | Implemented |
| `document_search` | search_documents | Implemented |
| `calendar_read` | get_calendar_events, search_calendar_events | Implemented |
| `reminders_read` | list_reminders, search_reminders | Implemented |
| `reminders_write` | create_reminder, complete_reminder | Implemented |
| `notifications` | send_notification | Implemented |
| `mail_read` | get_mail_messages, get_mail_message, search_mail, get_unread_count | Implemented |
| `mail_write` | send_email, mark_mail_read, mark_mail_flagged, move_mail_message | Implemented |
| `teams_write` | open_teams_browser, post_teams_message, confirm_teams_post, cancel_teams_post, close_teams_browser | Implemented |
| `decision_read` | search_decisions, list_pending_decisions | Implemented |
| `decision_write` | create_decision, update_decision, delete_decision | Implemented |
| `delegation_read` | list_delegations, check_overdue_delegations | Implemented |
| `delegation_write` | create_delegation, update_delegation, delete_delegation | Implemented |
| `alerts_read` | check_alerts, list_alert_rules | Implemented |
| `alerts_write` | create_alert_rule, dismiss_alert | Implemented |
| `scheduling` | find_my_open_slots, find_group_availability | Implemented |
| `agent_memory_read` | get_agent_memory | Implemented |
| `agent_memory_write` | clear_agent_memory | Implemented |
| `channel_read` | list_inbound_events, get_event_summary | Implemented |
| `proactive_read` | get_proactive_suggestions, dismiss_suggestion | Implemented |
| `webhook_read` | list_webhook_events, get_webhook_event | Implemented |
| `webhook_write` | process_webhook_event | Implemented |
| `scheduler_read` | list_scheduled_tasks, get_scheduler_status | Implemented |
| `scheduler_write` | create_scheduled_task, update_scheduled_task, delete_scheduled_task, run_scheduled_task | Implemented |
| `skill_read` | list_skill_suggestions | Implemented |
| `skill_write` | record_tool_usage, analyze_skill_patterns, auto_create_skill | Implemented |
| `web_search` | -- | Legacy |
| `code_analysis` | -- | Legacy |
| `writing` | -- | Legacy |
| `editing` | -- | Legacy |
| `data_analysis` | -- | Legacy |
| `planning` | -- | Legacy |
| `file_operations` | -- | Legacy |
| `code_execution` | -- | Legacy |

---

## 5. Unified Calendar System

The unified calendar routes operations across Apple Calendar (EventKit) and Microsoft 365 (via Claude CLI bridge), with provider-specific routing, event deduplication, and ownership tracking.

```mermaid
flowchart TD
    TOOL["calendar_tools.py<br/>(MCP tool handler)"] --> UCS["UnifiedCalendarService"]

    UCS --> ROUTER["ProviderRouter"]

    ROUTER --> DECIDE{"decide_read() or<br/>decide_write()"}

    DECIDE -->|"provider_preference=auto"| BOTH["Query both providers"]
    DECIDE -->|"provider_preference=apple"| APPLE_ONLY["Apple preferred,<br/>M365 fallback"]
    DECIDE -->|"provider_preference=microsoft_365"| M365_ONLY["M365 preferred,<br/>Apple fallback"]
    DECIDE -->|"provider_preference=both"| BOTH

    BOTH --> APPLE["AppleCalendarProvider<br/><i>CalendarStore (EventKit)</i>"]
    BOTH --> M365["Microsoft365Provider<br/><i>ClaudeM365Bridge</i>"]
    APPLE_ONLY --> APPLE
    M365_ONLY --> M365

    APPLE --> TAG["Tag events with provider"]
    M365 --> TAG

    TAG --> DEDUP["Deduplicate by iCal UID<br/>or title+start+end fallback"]
    DEDUP --> FILTER["Apply source_filter"]
    FILTER --> OWNERSHIP["Upsert ownership<br/>to calendar-routing.db"]
    OWNERSHIP --> RETURN["Return events"]

    subgraph WriteFlow["Write Operations"]
        WRITE_REQ["create/update/delete"] --> RESOLVE["_resolve_write_provider()"]
        RESOLVE --> PREFIXED{"Prefixed UID?<br/>(provider:id)"}
        PREFIXED -->|Yes| EXTRACT["Extract provider + native_id"]
        PREFIXED -->|No| LOOKUP["Lookup ownership DB"]
        LOOKUP -->|Found| USE_OWNED["Use owning provider"]
        LOOKUP -->|Not found| DEFAULT["Default routing<br/>(work calendars -> M365)"]
    end

    classDef service fill:#fdcb6e,stroke:#d4a017,color:#333
    classDef provider fill:#6c5ce7,stroke:#4834d4,color:#fff
    classDef process fill:#00b894,stroke:#00816a,color:#fff

    class UCS,ROUTER service
    class APPLE,M365 provider
    class TAG,DEDUP,FILTER,OWNERSHIP,RESOLVE process
```

### Dual-Read Policy

When `CALENDAR_REQUIRE_DUAL_READ=true` (default), both providers must succeed for read operations. If either fails, a structured error is returned containing partial results and the specific provider that failed.

---

## 6. Scheduler and Daemon

### Scheduler Architecture

```mermaid
flowchart TD
    subgraph Entry["Entry Points"]
        DAEMON["JarvisDaemon<br/><i>Persistent asyncio loop</i>"]
        STANDALONE["python -m scheduler.engine<br/><i>One-shot evaluation</i>"]
        MCP_TOOL["run_scheduled_task<br/><i>Manual trigger via MCP</i>"]
    end

    DAEMON --> ENGINE["SchedulerEngine"]
    STANDALONE --> ENGINE
    MCP_TOOL --> ENGINE

    ENGINE --> QUERY["get_due_tasks()<br/><i>WHERE next_run_at <= now<br/>AND enabled = 1</i>"]
    QUERY --> SQLITE[(scheduled_tasks<br/>SQLite)]

    ENGINE --> EXEC["Execute handler<br/><i>with timeout protection</i>"]

    EXEC --> HANDLERS{Handler Type}
    HANDLERS -->|alert_eval| ALERT["Alert rule evaluator"]
    HANDLERS -->|webhook_poll| WPOLL["Webhook inbox ingestion"]
    HANDLERS -->|webhook_dispatch| WDISP["Webhook event dispatch"]
    HANDLERS -->|skill_analysis| SKILL["Pattern detector"]
    HANDLERS -->|morning_brief| BRIEF["Morning brief generator"]
    HANDLERS -->|proactive_push| PUSH["Proactive notifications"]
    HANDLERS -->|custom| CUSTOM["Subprocess command<br/><i>(blocklist + sanitization)</i>"]

    EXEC --> NEXT["calculate_next_run()"]
    NEXT --> UPDATE["Update last_run_at,<br/>next_run_at, last_result"]
    UPDATE --> SQLITE

    EXEC --> DELIVER{"delivery_channel<br/>configured?"}
    DELIVER -->|Yes| DELIVERY["DeliveryService<br/><i>email, iMessage,<br/>notification, Teams</i>"]
    DELIVER -->|No| DONE["Done"]

    classDef entry fill:#4a9eff,stroke:#2d6cc0,color:#fff
    classDef engine fill:#e17055,stroke:#b33939,color:#fff
    classDef handler fill:#6c5ce7,stroke:#4834d4,color:#fff

    class DAEMON,STANDALONE,MCP_TOOL entry
    class ENGINE engine
    class ALERT,WPOLL,WDISP,SKILL,BRIEF,PUSH,CUSTOM handler
```

### Schedule Types

| Type | Config Format | Example |
|------|--------------|---------|
| `interval` | `{"minutes": N}` or `{"hours": N}` | Run every 30 minutes |
| `cron` | `{"expression": "*/15 * * * *"}` | Standard 5-field cron |
| `once` | `{"run_at": "2026-03-01T09:00:00"}` | Single future execution |

### Daemon Lifecycle

The `JarvisDaemon` replaces three separate launchd agents with a single persistent process:

| Old Agent | Poll Interval | Replacement |
|-----------|--------------|-------------|
| `com.chg.scheduler-engine.plist` | 5 min | Daemon tick loop |
| `com.chg.alert-evaluator.plist` | 2 hours | `alert_eval` handler |
| `com.chg.inbox-monitor.plist` | 5 min | `webhook_poll` handler |

---

## 7. Webhook and Event-Driven Dispatch

```mermaid
flowchart TD
    EXT["External system<br/>(CI/CD, monitoring, etc.)"] -->|"Drop JSON file"| INBOX["data/webhook-inbox/"]

    INBOX --> INGEST["webhook/ingest.py<br/><i>Validate + store</i>"]
    INGEST --> WE_TABLE[(webhook_events<br/>SQLite)]

    WE_TABLE --> MATCH["match_event_rules()<br/><i>Source + type pattern matching</i>"]

    MATCH --> ER_TABLE[(event_rules<br/>SQLite)]

    MATCH --> DISPATCH["EventDispatcher"]

    DISPATCH --> PARALLEL{"Multiple rules<br/>matched?"}
    PARALLEL -->|Yes| GATHER["asyncio.gather<br/><i>with semaphore</i>"]
    PARALLEL -->|No| SINGLE["Single dispatch"]

    GATHER --> AGENT["BaseExpertAgent.execute()"]
    SINGLE --> AGENT

    AGENT --> RESULT["Agent result text"]

    RESULT --> DELIVERY{"delivery_channel<br/>in rule?"}
    DELIVERY -->|Yes| DELIVER["DeliveryService<br/>(email, iMessage,<br/>notification, Teams)"]
    DELIVERY -->|No| RETURN["Return result"]

    classDef external fill:#636e72,stroke:#2d3436,color:#fff
    classDef store fill:#00b894,stroke:#00816a,color:#fff
    classDef dispatch fill:#e17055,stroke:#b33939,color:#fff

    class EXT external
    class WE_TABLE,ER_TABLE store
    class DISPATCH,GATHER dispatch
```

### Event Rule Schema

| Field | Purpose |
|-------|---------|
| `event_source` | Source to match (e.g. "github", "jira") |
| `event_type_pattern` | Glob pattern for event types (e.g. "alert.*") |
| `agent_name` | Expert agent to activate on match |
| `agent_input_template` | String.Template with `$event_type`, `$source`, `$payload`, `$timestamp` |
| `delivery_channel` | Result delivery: "email", "imessage", "notification", or "teams" |
| `priority` | Rule ordering (lower = higher priority) |

---

## 8. Session Management

```mermaid
flowchart TD
    subgraph SessionManager["SessionManager"]
        TRACK["track_interaction()<br/><i>Buffer interactions</i>"]
        EXTRACT["extract_structured_data()<br/><i>Keyword matching</i>"]
        FLUSH["flush()<br/><i>Persist to memory</i>"]
        RESTORE["restore_from_checkpoint()"]
        TOKENS["estimate_tokens()<br/><i>word_count * 1.3</i>"]
    end

    TRACK --> BUFFER["Session Buffer<br/><i>List of Interactions</i>"]
    BUFFER --> EXTRACT

    EXTRACT --> DECISIONS["decisions<br/><i>decided, agreed, will do</i>"]
    EXTRACT --> ACTIONS["action_items<br/><i>TODO, need to, should</i>"]
    EXTRACT --> FACTS["key_facts<br/><i>important, remember</i>"]

    FLUSH --> STORE_FACTS["Store as work facts<br/><i>with confidence scores</i>"]
    FLUSH --> STORE_CTX["Store context checkpoint"]
    FLUSH --> BRAIN_UPDATE["Update Session Brain<br/><i>decisions + action items</i>"]

    STORE_FACTS --> SQLITE[(memory.db)]
    STORE_CTX --> SQLITE
    BRAIN_UPDATE --> BRAIN["session_brain.md"]

    RESTORE --> SQLITE

    subgraph SessionBrain["Session Brain (Persistent Markdown)"]
        WS["Active Workstreams"]
        AI["Open Action Items"]
        DEC["Recent Decisions"]
        PPL["Key People Context"]
        HN["Session Handoff Notes"]
    end

    BRAIN --> WS & AI & DEC & PPL & HN

    classDef manager fill:#e17055,stroke:#b33939,color:#fff
    classDef store fill:#00b894,stroke:#00816a,color:#fff
    classDef brain fill:#fdcb6e,stroke:#d4a017,color:#333

    class TRACK,EXTRACT,FLUSH,RESTORE,TOKENS manager
    class SQLITE store
    class WS,AI,DEC,PPL,HN brain
```

---

## 9. Channel Routing

Outbound message routing with safety tiers, determining how messages should be delivered based on recipient type, content sensitivity, first-contact status, urgency, and work hours.

```mermaid
flowchart TD
    MSG["Outbound message"] --> TIER["determine_safety_tier()"]

    TIER --> BASELINE{"Recipient type?"}
    BASELINE -->|self| AUTO["AUTO_SEND<br/><i>Tier 1</i>"]
    BASELINE -->|internal| CONFIRM["CONFIRM<br/><i>Tier 2</i>"]
    BASELINE -->|external| DRAFT["DRAFT_ONLY<br/><i>Tier 3</i>"]

    AUTO --> SENSITIVE{"Sensitive<br/>content?"}
    CONFIRM --> SENSITIVE
    SENSITIVE -->|Yes| BUMP["Bump tier +1<br/><i>(capped at DRAFT_ONLY)</i>"]
    SENSITIVE -->|No| FIRST{"First<br/>contact?"}
    BUMP --> FIRST
    FIRST -->|Yes, not self| FORCE_DRAFT["Force DRAFT_ONLY"]
    FIRST -->|No| CHANNEL["select_channel()"]
    FORCE_DRAFT --> CHANNEL

    CHANNEL --> SELF_CH{"self?"}
    SELF_CH -->|urgent| IMSG["iMessage"]
    SELF_CH -->|ephemeral| NOTIF["Notification"]
    SELF_CH -->|other| EMAIL_S["Email"]

    CHANNEL --> INT_CH{"internal?"}
    INT_CH -->|work hours + informal/urgent| TEAMS["Teams"]
    INT_CH -->|work hours + other| EMAIL_I["Email"]
    INT_CH -->|off hours + urgent| IMSG2["iMessage"]
    INT_CH -->|off hours + other| QUEUE["Queued"]

    CHANNEL --> EXT_CH{"external?"}
    EXT_CH --> EMAIL_E["Email (always)"]
```

### Sensitive Topic Detection

Content is scanned for keywords matching HR, legal, financial, and confidential topics. Keywords include: salary, compensation, confidential, termination, PIP, harassment, merger, layoff, and others. Detection is case-insensitive and word-boundary aware.

---

## 10. Self-Authoring Skills

The system detects repeated tool usage patterns and suggests new agent configurations automatically.

```mermaid
flowchart TD
    TOOL_CALL["Tool invocation"] --> TRACKER["UsageTracker middleware<br/><i>Wraps call_tool</i>"]
    TRACKER --> RECORD["Record to skill_usage<br/>+ tool_usage_log"]
    RECORD --> SQLITE[(SQLite)]

    SQLITE --> ANALYZE["analyze_skill_patterns<br/><i>PatternDetector</i>"]
    ANALYZE --> CLUSTER["Cluster by tool_name<br/>+ Jaccard similarity"]
    CLUSTER --> THRESHOLD{"confidence >=<br/>SKILL_SUGGESTION_THRESHOLD?"}
    THRESHOLD -->|Yes| SUGGEST["Store skill_suggestion"]
    THRESHOLD -->|No| DISCARD["Below threshold"]

    SUGGEST --> SQLITE

    SUGGEST --> AUTO["auto_create_skill"]
    AUTO --> FACTORY["AgentFactory<br/><i>Claude generates YAML</i>"]
    FACTORY --> YAML["New agent config<br/><i>agent_configs/*.yaml</i>"]

    classDef track fill:#6c5ce7,stroke:#4834d4,color:#fff
    classDef detect fill:#e17055,stroke:#b33939,color:#fff
    classDef create fill:#00b894,stroke:#00816a,color:#fff

    class TRACKER,RECORD track
    class ANALYZE,CLUSTER detect
    class AUTO,FACTORY,YAML create
```

---

## 11. Proactive Suggestion Engine

Surfaces actionable insights by scanning existing data stores for items needing attention.

| Category | Trigger | Priority |
|----------|---------|----------|
| `delegation` | Active delegations past due date | High |
| `deadline` | Active delegations due within 3 days | High |
| `session` | Approaching context window limit (~120k tokens) | High |
| `decision` | Pending decisions older than 7 days | Medium |
| `skill` | Pending skill suggestions from pattern analysis | Medium |
| `checkpoint` | 50+ tool calls with no recent checkpoint | Medium |
| `session` | Unflushed decisions or action items | Medium |
| `session` | Open action items from previous sessions (via Brain) | Medium |
| `webhook` | Unprocessed webhook events | Low |
| `session` | Active workstreams (via Brain) | Low |

---

## 12. Identity Linking

Cross-channel identity resolution maps provider-specific accounts to canonical person names.

```mermaid
graph LR
    subgraph Providers
        IM["iMessage<br/><i>+1234567890</i>"]
        EM["Email<br/><i>john@example.com</i>"]
        TEAMS["M365 Teams<br/><i>john.smith@company.com</i>"]
        JIRA["Jira<br/><i>jsmith</i>"]
    end

    subgraph IdentityStore
        CANON["Canonical Name<br/><i>John Smith</i>"]
    end

    IM --> CANON
    EM --> CANON
    TEAMS --> CANON
    JIRA --> CANON

    CANON --> RESOLVE["resolve_sender()<br/><i>Used by enrichment,<br/>channels, etc.</i>"]
```

Supported providers: `imessage`, `email`, `m365_teams`, `m365_email`, `slack`, `jira`, `confluence`.

---

## 13. Plugin Hooks

YAML-configured lifecycle hooks that fire at key points without modifying core code.

```mermaid
sequenceDiagram
    participant Server as MCP Server
    participant Registry as HookRegistry
    participant Hook as Hook Callback

    Note over Server: Session Start
    Server->>Registry: fire_hooks("session_start", ctx)
    Registry->>Hook: callback(ctx_copy)
    Hook-->>Registry: result

    Note over Server: Tool Execution
    Server->>Registry: fire_hooks("before_tool_call", ctx)
    Registry->>Hook: callback(ctx_copy)
    Hook-->>Registry: Optional {tool_args: transformed}

    Note over Server: Execute tool handler

    Server->>Registry: fire_hooks("after_tool_call", ctx)
    Registry->>Hook: callback(ctx_copy)
    Hook-->>Registry: result

    Note over Server: Session End
    Server->>Registry: fire_hooks("session_end", ctx)
    Registry->>Hook: callback(ctx_copy)
```

Hook YAML config format:
```yaml
- event_type: before_tool_call
  name: my_hook
  handler: hooks.builtin.audit_log_hook
  priority: 50
  enabled: true
```

---

## 14. Person Enrichment

Builds a consolidated profile by fetching from 6 data sources in parallel.

| Source | Data Retrieved | Store |
|--------|---------------|-------|
| Identities | Provider links (iMessage, email, Teams, etc.) | `memory_store.search_identity()` |
| Facts | Stored facts mentioning the person | `memory_store.search_facts()` |
| Delegations | Active delegations assigned to the person | `memory_store.list_delegations()` |
| Decisions | Decisions referencing the person | `memory_store.search_decisions()` |
| iMessages | Recent message threads with the person | `messages_store.search_messages()` |
| Emails | Recent email threads with the person | `mail_store.search_messages()` |

All fetches run concurrently via `asyncio.gather`. Failed sources are silently skipped. Results capped at 10 items per source.

---

## 15. Teams Browser Integration

Playwright-based automation for posting messages to Microsoft Teams through a persistent browser session.

```mermaid
flowchart TD
    OPEN["open_teams_browser()"] --> LAUNCH["Launch Chromium<br/><i>Persistent profile</i>"]
    LAUNCH --> NAV["Navigate to<br/>teams.cloud.microsoft"]
    NAV -->|"Okta login needed?"| OKTA["OktaAuth flow<br/><i>browser/okta_auth.py</i>"]
    OKTA --> READY["Browser ready"]
    NAV -->|"Already logged in"| READY

    POST["post_teams_message(target, msg)"] --> SEARCH["Search Teams<br/>for target by name"]
    SEARCH --> STAGE["Navigate to chat/channel<br/>Stage message in input box"]
    STAGE --> CONFIRM{"Confirm?"}

    CONFIRM -->|"confirm_teams_post()"| SEND["Send message"]
    CONFIRM -->|"cancel_teams_post()"| ABORT["Abort message"]

    CLOSE["close_teams_browser()"] --> KILL["SIGTERM Chromium"]
```

---

## 16. iMessage Inbox Monitor

The `inbox-monitor.sh` script polls iMessage for "jarvis:" commands using a three-pass Claude CLI pipeline.

| Pass | Purpose | Claude Model | Output |
|------|---------|-------------|--------|
| **Pass 1** | Classify message intent | Sonnet | `{category, agent, instruction}` |
| **Pass 2** | Execute via agent or inline | Sonnet | `{action_taken, success, provider_used}` |
| **Pass 3** | Deliver result to user | Sonnet | Email, iMessage reply, or notification |

---

## 17. Team Playbooks

YAML-defined parallel workstreams with input substitution and condition evaluation.

| Playbook | Purpose | Workstreams |
|----------|---------|-------------|
| `meeting_prep` | Pre-meeting research and agenda | Attendee research, topic prep, agenda drafting |
| `expert_research` | Multi-source research | Web, documents, memory, synthesis |
| `software_dev_team` | Parallel development | Architecture, implementation, testing, review |
| `daily_briefing` | Morning briefing | Calendar, email, messages, delegations, reminders |

---

## 18. Delivery System

Task and event results are delivered via configurable channel adapters. The delivery service is used by the scheduler, event dispatcher, and proactive engine.

```mermaid
flowchart LR
    RESULT["Task/event result"] --> HUMANIZE["Humanizer<br/><i>Remove AI patterns</i>"]
    HUMANIZE --> BRIEF{"Daily brief<br/>JSON?"}
    BRIEF -->|Yes| FORMAT["render_daily()<br/><i>formatter/brief.py</i>"]
    BRIEF -->|No| ADAPTER

    FORMAT --> ADAPTER{"Delivery Channel"}
    ADAPTER -->|email| EMAIL["EmailDeliveryAdapter<br/><i>Apple Mail</i>"]
    ADAPTER -->|imessage| IMSG["IMessageDeliveryAdapter<br/><i>AppleScript</i>"]
    ADAPTER -->|notification| NOTIF["NotificationDeliveryAdapter<br/><i>osascript</i>"]
    ADAPTER -->|teams| TEAMS["TeamsDeliveryAdapter<br/><i>Playwright browser</i>"]
```

---

## 19. Humanizer

Rule-based text transformer that removes common AI writing patterns before delivery. Applied automatically by the delivery service.

Categories of rules:
- **Em dash removal** -- Replaces `--` and `---` with commas
- **AI vocabulary swaps** -- "utilize" to "use", "leverage" to "use", "comprehensive" to "full", etc.
- **Filler phrase removal** -- "In order to" to "To", "It is worth noting that" removed entirely
- **Sycophantic pattern removal** -- "Great question!", "I hope this helps!", etc.
- **Copula avoidance** -- "serves as" to "is", "functions as" to "is"
- **Hedging reduction** -- "could potentially" to "could"
