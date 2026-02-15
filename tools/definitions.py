# tools/definitions.py

CHIEF_TOOLS = [
    {
        "name": "query_memory",
        "description": "Look up facts, locations, or personal details from shared memory. Use this to recall things about the user or context from previous conversations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term to look up"},
                "category": {
                    "type": "string",
                    "description": "Optional category filter",
                    "enum": ["personal", "preference", "work", "relationship", "location"],
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "store_memory",
        "description": "Save a new fact or detail to shared memory so it can be recalled later.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Fact category",
                    "enum": ["personal", "preference", "work", "relationship"],
                },
                "key": {"type": "string", "description": "Fact key (e.g., 'name', 'favorite_food')"},
                "value": {"type": "string", "description": "Fact value"},
            },
            "required": ["category", "key", "value"],
        },
    },
    {
        "name": "search_documents",
        "description": "Search over ingested documents using semantic similarity. Returns relevant passages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "top_k": {"type": "integer", "description": "Number of results", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_agents",
        "description": "List all available expert agents and their descriptions.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "dispatch_agent",
        "description": "Send a task to a specific expert agent and get their response.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Name of the expert agent to dispatch"},
                "task": {"type": "string", "description": "The task description for the agent"},
            },
            "required": ["agent_name", "task"],
        },
    },
    {
        "name": "create_agent",
        "description": "Create a new expert agent when no existing agent has the right expertise. Provide explicit config fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent name (lowercase, underscores, e.g. 'event_planner')"},
                "description": {"type": "string", "description": "One-line description of expertise"},
                "system_prompt": {"type": "string", "description": "Detailed system prompt for the agent"},
                "capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of capabilities: memory_read, memory_write, document_search",
                },
            },
            "required": ["name", "description", "system_prompt"],
        },
    },
    {
        "name": "dispatch_parallel",
        "description": "Send tasks to multiple expert agents simultaneously. Use when a request benefits from multiple perspectives or specialties.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "List of agent-task pairs to dispatch in parallel",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent_name": {"type": "string"},
                            "task": {"type": "string"},
                        },
                        "required": ["agent_name", "task"],
                    },
                },
            },
            "required": ["tasks"],
        },
    },
    {
        "name": "log_decision",
        "description": "Log a decision for tracking and follow-up. Use when the user mentions a decision that was made, needs to be made, or should be recorded.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title of the decision"},
                "description": {"type": "string", "description": "Detailed description"},
                "context": {"type": "string", "description": "Background context or rationale"},
                "decided_by": {"type": "string", "description": "Who made the decision"},
                "owner": {"type": "string", "description": "Who is responsible for execution"},
                "status": {
                    "type": "string",
                    "description": "Decision status",
                    "enum": ["pending_execution", "executed", "deferred", "reversed"],
                    "default": "pending_execution",
                },
                "follow_up_date": {"type": "string", "description": "Follow-up date (YYYY-MM-DD)"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "source": {"type": "string", "description": "Where the decision was made"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "add_delegation",
        "description": "Track a task delegated to someone. Use when the user assigns or mentions assigning work to another person.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Short description of the task"},
                "delegated_to": {"type": "string", "description": "Who the task is assigned to"},
                "description": {"type": "string", "description": "Detailed expectations"},
                "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD)"},
                "priority": {
                    "type": "string",
                    "description": "Priority level",
                    "enum": ["low", "medium", "high", "critical"],
                    "default": "medium",
                },
                "source": {"type": "string", "description": "Origin of the delegation"},
            },
            "required": ["task", "delegated_to"],
        },
    },
    {
        "name": "check_alerts",
        "description": "Check for overdue delegations, stale pending decisions, and upcoming deadlines. Use proactively at the start of conversations or when asked for a status update.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_calendars",
        "description": "List all calendars available on this Mac, including Exchange/Outlook synced calendars.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_calendar_events",
        "description": "Get calendar events within a date range. Returns event details including title, time, location, attendees, and calendar name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"},
                "calendar_name": {"type": "string", "description": "Optional: filter to a specific calendar"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a new calendar event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start_date": {"type": "string", "description": "Start date/time (YYYY-MM-DDTHH:MM:SS)"},
                "end_date": {"type": "string", "description": "End date/time (YYYY-MM-DDTHH:MM:SS)"},
                "calendar_name": {"type": "string", "description": "Which calendar to add to"},
                "location": {"type": "string", "description": "Event location"},
                "notes": {"type": "string", "description": "Event notes/description"},
                "is_all_day": {"type": "boolean", "description": "Whether this is an all-day event"},
            },
            "required": ["title", "start_date", "end_date"],
        },
    },
    {
        "name": "list_reminder_lists",
        "description": "List all reminder lists (Apple Reminders) available on this Mac.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_reminders",
        "description": "Get reminders, optionally filtered by list name and completion status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "Optional: filter to a specific reminder list"},
                "completed": {"type": "boolean", "description": "Optional: true for completed only, false for incomplete only, omit for all"},
            },
        },
    },
    {
        "name": "create_reminder",
        "description": "Create a new reminder in Apple Reminders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Reminder title"},
                "list_name": {"type": "string", "description": "Which reminder list to add to (uses default if omitted)"},
                "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"},
                "priority": {"type": "integer", "description": "Priority: 0=none, 1=high, 4=medium, 9=low"},
                "notes": {"type": "string", "description": "Notes/description for the reminder"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "complete_reminder",
        "description": "Mark a reminder as completed by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "string", "description": "The ID of the reminder to complete"},
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "search_reminders",
        "description": "Search reminders by title text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for in reminder titles"},
                "include_completed": {"type": "boolean", "description": "Whether to include completed reminders (default: false)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "send_notification",
        "description": "Send a macOS notification to the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Notification title"},
                "message": {"type": "string", "description": "Notification body text"},
                "subtitle": {"type": "string", "description": "Optional subtitle"},
                "sound": {"type": "string", "description": "Sound name (default: 'default')"},
            },
            "required": ["title", "message"],
        },
    },
]


def get_chief_tools() -> list[dict]:
    return CHIEF_TOOLS
