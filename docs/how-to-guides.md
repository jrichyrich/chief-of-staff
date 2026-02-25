# Jarvis How-To Guides

Practical guides for getting things done with Jarvis (Chief of Staff) through Claude Code. You interact with Jarvis conversationally — just say "Jarvis, ..." and Claude Code will call the right MCP tools on your behalf.

---

## Table of Contents

1. [Running a Daily Briefing](#1-running-a-daily-briefing)
2. [Sending Teams Messages](#2-sending-teams-messages)
3. [Sending and Reading iMessages](#3-sending-and-reading-imessages)
4. [Managing Memory](#4-managing-memory)
5. [Email Operations](#5-email-operations)
6. [Calendar Management](#6-calendar-management)
7. [Person Enrichment](#7-person-enrichment)
8. [Decision and Delegation Tracking](#8-decision-and-delegation-tracking)
9. [Scheduling Recurring Tasks](#9-scheduling-recurring-tasks)
10. [Creating Custom Agents](#10-creating-custom-agents)
11. [Document Ingestion and Search](#11-document-ingestion-and-search)
12. [Setting Up Alert Rules](#12-setting-up-alert-rules)
13. [Using Session Brain for Cross-Session Context](#13-using-session-brain-for-cross-session-context)
14. [Running Team Playbooks](#14-running-team-playbooks)

---

## 1. Running a Daily Briefing

### What it does

A daily briefing pulls together everything you need to start your day: your meetings, unread emails, Teams messages, iMessages, active delegations, pending decisions, and reminders — all queried in parallel and synthesized into a single summary.

### Important: Do not use the `daily_briefing` agent

The `daily_briefing` expert agent lacks access to Microsoft 365 and Atlassian connectors. Run briefings directly at the Claude Code level instead, where all MCP connectors are available.

### Sources queried (always in parallel)

| Source | Tool | Notes |
|--------|------|-------|
| M365 Calendar | `mcp__claude_ai_Microsoft_365__outlook_calendar_search` | Primary source for work meetings |
| Apple Calendar | `get_calendar_events` | iCloud/personal calendars only |
| M365 Email | `mcp__claude_ai_Microsoft_365__outlook_email_search` | Primary source for work email |
| M365 Teams | `mcp__claude_ai_Microsoft_365__chat_message_search` | DMs, mentions, channel threads |
| iMessages | `get_imessages` | Personal messages |
| Memory | `query_memory`, `list_delegations`, `list_pending_decisions` | Delegations, decisions |
| Reminders | `list_reminders` | Apple Reminders |

> Apple Calendar and Apple Mail often return empty or incomplete results — never rely on them alone for coverage. M365 is the authoritative source for work communications.

### How to invoke

```
Jarvis, prepare my daily briefing.
```

```
Jarvis, give me my morning brief — what's on my calendar today, any urgent emails or Teams messages, and what delegations are overdue?
```

### What to expect

Jarvis queries all seven sources simultaneously, then presents:

- Today's meetings in chronological order (with meeting links if available)
- Unread emails flagged as urgent or from key contacts
- Teams mentions or DMs that need a response
- iMessages from the last few hours
- Active delegations — especially anything overdue or due today
- Pending decisions awaiting action
- Reminders due today or this week

---

## 2. Sending Teams Messages

### What it does

Jarvis can send messages to any Teams channel or person using a persistent Chromium browser session. The browser launches once and stays running in the background, so subsequent messages are fast.

### Tools involved

| Tool | Purpose |
|------|---------|
| `open_teams_browser` | Launch Chromium and navigate to Teams (idempotent) |
| `post_teams_message` | Find the target by name and prepare the message |
| `confirm_teams_post` | Actually send the prepared message |
| `cancel_teams_post` | Abort without sending |
| `close_teams_browser` | Shut down the browser when done |

### The confirm/cancel flow

By default, `post_teams_message` prepares the message but does not send it. Jarvis will show you a preview and ask you to confirm. This prevents accidental sends. You can skip confirmation by adding `auto_send=True` if you trust the message is ready.

### How to invoke

```
Jarvis, send Brad a Teams message: "Hey Brad, are you available for a quick sync tomorrow at 2pm?"
```

```
Jarvis, post a message to the Engineering channel saying the deployment is complete.
```

```
Jarvis, open the Teams browser and send Kelly a message asking for the Q1 numbers by EOD Friday.
```

### Typical sequence

1. Jarvis calls `open_teams_browser` (launches or reattaches to existing browser)
2. Calls `post_teams_message` with the target and message text
3. Shows you the prepared message and asks for confirmation
4. You say "yes, send it" — Jarvis calls `confirm_teams_post`
5. Message is sent

### Notes

- The browser session is cached, so authentication persists between calls. If Teams signs you out, open the browser window manually and re-authenticate — the session will be saved for next time.
- The browser stays open in the background after sending. Call `close_teams_browser` if you want to free resources.
- Target lookup uses fuzzy name matching — "Brad" will find "Brad Smith" in your Teams contacts.

---

## 3. Sending and Reading iMessages

### What it does

Jarvis can read your iMessage history directly from the Messages SQLite database (`chat.db`) and send replies via AppleScript. This works for both personal phone numbers and iMessage-enabled email addresses.

### Prerequisite: Full Disk Access

The iMessage integration requires Full Disk Access for Terminal (or the process running Jarvis) in **System Settings > Privacy & Security > Full Disk Access**. Without it, reads from `chat.db` will fail silently.

### Tools involved

| Tool | Purpose |
|------|---------|
| `get_imessages` | Recent messages across all threads (default: last 60 minutes) |
| `list_imessage_threads` | All active threads from the last 7 days |
| `get_imessage_thread_messages` | Full message history for a specific thread |
| `get_thread_context` | Thread profile + recent messages combined |
| `search_imessages` | Search by text, sender, or chat identifier |
| `send_imessage_reply` | Send a message (requires `confirm_send=True`) |

### How to invoke

**Reading recent messages:**
```
Jarvis, what iMessages have I received in the last 2 hours?
```

```
Jarvis, show me my recent text threads from the last week.
```

**Searching:**
```
Jarvis, search my iMessages for anything from Sarah about the project deadline.
```

**Sending:**
```
Jarvis, send an iMessage to +15551234567 saying "Running 10 minutes late, be there soon."
```

```
Jarvis, reply to Mom's last message saying I'll call her tonight.
```

### Safety: confirm_send

`send_imessage_reply` requires `confirm_send=True` to actually send. Jarvis will always show you the message and recipient first and ask for explicit confirmation before sending.

### Lookback windows

- `get_imessages` defaults to the last 60 minutes. Increase with `minutes=1440` for the last 24 hours.
- `list_imessage_threads` defaults to 7 days.
- `search_imessages` defaults to 24 hours — increase `minutes` for broader searches.

---

## 4. Managing Memory

### What it does

Jarvis stores facts about you, your preferences, your work context, and your relationships in a persistent SQLite database. Facts are scored by confidence and decay over time (90-day half-life by default), except pinned facts which never expire. Memory uses hybrid search: FTS5 full-text, LIKE, and ChromaDB vector embeddings merged with MMR reranking for diverse results.

### Categories

| Category | Use for |
|----------|---------|
| `personal` | Name, contact info, personal preferences |
| `preference` | How you like things done, communication style, tools you prefer |
| `work` | Job title, team, projects, work context |
| `relationship` | Notes about colleagues, stakeholders, clients |
| `backlog` | Temporary or low-confidence items to revisit |

### Tools involved

| Tool | Purpose |
|------|---------|
| `store_fact` | Save a fact (overwrites if category+key already exists) |
| `query_memory` | Search facts by text with temporal scoring |
| `delete_fact` | Remove a specific fact by category and key |
| `store_location` | Save a named location with address and coordinates |
| `list_locations` | List all stored locations |
| `checkpoint_session` | Save session context before context compaction |

### How to invoke

**Storing facts:**
```
Jarvis, remember that Sarah prefers to receive status updates by email, not Slack.
```

```
Jarvis, store a work fact: my current focus area is platform reliability and SLO improvements.
```

```
Jarvis, remember my home address is 123 Main Street, Salt Lake City, UT.
```

**Querying:**
```
Jarvis, what do you know about my relationship with Brad?
```

```
Jarvis, what have you stored about my work context and current projects?
```

```
Jarvis, search your memory for anything related to the vendor contract.
```

**Pinning important facts (they never decay):**
```
Jarvis, store a personal fact with key "manager" and value "Kelly Johnson" and pin it so it never expires.
```

**Deleting outdated facts:**
```
Jarvis, delete the work fact with key "current_project" — that project is done.
```

**Session checkpoints:**

If you have been working through a long session and want to make sure key context survives a session reset:
```
Jarvis, checkpoint this session. We decided to move the launch date to March 15th and delegate vendor negotiation to Sarah.
```

### Notes on temporal decay

Facts decay in relevance over time using a 90-day half-life. A fact stored 90 days ago has half the relevance score of one stored today (at the same confidence level). Pinned facts (`pinned=True`) bypass decay entirely — use pinning for stable facts like your name, role, or organizational structure.

---

## 5. Email Operations

### What it does

Jarvis reads and sends Apple Mail via AppleScript. For work email, M365 Outlook is the primary source — use the `mcp__claude_ai_Microsoft_365__outlook_email_search` tool for Outlook. Apple Mail works for personal accounts or as a fallback.

### Tools involved

| Tool | Purpose |
|------|---------|
| `list_mailboxes` | List all mailboxes with unread counts |
| `get_mail_messages` | Get message headers from a mailbox (default: INBOX, limit 25) |
| `get_mail_message` | Get full message content by ID |
| `search_mail` | Search by subject or sender text |
| `mark_mail_read` | Mark a message read or unread |
| `mark_mail_flagged` | Flag or unflag a message |
| `move_mail_message` | Move a message to another mailbox |
| `reply_to_email` | Send a threaded reply (requires `confirm_send=True`) |
| `send_email` | Compose and send a new email (requires `confirm_send=True`) |
| `send_notification` | Push a macOS notification |

### How to invoke

**Reading:**
```
Jarvis, show me my last 10 unread emails.
```

```
Jarvis, search my inbox for anything from Kelly about the budget.
```

**Sending:**
```
Jarvis, send an email to brad@example.com with subject "Meeting Notes" and body "Here are the notes from today's discussion..."
```

**Replying:**
```
Jarvis, reply to the email from Sarah about the vendor contract. Tell her we're good to proceed, just need the signed NDA first.
```

**Organization:**
```
Jarvis, flag the email from legal about the contract renewal.
```

```
Jarvis, move the Amazon receipt to my Receipts mailbox.
```

### Safety: confirm_send

Both `send_email` and `reply_to_email` require `confirm_send=True` to send. Calling without it returns a preview so you can check the message before committing. Jarvis will always ask for your explicit confirmation before setting `confirm_send=True`.

### M365 vs Apple Mail

For work email on Microsoft 365, prefer:
```
Jarvis, search my Outlook for unread emails from the last 48 hours mentioning "incident".
```
This uses `mcp__claude_ai_Microsoft_365__outlook_email_search`, which has direct access to your Exchange mailbox. Apple Mail may not reflect Outlook in real time if sync is delayed.

---

## 6. Calendar Management

### What it does

Jarvis manages calendars across two providers: Apple Calendar (via PyObjC EventKit) and Microsoft 365 (via the Claude CLI M365 bridge). A routing database tracks which provider owns each event so updates go to the right place automatically.

### Tools involved

| Tool | Purpose |
|------|---------|
| `list_calendars` | List all calendars across providers |
| `get_calendar_events` | Get events in a date range |
| `create_calendar_event` | Create a new event |
| `update_calendar_event` | Update an existing event by UID |
| `delete_calendar_event` | Delete an event by UID |
| `search_calendar_events` | Search events by title text (default: ±30 days) |
| `find_my_open_slots` | Find available time blocks in your calendar |
| `find_group_availability` | Guidance workflow for scheduling with multiple attendees |

### Provider preference

The `provider_preference` parameter controls which calendar source to query:
- `auto` (default) — Jarvis picks the right provider based on ownership
- `apple` — Apple Calendar only
- `microsoft_365` — M365/Outlook only
- `both` — Pull from all providers simultaneously

`find_my_open_slots` defaults to `provider_preference="both"` to ensure accurate availability across all your calendars. Never check availability using only one provider.

### How to invoke

**Viewing events:**
```
Jarvis, what's on my calendar today and tomorrow?
```

```
Jarvis, show me all my meetings next week.
```

**Searching:**
```
Jarvis, find any calendar events related to the Q1 planning meeting.
```

**Creating events:**
```
Jarvis, create a calendar event: "1:1 with Kelly" on March 5th from 2:00 PM to 2:30 PM.
```

```
Jarvis, add a focus block on Friday from 9am to 11am with the title "Deep Work: Architecture Review".
```

**Finding open time:**
```
Jarvis, find me 30-minute open slots this week between 9am and 5pm.
```

```
Jarvis, when am I free for an hour-long meeting next Monday or Tuesday?
```

**Group scheduling:**
```
Jarvis, find a time that works for me, brad@example.com, and sarah@example.com for a 45-minute meeting next week.
```

This triggers the two-step group availability workflow:
1. M365 `find_meeting_availability` checks everyone's Outlook calendars
2. `find_my_open_slots` checks your real availability with soft block logic (Focus Time, Lunch, etc. treated as available by default)
3. Results are cross-referenced for times that work for everyone

### Working hours and soft blocks

`find_my_open_slots` uses Mountain Time (America/Denver) and a default working window of 08:00–18:00. Soft block keywords (focus, lunch, prep, hold, tentative) are treated as available by default. You can override:

```
Jarvis, find 60-minute open slots this week. Treat my Focus Time blocks as busy.
```

---

## 7. Person Enrichment

### What it does

`enrich_person` fetches a consolidated profile for a person from six data sources simultaneously: cross-channel identities, stored facts, delegations, decisions, recent iMessages, and recent emails. It is much faster than calling each tool individually and omits any sections that return no data.

### Tool involved

`enrich_person(name, days_back=7)`

The `days_back` parameter controls the lookback window for communications (default: 7 days).

### How to invoke

```
Jarvis, tell me everything you know about Sarah Chen.
```

```
Jarvis, enrich Brad's profile — what delegations does he have, what have we discussed recently, and what's in memory about him?
```

```
Jarvis, pull a context card for Kelly before my 1:1 with her. Look back 14 days.
```

### What comes back

The result is a JSON profile with any of these sections that have data:

- **identities** — Known accounts for this person across providers (email, Teams handle, iMessage, Jira, etc.)
- **facts** — Stored memory facts about them (role, preferences, relationship notes)
- **delegations** — Tasks delegated to them, with status and due dates
- **decisions** — Decisions involving them from the decision log
- **recent_messages** — iMessages to/from them in the lookback window
- **recent_emails** — Emails to/from them in the lookback window

Empty sections are silently omitted. If a data source is unavailable (e.g., iMessage on a non-macOS system), that section is skipped without error.

---

## 8. Decision and Delegation Tracking

### What it does

Jarvis maintains a log of decisions you make and tasks you delegate to others. Decisions track what was decided, who decided it, and whether it has been acted on. Delegations track what you asked someone else to do, with due dates and priority levels — so nothing you are accountable for slips through the cracks.

### Decision statuses

`pending_execution` | `executed` | `deferred` | `reversed`

### Delegation priorities and statuses

Priorities: `low` | `medium` | `high` | `critical`
Statuses: `active` | `completed` | `cancelled`

### Tools involved

| Tool | Purpose |
|------|---------|
| `create_decision` | Log a new decision |
| `search_decisions` | Search decisions by text or status |
| `update_decision` | Change status or add notes |
| `list_pending_decisions` | List all decisions awaiting execution |
| `delete_decision` | Remove a decision |
| `create_delegation` | Track a task delegated to someone |
| `list_delegations` | List delegations with optional filters |
| `update_delegation` | Mark a delegation complete or add notes |
| `check_overdue_delegations` | List active delegations past their due date |
| `delete_delegation` | Remove a delegation |

### How to invoke

**Decisions:**
```
Jarvis, log a decision: we decided to migrate the authentication service to OAuth 2.0. Owner is the platform team, decided in today's architecture review.
```

```
Jarvis, what decisions are still pending execution?
```

```
Jarvis, mark decision 42 as executed. We shipped it this morning.
```

```
Jarvis, search decisions related to the vendor contract.
```

**Delegations:**
```
Jarvis, I delegated the Q1 security report to Sarah. Due date is March 14th. Priority: high.
```

```
Jarvis, what delegations are overdue?
```

```
Jarvis, list all active delegations for Brad.
```

```
Jarvis, mark delegation 17 as completed — Brad sent over the final numbers.
```

### Relationship with agents

The `delegation_tracker` and `decision_tracker` expert agents can do deeper analysis — generating follow-up nudges for overdue items, flagging patterns (e.g., a person who consistently misses deadlines), and producing formatted summaries. Invoke them when you want analysis, not just data:

```
Jarvis, run the delegation_tracker agent. Generate follow-up messages for anything overdue.
```

---

## 9. Scheduling Recurring Tasks

### What it does

The built-in scheduler persists tasks in SQLite and evaluates them on a schedule. A background daemon (`com.chg.jarvis-scheduler`) runs the scheduler engine every 5 minutes via launchd. Results can be delivered via email, iMessage, or macOS notification.

### Schedule types

| Type | Config example | Description |
|------|---------------|-------------|
| `interval` | `{"minutes": 30}` or `{"hours": 2}` | Run every N minutes or hours |
| `cron` | `{"expression": "0 8 * * 1-5"}` | Cron expression (minute hour day month weekday; 0=Monday) |
| `once` | `{"run_at": "2026-03-01T09:00:00"}` | Run once at a specific time |

### Handler types

| Handler | Purpose |
|---------|---------|
| `alert_eval` | Evaluate alert rules (overdue delegations, stale decisions, deadlines) |
| `backup` | Run backup jobs |
| `webhook_poll` | Poll for incoming webhook events |
| `custom` | Run a shell command: `{"command": "echo hello"}` |

### Delivery channels

| Channel | Config example |
|---------|---------------|
| `email` | `{"to": ["you@example.com"], "subject_template": "Task $task_name completed"}` |
| `imessage` | `{"recipient": "+15551234567"}` |
| `notification` | `{"sound": "default", "title_template": "Task: $task_name"}` |

### Tools involved

| Tool | Purpose |
|------|---------|
| `create_scheduled_task` | Create a new scheduled task |
| `list_scheduled_tasks` | List all tasks |
| `update_scheduled_task` | Change schedule, handler, or delivery config |
| `delete_scheduled_task` | Remove a task |
| `run_scheduled_task` | Manually trigger a task now |
| `get_scheduler_status` | Overview of all tasks with last/next run times and overdue status |

### How to invoke

```
Jarvis, create a scheduled task that runs alert checks every morning at 8am on weekdays and sends me a notification.
```

```
Jarvis, set up a task to check for overdue delegations every 2 hours and send results to my iMessage.
```

```
Jarvis, what scheduled tasks are set up and when did they last run?
```

```
Jarvis, manually run task 3 now.
```

```
Jarvis, disable the backup task — I'll re-enable it after the migration.
```

### Example: weekday morning alert

To create a task that checks alerts every weekday at 8:00 AM Mountain Time and sends a macOS notification:

```
Jarvis, create a scheduled task:
- Name: morning_alerts
- Schedule: cron, expression "0 8 * * 1-5"
- Handler: alert_eval
- Delivery: notification with title "Morning Alert Check"
```

---

## 10. Creating Custom Agents

### What it does

Expert agents are Claude instances pre-configured with a specific persona, system prompt, and a scoped set of capabilities (tools they are allowed to use). You can create agents that specialize in things like security metrics analysis, meeting debriefs, OKR tracking, project reviews, or anything domain-specific.

Agents are stored as YAML files in `agent_configs/` and can be created in two ways:

1. **Dynamically via AgentFactory** — describe what you need and Claude generates the config
2. **Manually** — write the YAML directly for full control

### Dynamic creation

```
Jarvis, create an agent that specializes in analyzing iMessage threads with my direct reports and summarizing patterns and action items.
```

```
Jarvis, create a new agent for tracking security incidents — it should be able to read memory, search documents, read decisions, and query delegation status.
```

Jarvis will call `create_agent` with your description. The factory uses Claude (Haiku tier) to generate a name, description, system prompt, and capability list. Auto-generated agents are capped at 8 capabilities and cannot have `mail_write`, `notifications`, or `alerts_write` without manual override.

### Manual YAML creation

Write a file in `agent_configs/your_agent_name.yaml`:

```yaml
name: vendor_tracker
description: Tracks vendor contracts, renewal dates, and negotiation status.
capabilities:
  - memory_read
  - memory_write
  - document_search
  - delegation_read
  - decision_read
system_prompt: |
  You are a vendor relationship tracker. Your job is to maintain an accurate
  picture of all active vendor contracts, upcoming renewals, and open negotiations.

  When asked about a vendor, search memory for stored facts, check delegations
  for any open tasks related to that vendor, and search documents for contract files.

  Always note when contracts are due for renewal within 90 days.
temperature: 0.3
max_tokens: 4096
```

### Available capabilities

Capabilities gate which tools an agent can access. Common ones include:

| Capability | Grants access to |
|-----------|-----------------|
| `memory_read` | `query_memory`, facts retrieval |
| `memory_write` | `store_fact`, `checkpoint_session` |
| `calendar_read` | `get_calendar_events`, `search_calendar_events`, `find_my_open_slots` |
| `mail_read` | `get_mail_messages`, `search_mail` |
| `mail_write` | `send_email`, `reply_to_email` |
| `document_search` | `search_documents` |
| `delegation_read` | `list_delegations`, `check_overdue_delegations` |
| `delegation_write` | `create_delegation`, `update_delegation` |
| `decision_read` | `search_decisions`, `list_pending_decisions` |
| `decision_write` | `create_decision`, `update_decision` |
| `reminders_read` | `list_reminders`, `search_reminders` |
| `notifications` | `send_notification` |

### How to invoke an agent

Once created, invoke an agent by name:

```
Jarvis, run the vendor_tracker agent. Tell me which vendors have contracts expiring in Q2.
```

```
Jarvis, use the meeting_prep agent to prep me for my 1:1 with Sarah tomorrow.
```

```
Jarvis, run the delegation_tracker agent and generate follow-up messages for anything overdue.
```

### Viewing existing agents

```
Jarvis, list all available agents.
```

```
Jarvis, show me the config for the meeting_prep agent.
```

---

## 11. Document Ingestion and Search

### What it does

Jarvis can ingest files into a ChromaDB vector store and perform semantic search over them. Documents are chunked into 500-word segments with 50-word overlap, SHA256 deduplicated (re-ingesting the same file is a no-op), and embedded using the `all-MiniLM-L6-v2` model.

### Supported file types

`.txt`, `.md`, `.py`, `.json`, `.yaml`, `.pdf`, `.docx`

### Tools involved

| Tool | Purpose |
|------|---------|
| `ingest_documents` | Ingest a file or directory into the vector store |
| `search_documents` | Semantic search over ingested documents |

### How to invoke

**Ingesting:**
```
Jarvis, ingest the document at /Users/me/Documents/architecture-decision-records.md
```

```
Jarvis, ingest everything in /Users/me/Documents/project-docs/ into the document store.
```

**Searching:**
```
Jarvis, search the document store for anything about our authentication architecture decisions.
```

```
Jarvis, find documents related to the data retention policy.
```

```
Jarvis, what do my ingested docs say about incident response procedures?
```

### Deduplication

If you re-ingest a file that has not changed, the SHA256 check will detect the duplicate and skip it. Only new or modified content is added. This makes it safe to re-run ingestion on a directory — it will only process new files.

### Using documents with agents

Once ingested, any agent with the `document_search` capability can search your document store. The `document_librarian` and `meeting_prep` agents use document search by default. For best results, ingest related documents before running those agents.

---

## 12. Setting Up Alert Rules

### What it does

Alert rules define conditions that Jarvis watches for and reports on. The scheduler evaluates alert rules on a schedule (every 2 hours by default via launchd, or whenever `check_alerts` is called manually). When conditions are met, Jarvis surfaces the alerts so you can act on them.

### Built-in alert types

| Alert type | What it checks |
|-----------|---------------|
| `overdue_delegation` | Active delegations past their due date |
| `pending_decision` | Decisions in `pending_execution` status for more than 7 days |
| `upcoming_deadline` | Delegations or decisions with due dates within 3 days |

### Tools involved

| Tool | Purpose |
|------|---------|
| `create_alert_rule` | Create or update an alert rule |
| `list_alert_rules` | List all configured rules |
| `check_alerts` | Run all alert checks immediately and return results |
| `dismiss_alert` | Disable an alert rule so it stops triggering |

### How to invoke

**Creating alert rules:**
```
Jarvis, create an alert rule called "overdue_check" that fires when any delegation is past its due date.
```

```
Jarvis, set up an alert for decisions that have been pending execution for more than a week.
```

```
Jarvis, create an alert rule for upcoming deadlines — anything due within 3 days.
```

**Running alerts:**
```
Jarvis, check all my alert rules now. What's firing?
```

**Reviewing rules:**
```
Jarvis, list all my alert rules.
```

**Dismissing:**
```
Jarvis, dismiss alert rule 3 — that project is closed.
```

### Combining alerts with scheduled tasks

The most powerful setup is combining an alert rule with a scheduled task that runs `alert_eval` on a schedule and delivers results to your preferred channel:

```
Jarvis, create an alert rule called "morning_overdue" for overdue delegations.

Then create a scheduled task called "morning_alert_run" that runs alert_eval every weekday at 8am and sends results as a macOS notification.
```

This gives you automatic, proactive surfacing of things that need attention without having to ask.

---

## 13. Using Session Brain for Cross-Session Context

### What it does

The Session Brain is a persistent markdown file (`data/session_brain.md`) that carries structured context across Claude Code sessions. Unlike memory facts (which store isolated key-value pairs), the brain maintains a living document with active workstreams, open action items, recent decisions, key people context, and handoff notes. When a new session starts, the brain loads automatically so you pick up right where you left off.

### Brain sections

| Section | Purpose |
|---------|---------|
| Active Workstreams | Projects or threads you are actively working on, with status and context |
| Open Action Items | Tasks tracked as a checklist with source attribution and dates |
| Recent Decisions | Decisions made during sessions, dated for reference |
| Key People Context | Notes about people relevant to current work |
| Session Handoff Notes | Free-form notes for your future self about what to do next |

### Tools involved

| Tool | Purpose |
|------|---------|
| `get_session_brain` | Read the full brain state (all five sections) |
| `update_session_brain` | Modify the brain with a specific action |

### Viewing the brain

```
Jarvis, show me the Session Brain.
```

```
Jarvis, what workstreams and action items are open right now?
```

This calls `get_session_brain` and returns all sections with their current content.

### Adding workstreams

```
Jarvis, add a workstream to the brain: "OAuth Migration" with status "in-progress" and context "Migrating auth service from SAML to OAuth 2.0, targeting March 15 launch."
```

This calls `update_session_brain` with `action="add_workstream"`. If a workstream with the same name already exists, it updates the status and context instead of creating a duplicate.

### Tracking action items

**Adding:**
```
Jarvis, add an action item to the brain: "Review Sarah's PR for the calendar connector."
```

**Completing:**
```
Jarvis, mark the action item "Review Sarah's PR for the calendar connector" as complete in the brain.
```

Action items are stored as checkbox items with metadata (source, date added). The `complete_action_item` action marks the first matching item as done.

### Recording decisions and people context

**Decisions:**
```
Jarvis, add a decision to the brain: "Decided to use ChromaDB over Pinecone for the vector store."
```

Decisions are automatically dated with today's date.

**People context:**
```
Jarvis, add to the brain that Kelly is the new VP of Engineering and prefers async updates over meetings.
```

People entries are upserted by name, so updating someone's context replaces the previous entry.

### Handoff notes

```
Jarvis, add a handoff note: "Left off debugging the M365 bridge timeout issue. Check the logs in data/m365-bridge.log. Next step is to increase M365_BRIDGE_TIMEOUT_SECONDS and retest."
```

Handoff notes are free-form and deduplicated. They are the best place to leave yourself a note about exactly where you stopped.

### Automatic updates during session flush

When you call `flush_session_memory` (via the session tools), the session manager automatically extracts decisions and action items from the session and writes them to the brain. You do not need to manually add every item. The flush process:

1. Extracts structured data from the session (decisions, action items)
2. Calls `brain.add_decision()` for each decision found
3. Calls `brain.add_action_item()` for each action item (with source "session_flush")
4. Saves the brain file

### Example workflow

1. **Start a session** -- Jarvis loads the brain automatically
   ```
   Jarvis, show me the Session Brain so I know where we left off.
   ```
2. **Work through tasks** -- update the brain as you go
   ```
   Jarvis, mark "Draft the architecture RFC" as complete. Add a new action item: "Get sign-off from platform team on RFC."
   ```
3. **End the session** -- flush captures remaining context
   ```
   Jarvis, flush the session memory.
   ```
4. **Next session** -- the brain has everything
   ```
   Jarvis, what's in the brain? What was I working on last time?
   ```

The brain file is plain markdown, so you can also read or edit it directly at `data/session_brain.md` if you prefer.

---

## 14. Running Team Playbooks

### What it does

Team Playbooks are YAML-defined templates for parallel workstreams. Instead of manually asking Jarvis to query five different sources one at a time, a playbook fans out all workstreams simultaneously using the Task tool, then synthesizes the results into a single deliverable. Think of them as reusable recipes for common multi-source workflows.

### Tools involved

| Tool | Purpose |
|------|---------|
| `list_playbooks` | List all available playbooks with descriptions |
| `get_playbook` | View a playbook's inputs, workstreams, synthesis, and delivery options |

### Listing available playbooks

```
Jarvis, list all available playbooks.
```

```
Jarvis, what playbooks do I have?
```

### Viewing playbook details

```
Jarvis, show me the meeting_prep playbook.
```

This returns the playbook's description, required inputs, workstream definitions, synthesis prompt, and delivery options.

### Built-in playbooks

| Playbook | When to use | Inputs |
|----------|-------------|--------|
| `meeting_prep` | Before an important meeting. Pulls email threads, documents, decision history, and calendar context for attendees. | `meeting_subject`, `meeting_time`, `attendees` |
| `expert_research` | Deep-dive on any topic. Queries memory, documents, email, calendar, and identity data in parallel. Optionally includes web research. | `topic`, `context`, `depth` |
| `software_dev_team` | Before implementing code changes. Runs architecture analysis, code review, test analysis, dependency scanning, and docs checking in parallel. | `task`, `scope` |
| `daily_briefing` | Automated morning briefing. Queries calendar, email, Teams, iMessages, memory, and reminders all at once. | `briefing_date`, `email_recipient` |

### How playbooks work

1. **Inputs** -- You provide values for the playbook's declared inputs (e.g., `meeting_subject`, `attendees`). These get substituted into workstream prompts wherever `$variable_name` appears.
2. **Workstreams** -- Each workstream runs in parallel via the Task tool. Every workstream has a name and a prompt that may reference input variables. Some workstreams have a `condition` field (e.g., `depth == thorough`) that determines whether they run.
3. **Synthesis** -- After all workstreams complete, their results are combined using the synthesis prompt. This prompt defines the structure and format of the final output.
4. **Delivery** -- Each playbook has a default delivery method (`inline`, `email`, `teams`, or `confluence`) and a list of alternative options.

### Running a playbook

```
Jarvis, run the meeting_prep playbook:
- meeting_subject: "Q1 Platform Review"
- meeting_time: "2026-02-25 at 2pm"
- attendees: "Kelly Johnson, Brad Smith, Sarah Chen"
```

```
Jarvis, run expert_research on topic "vendor contract renewal" with context "Our SaaS vendor contract expires in April, need to decide whether to renew or switch" and depth "thorough".
```

```
Jarvis, run the software_dev_team playbook for task "Add webhook retry logic" with scope "webhook/ and scheduler/".
```

```
Jarvis, run the daily_briefing playbook for today.
```

### Creating custom playbooks

Playbooks are YAML files in the `playbooks/` directory. To create a custom playbook, add a new `.yaml` file following this format:

```yaml
name: my_playbook
description: Brief description of what this playbook does
inputs:
  - input_one
  - input_two
workstreams:
  - name: workstream_a
    prompt: |
      Instructions for this workstream.
      Use $input_one and $input_two to reference inputs.
  - name: workstream_b
    condition: "input_two == detailed"
    prompt: |
      This workstream only runs when the condition is met.
      Analyze $input_one in detail.
synthesis:
  prompt: |
    Combine all workstream results into a structured output:
    1. Section one
    2. Section two
    Context: $input_one
delivery:
  default: inline
  options:
    - email
    - teams
```

Key points about the YAML format:

- **inputs**: List of variable names. Users provide values when running the playbook. Variables are referenced as `$variable_name` in prompts.
- **workstreams**: Each needs a `name` and `prompt`. The optional `condition` field is a simple expression evaluated against the inputs to decide whether the workstream runs.
- **synthesis**: The `prompt` field defines how results are combined. Reference inputs here too.
- **delivery**: `default` is the delivery method used unless overridden. `options` lists all supported methods.

Place the file in the `playbooks/` directory (configurable via `PLAYBOOKS_DIR`) and it will appear in `list_playbooks` immediately.

---

## Tips and Patterns

### Ask for things in plain language

Jarvis understands conversational requests. You do not need to know tool names or parameter formats — just describe what you want:

- "Jarvis, remind me what we decided about the vendor contract last month" → `query_memory` + `search_decisions`
- "Jarvis, who do I have meetings with tomorrow?" → `get_calendar_events` with tomorrow's date range
- "Jarvis, is Sarah still working on the security audit?" → `list_delegations` filtered to Sarah

### Parallelize when possible

When you need information from multiple sources, ask for everything at once:

```
Jarvis, prepare for my 1:1 with Brad tomorrow — pull his delegations, recent emails, any decisions he's involved in, and what I have stored in memory about him.
```

Jarvis will query all four sources in parallel rather than sequentially.

### Session checkpoints

For long working sessions, periodically checkpoint to preserve context:

```
Jarvis, checkpoint this session. Key decisions: migrating to OAuth, delegating vendor review to Sarah, deferring the architecture doc until next sprint.
```

This writes context and structured facts to the memory store so nothing is lost if the session resets.

### Check session health

If you have been working in a long session and want to know whether a checkpoint is recommended:

```
Jarvis, how is the session health? Should I checkpoint?
```

`get_session_health` returns the tool call count, time since last checkpoint, and a recommendation flag.
