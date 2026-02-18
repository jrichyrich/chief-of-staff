# MCP Tools Reference

Complete reference for all MCP tools and resources exposed by the Chief of Staff (Jarvis) server.

**Total: 56 tools across 10 modules, plus 3 MCP resources.**

---

## Table of Contents

1. [Memory Tools](#memory-tools) (5 tools)
2. [Document Tools](#document-tools) (2 tools)
3. [Agent Tools](#agent-tools) (3 tools)
4. [Lifecycle Tools](#lifecycle-tools) (14 tools)
5. [Calendar Tools](#calendar-tools) (8 tools)
6. [Reminder Tools](#reminder-tools) (6 tools)
7. [Mail Tools](#mail-tools) (9 tools)
8. [iMessage Tools](#imessage-tools) (7 tools)
9. [OKR Tools](#okr-tools) (2 tools)
10. [Resources](#resources) (3 resources)

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

**Returns:** JSON with `status`, `category`, `key`, `value` on success; `error` on failure.

### delete_fact

Delete a fact from long-term memory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `category` | `str` | Yes | The fact category (`personal`, `preference`, `work`, `relationship`, `backlog`) |
| `key` | `str` | Yes | The fact key to delete |

**Returns:** JSON with `status: "deleted"` or `status: "not_found"`.

### query_memory

Search stored facts about the user. Returns matching facts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | Yes | Search term to match against fact keys and values |
| `category` | `str` | No | Filter to a specific category. Leave empty to search all. |

**Returns:** JSON with `results` array of matching facts (category, key, value, confidence).

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

Tools for managing expert agent configurations stored as YAML files in `agent_configs/`.

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
| Memory | 5 | Fact and location CRUD |
| Documents | 2 | Semantic search and ingestion |
| Agents | 3 | Agent config management |
| Lifecycle | 14 | Decisions, delegations, alerts |
| Calendar | 8 | Calendar CRUD and availability |
| Reminders | 6 | Apple Reminders CRUD |
| Mail | 9 | Mail read/search/send + notifications |
| iMessage | 7 | iMessage read/search/send |
| OKR | 2 | OKR tracking and queries |
| **Total** | **56** | |
| Resources | 3 | Read-only data endpoints |
