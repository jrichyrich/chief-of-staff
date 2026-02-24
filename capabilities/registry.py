"""Canonical capability registry for agent creation, validation, and execution."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Iterable


TOOL_SCHEMAS: dict[str, dict] = {
    "query_memory": {
        "name": "query_memory",
        "description": "Look up facts, locations, or personal details from shared memory",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term to look up in memory"},
                "category": {
                    "type": "string",
                    "description": "Optional category filter (personal, preference, work, relationship, location)",
                },
            },
            "required": ["query"],
        },
    },
    "store_memory": {
        "name": "store_memory",
        "description": "Save a new fact to shared memory",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Fact category (personal, preference, work, relationship)",
                },
                "key": {"type": "string", "description": "Fact key (e.g., 'name', 'favorite_food')"},
                "value": {"type": "string", "description": "Fact value"},
            },
            "required": ["category", "key", "value"],
        },
    },
    "search_documents": {
        "name": "search_documents",
        "description": "Semantic search over ingested documents",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    "get_calendar_events": {
        "name": "get_calendar_events",
        "description": "Get calendar events within a date range across available providers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD or ISO datetime)"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD or ISO datetime)"},
                "calendar_name": {"type": "string", "description": "Optional: filter by calendar name"},
                "provider_preference": {"type": "string", "description": "Optional: auto, apple, microsoft_365, or both"},
                "source_filter": {"type": "string", "description": "Optional: source/provider text filter"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    "search_calendar_events": {
        "name": "search_calendar_events",
        "description": "Search calendar events by title text across available providers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for in event titles"},
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD), optional"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD), optional"},
                "provider_preference": {"type": "string", "description": "Optional: auto, apple, microsoft_365, or both"},
                "source_filter": {"type": "string", "description": "Optional: source/provider text filter"},
            },
            "required": ["query"],
        },
    },
    "list_reminders": {
        "name": "list_reminders",
        "description": "Get reminders, optionally filtered by list name and completion status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "Optional list name filter"},
                "completed": {
                    "type": "boolean",
                    "description": "Optional: true for completed only, false for incomplete only",
                },
            },
        },
    },
    "search_reminders": {
        "name": "search_reminders",
        "description": "Search reminders by title text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for"},
                "include_completed": {
                    "type": "boolean",
                    "description": "Whether to include completed reminders",
                },
            },
            "required": ["query"],
        },
    },
    "create_reminder": {
        "name": "create_reminder",
        "description": "Create a new reminder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Reminder title"},
                "list_name": {"type": "string", "description": "Reminder list name"},
                "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD or ISO datetime)"},
                "priority": {"type": "integer", "description": "Priority: 0=none, 1=high, 4=medium, 9=low"},
                "notes": {"type": "string", "description": "Reminder notes"},
            },
            "required": ["title"],
        },
    },
    "complete_reminder": {
        "name": "complete_reminder",
        "description": "Mark a reminder as completed by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "string", "description": "Reminder ID"},
            },
            "required": ["reminder_id"],
        },
    },
    "send_notification": {
        "name": "send_notification",
        "description": "Send a macOS notification to the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Notification title"},
                "message": {"type": "string", "description": "Notification body text"},
                "subtitle": {"type": "string", "description": "Optional subtitle"},
                "sound": {"type": "string", "description": "Sound name"},
            },
            "required": ["title", "message"],
        },
    },
    "get_mail_messages": {
        "name": "get_mail_messages",
        "description": "Get recent email messages from a mailbox (headers only).",
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox name (default: INBOX)"},
                "account": {"type": "string", "description": "Account name filter"},
                "limit": {"type": "integer", "description": "Max messages to return"},
            },
        },
    },
    "get_mail_message": {
        "name": "get_mail_message",
        "description": "Get full email content by Message-ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Message-ID"},
            },
            "required": ["message_id"],
        },
    },
    "search_mail": {
        "name": "search_mail",
        "description": "Search emails by subject and sender text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text"},
                "mailbox": {"type": "string", "description": "Mailbox name"},
                "account": {"type": "string", "description": "Account name"},
                "limit": {"type": "integer", "description": "Max results"},
            },
            "required": ["query"],
        },
    },
    "get_unread_count": {
        "name": "get_unread_count",
        "description": "Get unread email count for a mailbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox name (default: INBOX)"},
                "account": {"type": "string", "description": "Account name"},
            },
        },
    },
    "send_email": {
        "name": "send_email",
        "description": "Send an email. Requires explicit confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Comma-separated recipient addresses"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body"},
                "cc": {"type": "string", "description": "Comma-separated CC addresses"},
                "bcc": {"type": "string", "description": "Comma-separated BCC addresses"},
                "confirm_send": {"type": "boolean", "description": "Must be true to send"},
            },
            "required": ["to", "subject", "body", "confirm_send"],
        },
    },
    "mark_mail_read": {
        "name": "mark_mail_read",
        "description": "Mark an email as read or unread.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Message-ID"},
                "read": {"type": "boolean", "description": "True for read"},
            },
            "required": ["message_id"],
        },
    },
    "mark_mail_flagged": {
        "name": "mark_mail_flagged",
        "description": "Flag or unflag an email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Message-ID"},
                "flagged": {"type": "boolean", "description": "True to flag"},
            },
            "required": ["message_id"],
        },
    },
    "move_mail_message": {
        "name": "move_mail_message",
        "description": "Move an email to another mailbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Message-ID"},
                "target_mailbox": {"type": "string", "description": "Target mailbox"},
                "target_account": {"type": "string", "description": "Target account"},
            },
            "required": ["message_id", "target_mailbox"],
        },
    },
    "open_teams_browser": {
        "name": "open_teams_browser",
        "description": "Launch persistent Chromium browser and navigate to Teams.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    "post_teams_message": {
        "name": "post_teams_message",
        "description": "Search for a Teams channel or person by name and prepare a message. Returns confirmation info — call confirm_teams_post to send.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Channel name or person name (e.g. 'Engineering', 'John Smith')",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to post",
                },
            },
            "required": ["target", "message"],
        },
    },
    "confirm_teams_post": {
        "name": "confirm_teams_post",
        "description": "Send the previously prepared Teams message after user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    "cancel_teams_post": {
        "name": "cancel_teams_post",
        "description": "Cancel the previously prepared Teams message.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    "close_teams_browser": {
        "name": "close_teams_browser",
        "description": "Close the persistent Teams browser process.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    "create_decision": {
        "name": "create_decision",
        "description": "Log a decision for tracking and follow-up.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Decision title"},
                "description": {"type": "string", "description": "Decision details"},
                "context": {"type": "string", "description": "Decision context"},
                "decided_by": {"type": "string", "description": "Who made the decision"},
                "owner": {"type": "string", "description": "Execution owner"},
                "status": {
                    "type": "string",
                    "enum": ["pending_execution", "executed", "deferred", "reversed"],
                    "description": "Decision status",
                },
                "follow_up_date": {"type": "string", "description": "Follow-up date YYYY-MM-DD"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "source": {"type": "string", "description": "Where this decision was made"},
            },
            "required": ["title"],
        },
    },
    "search_decisions": {
        "name": "search_decisions",
        "description": "Search decisions by text and/or status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "status": {"type": "string", "description": "Filter by decision status"},
            },
        },
    },
    "update_decision": {
        "name": "update_decision",
        "description": "Update a decision status or append notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "decision_id": {"type": "integer", "description": "Decision ID"},
                "status": {"type": "string", "description": "New decision status"},
                "notes": {"type": "string", "description": "Notes to append"},
            },
            "required": ["decision_id"],
        },
    },
    "list_pending_decisions": {
        "name": "list_pending_decisions",
        "description": "List all decisions with pending execution.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "delete_decision": {
        "name": "delete_decision",
        "description": "Delete a decision by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "decision_id": {"type": "integer", "description": "Decision ID"},
            },
            "required": ["decision_id"],
        },
    },
    "create_delegation": {
        "name": "create_delegation",
        "description": "Track a delegated task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Delegated task"},
                "delegated_to": {"type": "string", "description": "Assignee"},
                "description": {"type": "string", "description": "Delegation details"},
                "due_date": {"type": "string", "description": "Due date YYYY-MM-DD"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Priority level",
                },
                "source": {"type": "string", "description": "Delegation source"},
            },
            "required": ["task", "delegated_to"],
        },
    },
    "list_delegations": {
        "name": "list_delegations",
        "description": "List delegations with optional filters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Status filter"},
                "delegated_to": {"type": "string", "description": "Assignee filter"},
            },
        },
    },
    "update_delegation": {
        "name": "update_delegation",
        "description": "Update delegation status or notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "delegation_id": {"type": "integer", "description": "Delegation ID"},
                "status": {"type": "string", "description": "New status"},
                "notes": {"type": "string", "description": "Notes to append"},
            },
            "required": ["delegation_id"],
        },
    },
    "check_overdue_delegations": {
        "name": "check_overdue_delegations",
        "description": "Return active delegations past due date.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "delete_delegation": {
        "name": "delete_delegation",
        "description": "Delete a delegation by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "delegation_id": {"type": "integer", "description": "Delegation ID"},
            },
            "required": ["delegation_id"],
        },
    },
    "create_alert_rule": {
        "name": "create_alert_rule",
        "description": "Create or update an alert rule.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Alert rule name"},
                "alert_type": {"type": "string", "description": "Alert type"},
                "description": {"type": "string", "description": "Human-readable description"},
                "condition": {"type": "string", "description": "Condition expression"},
                "enabled": {"type": "boolean", "description": "Whether alert is active"},
            },
            "required": ["name", "alert_type"],
        },
    },
    "list_alert_rules": {
        "name": "list_alert_rules",
        "description": "List configured alert rules.",
        "input_schema": {
            "type": "object",
            "properties": {
                "enabled_only": {"type": "boolean", "description": "Return only enabled rules"},
            },
        },
    },
    "check_alerts": {
        "name": "check_alerts",
        "description": "Check for overdue delegations, stale decisions, and upcoming deadlines.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "dismiss_alert": {
        "name": "dismiss_alert",
        "description": "Disable an alert rule.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "integer", "description": "Alert rule ID"},
            },
            "required": ["rule_id"],
        },
    },
    "find_my_open_slots": {
        "name": "find_my_open_slots",
        "description": "Find available time slots in your calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                "duration_minutes": {"type": "integer", "description": "Minimum slot duration"},
                "include_soft_blocks": {"type": "boolean", "description": "Treat soft blocks as available"},
                "soft_keywords": {"type": "string", "description": "Comma-separated soft keywords"},
                "calendar_name": {"type": "string", "description": "Calendar filter"},
                "working_hours_start": {"type": "string", "description": "Working start time HH:MM"},
                "working_hours_end": {"type": "string", "description": "Working end time HH:MM"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    "find_group_availability": {
        "name": "find_group_availability",
        "description": "Guidance for finding group meeting times across calendars.",
        "input_schema": {
            "type": "object",
            "properties": {
                "participants": {"type": "string", "description": "Comma-separated emails"},
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                "duration_minutes": {"type": "integer", "description": "Meeting duration"},
                "include_my_soft_blocks": {"type": "boolean", "description": "Treat soft blocks as available"},
                "max_suggestions": {"type": "integer", "description": "Max suggestions to return"},
            },
            "required": ["participants", "start_date", "end_date"],
        },
    },
    # --- Agent memory tools ---
    "get_agent_memory": {
        "name": "get_agent_memory",
        "description": "Get all memories stored by a specific agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "The agent name to retrieve memories for"},
            },
            "required": ["agent_name"],
        },
    },
    "clear_agent_memory": {
        "name": "clear_agent_memory",
        "description": "Delete all memories for a specific agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "The agent name whose memories should be cleared"},
            },
            "required": ["agent_name"],
        },
    },
    # --- Channel tools ---
    "list_inbound_events": {
        "name": "list_inbound_events",
        "description": "List recent inbound events normalized across channels (iMessage, Mail, Webhook).",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Filter by channel (imessage, mail, webhook)"},
                "event_type": {"type": "string", "description": "Filter by event type (message, email, webhook_event)"},
                "limit": {"type": "integer", "description": "Maximum events per channel (default 25, max 100)"},
            },
        },
    },
    "get_event_summary": {
        "name": "get_event_summary",
        "description": "Get a count of recent inbound events by channel.",
        "input_schema": {"type": "object", "properties": {}},
    },
    # --- Proactive tools ---
    "get_proactive_suggestions": {
        "name": "get_proactive_suggestions",
        "description": "Run the proactive suggestion engine and return prioritized suggestions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "dismiss_suggestion": {
        "name": "dismiss_suggestion",
        "description": "Dismiss a proactive suggestion so it doesn't reappear.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "The suggestion category"},
                "title": {"type": "string", "description": "The title of the suggestion to dismiss"},
            },
            "required": ["category", "title"],
        },
    },
    # --- Webhook tools ---
    "list_webhook_events": {
        "name": "list_webhook_events",
        "description": "List webhook events with optional filters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status (pending, processed, failed)"},
                "source": {"type": "string", "description": "Filter by event source"},
                "limit": {"type": "integer", "description": "Maximum events to return (default 50, max 500)"},
            },
        },
    },
    "get_webhook_event": {
        "name": "get_webhook_event",
        "description": "Get full details of a webhook event including its payload.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer", "description": "The ID of the webhook event to retrieve"},
            },
            "required": ["event_id"],
        },
    },
    "process_webhook_event": {
        "name": "process_webhook_event",
        "description": "Mark a webhook event as processed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer", "description": "The ID of the webhook event to mark as processed"},
            },
            "required": ["event_id"],
        },
    },
    # --- Scheduler tools ---
    "list_scheduled_tasks": {
        "name": "list_scheduled_tasks",
        "description": "List all scheduled tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "enabled_only": {"type": "boolean", "description": "If True, only return enabled tasks"},
            },
        },
    },
    "get_scheduler_status": {
        "name": "get_scheduler_status",
        "description": "Get a summary of all scheduled tasks with their last and next run times.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "create_scheduled_task": {
        "name": "create_scheduled_task",
        "description": "Create a new scheduled task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique name for the task"},
                "schedule_type": {"type": "string", "description": "Type of schedule: interval, cron, or once"},
                "schedule_config": {"type": "string", "description": "JSON config for the schedule"},
                "handler_type": {"type": "string", "description": "Type of handler: alert_eval, backup, webhook_poll, or custom"},
                "handler_config": {"type": "string", "description": "JSON config for the handler"},
                "description": {"type": "string", "description": "Human-readable description"},
                "enabled": {"type": "boolean", "description": "Whether the task is active (default: True)"},
            },
            "required": ["name", "schedule_type", "schedule_config", "handler_type"],
        },
    },
    "update_scheduled_task": {
        "name": "update_scheduled_task",
        "description": "Update a scheduled task's configuration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The ID of the task to update"},
                "enabled": {"type": "boolean", "description": "Enable or disable the task"},
                "schedule_config": {"type": "string", "description": "New schedule config (JSON string)"},
                "handler_config": {"type": "string", "description": "New handler config (JSON string)"},
            },
            "required": ["task_id"],
        },
    },
    "delete_scheduled_task": {
        "name": "delete_scheduled_task",
        "description": "Delete a scheduled task by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The ID of the task to delete"},
            },
            "required": ["task_id"],
        },
    },
    "run_scheduled_task": {
        "name": "run_scheduled_task",
        "description": "Manually trigger a scheduled task to run now.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The ID of the task to run"},
            },
            "required": ["task_id"],
        },
    },
    # --- Skill tools ---
    "list_skill_suggestions": {
        "name": "list_skill_suggestions",
        "description": "List skill suggestions filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status (pending, accepted, rejected)"},
            },
        },
    },
    "record_tool_usage": {
        "name": "record_tool_usage",
        "description": "Record a tool usage pattern for skill analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "Name of the tool that was used"},
                "query_pattern": {"type": "string", "description": "Description of the usage pattern"},
            },
            "required": ["tool_name", "query_pattern"],
        },
    },
    "analyze_skill_patterns": {
        "name": "analyze_skill_patterns",
        "description": "Analyze recorded tool usage patterns and generate skill suggestions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "auto_create_skill": {
        "name": "auto_create_skill",
        "description": "Accept a skill suggestion and create an agent from it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "suggestion_id": {"type": "integer", "description": "The ID of the skill suggestion to accept"},
            },
            "required": ["suggestion_id"],
        },
    },
}


@dataclass(frozen=True)
class CapabilityDefinition:
    name: str
    description: str
    tool_names: tuple[str, ...] = ()
    implemented: bool = True


CAPABILITY_DEFINITIONS: dict[str, CapabilityDefinition] = {
    "memory_read": CapabilityDefinition(
        name="memory_read",
        description="Read from shared memory (facts, locations, and personal context)",
        tool_names=("query_memory",),
    ),
    "memory_write": CapabilityDefinition(
        name="memory_write",
        description="Write facts to shared memory",
        tool_names=("store_memory",),
    ),
    "document_search": CapabilityDefinition(
        name="document_search",
        description="Search ingested documents semantically",
        tool_names=("search_documents",),
    ),
    "calendar_read": CapabilityDefinition(
        name="calendar_read",
        description="Read and search calendar events",
        tool_names=("get_calendar_events", "search_calendar_events"),
    ),
    "reminders_read": CapabilityDefinition(
        name="reminders_read",
        description="Read and search reminders",
        tool_names=("list_reminders", "search_reminders"),
    ),
    "reminders_write": CapabilityDefinition(
        name="reminders_write",
        description="Create and complete reminders",
        tool_names=("create_reminder", "complete_reminder"),
    ),
    "notifications": CapabilityDefinition(
        name="notifications",
        description="Send user-facing notifications",
        tool_names=("send_notification",),
    ),
    "mail_read": CapabilityDefinition(
        name="mail_read",
        description="Read and search mailboxes and messages",
        tool_names=("get_mail_messages", "get_mail_message", "search_mail", "get_unread_count"),
    ),
    "mail_write": CapabilityDefinition(
        name="mail_write",
        description="Send and update email state",
        tool_names=("send_email", "mark_mail_read", "mark_mail_flagged", "move_mail_message"),
    ),
    "teams_write": CapabilityDefinition(
        name="teams_write",
        description="Post messages to Microsoft Teams channels via persistent browser automation",
        tool_names=("open_teams_browser", "post_teams_message", "confirm_teams_post", "cancel_teams_post", "close_teams_browser"),
    ),
    "decision_read": CapabilityDefinition(
        name="decision_read",
        description="Search and list tracked decisions",
        tool_names=("search_decisions", "list_pending_decisions"),
    ),
    "decision_write": CapabilityDefinition(
        name="decision_write",
        description="Log, update, and delete tracked decisions",
        tool_names=("create_decision", "update_decision", "delete_decision"),
    ),
    "delegation_read": CapabilityDefinition(
        name="delegation_read",
        description="List delegation status and overdue items",
        tool_names=("list_delegations", "check_overdue_delegations"),
    ),
    "delegation_write": CapabilityDefinition(
        name="delegation_write",
        description="Create, update, and delete delegations",
        tool_names=("create_delegation", "update_delegation", "delete_delegation"),
    ),
    "alerts_read": CapabilityDefinition(
        name="alerts_read",
        description="Run and inspect proactive alert checks",
        tool_names=("check_alerts", "list_alert_rules"),
    ),
    "alerts_write": CapabilityDefinition(
        name="alerts_write",
        description="Create and dismiss alert rules",
        tool_names=("create_alert_rule", "dismiss_alert"),
    ),
    "scheduling": CapabilityDefinition(
        name="scheduling",
        description="Find available calendar slots and analyze group availability",
        tool_names=("find_my_open_slots", "find_group_availability"),
    ),
    "agent_memory_read": CapabilityDefinition(
        name="agent_memory_read",
        description="Read agent-specific memories",
        tool_names=("get_agent_memory",),
    ),
    "agent_memory_write": CapabilityDefinition(
        name="agent_memory_write",
        description="Clear agent-specific memories",
        tool_names=("clear_agent_memory",),
    ),
    "channel_read": CapabilityDefinition(
        name="channel_read",
        description="Read unified inbound events across channels",
        tool_names=("list_inbound_events", "get_event_summary"),
    ),
    "proactive_read": CapabilityDefinition(
        name="proactive_read",
        description="Read and dismiss proactive suggestions",
        tool_names=("get_proactive_suggestions", "dismiss_suggestion"),
    ),
    "webhook_read": CapabilityDefinition(
        name="webhook_read",
        description="List and inspect webhook events",
        tool_names=("list_webhook_events", "get_webhook_event"),
    ),
    "webhook_write": CapabilityDefinition(
        name="webhook_write",
        description="Process and update webhook event status",
        tool_names=("process_webhook_event",),
    ),
    "scheduler_read": CapabilityDefinition(
        name="scheduler_read",
        description="List scheduled tasks and view scheduler status",
        tool_names=("list_scheduled_tasks", "get_scheduler_status"),
    ),
    "scheduler_write": CapabilityDefinition(
        name="scheduler_write",
        description="Create, update, delete, and run scheduled tasks",
        tool_names=("create_scheduled_task", "update_scheduled_task", "delete_scheduled_task", "run_scheduled_task"),
    ),
    "skill_read": CapabilityDefinition(
        name="skill_read",
        description="List skill suggestions from pattern analysis",
        tool_names=("list_skill_suggestions",),
    ),
    "skill_write": CapabilityDefinition(
        name="skill_write",
        description="Record tool usage, analyze patterns, and auto-create skills",
        tool_names=("record_tool_usage", "analyze_skill_patterns", "auto_create_skill"),
    ),
    # Accepted legacy/non-runtime capabilities kept for compatibility.
    "web_search": CapabilityDefinition(
        name="web_search",
        description="Legacy capability for web lookup (no local runtime tool mapping yet)",
        implemented=False,
    ),
    "code_analysis": CapabilityDefinition(
        name="code_analysis",
        description="Legacy capability for static code analysis workflows",
        implemented=False,
    ),
    "writing": CapabilityDefinition(
        name="writing",
        description="Legacy capability for long-form writing assistance",
        implemented=False,
    ),
    "editing": CapabilityDefinition(
        name="editing",
        description="Legacy capability for editing-focused writing workflows",
        implemented=False,
    ),
    "data_analysis": CapabilityDefinition(
        name="data_analysis",
        description="Legacy capability for analytical workflows",
        implemented=False,
    ),
    "planning": CapabilityDefinition(
        name="planning",
        description="Legacy capability for planning workflows",
        implemented=False,
    ),
    "file_operations": CapabilityDefinition(
        name="file_operations",
        description="Legacy capability for local file manipulation",
        implemented=False,
    ),
    "code_execution": CapabilityDefinition(
        name="code_execution",
        description="Legacy capability for code execution workflows",
        implemented=False,
    ),
}


def get_capability_names(include_unimplemented: bool = True) -> list[str]:
    """Return known capability names sorted alphabetically."""
    items = []
    for name, definition in CAPABILITY_DEFINITIONS.items():
        if include_unimplemented or definition.implemented:
            items.append(name)
    return sorted(items)


def validate_capabilities(capabilities: Iterable[str] | None) -> list[str]:
    """Validate and normalize capability names.

    Returns a de-duplicated list preserving first-seen order.
    """
    if capabilities is None:
        return []

    seen: set[str] = set()
    normalized: list[str] = []

    for raw in capabilities:
        name = (raw or "").strip()
        if not name:
            continue
        if name not in CAPABILITY_DEFINITIONS:
            valid = ", ".join(get_capability_names(include_unimplemented=True))
            raise ValueError(f"Unknown capability '{name}'. Valid capabilities: {valid}")
        if name not in seen:
            normalized.append(name)
            seen.add(name)

    return normalized


def parse_capabilities_csv(capabilities_csv: str) -> list[str]:
    """Parse comma-separated capabilities and validate them."""
    parts = [piece.strip() for piece in capabilities_csv.split(",") if piece.strip()]
    return validate_capabilities(parts)


def get_tools_for_capabilities(capabilities: Iterable[str] | None) -> list[dict]:
    """Return tool schemas for the given capabilities.

    Capabilities without runtime tool mappings are treated as no-op and ignored.
    """
    validated = validate_capabilities(capabilities)
    tools: list[dict] = []
    seen_tool_names: set[str] = set()

    for capability_name in validated:
        definition = CAPABILITY_DEFINITIONS[capability_name]
        for tool_name in definition.tool_names:
            if tool_name in seen_tool_names:
                continue
            schema = TOOL_SCHEMAS.get(tool_name)
            if schema is None:
                continue
            tools.append(deepcopy(schema))
            seen_tool_names.add(tool_name)

    return tools


def capability_prompt_lines(include_unimplemented: bool = True) -> list[str]:
    """Return capability descriptions formatted for prompt text."""
    lines: list[str] = []
    for name in get_capability_names(include_unimplemented=include_unimplemented):
        definition = CAPABILITY_DEFINITIONS[name]
        suffix = "" if definition.implemented else " [legacy/no local tools]"
        lines.append(f"{name}: {definition.description}{suffix}")
    return lines
