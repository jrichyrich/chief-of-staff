# Hybrid Agent Execution Model

## Status: Design Plan
## Date: 2026-03-04
## Author: Jarvis Research Agent

---

## 1. Executive Summary

The Jarvis system has **34 expert agents** defined as YAML configs in `agent_configs/`, each with detailed system prompts, capability declarations, and model settings. **None of these agents are used when Claude Code handles requests directly** — Claude Code calls MCP tools itself and never delegates to `dispatch_agents`. Meanwhile, the agent configs contain valuable structured knowledge (processes, report formats, source-attribution rules, cross-agent awareness) that goes completely unused in the interactive path.

The core problem: agents are locked into the `BaseExpertAgent` tool-use loop, which can only access **Jarvis-internal tools** (~57 tools across 28 capabilities). Claude Code, by contrast, has access to **~180+ MCP tools** including M365, Atlassian, Miro, and the security-metrics-vacuum server. Agent system prompts actually _reference_ these external sources (Teams, Jira, Confluence) but the agents literally cannot access them.

**Proposed solution**: A hybrid execution model where:
- **Claude Code path**: Agent configs serve as structured playbooks/guidance. Claude Code loads the agent's system prompt and follows its process using ALL available MCP tools.
- **Daemon/autonomous path**: The inner agent loop (`dispatch_agents` → `BaseExpertAgent`) continues as-is for iMessage commands, scheduled tasks, and event rules.

---

## 2. Current State Audit

### 2.1 Agent Configs (34 total)

All YAML files live in `agent_configs/`. Each defines:

| Field | Purpose |
|-------|---------|
| `name` | Unique identifier (e.g. `meeting_prep`, `daily_briefing`) |
| `description` | What the agent specializes in |
| `system_prompt` | Full behavioral instructions (typically 1000-3000 words) |
| `capabilities` | List of capability names gating tool access |
| `model` | Model tier: `haiku`, `sonnet` (default), or `opus` |
| `temperature` | 0.0-1.0 (most use 0.2-0.3) |
| `max_tokens` | Response size limit (512-4096) |
| `namespaces` | Optional shared memory namespaces |

**Key agents by category:**

| Category | Agents | Primary Gap |
|----------|--------|-------------|
| Briefing & Planning | `daily_briefing`, `weekly_planner`, `meeting_prep`, `meeting_debrief` | No M365 email/calendar/Teams access |
| Communications | `communications`, `inbox_triage` | No M365 email/Teams, no iMessage send |
| Project Management | `project_manager`, `delegation_tracker`, `decision_tracker`, `action_item_tracker` | No Jira, no Confluence |
| Security | `security_metrics`, `github_security`, `endpoint_security_metrics`, `email_and_awareness_metrics`, `security_auditor` | No security-metrics-vacuum MCP |
| Code & Dev | `code_quality_reviewer`, `workflow_optimizer` | No filesystem/code execution access |
| Review Suite | `project_review_board`, `project_review_delivery`, `project_review_product`, `project_review_security`, `project_review_architecture`, `project_review_reliability` | No codebase read access |
| Research | `research_and_strategy`, `report_builder`, `document_librarian` | No Confluence/SharePoint search |
| Other | `scheduler`, `approval_triage`, `backlog_manager`, `okr_tracker`, `incident_summarizer`, `proactive_alerts`, `agenda_manager`, `project_planner` | Various gaps |

### 2.2 Agent Execution Path (`agents/base.py`)

```
AgentConfig → BaseExpertAgent.__init__()
  → build_system_prompt()  (config prompt + runtime context + agent memory + shared memory)
  → get_tools()  (capability-gated via capabilities/registry.py)
  → execute(task)  (tool-use loop, max 25 rounds)
    → _call_api()  (Anthropic messages.create with tools)
    → _handle_tool_call()  (before/after hooks → _dispatch_tool)
    → _dispatch_tool()  (hardcoded dispatch table: tool_name → handler)
```

The dispatch table in `_get_dispatch_table()` maps **exactly 37 tool names** to handler methods (from base class + mixins). These are the ONLY tools any agent can ever call.

### 2.3 Capability → Tool Mapping (`capabilities/registry.py`)

**28 capabilities** → **57 tool schemas** (all Jarvis-internal):

| Capability | Tools | Backend |
|-----------|-------|---------|
| `memory_read` | query_memory | SQLite + ChromaDB |
| `memory_write` | store_memory | SQLite |
| `document_search` | search_documents | ChromaDB |
| `calendar_read` | get_calendar_events, search_calendar_events | Apple Calendar (PyObjC) |
| `reminders_read` | list_reminders, search_reminders | Apple Reminders (PyObjC) |
| `reminders_write` | create_reminder, complete_reminder | Apple Reminders (PyObjC) |
| `notifications` | send_notification | macOS (osascript) |
| `mail_read` | get_mail_messages, get_mail_message, search_mail, get_unread_count | Apple Mail (AppleScript) |
| `mail_write` | send_email, mark_mail_read, mark_mail_flagged, move_mail_message | Apple Mail (AppleScript) |
| `teams_write` | open_teams_browser, post_teams_message, confirm/cancel/close | Playwright browser |
| `decision_read/write` | search/list/create/update/delete decisions | SQLite |
| `delegation_read/write` | list/check/create/update/delete delegations | SQLite |
| `alerts_read/write` | check/list/create/dismiss alerts | SQLite |
| `scheduling` | find_my_open_slots, find_group_availability | Apple Calendar + M365 bridge |
| `agent_memory_read/write` | get/clear agent memory | SQLite |
| `channel_read` | list_inbound_events, get_event_summary | Unified channel adapters |
| `webhook_read/write` | list/get/process webhook events | SQLite |
| `scheduler_read/write` | list/create/update/delete/run scheduled tasks | SQLite |
| `skill_read/write` | list/record/analyze/auto-create skills | SQLite |
| `web_browse/write/state` | web_open/snapshot/click/fill/screenshot/js/scroll/find/state | agent-browser (Playwright) |
| `proactive_read` | get_proactive_suggestions, dismiss_suggestion | Proactive engine |

**Legacy capabilities** (no tool mapping): `web_search`, `code_analysis`, `writing`, `editing`, `data_analysis`, `planning`, `file_operations`, `code_execution`.

### 2.4 Existing Playbook System

**4 YAML playbooks** in `playbooks/`:
- `daily_briefing.yaml` — 6 workstreams (calendar, email, teams, imessage, memory, reminders)
- `meeting_prep.yaml` — 4 workstreams (email, docs, decisions, calendar)
- `expert_research.yaml` — 6 workstreams (memory, docs, email, calendar, identity, web)
- `software_dev_team.yaml` — 5 workstreams (architect, code_reviewer, test, deps, docs)

**Execution flow**: `execute_playbook` MCP tool → `PlaybookLoader` → `playbook_executor.execute_playbook()` → `_dispatch_workstream()` → `BaseExpertAgent.execute()` → same capability-limited tools.

Playbook workstreams reference M365 and Confluence in their prompts but the executing agents can't access them.

### 2.5 Dispatch System (`mcp_tools/dispatch_tools.py`)

`dispatch_agents` selects agents by name, capability, or auto-detection, then runs them in parallel via `asyncio.gather`. Each agent gets a `BaseExpertAgent` instance with the same limited tool set. Results can optionally be synthesized via a Haiku merge pass (`DISPATCH_SYNTHESIS_ENABLED`).

---

## 3. The M365/Atlassian/External Tool Gap

### 3.1 What Claude Code Has That Agents Don't

| MCP Server | Tool Count | Key Tools | Which Agents Need It |
|-----------|-----------|-----------|---------------------|
| **Microsoft 365** | 6 | `outlook_email_search`, `outlook_calendar_search`, `chat_message_search`, `sharepoint_search`, `sharepoint_folder_search`, `find_meeting_availability`, `read_resource` | daily_briefing, meeting_prep, inbox_triage, project_manager, report_builder, research_and_strategy, weekly_planner |
| **Atlassian** | 30+ | `searchJiraIssuesUsingJql`, `getJiraIssue`, `createJiraIssue`, `editJiraIssue`, `getConfluencePage`, `searchConfluenceUsingCql`, `createConfluencePage` | project_manager, incident_summarizer, meeting_prep, report_builder |
| **Security Metrics Vacuum** | 20+ | `query_metrics`, `collect_*`, `generate_snapshot_report`, `generate_trend_report`, `kev_*`, `compare_periods` | security_metrics, endpoint_security_metrics, email_and_awareness_metrics, github_security |
| **Miro** | 10+ | `board_list_items`, `diagram_create`, `table_create`, `doc_create` | report_builder, project_planner |
| **Jarvis MCP tools NOT in capability registry** | ~30 | `enrich_person`, `get/send_imessage*`, `search_identity`, `get_session_brain`, `refresh_okr_data`, `query_okr_status`, `route_message`, `dispatch_agents`, `execute_playbook` | Various |

### 3.2 Impact Analysis

**Critically affected agents** (system prompt references sources they can't access):

1. **`daily_briefing`** — Prompt says "Microsoft Teams: Search recent Teams chat messages" and "Outlook Email: Unread and flagged emails" but has NO M365 access. Only gets Apple Calendar and Apple Mail (which the MEMORY.md explicitly says "often return empty/incomplete").

2. **`meeting_prep`** — Prompt says "the orchestrator should ALSO search Microsoft Teams chats and Outlook via the M365 connector" but the agent itself can't. Only gets Apple-side data.

3. **`security_metrics`** — Prompt says "Query memory and webhooks for each source's latest metrics" but the security-metrics-vacuum MCP server is the authoritative source. Memory only has what was previously stored.

4. **`project_manager`** — References Jira tickets, blockers, status changes — has no Jira access.

5. **`inbox_triage`** — Classifies messages from all channels but can only read via `channel_read` (unified adapter). Can't access M365 Teams/email directly.

### 3.3 Why Not Just Add M365/Atlassian as Capabilities?

Two reasons:

1. **Architecture**: These are remote MCP connectors accessed via `claude_ai_*` protocol. The agent's `_dispatch_tool` method calls local Python functions — it has no way to invoke remote MCP tools. Adding them would require either:
   - A bridge layer (like the existing `claude_m365_bridge.py`) for each connector — expensive, fragile, slow
   - Rewriting `BaseExpertAgent` to be an MCP client itself — massive scope change

2. **Cost/performance**: Running agents through `BaseExpertAgent` uses the Anthropic API directly (one call per tool-use round). Claude Code already has a conversation context with all tools available. Using agents would mean: user → Claude Code → dispatch_agents → new Anthropic API session per agent → tool calls. This doubles the API cost and adds latency.

---

## 4. Hybrid Execution Model Design

### 4.1 Core Concept

**Two execution paths for every agent config:**

```
┌─────────────────────────────────────────────────────────┐
│                   Agent YAML Config                      │
│  (name, system_prompt, capabilities, model, etc.)        │
├─────────────────────────┬───────────────────────────────┤
│    Claude Code Path     │     Daemon/Autonomous Path    │
│    (Interactive)        │     (Background)              │
├─────────────────────────┼───────────────────────────────┤
│ Load system_prompt as   │ BaseExpertAgent executes      │
│ guidance/instructions   │ with capability-gated tools   │
│                         │                               │
│ Claude Code follows the │ Used by:                      │
│ agent's process using   │  - iMessage command channel   │
│ ALL available MCP tools │  - Scheduled tasks            │
│ (Jarvis + M365 +        │  - Event rules/webhooks       │
│  Atlassian + security   │  - Daemon tick loop           │
│  metrics + etc.)        │                               │
│                         │                               │
│ Used by:                │ Tools: capability-limited     │
│  - Interactive Claude   │ (~57 Jarvis-internal)         │
│    Code sessions        │                               │
│  - Claude Code agent    │                               │
│    teams                │                               │
│                         │                               │
│ Tools: ALL MCP (~180+)  │                               │
└─────────────────────────┴───────────────────────────────┘
```

### 4.2 Claude Code Path: Agent-as-Playbook

When Claude Code needs to perform a task that matches an agent's domain:

1. **Load the agent config** via `get_agent(name)` MCP tool
2. **Extract the system prompt** — this becomes Claude Code's task instructions
3. **Follow the agent's process** (the numbered steps in the system prompt)
4. **Use ALL available MCP tools** — Jarvis, M365, Atlassian, security-metrics-vacuum, etc.
5. **Respect the agent's output format** — the structured sections, source attribution, etc.

This is _already_ what Claude Code does manually when following MEMORY.md rules (e.g., "Do NOT use the `daily_briefing` expert agent — run the briefing directly"). The hybrid model formalizes this pattern.

### 4.3 New MCP Tool: `get_agent_as_playbook`

Add a new tool that returns the agent config formatted specifically for Claude Code consumption:

```python
@mcp.tool()
async def get_agent_as_playbook(name: str) -> str:
    """Load an agent config as a structured playbook for Claude Code execution.

    Returns the agent's system prompt, process steps, output format, and
    cross-agent references — formatted as instructions that Claude Code
    follows directly using all available MCP tools.

    Use this instead of dispatch_agents when running in Claude Code/Desktop,
    where you have access to M365, Atlassian, and other MCP connectors that
    agents cannot access directly.

    Args:
        name: Agent name (e.g. 'meeting_prep', 'daily_briefing')
    """
    config = state.agent_registry.get_agent(name)
    if not config:
        return json.dumps({"error": f"Agent '{name}' not found"})

    # Extract the capabilities as tool guidance
    from capabilities.registry import CAPABILITY_DEFINITIONS
    tool_guidance = []
    for cap in config.capabilities:
        defn = CAPABILITY_DEFINITIONS.get(cap)
        if defn:
            tool_guidance.append({
                "capability": cap,
                "description": defn.description,
                "jarvis_tools": list(defn.tool_names),
                "mcp_alternatives": _get_mcp_alternatives(cap),
            })

    return json.dumps({
        "mode": "playbook",
        "name": config.name,
        "description": config.description,
        "instructions": config.system_prompt,
        "capabilities_needed": config.capabilities,
        "tool_guidance": tool_guidance,
        "output_settings": {
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        },
        "agent_memory": _get_agent_memories(config.name),
        "note": (
            "Execute this playbook using ALL available MCP tools. "
            "The instructions reference data sources that may require M365, "
            "Atlassian, or other external MCP connectors beyond Jarvis tools."
        ),
    })
```

### 4.4 MCP Alternative Mapping

A key part of the hybrid model: mapping each Jarvis capability to its richer MCP alternative:

```python
MCP_ALTERNATIVES = {
    "calendar_read": {
        "primary": "mcp__claude_ai_Microsoft_365__outlook_calendar_search",
        "also_use": ["mcp__jarvis__get_calendar_events"],
        "note": "M365 is primary for work calendar; Apple Calendar for personal/iCloud",
    },
    "mail_read": {
        "primary": "mcp__claude_ai_Microsoft_365__outlook_email_search",
        "also_use": ["mcp__jarvis__search_mail"],
        "note": "M365 Outlook is primary; Apple Mail may be incomplete",
    },
    "document_search": {
        "primary": "mcp__claude_ai_Atlassian__searchConfluenceUsingCql",
        "also_use": ["mcp__jarvis__search_documents"],
        "note": "Confluence for team docs; Jarvis documents for locally ingested files",
    },
    # No Jarvis equivalent — M365-only
    "teams_read": {
        "primary": "mcp__claude_ai_Microsoft_365__chat_message_search",
        "note": "Teams chat messages only accessible via M365 connector",
    },
    # No Jarvis equivalent — Atlassian-only
    "jira_read": {
        "primary": "mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql",
        "note": "Jira issues only accessible via Atlassian connector",
    },
}
```

### 4.5 CLAUDE.md Routing Rules

Add a routing section to CLAUDE.md that tells Claude Code when to use the playbook pattern:

```markdown
## Agent Playbook Routing

When a task matches an agent's domain, load the agent config as a playbook:

| Task Pattern | Agent to Load | Key External Sources |
|-------------|--------------|---------------------|
| "daily briefing", "morning brief" | daily_briefing | M365 Calendar + Email + Teams, Apple Calendar, iMessage, Jarvis memory |
| "meeting prep", "talking points for" | meeting_prep | M365 Email + Teams, Confluence, Jarvis memory + decisions + delegations |
| "security metrics", "security posture" | security_metrics | security-metrics-vacuum MCP, Jarvis memory + webhooks |
| "project status", "track project" | project_manager | Jira, Confluence, M365 Email, Jarvis delegations + decisions |
| "draft email", "send message" | communications | M365 Email, Jarvis memory for contacts |
| "incident summary", "postmortem" | incident_summarizer | Jira, M365 Teams, Jarvis memory + webhooks |

### How to Use

1. Call `get_agent(name)` to load the agent config
2. Read the `system_prompt` — this is your process guide
3. Follow its numbered steps, but use ALL available MCP tools
4. Respect its output format and source attribution rules
5. After completion, optionally store results via agent memory
```

### 4.6 Daemon/Autonomous Path (Unchanged)

The following paths continue using `BaseExpertAgent` as-is:

1. **iMessage command channel** (`channels/imessage_adapter.py` → `inbox_triage` → agent dispatch)
2. **Scheduled tasks** (`scheduler/engine.py` → handler runs agent)
3. **Event rules** (`webhook/dispatcher.py` → matches event → dispatches agent)
4. **Proactive actions** (`proactive/action_executor.py` → auto-acts on suggestions)

These run headless without Claude Code, so they can only use Jarvis-internal tools. The existing playbook system also stays as-is for scheduled delivery (e.g., daily brief via email).

---

## 5. Implementation Plan

### Phase 1: Expose Agent Configs as Playbooks (Low effort, high impact)

**Files to modify:**
- `mcp_tools/agent_tools.py` — Add `get_agent_as_playbook` tool
- `capabilities/registry.py` — Add `MCP_ALTERNATIVES` mapping dict and `_get_mcp_alternatives()` function

**New tool**: `get_agent_as_playbook(name)` returns:
- Full system prompt
- Capability-to-MCP-tool mapping for Claude Code
- Agent memory (prior run context)
- Shared namespace memories
- Cross-agent awareness hints

**Tests**: New test file `tests/test_agent_playbook_tool.py`

**Estimated scope**: ~150 lines of code, ~100 lines of tests

### Phase 2: CLAUDE.md Routing Table (Zero code change)

**Files to modify:**
- `CLAUDE.md` — Add "Agent Playbook Routing" section with:
  - Task pattern → agent name mapping table
  - Usage instructions for the playbook pattern
  - Rules: "When in Claude Code, prefer playbook mode over dispatch_agents"

This is a documentation-only change that gives Claude Code the routing intelligence to know _when_ to load an agent config as a playbook.

### Phase 3: Enhanced Playbook Format (Medium effort)

Extend agent YAML configs with optional `playbook_hints` field:

```yaml
name: meeting_prep
description: ...
system_prompt: ...
capabilities: [...]
playbook_hints:
  external_sources:
    - name: M365 Email
      tool: outlook_email_search
      query_template: "threads with {attendees} about {topic} last 14 days"
    - name: Teams Chat
      tool: chat_message_search
      query_template: "messages from {attendees} last 7 days"
    - name: Confluence
      tool: searchConfluenceUsingCql
      query_template: "text ~ '{topic}' order by lastModified desc"
  parallel_groups:
    - [calendar_context, email_context, teams_context]
    - [decision_history, document_context]
  synthesis_format: "meeting_brief"
```

**Files to modify:**
- `agents/registry.py` — Extend `AgentConfig` dataclass with `playbook_hints` field
- `agent_configs/*.yaml` — Add hints to key agents (start with meeting_prep, daily_briefing, security_metrics)
- `mcp_tools/agent_tools.py` — Include hints in `get_agent_as_playbook` response

**Estimated scope**: ~50 lines registry change, ~50 lines per agent config update

### Phase 4: Unify Playbook Systems (Future)

Currently there are TWO playbook concepts:
1. **Agent YAML configs** (34 files in `agent_configs/`) — system prompts with process steps
2. **Playbook YAML files** (4 files in `playbooks/`) — workstream definitions with synthesis

These should converge. Agent configs already contain the "what to do" (system_prompt) while playbooks add "how to parallelize" (workstreams) and "how to combine" (synthesis). The unified model would be:

```yaml
# Merged format
name: meeting_prep
description: ...
system_prompt: ...  # Full behavioral instructions
capabilities: [...]  # For daemon/autonomous path
playbook_hints:  # For Claude Code path
  external_sources: [...]
  parallel_groups: [...]
workstreams: [...]  # For playbook executor path
synthesis: ...  # For multi-agent result combination
```

This is a larger refactor and should wait until Phases 1-3 prove the pattern.

---

## 6. Decision: What NOT to Build

### Don't: Add MCP connector bridges to BaseExpertAgent

Adding M365/Atlassian tool access to the agent execution loop would require:
- A bridge subprocess per connector (like `claude_m365_bridge.py`)
- Each bridge spawns a Claude CLI process with the connector configured
- Agent tools would need to route through bridges
- Cost: 2x API calls (agent + bridge), 5-10s latency per bridge call

This is the wrong approach. The hybrid model gives Claude Code direct access to these tools without the bridge overhead.

### Don't: Replace dispatch_agents entirely

`dispatch_agents` and `BaseExpertAgent` serve the autonomous path well. The daemon, scheduler, and iMessage channel need them. The hybrid model adds a parallel path, not a replacement.

### Don't: Auto-detect execution context

We could try to detect whether we're running in Claude Code vs daemon and auto-switch behavior. This adds complexity and fragility. Better: explicit routing via CLAUDE.md rules and the `get_agent_as_playbook` tool.

---

## 7. Migration Path for Key Agents

### daily_briefing
- **Current**: MEMORY.md says "Do NOT use the `daily_briefing` expert agent"
- **After Phase 1**: `get_agent_as_playbook("daily_briefing")` → follow system prompt with M365 tools
- **After Phase 3**: Playbook hints specify parallel M365 queries + Apple Calendar + iMessage

### meeting_prep
- **Current**: System prompt says "MCP orchestrator note: search Teams and Outlook" but agent can't
- **After Phase 1**: Playbook mode enables Teams + Outlook + Confluence search
- **After Phase 3**: Hints add query templates for attendee-based searches

### security_metrics
- **Current**: Agent queries memory/webhooks for stored metrics (stale data)
- **After Phase 1**: Playbook mode enables direct security-metrics-vacuum MCP calls
- **After Phase 3**: Hints map each security source to its vacuum MCP tool

### project_manager
- **Current**: No Jira or Confluence access
- **After Phase 1**: Playbook mode enables Jira JQL queries + Confluence search
- **After Phase 3**: Hints include standard JQL patterns for project tracking

---

## 8. Success Metrics

1. **Coverage**: All 34 agent system prompts are usable as playbooks via `get_agent_as_playbook`
2. **Tool access**: Claude Code playbook execution can reach M365, Atlassian, and security-metrics-vacuum
3. **No regressions**: Daemon/scheduler/iMessage paths continue working with `BaseExpertAgent`
4. **Reduced duplication**: No more ad-hoc process definitions in MEMORY.md (e.g., daily briefing rules)
5. **Agent memory continuity**: Playbook executions can read/write agent memory for cross-session learning

---

## 9. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Claude Code ignores playbook instructions | Low | Medium | Strong routing in CLAUDE.md + tool description |
| Agent config drift from playbook usage patterns | Medium | Low | Phase 3 hints keep configs authoritative |
| Daemon path breaks during refactor | Low | High | Phase 1 doesn't touch BaseExpertAgent |
| MCP alternative mapping goes stale | Medium | Medium | Generate mapping from live tool discovery |
| System prompt too long for Claude Code context | Low | Medium | Summarize for context-constrained scenarios |

---

## 10. Appendix: All 34 Agent Configs

| # | Agent Name | Capabilities | Model | Description |
|---|-----------|-------------|-------|-------------|
| 1 | `action_item_tracker` | memory, docs, mail, decisions, delegations | sonnet | Tracks action items across sources |
| 2 | `agenda_manager` | memory, calendar, decisions, delegations | sonnet | Meeting agenda management |
| 3 | `approval_triage` | memory, mail, decisions, delegations | sonnet | Routes approval requests |
| 4 | `backlog_manager` | memory, docs, decisions, delegations | sonnet | Backlog grooming and prioritization |
| 5 | `code_quality_reviewer` | memory, docs | sonnet | Code review and quality checks |
| 6 | `communications` | memory, mail, notifications | haiku | Outbound email/notification delivery |
| 7 | `daily_briefing` | memory, docs, calendar, reminders, mail, delegations, decisions | sonnet | Morning briefing generation |
| 8 | `decision_tracker` | memory, decisions, delegations | sonnet | Decision lifecycle management |
| 9 | `delegation_tracker` | memory, delegations, mail | sonnet | Delegation monitoring and follow-ups |
| 10 | `document_librarian` | memory, docs | sonnet | Document organization and search |
| 11 | `email_and_awareness_metrics` | memory, docs, webhooks, alerts | sonnet | Mimecast + KnowBe4 metrics |
| 12 | `endpoint_security_metrics` | memory, docs, webhooks, alerts | sonnet | SentinelOne + Tanium metrics |
| 13 | `github_security` | memory, docs, webhooks, alerts | sonnet | GitHub Advanced Security metrics |
| 14 | `inbox_triage` | memory, channels | haiku | Message classification and routing |
| 15 | `incident_summarizer` | memory, docs, webhooks, mail | sonnet | Incident summaries and postmortems |
| 16 | `meeting_debrief` | memory, docs, decisions, delegations, reminders | sonnet | Post-meeting outcome capture |
| 17 | `meeting_prep` | memory, docs, calendar, reminders, mail, decisions, delegations | sonnet | Pre-meeting briefing materials |
| 18 | `okr_tracker` | memory, docs, decisions, delegations | sonnet | OKR status tracking |
| 19 | `proactive_alerts` | memory, alerts, webhooks, delegations, decisions | sonnet | Alert evaluation and notifications |
| 20 | `project_manager` | memory, docs, mail, decisions, delegations, calendar, reminders, agent_memory | sonnet | Project status tracking |
| 21 | `project_planner` | memory, docs, decisions, delegations | sonnet | Project planning and breakdown |
| 22 | `project_review_architecture` | memory, docs | sonnet | Architecture quality review |
| 23 | `project_review_board` | memory, docs | sonnet | Synthesizes specialist reviews |
| 24 | `project_review_delivery` | memory, docs | sonnet | Engineering delivery health |
| 25 | `project_review_product` | memory, docs | sonnet | Product usability review |
| 26 | `project_review_reliability` | memory, docs | sonnet | Reliability and test coverage |
| 27 | `project_review_security` | memory, docs | sonnet | Security posture review |
| 28 | `report_builder` | memory, docs, mail, decisions, delegations, calendar, reminders, agent_memory | sonnet | Structured report generation |
| 29 | `research_and_strategy` | memory, docs, mail, webhooks | sonnet | Deep research and strategy |
| 30 | `scheduler` | memory, calendar, reminders, scheduling | sonnet | Time management and scheduling |
| 31 | `security_auditor` | memory, docs | sonnet | System security audit |
| 32 | `security_metrics` | memory, docs, webhooks, alerts | sonnet | Unified security posture reports |
| 33 | `weekly_planner` | memory, docs, calendar, reminders, mail, delegations, decisions | sonnet | Weekly priority planning |
| 34 | `workflow_optimizer` | memory, docs | sonnet | Process optimization suggestions |

---

## 11. Appendix: External MCP Tools Available to Claude Code

### Microsoft 365 (7 tools)
- `outlook_email_search` — Search Outlook email by query
- `outlook_calendar_search` — Search Outlook calendar events
- `chat_message_search` — Search Teams chat messages
- `sharepoint_search` — Search SharePoint content
- `sharepoint_folder_search` — Browse SharePoint folder contents
- `find_meeting_availability` — Find available meeting slots for participants
- `read_resource` — Read a specific M365 resource by ID

### Atlassian (30+ tools)
- `searchJiraIssuesUsingJql` — Search Jira issues using JQL
- `getJiraIssue` — Get full Jira issue details
- `createJiraIssue` / `editJiraIssue` — Create/edit Jira issues
- `getTransitionsForJiraIssue` / `transitionJiraIssue` — Manage issue workflow
- `searchConfluenceUsingCql` — Search Confluence using CQL
- `getConfluencePage` — Get Confluence page content
- `createConfluencePage` / `updateConfluencePage` — Create/update pages
- `getConfluenceSpaces` / `getPagesInConfluenceSpace` — Browse spaces
- `addCommentToJiraIssue` — Comment on issues
- `getJiraProjectIssueTypesMetadata` — Get project metadata
- Plus 15+ additional tools for comments, worklogs, links, etc.

### Security Metrics Vacuum (20+ tools)
- `query_metrics` — Query stored security metrics with filters
- `collect_tanium` / `collect_sentinelone` / `collect_knowbe4` / `collect_github` — Collect from sources
- `collect_all` — Collect from all configured sources
- `generate_snapshot_report` / `generate_trend_report` — Generate reports
- `kev_sync_catalog` / `kev_calculate_compliance` / `kev_list_overdue` — KEV management
- `compare_periods` — Compare metrics across time periods
- `list_metrics` / `get_metric_config` — Inspect configuration
- `run_full_automation` — Full collection + report pipeline

### Miro (10+ tools)
- `board_list_items` — List board items
- `diagram_create` / `diagram_get_dsl` — Create/read diagrams
- `doc_create` / `doc_get` / `doc_update` — Document management
- `table_create` / `table_list_rows` / `table_sync_rows` — Table management
- `image_get_data` / `image_get_url` — Image access
