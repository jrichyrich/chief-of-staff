# MCP Tools Reference

Complete reference for all MCP tools and resources exposed by the Chief of Staff (Jarvis) server.

**Total: 105 tools across 24 modules, plus 3 MCP resources.**

---

## Table of Contents

1. [Memory Tools](#memory-tools) (7 tools)
2. [Document Tools](#document-tools) (2 tools)
3. [Agent Tools](#agent-tools) (7 tools)
4. [Lifecycle Tools](#lifecycle-tools) (14 tools)
5. [Calendar Tools](#calendar-tools) (8 tools)
6. [Reminder Tools](#reminder-tools) (6 tools)
7. [Mail Tools](#mail-tools) (10 tools)
8. [iMessage Tools](#imessage-tools) (7 tools)
9. [OKR Tools](#okr-tools) (2 tools)
10. [Webhook Tools](#webhook-tools) (3 tools)
11. [Skill Tools](#skill-tools) (5 tools)
12. [Scheduler Tools](#scheduler-tools) (6 tools)
13. [Channel Tools](#channel-tools) (2 tools)
14. [Proactive Tools](#proactive-tools) (2 tools)
15. [Identity Tools](#identity-tools) (4 tools)
16. [Event Rule Tools](#event-rule-tools) (5 tools)
17. [Session Tools](#session-tools) (3 tools)
18. [Enrichment Tools](#enrichment-tools) (1 tool)
19. [Teams Browser Tools](#teams-browser-tools) (5 tools)
20. [Channel Routing Tools](#channel-routing-tools) (1 tool)
21. [Session Brain Tools](#session-brain-tools) (2 tools)
22. [Playbook Tools](#playbook-tools) (2 tools)
23. [Resources](#resources) (3 resources)

---

## Memory Tools

**Module:** `mcp_tools/memory_tools.py`

Tools for storing, querying, and managing facts and locations in long-term memory. Backed by SQLite (`data/memory.db`).

### store_fact

Store a fact about the user in long-term memory. Overwrites if category+key already exists.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `category` | `str` | Yes | One of `personal`, `preference`, `work`, `relationship`, `backlog` |
| `key` | `str` | Yes | Short label for the fact (e.g. `name`, `favorite_color`, `job_title`) |
| `value` | `str` | Yes | The fact value |
| `confidence` | `float` | No | Confidence score from 0.0 to 1.0 (default: 1.0) |
| `pinned` | `bool` | No | If `True`, this fact never decays over time (default: `False`) |

**Returns:** JSON with `status`, `category`, `key`, `value` on success; `error` on failure.

### delete_fact

Delete a fact from long-term memory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `category` | `str` | Yes | The fact category (`personal`, `preference`, `work`, `relationship`, `backlog`) |
| `key` | `str` | Yes | The fact key to delete |

**Returns:** JSON with `status: "deleted"` or `status: "not_found"`.

### query_memory

Search stored facts about the user. Returns matching facts ranked by relevance using temporal decay scoring (recent facts score higher). Uses hybrid FTS5 + vector search when no category filter is specified.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | Yes | Search term to match against fact keys and values |
| `category` | `str` | No | Filter to a specific category. Leave empty to search all. |
| `diverse` | `bool` | No | Apply MMR re-ranking to reduce redundant results (default: `True`) |
| `half_life_days` | `int` | No | Number of days for temporal decay half-life (default: 90). Lower = faster decay of old facts. |

**Returns:** JSON with `results` array of matching facts (category, key, value, confidence, relevance_score, updated_at).

### store_location

Store a named location in memory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | Location name (e.g. `home`, `office`, `favorite_restaurant`) |
| `address` | `str` | No | Street address |
| `notes` | `str` | No | Additional notes about this location |
| `latitude` | `float` | No | GPS latitude (default: 0.0 if unknown) |
| `longitude` | `float` | No | GPS longitude (default: 0.0 if unknown) |

**Returns:** JSON with `status: "stored"`, `name`, `address`.

### list_locations

List all stored locations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `results` array of locations (name, address, notes).

### checkpoint_session

Save important session context to persistent memory before context compaction. Call this when important decisions, facts, or context have emerged during a conversation that should persist across sessions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `summary` | `str` | Yes | Concise summary of the current session's key context and outcomes |
| `key_facts` | `str` | No | Comma-separated key facts to persist as individual memory facts |
| `session_id` | `str` | No | Optional session identifier for organizing context entries |
| `auto_checkpoint` | `bool` | No | If `True`, marks this as an automatic (system-triggered) checkpoint (default: `False`) |

**Returns:** JSON with `status: "checkpoint_saved"`, `context_id`, `facts_stored` count, `enriched_facts` count.

### get_session_health

Return session activity metrics: tool call count, session start time, last checkpoint. Use this to decide whether a `checkpoint_session` call is needed before context compaction.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with session health metrics including `tool_call_count`, `minutes_since_checkpoint`, and `checkpoint_recommended` flag.

---

## Document Tools

**Module:** `mcp_tools/document_tools.py`

Semantic search and ingestion over documents. Backed by ChromaDB with all-MiniLM-L6-v2 embeddings.

### search_documents

Semantic search over ingested documents. Returns the most relevant chunks.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | Yes | Natural language search query |
| `top_k` | `int` | No | Number of results to return (default: 5) |

**Returns:** JSON with `results` array of matching document chunks.

### ingest_documents

Ingest documents from a file or directory into the knowledge base for semantic search. Supports `.txt`, `.md`, `.py`, `.json`, `.yaml` files.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | `str` | Yes | Absolute path to a file or directory to ingest |

**Returns:** Summary string of ingested documents. Access is restricted to paths within the user's home directory.

---

## Agent Tools

**Module:** `mcp_tools/agent_tools.py`

Tools for managing expert agent configurations stored as YAML files in `agent_configs/`, plus shared memory for cross-agent collaboration.

### list_agents

List all available expert agent configurations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `results` array of agents (name, description, capabilities).

### get_agent

Get full details for a specific expert agent by name.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | The agent name to look up |

**Returns:** JSON with name, description, system_prompt, capabilities, temperature, max_tokens.

### create_agent

Create or update an expert agent configuration.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | Agent name (lowercase, no spaces -- e.g. `researcher`, `code_reviewer`) |
| `description` | `str` | Yes | What this agent specializes in |
| `system_prompt` | `str` | Yes | The system prompt that defines this agent's behavior |
| `capabilities` | `str` | No | Comma-separated list of capabilities (e.g. `web_search,memory_read,document_search`) |

**Returns:** JSON with `status: "created"`, `name`, `capabilities`.

### get_agent_memory

Retrieve persistent memories for an agent (insights, preferences, context retained across runs).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_name` | `str` | Yes | The agent whose memories to retrieve |
| `memory_type` | `str` | No | Filter by type (e.g. `insight`, `preference`, `context`) |

**Returns:** JSON with `agent_name`, `results` array of memories (key, value, memory_type, confidence).

### clear_agent_memory

Clear all persistent memories for an agent.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_name` | `str` | Yes | The agent whose memories to clear |

**Returns:** JSON with `agent_name`, `deleted_count`.

### store_shared_memory

Store a memory in a shared namespace for cross-agent collaboration.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `namespace` | `str` | Yes | The shared namespace (e.g. `research-team`, `onboarding`) |
| `memory_type` | `str` | Yes | Type of memory (`insight`, `preference`, `context`) |
| `key` | `str` | Yes | A short label for this memory |
| `value` | `str` | Yes | The memory content |
| `confidence` | `float` | No | Confidence score from 0.0 to 1.0 (default: 1.0) |

**Returns:** JSON with `status: "stored"`, `namespace`, `memory_type`, `key`, `value`, `confidence`.

### get_shared_memory

Retrieve shared memories from a namespace.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `namespace` | `str` | Yes | The shared namespace to query |
| `memory_type` | `str` | No | Filter by memory type (`insight`, `preference`, `context`) |

**Returns:** JSON with `namespace`, `results` array of memories (memory_type, key, value, confidence, updated_at).

---

## Lifecycle Tools

**Module:** `mcp_tools/lifecycle_tools.py`

Decision log, delegation tracking, and alert rule management. All backed by SQLite.

### Decision Tools

#### create_decision

Log a decision for tracking and follow-up.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `title` | `str` | Yes | Short title of the decision |
| `description` | `str` | No | Detailed description of what was decided |
| `context` | `str` | No | Background context or rationale |
| `decided_by` | `str` | No | Who made the decision |
| `owner` | `str` | No | Who is responsible for execution |
| `status` | `str` | No | Decision status (default: `pending_execution`) |
| `follow_up_date` | `str` | No | Date to follow up (`YYYY-MM-DD`) |
| `tags` | `str` | No | Comma-separated tags for categorization |
| `source` | `str` | No | Where the decision was made (e.g. meeting name, email) |

**Returns:** JSON with the created decision record.

#### search_decisions

Search decisions by text and/or filter by status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | No | Text to search in title, description, and tags |
| `status` | `str` | No | Filter by status (e.g. `pending_execution`, `executed`, `deferred`) |

**Returns:** JSON with matching decision records.

#### update_decision

Update a decision's status or add notes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `decision_id` | `int` | Yes | The ID of the decision to update |
| `status` | `str` | No | New status value |
| `notes` | `str` | No | Additional notes to append to the description |

**Returns:** JSON with the updated decision record.

#### list_pending_decisions

List all decisions with status `pending_execution`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with all pending decisions.

#### delete_decision

Delete a decision by ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `decision_id` | `int` | Yes | The ID of the decision to delete |

**Returns:** JSON with deletion status.

### Delegation Tools

#### create_delegation

Create a new delegation to track a task assigned to someone.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task` | `str` | Yes | Short description of the delegated task |
| `delegated_to` | `str` | Yes | Who the task is delegated to |
| `description` | `str` | No | Detailed description of expectations |
| `due_date` | `str` | No | Due date (`YYYY-MM-DD`) |
| `priority` | `str` | No | Priority level: `low`, `medium`, `high`, `critical` (default: `medium`) |
| `source` | `str` | No | Where the delegation originated |

**Returns:** JSON with the created delegation record.

#### list_delegations

List delegations with optional filters.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | `str` | No | Filter by status (`active`, `completed`, `cancelled`) |
| `delegated_to` | `str` | No | Filter by who the task is delegated to |

**Returns:** JSON with matching delegation records.

#### update_delegation

Update a delegation's status or add notes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `delegation_id` | `int` | Yes | The ID of the delegation to update |
| `status` | `str` | No | New status value (`active`, `completed`, `cancelled`) |
| `notes` | `str` | No | Additional notes |

**Returns:** JSON with the updated delegation record.

#### check_overdue_delegations

Return all active delegations that are past their due date.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with overdue delegation records.

#### delete_delegation

Delete a delegation by ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `delegation_id` | `int` | Yes | The ID of the delegation to delete |

**Returns:** JSON with deletion status.

### Alert Tools

#### create_alert_rule

Create or update an alert rule.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | Unique name for the alert rule |
| `alert_type` | `str` | Yes | Type of alert: `overdue_delegation`, `pending_decision`, `upcoming_deadline` |
| `description` | `str` | No | Human-readable description of what this alert checks |
| `condition` | `str` | No | Machine-readable condition expression |
| `enabled` | `bool` | No | Whether the rule is active (default: `True`) |

**Returns:** JSON with the created/updated alert rule.

#### list_alert_rules

List all alert rules.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `enabled_only` | `bool` | No | If `True`, only return enabled rules (default: `False`) |

**Returns:** JSON with alert rule records.

#### check_alerts

Run alert checks: overdue delegations, stale pending decisions (>7 days), and upcoming deadlines (within 3 days).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with triggered alert results.

#### dismiss_alert

Disable an alert rule so it no longer triggers.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `rule_id` | `int` | Yes | The ID of the alert rule to disable |

**Returns:** JSON with the updated alert rule.

---

## Calendar Tools

**Module:** `mcp_tools/calendar_tools.py`

Calendar operations across Apple Calendar and Microsoft 365 via the unified calendar system. All dates use ISO format.

### list_calendars

List calendars from available providers (Apple and optionally Microsoft 365).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `provider_preference` | `str` | No | `auto` \| `apple` \| `microsoft_365` \| `both` (default: `auto`) |
| `source_filter` | `str` | No | Source/provider text filter (e.g. `iCloud`, `Google`, `Exchange`) |

**Returns:** JSON with `results` array of calendars.

### get_calendar_events

Get events in a date range across configured providers.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` | `str` | Yes | Start date in ISO format (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`) |
| `end_date` | `str` | Yes | End date in ISO format |
| `calendar_name` | `str` | No | Calendar name to filter by |
| `provider_preference` | `str` | No | `auto` \| `apple` \| `microsoft_365` \| `both` (default: `auto`) |
| `source_filter` | `str` | No | Source/provider text filter |

**Returns:** JSON with `results` array of events.

### create_calendar_event

Create a new calendar event using routing policy.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `title` | `str` | Yes | Event title |
| `start_date` | `str` | Yes | Start date in ISO format |
| `end_date` | `str` | Yes | End date in ISO format |
| `calendar_name` | `str` | No | Calendar to create the event in (uses default if empty) |
| `location` | `str` | No | Event location |
| `notes` | `str` | No | Event notes/description |
| `is_all_day` | `bool` | No | Whether this is an all-day event (default: `False`) |
| `target_provider` | `str` | No | Explicit provider override (`apple` or `microsoft_365`) |
| `provider_preference` | `str` | No | Provider hint (default: `auto`) |

**Returns:** JSON with `status: "created"` and event details.

### update_calendar_event

Update an existing calendar event by UID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_uid` | `str` | Yes | The unique identifier of the event |
| `calendar_name` | `str` | No | Calendar the event belongs to (optional when ownership is known) |
| `title` | `str` | No | New event title |
| `start_date` | `str` | No | New start date in ISO format |
| `end_date` | `str` | No | New end date in ISO format |
| `location` | `str` | No | New event location |
| `notes` | `str` | No | New event notes |
| `target_provider` | `str` | No | Explicit provider override |
| `provider_preference` | `str` | No | Provider hint (default: `auto`) |

**Returns:** JSON with `status: "updated"` and event details.

### delete_calendar_event

Delete a calendar event by UID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_uid` | `str` | Yes | The unique identifier of the event |
| `calendar_name` | `str` | No | Calendar the event belongs to |
| `target_provider` | `str` | No | Explicit provider override |
| `provider_preference` | `str` | No | Provider hint (default: `auto`) |

**Returns:** JSON with deletion status.

### search_calendar_events

Search events by title text. Defaults to +/- 30 days if no dates provided.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | Yes | Text to search for in event titles |
| `start_date` | `str` | No | Start date in ISO format (defaults to 30 days ago) |
| `end_date` | `str` | No | End date in ISO format (defaults to 30 days from now) |
| `provider_preference` | `str` | No | `auto` \| `apple` \| `microsoft_365` \| `both` (default: `auto`) |
| `source_filter` | `str` | No | Source/provider text filter |

**Returns:** JSON with `results` array of matching events.

### find_my_open_slots

Find available time slots in your calendar within a date range. Analyzes calendar events to find open slots, treating soft blocks (Focus Time, Lunch, etc.) as available by default. Uses Mountain Time (America/Denver). Pulls from ALL configured calendar providers by default.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` | `str` | Yes | Start date (`YYYY-MM-DD` or ISO datetime) |
| `end_date` | `str` | Yes | End date (`YYYY-MM-DD` or ISO datetime) |
| `duration_minutes` | `int` | No | Minimum slot duration in minutes (default: 30) |
| `include_soft_blocks` | `bool` | No | Treat soft blocks as available (default: `True`) |
| `soft_keywords` | `str` | No | Comma-separated soft keywords (default: `focus,lunch,prep,hold,tentative`) |
| `calendar_name` | `str` | No | Optional calendar filter |
| `working_hours_start` | `str` | No | Working hours start time `HH:MM` (default: `08:00`) |
| `working_hours_end` | `str` | No | Working hours end time `HH:MM` (default: `18:00`) |
| `provider_preference` | `str` | No | `auto` \| `apple` \| `microsoft_365` \| `both` (default: `both`) |

**Returns:** JSON with `slots` array, `formatted_text` for sharing, and `count`.

### find_group_availability

Guidance tool that explains the workflow for finding group meeting times. Returns instructions for a two-step workflow combining M365 group availability with local soft-block logic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `participants` | `str` | Yes | Comma-separated email addresses |
| `start_date` | `str` | Yes | Start date (`YYYY-MM-DD`) |
| `end_date` | `str` | Yes | End date (`YYYY-MM-DD`) |
| `duration_minutes` | `int` | No | Meeting duration (default: 30) |
| `include_my_soft_blocks` | `bool` | No | Treat your soft blocks as available (default: `True`) |
| `max_suggestions` | `int` | No | Maximum number of suggestions to return (default: 5) |

**Returns:** JSON with workflow steps for the agent to follow (uses M365 find_meeting_availability + local find_my_open_slots).

---

## Reminder Tools

**Module:** `mcp_tools/reminder_tools.py`

Apple Reminders integration via PyObjC EventKit on macOS.

### list_reminder_lists

List all reminder lists available on this Mac.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `results` array of reminder lists.

### list_reminders

Get reminders, optionally filtered by list and completion status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `list_name` | `str` | No | Reminder list name to filter by |
| `completed` | `str` | No | `true` for completed only, `false` for incomplete only, empty for all |

**Returns:** JSON with `results` array of reminders.

### create_reminder

Create a new reminder.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `title` | `str` | Yes | Reminder title |
| `list_name` | `str` | No | Reminder list to add to (uses default if empty) |
| `due_date` | `str` | No | Due date in ISO format (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`) |
| `priority` | `int` | No | Priority level: `0`=none, `1`=high, `4`=medium, `9`=low (default: `0`) |
| `notes` | `str` | No | Additional notes |

**Returns:** JSON with `status: "created"` and reminder details.

### complete_reminder

Mark a reminder as completed.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `reminder_id` | `str` | Yes | The unique identifier of the reminder |

**Returns:** JSON with `status: "completed"` and reminder details.

### delete_reminder

Delete a reminder.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `reminder_id` | `str` | Yes | The unique identifier of the reminder |

**Returns:** JSON with deletion status.

### search_reminders

Search reminders by title text.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | Yes | Text to search for in reminder titles |
| `include_completed` | `bool` | No | Whether to include completed reminders (default: `False`) |

**Returns:** JSON with `results` array of matching reminders.

---

## Mail Tools

**Module:** `mcp_tools/mail_tools.py`

Apple Mail integration via AppleScript (osascript) and macOS notification center.

### send_notification

Send a macOS notification.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `title` | `str` | Yes | Notification title |
| `message` | `str` | Yes | Notification body text |
| `subtitle` | `str` | No | Subtitle displayed below the title |
| `sound` | `str` | No | Notification sound name (default: `default`, empty for silent) |

**Returns:** JSON with notification result.

### list_mailboxes

List all mailboxes across all Mail accounts with unread counts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `results` array of mailboxes.

### get_mail_messages

Get recent messages (headers only) from a mailbox. Returns subject, sender, date, read/flagged status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `mailbox` | `str` | No | Mailbox name to fetch from (default: `INBOX`) |
| `account` | `str` | No | Mail account name (uses first account if empty) |
| `limit` | `int` | No | Maximum number of messages to return (default: 25, max: 100) |

**Returns:** JSON with `results` array of message headers.

### get_mail_message

Get full message content by message ID, including body, to, and cc fields.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message_id` | `str` | Yes | The unique message ID |

**Returns:** JSON with full message content.

### search_mail

Search messages by subject or sender text in a mailbox.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | Yes | Text to search for in subject and sender fields |
| `mailbox` | `str` | No | Mailbox to search in (default: `INBOX`) |
| `account` | `str` | No | Mail account name (uses first account if empty) |
| `limit` | `int` | No | Maximum number of results (default: 25, max: 100) |

**Returns:** JSON with `results` array of matching messages.

### mark_mail_read

Mark a message as read or unread.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message_id` | `str` | Yes | The unique message ID |
| `read` | `str` | No | `true` to mark as read, `false` for unread (default: `true`) |

**Returns:** JSON with status result.

### mark_mail_flagged

Mark a message as flagged or unflagged.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message_id` | `str` | Yes | The unique message ID |
| `flagged` | `str` | No | `true` to flag, `false` to unflag (default: `true`) |

**Returns:** JSON with status result.

### move_mail_message

Move a message to a different mailbox.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message_id` | `str` | Yes | The unique message ID |
| `target_mailbox` | `str` | Yes | Destination mailbox name |
| `target_account` | `str` | No | Destination account name (uses first account if empty) |

**Returns:** JSON with move result.

### reply_to_email

Reply to an existing email within its thread. Sends a proper threaded reply that appears in the same conversation. Requires `confirm_send=True` after user explicitly confirms.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message_id` | `str` | Yes | The message ID of the email to reply to |
| `body` | `str` | Yes | Reply body text |
| `reply_all` | `bool` | No | If `True`, replies to all recipients; if `False`, replies only to sender (default: `False`) |
| `cc` | `str` | No | Comma-separated additional CC email addresses |
| `bcc` | `str` | No | Comma-separated BCC email addresses |
| `confirm_send` | `bool` | No | Must be `True` to actually send. `False` for preview only. (default: `False`) |

**Returns:** JSON with send result or preview.

### send_email

Compose and send an email. Requires `confirm_send=True` after user explicitly confirms they want to send.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `to` | `str` | Yes | Comma-separated recipient email addresses |
| `subject` | `str` | Yes | Email subject line |
| `body` | `str` | Yes | Email body text |
| `cc` | `str` | No | Comma-separated CC email addresses |
| `bcc` | `str` | No | Comma-separated BCC email addresses |
| `confirm_send` | `bool` | No | Must be `True` to actually send. `False` for preview only. (default: `False`) |

**Returns:** JSON with send result or preview.

---

## iMessage Tools

**Module:** `mcp_tools/imessage_tools.py`

iMessage integration via SQLite (chat.db) for reading and osascript for sending.

### get_imessages

Get recent iMessages from Messages.app chat history.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `minutes` | `int` | No | Lookback window in minutes (default: 60) |
| `limit` | `int` | No | Maximum number of messages to return (default: 25, max: 200) |
| `include_from_me` | `bool` | No | Include your own sent messages (default: `True`) |
| `conversation` | `str` | No | Sender/chat identifier filter |

**Returns:** JSON with `results` array of messages.

### list_imessage_threads

List active iMessage threads with persisted profile metadata.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `minutes` | `int` | No | Lookback window in minutes (default: 10080 / 7 days) |
| `limit` | `int` | No | Maximum number of threads to return (default: 50, max: 200) |

**Returns:** JSON with `results` array of threads.

### get_imessage_threads

Alias of `list_imessage_threads` for compatibility with prior plans/prompts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `minutes` | `int` | No | Lookback window in minutes (default: 10080 / 7 days) |
| `limit` | `int` | No | Maximum number of threads to return (default: 50, max: 200) |

**Returns:** JSON with `results` array of threads.

### get_imessage_thread_messages

Get messages for a specific iMessage thread by chat_identifier.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `chat_identifier` | `str` | Yes | iMessage thread identifier |
| `minutes` | `int` | No | Lookback window in minutes (default: 10080 / 7 days) |
| `limit` | `int` | No | Maximum number of messages to return (default: 50, max: 200) |
| `include_from_me` | `bool` | No | Include your own sent messages (default: `True`) |

**Returns:** JSON with `results` array of messages.

### get_thread_context

Get thread profile and recent messages for an iMessage conversation.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `chat_identifier` | `str` | Yes | iMessage thread identifier |
| `minutes` | `int` | No | Lookback window in minutes (default: 10080 / 7 days) |
| `limit` | `int` | No | Maximum number of recent messages to include (default: 20, max: 200) |

**Returns:** JSON with thread profile and recent messages.

### search_imessages

Search iMessages by text, sender, or chat identifier.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | Yes | Search text |
| `minutes` | `int` | No | Lookback window in minutes (default: 1440 / 1 day) |
| `limit` | `int` | No | Maximum number of messages to return (default: 25, max: 200) |
| `include_from_me` | `bool` | No | Include your own sent messages (default: `True`) |

**Returns:** JSON with `results` array of matching messages.

### send_imessage_reply

Send an iMessage reply. Requires `confirm_send=True` after explicit user confirmation.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `to` | `str` | No | Recipient handle (phone, email, or `self`). Optional when `chat_identifier` is provided. |
| `body` | `str` | No | Message content |
| `confirm_send` | `bool` | No | Must be `True` to actually send (default: `False`) |
| `chat_identifier` | `str` | No | Thread identifier for thread-aware reply |

**Returns:** JSON with send result.

---

## OKR Tools

**Module:** `mcp_tools/okr_tools.py`

OKR (Objectives and Key Results) tracking with Excel spreadsheet parsing and JSON-backed persistence.

### refresh_okr_data

Parse the ISP OKR Excel spreadsheet and store a fresh snapshot. Call this after downloading a new version of the spreadsheet.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_path` | `str` | No | Path to `.xlsx` file. Leave empty to use the default location (`data/okr/2026_ISP_OKR_Master_Final.xlsx`). |

**Returns:** JSON with `status: "refreshed"`, parsed summary (objective/key result/initiative counts).

### query_okr_status

Query the latest OKR data. Use after `refresh_okr_data` has been called.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | No | Free-text search across all OKR data |
| `okr_id` | `str` | No | Filter by OKR (e.g. `OKR 1`, `OKR 2`, `OKR 3`) |
| `team` | `str` | No | Filter by team (e.g. `IAM`, `SecOps`, `Product Security`, `Privacy & GRC`) |
| `status` | `str` | No | Filter by status (e.g. `On Track`, `At Risk`, `Blocked`, `Not Started`) |
| `blocked_only` | `bool` | No | If `True`, only return initiatives with blockers (default: `False`) |
| `summary_only` | `bool` | No | If `True`, return executive summary instead of detailed results (default: `False`) |

**Returns:** JSON with matching OKR data or executive summary.

---

## Webhook Tools

**Module:** `mcp_tools/webhook_tools.py`

Tools for managing inbound webhook events. Events are received by the HTTP webhook server (`webhook/server.py`) and queued in SQLite for processing.

### list_webhook_events

List webhook events with optional filters.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | `str` | No | Filter by status (`pending`, `processed`, `failed`). Leave empty for all. |
| `source` | `str` | No | Filter by event source. Leave empty for all. |
| `limit` | `int` | No | Maximum number of events to return (default: 50, max: 500) |

**Returns:** JSON with `results` array and `count`.

### get_webhook_event

Get full details of a webhook event including its payload.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_id` | `int` | Yes | The ID of the webhook event to retrieve |

**Returns:** JSON with full event details including parsed payload.

### process_webhook_event

Mark a webhook event as processed.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_id` | `int` | Yes | The ID of the webhook event to mark as processed |

**Returns:** JSON with `status: "processed"` and `processed_at` timestamp.

---

## Skill Tools

**Module:** `mcp_tools/skill_tools.py`

Tools for automatic pattern detection and agent creation. Tracks tool usage patterns and suggests new specialized agents when repeated patterns emerge.

### record_tool_usage

Record a tool usage pattern for future analysis.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tool_name` | `str` | Yes | Name of the tool being used |
| `query_pattern` | `str` | Yes | The query or pattern associated with this usage |

**Returns:** JSON with `status: "recorded"` and usage count.

### analyze_skill_patterns

Scan usage data and generate suggestions for new agents based on detected patterns.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `suggestions_created` count and `patterns` array of detected patterns with confidence scores.

### list_skill_suggestions

List auto-generated agent suggestions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | `str` | No | Filter by status (`pending`, `accepted`, `rejected`). Default: `pending`. |

**Returns:** JSON with `results` array of suggestions.

### auto_create_skill

Accept a suggestion and create a new agent configuration using AgentFactory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `suggestion_id` | `int` | Yes | The ID of the skill suggestion to accept |

**Returns:** JSON with `status: "created"` and agent details.

### auto_execute_skills

Auto-create agents from high-confidence pending skill suggestions. Uses the PatternDetector's `auto_create_threshold` (default: 0.9) to filter suggestions. Only runs if `SKILL_AUTO_EXECUTE_ENABLED` is `True`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `status`, `agents_created` count, and `agent_names` list.

---

## Scheduler Tools

**Module:** `mcp_tools/scheduler_tools.py`

Tools for managing the built-in task scheduler. Supports interval, cron, and one-time schedules with handler types for alert evaluation, backups, and custom commands. Supports delivery channel configuration for result delivery.

### create_scheduled_task

Create a new scheduled task.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | Unique name for the scheduled task |
| `schedule_type` | `str` | Yes | Schedule type: `interval`, `cron`, or `once` |
| `schedule_config` | `str` | Yes | JSON config (e.g. `{"minutes": 120}`, `{"expression": "0 8 * * 1-5"}`, `{"run_at": "..."}`) |
| `handler_type` | `str` | Yes | Handler: `alert_eval`, `backup`, `webhook_poll`, `custom` |
| `handler_config` | `str` | No | JSON config for the handler (e.g. command for custom handler) |
| `description` | `str` | No | Human-readable description |
| `enabled` | `bool` | No | Whether the task is active (default: `True`) |
| `delivery_channel` | `str` | No | Channel to deliver results: `email`, `imessage`, or `notification` |
| `delivery_config` | `str` | No | JSON config for delivery (e.g. `{"to": ["user@example.com"]}` for email, `{"recipient": "+15551234567"}` for imessage) |

**Returns:** JSON with `status: "created"` and task details.

### list_scheduled_tasks

List all scheduled tasks.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `enabled_only` | `bool` | No | If `True`, only return enabled tasks (default: `False`) |

**Returns:** JSON with `count` and `tasks` array including `delivery_channel`.

### update_scheduled_task

Update a scheduled task's configuration.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_id` | `int` | Yes | The ID of the task to update |
| `enabled` | `bool` | No | Enable or disable the task |
| `schedule_config` | `str` | No | New schedule configuration (JSON) |
| `handler_config` | `str` | No | New handler configuration (JSON) |
| `delivery_channel` | `str` | No | New delivery channel: `email`, `imessage`, `notification`, or `none` to clear |
| `delivery_config` | `str` | No | New delivery config (JSON) |

**Returns:** JSON with the updated task.

### delete_scheduled_task

Delete a scheduled task.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_id` | `int` | Yes | The ID of the task to delete |

**Returns:** JSON with deletion status.

### run_scheduled_task

Manually trigger a scheduled task immediately.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_id` | `int` | Yes | The ID of the task to run |

**Returns:** JSON with execution result.

### get_scheduler_status

Show scheduler overview with last run times and next due tasks.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with task summaries including `last_run_at`, `next_run_at`, `enabled` status, `overdue` flag.

---

## Channel Tools

**Module:** `mcp_tools/channel_tools.py`

Unified inbound event handling across iMessage, Mail, and Webhook sources.

### list_inbound_events

List recent inbound events from all channels.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `channel` | `str` | No | Filter by channel (`imessage`, `mail`, `webhook`). Leave empty for all. |
| `event_type` | `str` | No | Filter by event type (`message`, `email`, `webhook_event`). Leave empty for all. |
| `limit` | `int` | No | Maximum events per channel (default: 25, max: 100) |

**Returns:** JSON with `results` array of normalized events (channel, source, event_type, content_preview, received_at, raw_id, metadata) and `count`.

### get_event_summary

Get a summary of inbound event activity across all channels.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with per-channel event counts and `total`.

---

## Proactive Tools

**Module:** `mcp_tools/proactive_tools.py`

Proactive suggestion engine that surfaces actionable items without being asked.

### get_proactive_suggestions

Check for proactive suggestions (skill patterns, overdue delegations, stale decisions, upcoming deadlines, unprocessed webhook events).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `suggestions` array (category, priority, title, description, action, created_at) and `total`.

### dismiss_suggestion

Dismiss a proactive suggestion so it won't reappear.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `category` | `str` | Yes | The suggestion category (`skill`, `webhook`, `delegation`, `decision`, `deadline`) |
| `title` | `str` | Yes | The title of the suggestion to dismiss |

**Returns:** JSON with `status: "dismissed"`.

---

## Identity Tools

**Module:** `mcp_tools/identity_tools.py`

Cross-channel identity linking. Maps provider accounts (iMessage, email, Teams, etc.) to canonical person names for unified identity resolution.

### link_identity

Link a provider identity to a canonical person name.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `canonical_name` | `str` | Yes | The person's canonical name (e.g. `Jane Smith`) |
| `provider` | `str` | Yes | Provider name: `imessage`, `email`, `m365_teams`, `m365_email`, `slack`, `jira`, `confluence` |
| `provider_id` | `str` | Yes | Unique ID on the provider (phone number, email, user ID, etc.) |
| `display_name` | `str` | No | Display name on the provider |
| `email` | `str` | No | Email address associated with this identity |

**Returns:** JSON with the linked identity record.

### unlink_identity

Remove an identity link for a specific provider account.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `provider` | `str` | Yes | Provider name (e.g. `imessage`, `email`, `m365_teams`) |
| `provider_id` | `str` | Yes | Unique ID on the provider |

**Returns:** JSON with unlink result.

### get_identity

Get all linked accounts for a person by their canonical name.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `canonical_name` | `str` | Yes | The person's canonical name (e.g. `Jane Smith`) |

**Returns:** JSON with `canonical_name` and `identities` array of linked accounts.

### search_identity

Search identities by name, email, or provider ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | Yes | Search text to match against canonical_name, display_name, email, or provider_id |

**Returns:** JSON with `results` array of matching identities.

---

## Event Rule Tools

**Module:** `mcp_tools/event_rule_tools.py`

Event-driven agent dispatch. Manages rules that link webhook events to expert agent activation, enabling automated workflows.

### create_event_rule

Create an event rule that triggers an agent when a matching webhook event arrives.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | Unique name for this rule |
| `event_source` | `str` | Yes | Source to match (e.g. `github`, `jira`) |
| `event_type_pattern` | `str` | Yes | Glob pattern for event types (e.g. `alert.*`, `incident.critical`) |
| `agent_name` | `str` | Yes | Name of the expert agent to activate |
| `description` | `str` | No | Human-readable description of what this rule does |
| `agent_input_template` | `str` | No | Template for agent input with `$event_type`, `$source`, `$payload`, `$timestamp` vars |
| `delivery_channel` | `str` | No | Delivery channel for results (`email`, `imessage`, `notification`) |
| `delivery_config` | `str` | No | JSON config for the delivery channel |
| `enabled` | `bool` | No | Whether the rule is active (default: `True`) |
| `priority` | `int` | No | Priority for rule ordering (lower = higher priority, default: 100) |

**Returns:** JSON with the created event rule.

### update_event_rule

Update an existing event rule.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `rule_id` | `int` | Yes | The ID of the event rule to update |
| `name` | `str` | No | New name for the rule |
| `event_source` | `str` | No | New event source filter |
| `event_type_pattern` | `str` | No | New glob pattern for event types |
| `agent_name` | `str` | No | New agent to activate |
| `description` | `str` | No | New description |
| `agent_input_template` | `str` | No | New input template |
| `delivery_channel` | `str` | No | New delivery channel |
| `delivery_config` | `str` | No | New delivery config (JSON string) |
| `enabled` | `bool` | No | Whether the rule is active (default: `True`) |
| `priority` | `int` | No | New priority value (`-1` means no change) |

**Returns:** JSON with the updated event rule.

### delete_event_rule

Delete an event rule by ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `rule_id` | `int` | Yes | The ID of the event rule to delete |

**Returns:** JSON with deletion result.

### list_event_rules

List event rules.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `enabled_only` | `bool` | No | If `True`, only return enabled rules (default: `True`) |

**Returns:** JSON with `rules` array and `count`.

### process_webhook_event_with_agents

Manually trigger agent dispatch for a specific webhook event. Finds matching event rules and dispatches the event to the corresponding agents.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_id` | `int` | Yes | The ID of the webhook event to process |

**Returns:** JSON with `event_id`, `rules_matched`, `dispatches` array, and `event_status`.

---

## Session Tools

**Module:** `mcp_tools/session_tools.py`

Session lifecycle management. Tracks interaction context, estimates token usage, and provides structured flush/restore for persisting session data across context compaction.

### get_session_status

Return current session status: token estimate, interaction count, time since last checkpoint, and a preview of extracted items. Use this to decide whether a `flush_session_memory` call is needed.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `session_id`, `token_estimate`, `interaction_count`, `time_since_last_checkpoint`, `extracted_items_preview`, and `context_window_usage`.

### flush_session_memory

Persist structured session data to long-term memory. Extracts decisions, action items, and key facts from the current session and stores them as facts. Also creates a session checkpoint.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `priority` | `str` | No | What to flush: `all`, `decisions`, `action_items`, or `key_facts` (default: `all`) |

**Returns:** JSON with `status: "flushed"`, `session_id`, and flush details.

### restore_session

Restore context from a previous session checkpoint.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | `str` | Yes | The session ID to restore from |

**Returns:** JSON with `status: "restored"` and restored context.

---

## Enrichment Tools

**Module:** `mcp_tools/enrichment.py`

Contextual tool chaining — consolidated person profiles assembled from parallel data fetches across six sources. Much faster than calling each source tool individually.

### enrich_person

Get a consolidated profile for a person by fetching from identities, facts, delegations, decisions, recent iMessages, and recent emails in parallel. Empty sections are omitted from the response. If a data source is unavailable (e.g., no mail store configured), that section is silently skipped.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | Person's name to search for (canonical name or partial match) |
| `days_back` | `int` | No | How many days back to search communications (default: `7`) |

**Returns:** JSON object keyed by available data sections: `name` (always present), and any of `identities`, `facts`, `delegations`, `decisions`, `recent_messages`, `recent_emails`. Each section contains up to 10 results.

---

## Teams Browser Tools

**Module:** `mcp_tools/teams_browser_tools.py`

Browser automation tools for posting messages to Microsoft Teams. Uses a persistent Chromium browser (via Playwright) that is launched once and reused across calls. The two-step prepare/confirm flow prevents accidental sends; use `auto_send=True` on `post_teams_message` to skip confirmation.

### open_teams_browser

Launch a persistent Chromium browser and navigate to Microsoft Teams.

The browser stays open in the background. If the Teams session has expired, authenticate manually in the browser window — the session is cached in the browser profile for future calls. Idempotent: returns current status if the browser is already running.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `status: "running"` on success, or an error message if launch failed.

### post_teams_message

Prepare a message for posting to a Teams channel or person. Connects to the running browser, uses the Teams search bar to find the target by name, navigates there, and stages the message text in the compose box. Does **not** send unless `auto_send=True`.

After this returns `"confirm_required"`, call `confirm_teams_post` to send or `cancel_teams_post` to abort.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | `str` | Yes | Channel name or person name to search for (e.g. `"Engineering"`, `"John Smith"`) |
| `message` | `str` | Yes | The message text to post |
| `auto_send` | `bool` | No | If `True`, send immediately without requiring a confirmation step (default: `False`) |

**Returns:** JSON with `status: "confirm_required"` (two-step flow) or `status: "sent"` (when `auto_send=True`), plus `target` and `message` fields.

### confirm_teams_post

Send the previously prepared Teams message. Must be called after `post_teams_message` returned `"confirm_required"`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `status: "sent"` on success, or an error if no message was prepared.

### cancel_teams_post

Cancel the previously prepared Teams message. Disconnects from the browser without sending.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `status: "cancelled"`.

### close_teams_browser

Close the persistent Teams browser. Sends SIGTERM to the Chromium process. Call `open_teams_browser` to restart.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `status: "closed"` or `status: "not_running"`.

---

## Channel Routing Tools

**Module:** `mcp_tools/routing_tools.py`

Safety-tiered outbound message routing. Determines the appropriate safety tier and delivery channel for messages based on recipient type, urgency, sensitivity, and time of day.

### route_message

Determine the safety tier and delivery channel for an outbound message.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `recipient_type` | `str` | Yes | Type of recipient: `self`, `internal`, or `external` |
| `urgency` | `str` | No | Message urgency: `urgent`, `informational`, `formal`, `informal`, `ephemeral` (default: `informational`) |
| `sensitive` | `bool` | No | `True` if topic involves legal, HR, security, etc. (default: `False`) |
| `first_contact` | `bool` | No | `True` if this is the first message to this recipient (default: `False`) |
| `override` | `str` | No | Force a specific tier: `auto`, `confirm`, `draft_only` (default: none) |

**Returns:** JSON with `safety_tier`, `channel`, and `work_hours` status.

---

## Session Brain Tools

**Module:** `mcp_tools/brain_tools.py`

Persistent cross-session context document. The Session Brain maintains a human-readable markdown file that carries workstreams, action items, decisions, people context, and handoff notes across sessions.

### get_session_brain

Get the current Session Brain state: workstreams, action items, decisions, people context, handoff notes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with the current Session Brain contents including `workstreams`, `action_items`, `decisions`, `people`, and `handoff_notes`.

### update_session_brain

Update the Session Brain with new information.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `str` | Yes | Action to perform: `add_workstream`, `update_workstream`, `add_action_item`, `complete_action_item`, `add_decision`, `add_person`, `add_handoff_note` |
| `data` | `str` | Yes | JSON data for the action (fields vary by action type) |

**Returns:** JSON with `status` and updated brain state.

---

## Playbook Tools

**Module:** `mcp_tools/playbook_tools.py`

YAML-defined parallel workstreams for common multi-agent tasks. Each playbook declares inputs, workstreams (with optional conditions), a synthesis prompt, and delivery options.

### list_playbooks

List all available team playbooks with descriptions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | | | |

**Returns:** JSON with `playbooks` array containing `name`, `description`, and `workstream_count` for each available playbook.

### get_playbook

Get details of a specific playbook: inputs, workstreams, synthesis prompt, delivery options.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | Name of the playbook to retrieve |

**Returns:** JSON with full playbook definition including `inputs`, `workstreams`, `synthesis_prompt`, and `delivery` options.

---

## Resources

**Module:** `mcp_tools/resources.py`

MCP resources provide read-only data endpoints that clients can subscribe to.

### memory://facts

All stored facts about the user, organized by category.

**URI:** `memory://facts`

**Returns:** JSON object keyed by category (`personal`, `preference`, `work`, `relationship`), each containing an array of facts with `key`, `value`, `confidence`.

### memory://facts/{category}

Facts for a specific category.

**URI:** `memory://facts/{category}` where `{category}` is one of `personal`, `preference`, `work`, `relationship`

**Returns:** JSON array of facts with `key`, `value`, `confidence`.

### agents://list

All available expert agents and their descriptions.

**URI:** `agents://list`

**Returns:** JSON array of agents with `name`, `description`, `capabilities`.

---

## Summary

| Module | Tools | Description |
|--------|-------|-------------|
| Memory | 7 | Fact and location CRUD, session checkpoints, session health |
| Documents | 2 | Semantic search and ingestion |
| Agents | 7 | Agent config management, agent memory, shared memory |
| Lifecycle | 14 | Decisions, delegations, alerts |
| Calendar | 8 | Calendar CRUD and availability |
| Reminders | 6 | Apple Reminders CRUD |
| Mail | 10 | Mail read/search/send/reply + notifications |
| iMessage | 7 | iMessage read/search/send |
| OKR | 2 | OKR tracking and queries |
| Webhook | 3 | Inbound webhook event queue |
| Skills | 5 | Pattern detection, auto agent creation, auto-execution |
| Scheduler | 6 | Built-in task scheduling with cron and delivery channels |
| Channels | 2 | Unified inbound event adapter |
| Proactive | 2 | Proactive suggestion engine |
| Identity | 4 | Cross-channel identity linking |
| Event Rules | 5 | Event-driven agent dispatch |
| Session | 3 | Session lifecycle and context persistence |
| Enrichment | 1 | Parallel person profile aggregation across 6 data sources |
| Teams Browser | 5 | Playwright-based Teams message posting with confirm flow |
| Channel Routing | 1 | Safety-tiered outbound message routing |
| Session Brain | 2 | Persistent cross-session context document |
| Playbooks | 2 | YAML-defined parallel workstream definitions |
| **Total** | **105** | |
| Resources | 3 | Read-only data endpoints |
