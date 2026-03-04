# Capability Registry Extensions: M365 & Atlassian

Architecture document for extending the agent capability registry to surface Microsoft 365 and Atlassian tools to expert agents.

**Status**: Proposed
**Date**: 2026-03-04
**Author**: architect (Claude Code team agent)

---

## 1. Problem Statement

Expert agents (e.g., `daily_briefing`, `meeting_prep`, `incident_summarizer`) reference M365 and Atlassian data in their system prompts but **cannot access it** when running their own Claude tool-use loops via `BaseExpertAgent.execute()`. These connectors only exist as external MCP servers available to Claude Code / Claude Desktop — they are not Python functions that `_dispatch_tool()` in `agents/base.py` can call.

This creates a two-tier system:
- **Claude Code level**: Full access to M365 email, calendar, Teams, Jira, Confluence via MCP connectors
- **Agent level**: Limited to local Python tools (Apple Calendar, Apple Mail, memory, documents, etc.)

The daily briefing MEMORY.md rule ("Do NOT use the `daily_briefing` expert agent — it lacks M365/Atlassian access") is a direct consequence of this gap.

## 2. Current Capability Registry Architecture

### 2.1 Registry Structure (`capabilities/registry.py`)

The registry has three layers:

```
TOOL_SCHEMAS (dict[str, dict])     → Claude API tool definitions (name, description, input_schema)
CAPABILITY_DEFINITIONS (dict)      → Named groups mapping to tool_names tuples
get_tools_for_capabilities()       → Resolves capabilities → tool schemas for agent execution
```

### 2.2 Current Capability Map (33 capabilities)

| Capability | Tools | Implemented |
|-----------|-------|-------------|
| `memory_read` | `query_memory` | Yes |
| `memory_write` | `store_memory` | Yes |
| `document_search` | `search_documents` | Yes |
| `calendar_read` | `get_calendar_events`, `search_calendar_events` | Yes |
| `reminders_read` | `list_reminders`, `search_reminders` | Yes |
| `reminders_write` | `create_reminder`, `complete_reminder` | Yes |
| `notifications` | `send_notification` | Yes |
| `mail_read` | `get_mail_messages`, `get_mail_message`, `search_mail`, `get_unread_count` | Yes |
| `mail_write` | `send_email`, `mark_mail_read`, `mark_mail_flagged`, `move_mail_message` | Yes |
| `teams_write` | `open_teams_browser`, `post_teams_message`, `confirm_teams_post`, `cancel_teams_post`, `close_teams_browser` | Yes |
| `decision_read` | `search_decisions`, `list_pending_decisions` | Yes |
| `decision_write` | `create_decision`, `update_decision`, `delete_decision` | Yes |
| `delegation_read` | `list_delegations`, `check_overdue_delegations` | Yes |
| `delegation_write` | `create_delegation`, `update_delegation`, `delete_delegation` | Yes |
| `alerts_read` | `check_alerts`, `list_alert_rules` | Yes |
| `alerts_write` | `create_alert_rule`, `dismiss_alert` | Yes |
| `scheduling` | `find_my_open_slots`, `find_group_availability` | Yes |
| `agent_memory_read` | `get_agent_memory` | Yes |
| `agent_memory_write` | `clear_agent_memory` | Yes |
| `channel_read` | `list_inbound_events`, `get_event_summary` | Yes |
| `proactive_read` | `get_proactive_suggestions`, `dismiss_suggestion` | Yes |
| `webhook_read` | `list_webhook_events`, `get_webhook_event` | Yes |
| `webhook_write` | `process_webhook_event` | Yes |
| `scheduler_read` | `list_scheduled_tasks`, `get_scheduler_status` | Yes |
| `scheduler_write` | `create_scheduled_task`, `update_scheduled_task`, `delete_scheduled_task`, `run_scheduled_task` | Yes |
| `skill_read` | `list_skill_suggestions` | Yes |
| `skill_write` | `record_tool_usage`, `analyze_skill_patterns`, `auto_create_skill` | Yes |
| `web_browse` | `web_open`, `web_snapshot`, `web_get_text`, `web_screenshot`, `web_scroll`, `web_find` | Yes |
| `web_browse_write` | `web_click`, `web_fill`, `web_execute_js` | Yes |
| `web_state` | `web_state_save`, `web_state_load` | Yes |
| `web_search` | *(none)* | **Legacy** |
| `code_analysis` | *(none)* | **Legacy** |
| `writing` | *(none)* | **Legacy** |
| `editing` | *(none)* | **Legacy** |
| `data_analysis` | *(none)* | **Legacy** |
| `planning` | *(none)* | **Legacy** |
| `file_operations` | *(none)* | **Legacy** |
| `code_execution` | *(none)* | **Legacy** |

### 2.3 Agent Execution Flow

```
AgentConfig.capabilities → get_tools_for_capabilities() → tool schemas
                                                              ↓
BaseExpertAgent.execute() → Claude API (with tool schemas) → tool_use response
                                                              ↓
_handle_tool_call() → _dispatch_tool() → dispatch table → Python handler
```

Key constraint: `_dispatch_tool()` requires a Python handler in the dispatch table. There is no mechanism to forward tool calls to external MCP servers.

### 2.4 Existing M365 Bridge Pattern

The `ClaudeM365Bridge` (`connectors/claude_m365_bridge.py`) already bridges to M365 for **calendar operations** by spawning a Claude CLI subprocess with the M365 MCP connector. This provides:
- `list_calendars()`, `get_events()`, `search_events()`, `create_event()`, `update_event()`, `delete_event()`

This bridge is consumed by the unified calendar system (`connectors/calendar_unified.py`), which routes calendar reads/writes across Apple Calendar and M365. Agents already get M365 calendar data through `calendar_read` capability — the bridge is transparent.

However, there is **no equivalent bridge for M365 email, Teams, SharePoint, or any Atlassian tools**.

## 3. External MCP Tools to Integrate

### 3.1 Microsoft 365 Connector Tools

| MCP Tool | Purpose | Read/Write |
|----------|---------|------------|
| `outlook_email_search` | Search Outlook email by query | Read |
| `outlook_calendar_search` | Search Outlook calendar events | Read |
| `chat_message_search` | Search Teams DMs and channels | Read |
| `read_resource` | Read any M365 resource by URI | Read |
| `find_meeting_availability` | Find meeting times across attendees | Read |
| `sharepoint_search` | Search SharePoint sites and content | Read |
| `sharepoint_folder_search` | Search within a SharePoint folder | Read |

### 3.2 Atlassian Connector Tools

| MCP Tool | Purpose | Read/Write |
|----------|---------|------------|
| `searchJiraIssuesUsingJql` | Search Jira issues with JQL | Read |
| `getJiraIssue` | Get a single Jira issue by key | Read |
| `createJiraIssue` | Create a Jira issue | Write |
| `editJiraIssue` | Update a Jira issue | Write |
| `addCommentToJiraIssue` | Add comment to a Jira issue | Write |
| `searchConfluenceUsingCql` | Search Confluence with CQL | Read |
| `getConfluencePage` | Get a Confluence page | Read |
| `createConfluencePage` | Create a Confluence page | Write |
| `updateConfluencePage` | Update a Confluence page | Write |
| `search` | General Atlassian search | Read |
| `getConfluenceSpaces` | List Confluence spaces | Read |
| `getVisibleJiraProjects` | List accessible Jira projects | Read |

## 4. Proposed Capability Extensions

### 4.1 New Capability Definitions

```python
# --- M365 external connector capabilities ---
"m365_email_read": CapabilityDefinition(
    name="m365_email_read",
    description="Search and read Outlook email via M365 connector",
    tool_names=("m365_email_search",),
),
"m365_calendar_read": CapabilityDefinition(
    name="m365_calendar_read",
    description="Search Outlook calendar events via M365 connector",
    tool_names=("m365_calendar_search",),
),
"m365_teams_read": CapabilityDefinition(
    name="m365_teams_read",
    description="Search Teams messages and channels via M365 connector",
    tool_names=("m365_teams_search",),
),
"m365_sharepoint_read": CapabilityDefinition(
    name="m365_sharepoint_read",
    description="Search SharePoint sites and folders via M365 connector",
    tool_names=("m365_sharepoint_search",),
),
"m365_availability": CapabilityDefinition(
    name="m365_availability",
    description="Find meeting availability across M365 attendees",
    tool_names=("m365_find_availability",),
),

# --- Atlassian external connector capabilities ---
"atlassian_jira_read": CapabilityDefinition(
    name="atlassian_jira_read",
    description="Search and read Jira issues via Atlassian connector",
    tool_names=("jira_search", "jira_get_issue"),
),
"atlassian_jira_write": CapabilityDefinition(
    name="atlassian_jira_write",
    description="Create and update Jira issues via Atlassian connector",
    tool_names=("jira_create_issue", "jira_edit_issue", "jira_add_comment"),
),
"atlassian_confluence_read": CapabilityDefinition(
    name="atlassian_confluence_read",
    description="Search and read Confluence pages via Atlassian connector",
    tool_names=("confluence_search", "confluence_get_page"),
),
"atlassian_confluence_write": CapabilityDefinition(
    name="atlassian_confluence_write",
    description="Create and update Confluence pages via Atlassian connector",
    tool_names=("confluence_create_page", "confluence_update_page"),
),
```

### 4.2 Tool Schema Definitions

Each new tool needs a `TOOL_SCHEMAS` entry. These use **simplified, agent-friendly parameter names** (not the raw MCP tool names) so agents interact with clean interfaces. Example:

```python
"m365_email_search": {
    "name": "m365_email_search",
    "description": "Search Outlook email messages. Returns subjects, senders, dates, and snippets.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (e.g., 'from:shawn budget review')"},
            "max_results": {"type": "integer", "description": "Maximum results to return (default 10)"},
        },
        "required": ["query"],
    },
},
"m365_teams_search": {
    "name": "m365_teams_search",
    "description": "Search Microsoft Teams messages for DMs, mentions, and channel posts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Maximum results to return (default 10)"},
        },
        "required": ["query"],
    },
},
"jira_search": {
    "name": "jira_search",
    "description": "Search Jira issues using JQL or text query.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "JQL query or text search"},
            "max_results": {"type": "integer", "description": "Maximum results (default 20)"},
        },
        "required": ["query"],
    },
},
"jira_get_issue": {
    "name": "jira_get_issue",
    "description": "Get full details of a Jira issue by key (e.g., PROJ-123).",
    "input_schema": {
        "type": "object",
        "properties": {
            "issue_key": {"type": "string", "description": "Jira issue key (e.g., ITSD-467124)"},
        },
        "required": ["issue_key"],
    },
},
"confluence_search": {
    "name": "confluence_search",
    "description": "Search Confluence pages by text or CQL query.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query or CQL expression"},
            "max_results": {"type": "integer", "description": "Maximum results (default 10)"},
        },
        "required": ["query"],
    },
},
"confluence_get_page": {
    "name": "confluence_get_page",
    "description": "Get full content of a Confluence page by ID or title.",
    "input_schema": {
        "type": "object",
        "properties": {
            "page_id": {"type": "string", "description": "Page ID or title to retrieve"},
        },
        "required": ["page_id"],
    },
},
```

## 5. Bridge Pattern Design

### 5.1 The Two Execution Paths

Agents can execute in two fundamentally different contexts:

```
Path A: Claude Code Playbook Execution (external orchestration)
═══════════════════════════════════════════════════════════════
Claude Code ──→ dispatches workstreams ──→ each workstream is a Claude Code prompt
                                              ├── has MCP connectors (M365, Atlassian)
                                              ├── has Jarvis MCP tools
                                              └── orchestrated at Claude Code level

Path B: BaseExpertAgent Execution (internal Python loop)
═══════════════════════════════════════════════════════════════
MCP tool call ──→ dispatch_agents() ──→ BaseExpertAgent.execute()
                                           ├── Claude API with tool schemas
                                           ├── _dispatch_tool() → Python handlers
                                           └── NO access to external MCP servers
```

### 5.2 Recommended Approach: CLI Bridge (like ClaudeM365Bridge)

Extend the existing `ClaudeM365Bridge` pattern to cover all M365 and Atlassian operations. Create new bridge classes:

```
connectors/
├── claude_m365_bridge.py          # Existing: calendar only
├── claude_m365_email_bridge.py    # New: email search
├── claude_m365_teams_bridge.py    # New: Teams search
├── claude_m365_sharepoint_bridge.py  # New: SharePoint search
├── claude_atlassian_bridge.py     # New: Jira + Confluence
```

Each bridge follows the same pattern:
1. Spawn `claude -p <prompt> --output-format json --json-schema <schema>` with appropriate MCP config
2. Parse structured JSON response
3. Return normalized Python dicts

**Advantages**:
- Proven pattern (M365 calendar bridge works reliably)
- No dependency on MCP server internals
- Works in both Claude Code and daemon contexts
- Clean error handling with fallback

**Disadvantages**:
- Each bridge call spawns a subprocess (latency ~5-15s per call)
- Requires Claude CLI installed and MCP connectors configured
- Cost: each bridge call is a Claude API call

### 5.3 Alternative: Schema-Only Capabilities (for Claude Code path)

For the Claude Code playbook execution path, we don't need Python handlers at all. The schemas serve as **documentation** telling Claude Code which external MCP tools to use. Add a new field to `CapabilityDefinition`:

```python
@dataclass(frozen=True)
class CapabilityDefinition:
    name: str
    description: str
    tool_names: tuple[str, ...] = ()
    implemented: bool = True
    external: bool = False                    # NEW: marks as external MCP tool
    mcp_tool_mapping: dict[str, str] = field(default_factory=dict)  # NEW: maps tool_name → MCP tool name
```

Example:
```python
"m365_email_read": CapabilityDefinition(
    name="m365_email_read",
    description="Search Outlook email via M365 connector",
    tool_names=("m365_email_search",),
    external=True,
    mcp_tool_mapping={
        "m365_email_search": "mcp__claude_ai_Microsoft_365__outlook_email_search",
    },
),
```

When `external=True`:
- **Claude Code playbook path**: The orchestrator reads `mcp_tool_mapping` and knows to call the MCP tool directly
- **BaseExpertAgent path**: `_dispatch_tool()` routes to the CLI bridge handler if available, or returns a helpful error ("M365 email requires Claude Code execution context")

### 5.4 Recommended Hybrid: Schema + Bridge

Combine both approaches:

1. **Schema-only entries** in the registry with `external=True` and `mcp_tool_mapping`
2. **CLI bridges** wired into `_dispatch_tool()` for the subset that justifies the latency cost
3. **Graceful degradation**: if bridge isn't available, the tool returns an error explaining the limitation

Implementation priority for bridges (based on agent need):
1. **M365 email search** — highest impact, used by 8+ agents
2. **M365 Teams search** — second highest, referenced in daily_briefing/weekly_planner
3. **Jira search + get issue** — referenced by incident_summarizer, approval_triage, action_item_tracker
4. **Confluence search** — referenced by meeting_prep playbook
5. **M365 SharePoint** — lower priority, already have `download_from_sharepoint` MCP tool

## 6. Dispatch Table Extension

Add bridge handlers to `BaseExpertAgent._get_dispatch_table()`:

```python
def _get_dispatch_table(self) -> dict:
    table = {
        # ... existing handlers ...

        # M365 bridge handlers (conditional on bridge availability)
        "m365_email_search": self._handle_m365_email_search,
        "m365_teams_search": self._handle_m365_teams_search,
        "m365_calendar_search": self._handle_m365_calendar_search,
        "m365_sharepoint_search": self._handle_m365_sharepoint_search,
        "m365_find_availability": self._handle_m365_find_availability,

        # Atlassian bridge handlers
        "jira_search": self._handle_jira_search,
        "jira_get_issue": self._handle_jira_get_issue,
        "jira_create_issue": self._handle_jira_create_issue,
        "jira_edit_issue": self._handle_jira_edit_issue,
        "jira_add_comment": self._handle_jira_add_comment,
        "confluence_search": self._handle_confluence_search,
        "confluence_get_page": self._handle_confluence_get_page,
        "confluence_create_page": self._handle_confluence_create_page,
        "confluence_update_page": self._handle_confluence_update_page,
    }
    return table
```

These handlers would be provided by new mixins:

```python
class M365BridgeMixin:
    """Bridge handlers for M365 tools via Claude CLI subprocess."""

    def _handle_m365_email_search(self, tool_input: dict) -> dict: ...
    def _handle_m365_teams_search(self, tool_input: dict) -> dict: ...
    # ...

class AtlassianBridgeMixin:
    """Bridge handlers for Atlassian tools via Claude CLI subprocess."""

    def _handle_jira_search(self, tool_input: dict) -> dict: ...
    def _handle_jira_get_issue(self, tool_input: dict) -> dict: ...
    # ...
```

## 7. Agent YAML Impact Assessment

### 7.1 Agents That Would Gain M365/Atlassian Capabilities

| Agent | Current Capabilities | Would Gain | Impact |
|-------|---------------------|------------|--------|
| `daily_briefing` | calendar, mail, memory, docs, reminders, delegations, decisions | `m365_email_read`, `m365_teams_read` | **Critical** — currently bypassed per MEMORY.md rule |
| `meeting_prep` | calendar, mail, memory, docs, decisions, delegations, reminders | `m365_email_read`, `m365_teams_read`, `atlassian_confluence_read` | **High** — system prompt mentions Teams/Confluence but can't access them |
| `weekly_planner` | calendar, mail, memory, docs, reminders, delegations, decisions | `m365_email_read`, `m365_teams_read` | **High** — system prompt mentions Teams/Outlook explicitly |
| `incident_summarizer` | memory, docs, mail, calendar | `m365_email_read`, `m365_teams_read`, `atlassian_jira_read` | **High** — needs Jira for incident tracking |
| `action_item_tracker` | memory, docs, reminders, delegations, calendar, mail | `m365_email_read`, `m365_teams_read`, `atlassian_jira_read`, `atlassian_confluence_read` | **High** — references Confluence agendas, Jira, Teams |
| `approval_triage` | memory, docs, mail, decisions | `m365_email_read`, `atlassian_jira_read` | **Medium** — references Jira approvals, Workday |
| `project_manager` | memory, docs, mail, decisions, delegations, calendar, reminders, agent_memory | `m365_email_read`, `m365_teams_read`, `atlassian_jira_read` | **Medium** — broader data would improve project tracking |
| `research_and_strategy` | memory, docs, mail, decisions, delegations, calendar, agent_memory | `m365_email_read`, `m365_teams_read`, `atlassian_confluence_read`, `atlassian_jira_read` | **Medium** — deeper data access for research |
| `delegation_tracker` | memory, docs, delegations | `m365_email_read`, `m365_teams_read` | **Medium** — check for completion signals in email/Teams |
| `decision_tracker` | memory, docs, decisions | `m365_email_read` | **Low** — mainly memory-driven |
| `communications` | memory, mail, notifications | `m365_email_read` | **Low** — already has Apple Mail |
| `inbox_triage` | memory, channel_read | `m365_email_read`, `m365_teams_read` | **Medium** — broader triage across channels |

### 7.2 Agents That Don't Need External Connectors

| Agent | Reason |
|-------|--------|
| `meeting_debrief` | Post-meeting capture, works with user-provided input |
| `code_quality_reviewer` | Code analysis only |
| `security_auditor` | System security analysis |
| `backlog_manager` | Manages local backlog items |
| `workflow_optimizer` | Internal workflow analysis |
| `okr_tracker` | OKR data from dedicated store |
| `scheduler` | Manages scheduled tasks |
| `project_review_*` (5 agents) | Code review agents |
| `security_metrics` | Uses dedicated security-metrics-vacuum MCP |
| `email_and_awareness_metrics` | Uses dedicated security-metrics-vacuum MCP |
| `endpoint_security_metrics` | Uses dedicated security-metrics-vacuum MCP |
| `github_security` | Uses dedicated security-metrics-vacuum MCP |
| `proactive_alerts` | Internal alert evaluation |
| `document_librarian` | Document management only |
| `report_builder` | Report generation from existing data |
| `project_planner` | Planning workflows |
| `agenda_manager` | Meeting agenda management |

## 8. Playbook Integration

Playbooks (YAML-defined parallel workstreams) benefit most from external connectors because they execute at Claude Code level where MCP connectors are directly available.

### 8.1 Current Playbooks

| Playbook | Workstreams Using External Tools |
|----------|--------------------------------|
| `daily_briefing` | `calendar_review` (M365+Apple), `email_digest` (M365), `teams_digest` (M365 Teams) |
| `meeting_prep` | `email_context` (M365), `document_context` (Confluence + Jarvis docs) |
| `expert_research` | Could benefit from Confluence/Jira for internal research |
| `software_dev_team` | Could benefit from Jira for ticket context |

### 8.2 Playbook Execution with Capability Awareness

When a playbook workstream declares required capabilities, the executor can validate that the execution context provides them:

```yaml
# Proposed: capability annotations in playbook workstreams
workstreams:
  - name: email_digest
    requires: [m365_email_read]
    prompt: |
      Search M365 email for messages from the last 24 hours...
  - name: jira_review
    requires: [atlassian_jira_read]
    prompt: |
      Search Jira for open issues assigned to the user...
```

The playbook executor can then:
1. Check if the execution context (Claude Code vs daemon) provides the required capabilities
2. Skip workstreams whose requirements aren't met (with a note in the output)
3. Report which workstreams ran and which were skipped

## 9. Implementation Plan

### Phase 1: Registry Extension (no runtime changes)

1. Add `external` and `mcp_tool_mapping` fields to `CapabilityDefinition`
2. Add new capability definitions for M365 and Atlassian
3. Add corresponding tool schemas to `TOOL_SCHEMAS`
4. Update `validate_capabilities()` to accept new names
5. Update agent YAML configs with new capabilities
6. Tests for validation and schema generation

### Phase 2: CLI Bridges (runtime handlers)

1. Create `ClaudeM365EmailBridge` (email search)
2. Create `ClaudeM365TeamsBridge` (Teams search)
3. Create `ClaudeAtlassianBridge` (Jira + Confluence)
4. Create `M365BridgeMixin` and `AtlassianBridgeMixin` for `BaseExpertAgent`
5. Wire bridges into `_get_dispatch_table()`
6. Add bridge instances to `BaseExpertAgent.__init__()` via dependency injection
7. Tests with mocked subprocesses

### Phase 3: Playbook Capability Annotations

1. Add `requires` field to `Workstream` dataclass
2. Update `PlaybookLoader` to parse `requires`
3. Update playbook executor to validate capabilities against context
4. Add capability annotations to existing playbook YAMLs

### Phase 4: Graceful Degradation

1. Add connectivity detection for each bridge (like `is_connector_connected()`)
2. In `_dispatch_tool()`, return informative errors when bridge unavailable
3. Agent system prompts should instruct agents to work with available data when tools fail
4. Add `get_available_capabilities()` function that checks runtime connectivity

## 10. Configuration

### Environment Variables

```bash
# Existing
CLAUDE_BIN=/usr/local/bin/claude
CLAUDE_MCP_CONFIG=~/.claude/mcp_config.json
M365_BRIDGE_MODEL=sonnet
M365_BRIDGE_TIMEOUT_SECONDS=90

# New (same pattern)
ATLASSIAN_BRIDGE_MODEL=sonnet
ATLASSIAN_BRIDGE_TIMEOUT_SECONDS=90
BRIDGE_ENABLED=true                  # Master switch for all CLI bridges
M365_EMAIL_BRIDGE_ENABLED=true       # Per-bridge enable flags
M365_TEAMS_BRIDGE_ENABLED=true
ATLASSIAN_BRIDGE_ENABLED=true
```

### MCP Config Requirements

The Claude CLI MCP config must include both connectors:

```json
{
  "mcpServers": {
    "Microsoft 365": {
      "type": "url",
      "url": "https://mcp.anthropic.com/microsoft-365"
    },
    "Atlassian": {
      "type": "url",
      "url": "https://mcp.anthropic.com/atlassian"
    }
  }
}
```

## 11. Cost and Performance Considerations

### Bridge Call Costs

Each CLI bridge invocation:
- **Latency**: 5-15 seconds (Claude CLI startup + API call + response parsing)
- **API cost**: 1 Claude API call per bridge invocation (Sonnet tier by default)
- **Subprocess overhead**: Spawns `claude` process, initializes MCP connectors

### Mitigation Strategies

1. **Lazy initialization**: Don't check connector availability until first use
2. **Connection caching**: `is_connector_connected()` result cached per session
3. **Parallel bridge calls**: When an agent needs email + Teams data, spawn bridges concurrently
4. **Model tier selection**: Use Haiku for simple lookups, Sonnet for complex queries
5. **Result caching**: Cache bridge results for repeated queries within a session (5-minute TTL)
6. **Timeout tuning**: Per-bridge timeout settings to avoid blocking agent execution

### Expected Impact on Agent Execution Time

| Agent | Current (~seconds) | With Bridges (~seconds) | Notes |
|-------|-------------------|------------------------|-------|
| `daily_briefing` | 15-30 | 45-90 | Parallel bridge calls reduce wall time |
| `meeting_prep` | 10-20 | 30-60 | Email + Confluence bridges |
| `incident_summarizer` | 10-20 | 25-45 | Jira bridge |

## 12. Security Considerations

1. **Input sanitization**: Extend `_sanitize_for_prompt()` pattern to all bridges (already proven in M365 calendar bridge)
2. **Prompt injection**: User-supplied queries are wrapped in XML tags in bridge prompts (existing pattern)
3. **Credential isolation**: MCP connectors handle their own auth — bridges never see tokens
4. **Output validation**: All bridge responses are parsed and validated before returning to agents
5. **Subprocess isolation**: Bridge calls run in separate processes with timeout limits

## 13. Testing Strategy

1. **Unit tests**: Mock `subprocess.run` to test bridge parsing (existing pattern from `test_claude_m365_bridge.py`)
2. **Integration tests**: Test capability registry validation with new capabilities
3. **Agent tests**: Verify agents get correct tool schemas when new capabilities are declared
4. **Playbook tests**: Verify capability requirement checking in playbook executor
5. **No live API tests**: All external connector tests use mocked responses

## 14. Open Questions

1. **Bridge consolidation**: Should all M365 bridges live in one class (like the current `ClaudeM365Bridge`) or stay separate? Single class reduces subprocess overhead but increases complexity.

2. **Bi-directional sync**: Should `calendar_read` and `m365_calendar_read` merge, or remain separate? The unified calendar system already routes through both providers. Having separate capabilities gives agents explicit control but adds complexity.

3. **Write capability rollout**: How cautious should we be about Jira/Confluence write capabilities? Start read-only and add writes in a later phase?

4. **Playbook vs Agent execution preference**: When both paths are available, which should be preferred? Playbooks are faster (direct MCP access) but less flexible. Agent loops can adapt and iterate.

5. **Cost governance**: Should there be a per-agent or per-session budget for bridge calls to prevent runaway costs from agent loops?
