---
name: agent-orchestration
description: Use when the user wants to create, list, or manage expert agent configurations that define specialized AI assistants with specific capabilities
---

# Agent Orchestration

## Overview

Manage expert agent configurations stored as YAML files. Agents define specialized personas with system prompts and capability declarations.

## When to Use

- User asks to create a new expert agent ("Create a research agent", "I need a writing assistant")
- User wants to see available agents ("What agents do I have?", "List my agents")
- User wants details on a specific agent ("Tell me about the researcher agent")

## Available Tools

| Tool | Purpose | Key Args |
|------|---------|----------|
| `list_agents` | Show all agents | (none) |
| `get_agent` | Get agent details | name |
| `create_agent` | Create/update agent | name, description, system_prompt, capabilities |

## Pattern

**Creating an agent:**
1. Ask the user for the agent's purpose
2. Generate a descriptive name (lowercase, underscores — e.g., "research_analyst")
3. Write a focused system prompt
4. Define relevant capabilities (comma-separated: "web_search,memory_read,document_search")
5. Call `create_agent`

**Listing/viewing:**
1. Call `list_agents` for overview or `get_agent` for details
2. Present in organized format with name, description, and capabilities

## Capability Options

**Implemented capabilities** (mapped to runtime tools):
`memory_read`, `memory_write`, `document_search`, `calendar_read`, `reminders_read`, `reminders_write`, `notifications`, `mail_read`, `mail_write`, `decision_read`, `decision_write`, `delegation_read`, `delegation_write`, `alerts_read`, `alerts_write`, `scheduling`, `agent_memory_read`, `agent_memory_write`, `channel_read`, `proactive_read`, `webhook_read`, `webhook_write`, `scheduler_read`, `scheduler_write`, `skill_read`, `skill_write`

**Legacy capabilities** (accepted but no local runtime tools):
`web_search`, `code_analysis`, `writing`, `editing`, `data_analysis`, `planning`, `file_operations`, `code_execution`

## Common Mistakes

- Agent names with spaces — use underscores or hyphens
- Overly broad system prompts — keep them focused on the agent's specialty
- Empty capabilities — always declare what the agent can do
