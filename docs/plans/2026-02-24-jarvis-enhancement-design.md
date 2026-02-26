# Jarvis Enhancement Design: Hybrid Playbooks + Session Brain + Proactive Engine

**Date**: 2026-02-24
**Status**: Approved
**Approach**: C (Hybrid)

## Problem Statement

Jarvis has 99 tools across 21 modules, 47 expert agent configs, and deep integrations with Apple platforms, M365 (read-only), Atlassian, and Teams (via Playwright). Despite this, three core friction points prevent it from functioning as a true command center:

1. **Proactive intelligence gap**: Jarvis is reactive -- it waits to be asked. Suggestions exist but must be pulled via `get_proactive_suggestions`.
2. **Session continuity**: Every new conversation starts from zero. Context, action items, and workstream state are lost between sessions.
3. **Underutilized agent teams**: 47 expert agents exist but can't access MCP connectors (Atlassian, M365). The force-multiplying capability of parallel specialist teams goes unused.

## Key Constraint

M365 write capabilities are not available -- only read. Workarounds:
- Send email via Apple Mail
- Post Teams messages via Playwright browser
- Create calendar events via Apple Calendar (EventKit)

## Design

### Section 1: Team Playbooks

YAML-defined parallel workstreams dispatched via Claude Code's Task tool. Unlike expert agents (which run in their own tool-use loop with only capability-gated tools), Task tool subagents inherit full MCP connector access -- Atlassian, M365, and all Jarvis tools.

#### Playbook YAML structure

```yaml
name: <playbook_name>
description: <what this team does>
inputs:
  - <variable_name>    # populated at invocation time
workstreams:
  - name: <agent_name>
    prompt: |
      <task description referencing $variables>
    condition: <optional, e.g. depth == "thorough">
synthesis:
  prompt: |
    <instructions for combining workstream results>
delivery:
  default: inline       # show in conversation
  options: [email, teams, confluence]
```

#### Example playbooks

**Meeting Prep**
- email_context: Search M365 email for threads involving attendees
- document_context: Search Confluence for pages related to meeting subject
- decision_history: Query Jarvis memory for decisions and delegations involving attendees
- calendar_context: Find previous meetings with these attendees
- Synthesis: Combine into a briefing document with agenda, context, and open items

**Expert Research**
- memory_analyst: Query all Jarvis memory for the topic
- document_researcher: Search ingested documents and Confluence
- email_intel: Search M365 email and Teams messages
- calendar_context: Find related meetings (past 30 days, next 14 days)
- identity_mapper: Build stakeholder map across all channels
- web_researcher: External context (conditional, only for thorough depth)
- Synthesis: Executive summary, known/unknown gaps, stakeholder map, next steps

**Software Development Team**
- architect: Analyze architecture, dependencies, coupling risks
- code_reviewer: Review code for patterns, security, performance
- test_analyst: Examine test coverage, edge cases, patterns
- dependency_scanner: Map callers, importers, downstream consumers, breaking change risks
- docs_checker: Verify documentation matches current code
- Synthesis: Architecture assessment, risk areas, implementation plan, test plan

#### Playbook storage and invocation

- Playbook YAML files stored in `playbooks/` directory
- Invoked by name: "Jarvis, run meeting_prep for my 2pm with Maria"
- Jarvis parses inputs, dispatches workstreams as parallel Task tool calls, runs synthesis, delivers via configured channel

### Section 2: Session Brain

A living context document (`data/session_brain.md`) that persists across sessions, maintaining workstream state, action items, and operational knowledge.

#### Structure

```markdown
# Session Brain
Last updated: <timestamp>

## Active Workstreams
- <workstream>: <status> - <brief context>

## Open Action Items
- [ ] <item> (source, date added)

## Recent Decisions
- <date>: <decision summary>

## Key People Context
- <name>: <role, relationship, relevant notes>

## Session Handoff Notes
- <operational knowledge carried across sessions>
```

#### Lifecycle

1. **Session start**: Jarvis reads `session_brain.md` for immediate full context
2. **During session**: Updated as decisions are made, action items created, workstreams shift
3. **Session end / checkpoint**: Flush extracts new facts, updates action items, records handoff notes
4. **Cross-session**: File is always current -- no re-explaining needed

#### Differences from existing session tools

- Human-readable (user can open and read it directly)
- Curated summary, not raw interaction log
- Explicit action-item tracking with checkboxes
- Workstream status tracking (not just facts)
- Handoff notes for operational knowledge ("don't use agent X for Y")

The existing `flush_session_memory` and `restore_session` tools become the mechanism that updates the Session Brain, rather than being the end product.

### Section 3: Proactive Engine Enhancement

Push-based intelligence through three layers, building on the existing proactive engine and scheduler infrastructure.

#### Layer 1: Time-sensitive alerts (push immediately)

Triggers:
- Overdue delegation with an imminent meeting involving that person
- Calendar conflict between newly created events
- High-priority webhook event matching an event rule
- Action item deadline approaching (from Session Brain)

Delivery: iMessage for urgent, email for important-but-not-urgent.

#### Layer 2: Daily intelligence (scheduled push)

- Automated morning briefing at a configured time (no manual trigger)
- Includes Session Brain open items, not just raw calendar/email data
- Flags overnight changes: new emails on tracked threads, delegation updates
- Weekend mode: skip or reduce to critical-only

Delivery: Email, triggered by scheduler daemon (`com.chg.scheduler-engine`).

#### Layer 3: Contextual nudges (in-session)

On session start, Jarvis surfaces:
- Open action items from previous sessions
- Stale workstreams that need attention
- Upcoming meetings that could benefit from prep
- Proactive suggestions from the existing engine

These appear as the first thing Jarvis says, not buried in a tool call.

#### Implementation approach

Wire proactive engine output into existing scheduler/delivery infrastructure (`scheduler/engine.py`, `scheduler/delivery.py`) rather than building new delivery mechanisms.

### Section 4: Channel Routing

Situational delivery combining safety tiers with context awareness.

#### Safety tiers

| Tier | When | Behavior |
|------|------|----------|
| **Tier 1: Auto-send** | Messages to self, macOS notifications, Session Brain updates | No confirmation needed |
| **Tier 2: Confirm before send** | Messages to known contacts on routine topics | Jarvis prepares message, shows preview, user approves |
| **Tier 3: Draft only** | External parties, executives, sensitive topics, first-time contacts | Human must send manually |

#### Tier determination

| Signal | Logic |
|--------|-------|
| Recipient | Self = Tier 1. Known internal = Tier 2. External/executive/new = Tier 3 |
| Topic sensitivity | Keywords or categories (legal, HR, security, financial) bump up one tier |
| Explicit override | Playbook YAML can declare `safety: auto` or `safety: draft_only` |
| User preference | Stored as memory fact: "always confirm before messaging Maria" |

#### Channel selection

| Recipient | Urgent | Informational | Formal |
|-----------|--------|---------------|--------|
| Self | iMessage | Email | Email |
| Colleague (work hours) | Teams | Teams | Email |
| Colleague (off hours) | iMessage | Queue for morning | Queue for morning |
| External | N/A | Email (Tier 3) | Email (Tier 3) |

#### Channel capabilities

| Channel | Read | Write | Constraints |
|---------|------|-------|-------------|
| M365 Email | Yes | No | Send via Apple Mail |
| M365 Teams | Yes (search) | Yes (Playwright) | Requires browser session |
| M365 Calendar | Yes | No | Create via Apple Calendar |
| Apple Mail | Yes | Yes | Can't create drafts, only send |
| Apple Calendar | Yes | Yes | Full CRUD via EventKit |
| iMessage | Yes | Yes | Via AppleScript, needs phone number |
| macOS Notifications | N/A | Yes | Local only |
| Confluence | Yes | Yes | Via Atlassian MCP connector |

#### Time-of-day awareness

- Work hours (8am-6pm weekdays): Teams for colleagues, email for formal
- Off hours: Only iMessage or notification for urgent, queue rest for morning
- Weekends: Critical alerts only via iMessage, batch rest into Monday brief

#### Fallback chain

If primary channel fails: Teams -> Email -> iMessage -> macOS notification. Failures logged to Session Brain.

## Summary

| Component | Purpose |
|-----------|---------|
| Team Playbooks | YAML-defined parallel workstreams via Task tool with full connector access |
| Session Brain | Living context document carrying workstreams, action items, and handoff notes across sessions |
| Proactive Engine | Push-based intelligence: urgent alerts, scheduled briefs, session nudges |
| Channel Routing | Situational delivery with safety tiers and time-of-day awareness |
