# Agent System

## Overview

Agents in Chief of Staff (Jarvis) are expert specialists that each run their own Claude tool-use loop. Each agent is configured via a YAML file that defines its identity, system prompt, and a set of **capabilities** -- named permissions that map to specific MCP tool schemas. When an agent is invoked, it receives an instruction, calls Claude with its system prompt and capability-gated tools, executes tool calls in a loop, and returns a final text response.

This architecture means:

- **Agents are composable.** Each agent has a narrow focus and well-defined tool access.
- **Tool access is controlled.** An agent can only use tools granted by its declared capabilities. A `meeting_prep` agent with `calendar_read` cannot write to the calendar.
- **Agents are declarative.** Adding a new agent requires only a YAML file -- no Python code changes.
- **Agents are isolated.** Each agent runs its own conversation with Claude, separate from the MCP server's main interaction.

---

## How Agents Work

### Lifecycle

1. **Configuration** -- The agent's YAML config is loaded by `AgentRegistry` from `agent_configs/`. Capabilities are validated against the canonical registry.

2. **Instantiation** -- `BaseExpertAgent` is constructed with the config and injected store dependencies (memory, documents, calendar, reminders, mail, notifications).

3. **Tool Resolution** -- `get_tools_for_capabilities()` maps the agent's declared capabilities to concrete tool schemas. Only tools matching declared capabilities are included.

4. **Execution Loop** -- The agent sends the user's instruction plus its system prompt to Claude. If Claude responds with `stop_reason == "tool_use"`, the agent executes each tool call locally, appends the results to the conversation, and loops. This continues until Claude produces a text response or the loop limit is reached.

5. **Termination** -- The agent returns the final text response. If `MAX_TOOL_ROUNDS` (25) is hit without a text response, the agent returns an error message.

### Execution Flow

```
User instruction
       |
       v
BaseExpertAgent.execute(task)
       |
       v
  [Round 1..25]
       |
       +---> Claude API call (system_prompt + messages + tools)
       |           |
       |           v
       |     stop_reason == "tool_use"?
       |        YES -> execute tool calls -> append results -> next round
       |        NO  -> extract text response -> return
       |
       v
  "Agent reached maximum tool rounds" (if loop exhausted)
```

### Key Constants

| Constant | Value | Location | Purpose |
|----------|-------|----------|---------|
| `MAX_TOOL_ROUNDS` | 25 | `config.py` | Maximum tool-use loop iterations per agent execution |
| `AGENT_TIMEOUT_SECONDS` | 60 | `config.py` | Time bound for agent execution |
| `DEFAULT_MODEL` | `claude-sonnet-4-5-20250929` | `config.py` | Claude model used for agent API calls |

---

## Agent Config Format

Agent configs are YAML files stored in `agent_configs/`. Each file defines one agent.

### Schema

```yaml
name: my_agent                          # Required. Lowercase alphanumeric, underscores, hyphens.
                                        # Must match: ^[a-z0-9][a-z0-9_-]*$
description: One-line summary of what   # Required. Human-readable description.
  this agent does
system_prompt: |                        # Required. Multi-line system prompt sent to Claude.
  You are a specialist in...            # Defines the agent's persona, process, and output format.
capabilities:                           # Required. List of capability names from the registry.
  - memory_read                         # Controls which tools the agent can access.
  - calendar_read
temperature: 0.3                        # Optional. Default: 0.3. Controls response randomness.
max_tokens: 4096                        # Optional. Default: 4096. Max response tokens per API call.
created_by: chief_of_staff              # Optional. Set automatically for dynamically created agents.
created_at: "2026-01-15T10:30:00"       # Optional. ISO timestamp of creation.
```

### Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | -- | Unique identifier. Must match `^[a-z0-9][a-z0-9_-]*$`. Used as the YAML filename. |
| `description` | string | Yes | `""` | One-line summary shown when listing agents. |
| `system_prompt` | string | Yes | `""` | Full system prompt defining the agent's behavior, process, and output format. |
| `capabilities` | list[string] | Yes | `[]` | Capabilities from the registry that determine tool access. |
| `temperature` | float | No | `0.3` | Claude temperature parameter. Lower = more deterministic. |
| `max_tokens` | int | No | `4096` | Maximum tokens in Claude's response per API call. |
| `created_by` | string | No | `None` | Creator identifier. Set to `"chief_of_staff"` for factory-created agents. |
| `created_at` | string | No | `None` | ISO 8601 timestamp of when the agent was created. |

### Example Config

```yaml
name: weekly_planner
description: Runs a priority-focused weekly planning session by pulling context
  from calendar, email, Teams chats, and memory.
system_prompt: |
  You are a weekly planning specialist. Your job is to help the user run a
  focused weekly planning session...

  ## Your Process
  1. Gather Context -- Pull from calendar, email, Teams, memory.
  2. Synthesize Across Sources -- Connect related items.
  3. Prioritize -- Rank by impact and urgency.

  ## Output Format
  ### Top Priorities (3-5 items)
  ...
capabilities:
  - memory_read
  - document_search
  - calendar_read
  - reminders_read
  - mail_read
temperature: 0.3
max_tokens: 4096
```

---

## Capabilities Reference

Capabilities are named permissions defined in `capabilities/registry.py`. Each capability maps to one or more tool schemas. When an agent declares a capability, it gains access to all tools in that capability's `tool_names` list.

### Implemented Capabilities

These capabilities have runtime tool mappings and grant actual tool access to agents.

| Capability | Description | Tools Granted |
|------------|-------------|---------------|
| `memory_read` | Read from shared memory (facts, locations, personal context) | `query_memory` |
| `memory_write` | Write facts to shared memory | `store_memory` |
| `document_search` | Search ingested documents semantically | `search_documents` |
| `calendar_read` | Read and search calendar events | `get_calendar_events`, `search_calendar_events` |
| `reminders_read` | Read and search reminders | `list_reminders`, `search_reminders` |
| `reminders_write` | Create and complete reminders | `create_reminder`, `complete_reminder` |
| `notifications` | Send user-facing macOS notifications | `send_notification` |
| `mail_read` | Read and search mailboxes and messages | `get_mail_messages`, `get_mail_message`, `search_mail`, `get_unread_count` |
| `mail_write` | Send and update email state | `send_email`, `mark_mail_read`, `mark_mail_flagged`, `move_mail_message` |
| `decision_read` | Search and list tracked decisions | `search_decisions`, `list_pending_decisions` |
| `decision_write` | Log, update, and delete tracked decisions | `create_decision`, `update_decision`, `delete_decision` |
| `delegation_read` | List delegation status and overdue items | `list_delegations`, `check_overdue_delegations` |
| `delegation_write` | Create, update, and delete delegations | `create_delegation`, `update_delegation`, `delete_delegation` |
| `alerts_read` | Run and inspect proactive alert checks | `check_alerts`, `list_alert_rules` |
| `alerts_write` | Create and dismiss alert rules | `create_alert_rule`, `dismiss_alert` |
| `scheduling` | Find available calendar slots and analyze group availability | `find_my_open_slots`, `find_group_availability` |
| `agent_memory_read` | Read agent-specific memories | `get_agent_memory` |
| `agent_memory_write` | Clear agent-specific memories | `clear_agent_memory` |
| `channel_read` | Read unified inbound events across channels | `list_inbound_events`, `get_event_summary` |
| `proactive_read` | Read and dismiss proactive suggestions | `get_proactive_suggestions`, `dismiss_suggestion` |
| `webhook_read` | List and inspect webhook events | `list_webhook_events`, `get_webhook_event` |
| `webhook_write` | Process and update webhook event status | `process_webhook_event` |
| `scheduler_read` | List scheduled tasks and view scheduler status | `list_scheduled_tasks`, `get_scheduler_status` |
| `scheduler_write` | Create, update, delete, and run scheduled tasks | `create_scheduled_task`, `update_scheduled_task`, `delete_scheduled_task`, `run_scheduled_task` |
| `skill_read` | List skill suggestions from pattern analysis | `list_skill_suggestions` |
| `skill_write` | Record tool usage, analyze patterns, and auto-create skills | `record_tool_usage`, `analyze_skill_patterns`, `auto_create_skill` |

### Legacy Capabilities

These capabilities are accepted in agent configs for compatibility but have no runtime tool mappings. Agents declaring them will not receive any additional tools. They exist to support agent configs that reference workflow-level concepts not yet backed by local tools.

| Capability | Description |
|------------|-------------|
| `web_search` | Web lookup (no local runtime tool mapping) |
| `code_analysis` | Static code analysis workflows |
| `writing` | Long-form writing assistance |
| `editing` | Editing-focused writing workflows |
| `data_analysis` | Analytical workflows |
| `planning` | Planning workflows |
| `file_operations` | Local file manipulation |
| `code_execution` | Code execution workflows |

### Capability Validation

When an agent config is saved or loaded, its capabilities are validated:

- Unknown capability names raise a `ValueError` with the list of valid names.
- Duplicates are removed (first-seen order preserved).
- Empty or whitespace-only entries are skipped.

Validation happens in `validate_capabilities()` in `capabilities/registry.py`.

---

## Built-in Agents

The following agents ship with Chief of Staff in the `agent_configs/` directory. They are grouped by function.

### Planning and Briefing

| Agent | Description | Capabilities |
|-------|-------------|--------------|
| `daily_briefing` | Generates a prioritized daily briefing from calendar, email, Teams, and memory | `memory_read`, `memory_write`, `document_search`, `calendar_read`, `reminders_read`, `mail_read` |
| `weekly_planner` | Runs a priority-focused weekly planning session | `memory_read`, `document_search`, `calendar_read`, `reminders_read`, `mail_read` |
| `meeting_prep` | Prepares talking points, agendas, and briefing notes for meetings by gathering context from emails, calendar, Teams, documents, decisions, delegations, and memory | `memory_read`, `document_search`, `calendar_read`, `reminders_read`, `mail_read`, `decision_read`, `delegation_read` |
| `meeting_debrief` | Captures post-meeting outcomes -- decisions, action items, delegations -- and stores them in tracking systems for future meeting prep | `memory_read`, `memory_write`, `decision_write`, `delegation_write`, `calendar_read` |
| `agenda_manager` | Creates and updates meeting agendas, publishes to Confluence | `memory_read`, `memory_write`, `document_search` |
| `scheduler` | Finds available meeting times by analyzing calendar events | `calendar_read` |

### Project Management

| Agent | Description | Capabilities |
|-------|-------------|--------------|
| `project_manager` | Tracks active projects, surfaces blockers, drives accountability, maps stakeholders with RACI classification | `memory_read`, `memory_write`, `document_search`, `mail_read`, `delegation_write`, `reminders_read` |
| `research_and_strategy` | Conducts deep research, drives product strategy, evaluates technical approaches, and coordinates agent capabilities | `memory_read`, `memory_write`, `document_search`, `mail_read`, `decision_read`, `decision_write`, `delegation_read`, `calendar_read`, `agent_memory_read`, `agent_memory_write` |
| `project_planner` | Plans and structures projects from inception through execution | `memory_read`, `memory_write`, `document_search` |
| `backlog_manager` | Captures, organizes, and prioritizes a persistent backlog of work items | `memory_read`, `memory_write`, `document_search` |
| `okr_tracker` | Tracks ISP OKR progress from Excel spreadsheets | `memory_read`, `memory_write`, `document_search` |

### Tracking and Accountability

| Agent | Description | Capabilities |
|-------|-------------|--------------|
| `decision_tracker` | Captures, tracks, and follows up on decisions | `memory_read`, `memory_write`, `document_search` |
| `delegation_tracker` | Tracks tasks delegated to others, monitors completion, flags overdue items | `memory_read`, `memory_write`, `document_search` |
| `action_item_tracker` | Consolidates action items across Confluence, email, Teams, and Jira | `memory_read`, `memory_write`, `document_search`, `reminders_read`, `reminders_write` |
| `proactive_alerts` | Monitors for conditions needing attention and generates proactive alerts | `memory_read`, `memory_write`, `document_search` |

### Communications and Triage

| Agent | Description | Capabilities |
|-------|-------------|--------------|
| `communications` | Handles outbound email drafts and iMessage notifications | `memory_read`, `memory_write`, `mail_read`, `mail_write`, `notifications` |
| `inbox_triage` | Classifies incoming iMessage commands and routes to appropriate agents | `memory_read`, `memory_write`, `mail_read` |
| `approval_triage` | Consolidates pending approvals across Jira, Workday, Okta, and email | `memory_read`, `document_search` |
| `incident_summarizer` | Consolidates active incidents and trending patterns | `memory_read`, `memory_write`, `document_search` |

### Code and Architecture Quality

| Agent | Description | Capabilities |
|-------|-------------|--------------|
| `security_auditor` | Audits for security vulnerabilities, data protection, and compliance risks | `memory_read`, `memory_write`, `document_search` |
| `code_quality_reviewer` | Reviews Python code for quality, consistency, and maintainability | `memory_read`, `memory_write`, `document_search` |
| `workflow_optimizer` | Analyzes workflows for efficiency and simplification opportunities | `memory_read`, `memory_write`, `document_search` |

### Project Review Board

A specialized set of agents that conduct structured reviews from different perspectives, coordinated by a board chair that synthesizes findings.

| Agent | Description | Capabilities |
|-------|-------------|--------------|
| `project_review_board` | Synthesizes specialist review outputs into a graded assessment and action plan | `memory_read`, `memory_write`, `document_search` |
| `project_review_architecture` | Reviews architecture quality, modularity, maintainability risks, configuration/environment management, scalability, and code patterns | `memory_read`, `document_search` |
| `project_review_reliability` | Reviews test coverage, failure handling, production readiness, and end-user/black-box testing perspective | `memory_read`, `document_search` |
| `project_review_security` | Reviews security posture, data protection, and abuse risk | `memory_read`, `document_search` |
| `project_review_product` | Reviews user value, workflow fit, and product-level gaps | `memory_read`, `document_search` |
| `project_review_delivery` | Reviews delivery health, maintainability, and execution velocity | `memory_read`, `document_search` |

### Document and Output Generation

| Agent | Description | Capabilities |
|-------|-------------|--------------|
| `document_librarian` | Organizes Jarvis-created documents into a structured folder hierarchy | `memory_read`, `memory_write`, `document_search` |
| `report_builder` | Converts markdown output into polished HTML/PDF reports with data visualization (charts, dashboards, matrices, timelines via matplotlib, plotly, Mermaid) | `memory_read`, `memory_write`, `document_search` |

### Security Metrics

A coordinator agent with source-specific collection agents for security telemetry.

| Agent | Description | Capabilities |
|-------|-------------|--------------|
| `security_metrics` | Coordinator that dispatches collection and synthesizes a unified security posture report | `memory_read`, `memory_write`, `document_search` |
| `endpoint_security_metrics` | Analyzes endpoint detection/response (SentinelOne) and compliance/patching (Tanium) metrics | `memory_read`, `memory_write`, `document_search`, `webhook_read` |
| `email_and_awareness_metrics` | Analyzes email threat protection (Mimecast) and phishing awareness training (KnowBe4) metrics | `memory_read`, `memory_write`, `document_search`, `webhook_read` |
| `github_security` | Collects Dependabot, CodeQL, SonarCloud, and Secret Scanning alerts | `memory_read`, `memory_write` |

---

## Creating a New Agent

### Step-by-Step

1. **Choose a name.** Must be lowercase alphanumeric with underscores or hyphens, starting with a letter or digit. Examples: `budget_tracker`, `onboarding-guide`, `sprint_reporter`.

2. **Select capabilities.** Pick from the [Capabilities Reference](#capabilities-reference) above. Only grant what the agent needs -- principle of least privilege applies. An agent that only reads calendar data should have `calendar_read`, not `calendar_read` and `calendar_write`.

3. **Write the system prompt.** This is the most important part. A good system prompt includes:
   - **Role definition** -- Who the agent is and what it does.
   - **Process** -- Step-by-step instructions for how it should approach tasks.
   - **Output format** -- Exactly how results should be structured.
   - **Guidelines** -- Guardrails and principles for behavior.

4. **Set parameters.** Choose `temperature` (lower for deterministic tasks like classification, higher for creative tasks) and `max_tokens` (increase for agents that produce long output).

5. **Save the YAML file.** Save to `agent_configs/<name>.yaml`. The filename must match the `name` field.

6. **Verify.** The agent is immediately available. No code changes or restarts needed. The `AgentRegistry` will pick it up on the next `list_agents` or `get_agent` call.

### Example: Creating a Sprint Reporter

```yaml
name: sprint_reporter
description: Generates end-of-sprint reports summarizing completed work, carry-over
  items, velocity metrics, and blockers for the next sprint.
system_prompt: |
  You are a sprint reporting specialist. At the end of each sprint, you generate
  a clear, data-driven report for stakeholders.

  ## Process
  1. Query memory for the current sprint's goals and committed items.
  2. Search documents and email for status updates and completion signals.
  3. Cross-reference with calendar for sprint ceremonies and their outcomes.

  ## Output Format
  ### Sprint Summary
  - Sprint goal and whether it was met
  - Completed items with links
  - Carry-over items with reasons

  ### Metrics
  - Velocity (story points completed vs committed)
  - Completion rate

  ### Next Sprint
  - Recommended focus areas
  - Known blockers to address
capabilities:
  - memory_read
  - document_search
  - calendar_read
temperature: 0.3
max_tokens: 4096
```

---

## Dynamic Agent Creation

The `AgentFactory` class in `agents/factory.py` uses Claude to generate new agent configs on the fly. This is used when a user requests an agent through the `create_agent` MCP tool and provides a natural-language description rather than a full YAML config.

### How It Works

1. The user provides a description like "I need an agent for tracking vendor contracts and renewal dates."

2. `AgentFactory.create_agent(description)` sends this to Claude with a specialized system prompt (`AGENT_CREATION_PROMPT`) that includes the full list of available capabilities.

3. Claude returns a JSON object with `name`, `description`, `system_prompt`, `capabilities`, and `temperature`.

4. The factory validates the capabilities, constructs an `AgentConfig`, and saves it via `AgentRegistry.save_agent()`.

5. The new agent is immediately available for use. The config is persisted as a YAML file in `agent_configs/`.

### When to Use Dynamic vs Manual Creation

| Scenario | Approach |
|----------|----------|
| Quick prototype or one-off need | Dynamic (`create_agent` tool) |
| Production agent with carefully tuned prompt | Manual YAML |
| Agent that requires specific output formats | Manual YAML |
| Exploring what agent would fit a need | Dynamic, then refine the YAML |

Dynamic agents have `created_by: chief_of_staff` and a `created_at` timestamp in their config, making them easy to identify and refine later.

### Auto-Suggested Agents (Self-Authoring Skills)

In addition to on-demand dynamic creation, agents can be **auto-suggested** based on tool usage patterns. The self-authoring skills system (`skills/pattern_detector.py`) tracks how MCP tools are used over time, clusters repeated patterns using Jaccard similarity, and generates suggestions when a pattern exceeds configured confidence and frequency thresholds (`SKILL_SUGGESTION_THRESHOLD` and `SKILL_MIN_OCCURRENCES` in `config.py`).

Suggestions are stored in the `skill_suggestions` SQLite table and can be reviewed via the `list_skill_suggestions` MCP tool. Accepting a suggestion with `auto_create_skill` delegates to the existing `AgentFactory` to generate a YAML config, making the new agent immediately available -- no manual YAML authoring required.

See [Architecture: Self-Authoring Skills](architecture.md#6-self-authoring-skills) for the full system flow.

---

## Agent Execution Details

### The Tool-Use Loop (from `agents/base.py`)

The core execution logic in `BaseExpertAgent.execute()`:

```python
async def execute(self, task: str) -> str:
    messages = [{"role": "user", "content": task}]
    tools = self.get_tools()

    for _round in range(MAX_TOOL_ROUNDS):
        response = await self._call_api(messages, tools)

        if response.stop_reason == "tool_use":
            # Append assistant's tool-use content
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool call and collect results
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = self._handle_tool_call(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

            messages.append({"role": "user", "content": tool_results})
            continue

        # Extract final text response
        for block in response.content:
            if block.type == "text":
                return block.text

        return ""

    return "[Agent reached maximum tool rounds without producing a final response]"
```

### API Call Details

Each API call is wrapped with `@retry_api_call` which provides exponential backoff with up to 3 retries. The call parameters:

- **model**: `config.DEFAULT_MODEL` (currently `claude-sonnet-4-5-20250929`)
- **max_tokens**: From the agent's config (default 4096)
- **system**: The agent's `system_prompt`
- **tools**: Only included if the agent has any (capabilities with no runtime tools result in an empty list, and `tools` is omitted from the API call)

### Tool Dispatch

`_handle_tool_call()` routes tool names to handler methods. Each handler:

1. Extracts parameters from `tool_input`.
2. Calls the appropriate store method (memory, calendar, reminders, mail, etc.).
3. Returns a result dict that gets JSON-serialized back to Claude.

If a tool name is unrecognized, the handler returns `{"error": "Unknown tool: <name>"}`.

### Error Handling

- **API errors**: Retried up to 3 times with exponential backoff via `retry_api_call`.
- **Platform-unavailable tools**: Calendar, reminders, notifications, and mail handlers check for `None` stores and return `{"error": "... not available (macOS only)"}`.
- **Loop exhaustion**: Returns a clear error message: `"[Agent reached maximum tool rounds without producing a final response]"`.
- **Empty response**: If Claude returns no text blocks, the agent returns an empty string.

### Dependency Injection

`BaseExpertAgent` receives all its dependencies through the constructor:

| Parameter | Type | Required | Purpose |
|-----------|------|----------|---------|
| `config` | `AgentConfig` | Yes | Agent configuration |
| `memory_store` | `MemoryStore` | Yes | SQLite-backed fact/decision/delegation storage |
| `document_store` | `DocumentStore` | Yes | ChromaDB-backed semantic search |
| `client` | `AsyncAnthropic` | No | Anthropic API client (auto-created if not provided) |
| `calendar_store` | CalendarStore | No | Unified calendar (macOS only) |
| `reminder_store` | ReminderStore | No | Apple Reminders (macOS only) |
| `notifier` | Notifier | No | macOS notifications (macOS only) |
| `mail_store` | MailStore | No | Apple Mail (macOS only) |

This pattern makes agents fully testable -- tests inject mock stores without hitting real APIs or platform services.
