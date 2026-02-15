# mcp_server.py
"""Chief of Staff MCP Server -- Claude Desktop & Claude Code plugin.

Exposes granular tools for memory, document search, and agent management.
No internal LLM calls — the host Claude handles all reasoning.
"""

import json
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import config as app_config
from agents.registry import AgentConfig, AgentRegistry
from apple_calendar.eventkit import CalendarStore
from documents.ingestion import ingest_path as _ingest_path
from documents.store import DocumentStore
from memory.models import AlertRule, Decision, Delegation, Fact, Location
from memory.store import MemoryStore

# All logging to stderr (stdout is the JSON-RPC channel for stdio transport)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("jarvis-mcp")

# Module-level state populated by the lifespan manager.
_state: dict = {}


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize shared resources on startup, clean up on shutdown."""
    app_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    app_config.AGENT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    memory_store = MemoryStore(app_config.MEMORY_DB_PATH)
    document_store = DocumentStore(persist_dir=app_config.CHROMA_PERSIST_DIR)
    agent_registry = AgentRegistry(app_config.AGENT_CONFIGS_DIR)
    calendar_store = CalendarStore()

    _state.update({
        "memory_store": memory_store,
        "document_store": document_store,
        "agent_registry": agent_registry,
        "calendar_store": calendar_store,
    })

    logger.info("Jarvis MCP server initialized")

    try:
        yield
    finally:
        _state.clear()
        memory_store.close()
        logger.info("Jarvis MCP server shut down")


mcp = FastMCP(
    "jarvis",
    lifespan=app_lifespan,
)


# --- Memory Tools ---


VALID_CATEGORIES = {"personal", "preference", "work", "relationship"}


@mcp.tool()
async def store_fact(category: str, key: str, value: str, confidence: float = 1.0) -> str:
    """Store a fact about the user in long-term memory. Overwrites if category+key already exists.

    Args:
        category: One of 'personal', 'preference', 'work', 'relationship'
        key: Short label for the fact (e.g. 'name', 'favorite_color', 'job_title')
        value: The fact value
        confidence: Confidence score from 0.0 to 1.0 (default 1.0)
    """
    if category not in VALID_CATEGORIES:
        return json.dumps({
            "error": f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
        })
    memory_store = _state["memory_store"]
    fact = Fact(category=category, key=key, value=value, confidence=confidence)
    stored = memory_store.store_fact(fact)
    return json.dumps({
        "status": "stored",
        "category": stored.category,
        "key": stored.key,
        "value": stored.value,
    })


@mcp.tool()
async def delete_fact(category: str, key: str) -> str:
    """Delete a fact from long-term memory.

    Args:
        category: The fact category (personal, preference, work, relationship)
        key: The fact key to delete
    """
    if category not in VALID_CATEGORIES:
        return json.dumps({
            "error": f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
        })
    memory_store = _state["memory_store"]
    deleted = memory_store.delete_fact(category, key)
    if deleted:
        return json.dumps({"status": "deleted", "category": category, "key": key})
    return json.dumps({"status": "not_found", "message": f"No fact found with category='{category}', key='{key}'"})


@mcp.tool()
async def query_memory(query: str, category: str = "") -> str:
    """Search stored facts about the user. Returns matching facts.

    Args:
        query: Search term to match against fact keys and values
        category: Optional — filter to a specific category (personal, preference, work, relationship). Leave empty to search all.
    """
    memory_store = _state["memory_store"]

    if category:
        facts = memory_store.get_facts_by_category(category)
        # Filter by query text within the category results
        if query:
            q = query.lower()
            facts = [f for f in facts if q in f.value.lower() or q in f.key.lower()]
    else:
        facts = memory_store.search_facts(query)

    if not facts:
        return json.dumps({"message": f"No facts found for query '{query}'.", "results": []})

    results = [{"category": f.category, "key": f.key, "value": f.value, "confidence": f.confidence} for f in facts]
    return json.dumps({"results": results})


@mcp.tool()
async def store_location(name: str, address: str = "", notes: str = "",
                         latitude: float = 0.0, longitude: float = 0.0) -> str:
    """Store a named location in memory.

    Args:
        name: Location name (e.g. 'home', 'office', 'favorite_restaurant')
        address: Street address
        notes: Additional notes about this location
        latitude: GPS latitude (optional, 0.0 if unknown)
        longitude: GPS longitude (optional, 0.0 if unknown)
    """
    memory_store = _state["memory_store"]
    loc = Location(
        name=name,
        address=address or None,
        notes=notes or None,
        latitude=latitude if latitude != 0.0 else None,
        longitude=longitude if longitude != 0.0 else None,
    )
    stored = memory_store.store_location(loc)
    return json.dumps({"status": "stored", "name": stored.name, "address": stored.address})


@mcp.tool()
async def list_locations() -> str:
    """List all stored locations."""
    memory_store = _state["memory_store"]
    locations = memory_store.list_locations()
    if not locations:
        return json.dumps({"message": "No locations stored yet.", "results": []})
    results = [{"name": l.name, "address": l.address, "notes": l.notes} for l in locations]
    return json.dumps({"results": results})


# --- Document Tools ---


@mcp.tool()
async def search_documents(query: str, top_k: int = 5) -> str:
    """Semantic search over ingested documents. Returns the most relevant chunks.

    Args:
        query: Natural language search query
        top_k: Number of results to return (default 5)
    """
    document_store = _state["document_store"]
    results = document_store.search(query, top_k=top_k)

    if not results:
        return json.dumps({"message": "No documents found. Ingest documents first.", "results": []})

    return json.dumps({"results": results})


@mcp.tool()
async def ingest_documents(path: str) -> str:
    """Ingest documents from a file or directory into the knowledge base for semantic search.
    Supports .txt, .md, .py, .json, .yaml files.

    Args:
        path: Absolute path to a file or directory to ingest
    """
    document_store = _state["document_store"]
    target = Path(path).resolve()

    # Security: prevent path traversal outside allowed directories
    allowed_roots = _state.get("allowed_ingest_roots")
    if allowed_roots is None:
        allowed_roots = [Path.home().resolve()]
    if not any(str(target).startswith(str(root)) for root in allowed_roots):
        return f"Access denied: path must be within your home directory ({allowed_roots[0]})"

    if not target.exists():
        return f"Path not found: {path}"

    result = _ingest_path(target, document_store)
    logger.info(f"Ingested from {path}: {result}")
    return result


# --- Agent Tools ---


@mcp.tool()
async def list_agents() -> str:
    """List all available expert agent configurations."""
    agent_registry = _state["agent_registry"]
    agents = agent_registry.list_agents()
    if not agents:
        return json.dumps({"message": "No agents configured yet.", "results": []})
    results = [
        {"name": a.name, "description": a.description, "capabilities": a.capabilities}
        for a in agents
    ]
    return json.dumps({"results": results})


@mcp.tool()
async def get_agent(name: str) -> str:
    """Get full details for a specific expert agent by name.

    Args:
        name: The agent name to look up
    """
    agent_registry = _state["agent_registry"]
    agent = agent_registry.get_agent(name)
    if not agent:
        return json.dumps({"error": f"Agent '{name}' not found."})
    return json.dumps({
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "capabilities": agent.capabilities,
        "temperature": agent.temperature,
        "max_tokens": agent.max_tokens,
    })


@mcp.tool()
async def create_agent(name: str, description: str, system_prompt: str, capabilities: str = "") -> str:
    """Create or update an expert agent configuration.

    Args:
        name: Agent name (lowercase, no spaces — e.g. 'researcher', 'code_reviewer')
        description: What this agent specializes in
        system_prompt: The system prompt that defines this agent's behavior
        capabilities: Comma-separated list of capabilities (e.g. 'web_search,memory_read,document_search')
    """
    agent_registry = _state["agent_registry"]
    caps = [c.strip() for c in capabilities.split(",") if c.strip()] if capabilities else []
    config = AgentConfig(
        name=name,
        description=description,
        system_prompt=system_prompt,
        capabilities=caps,
    )
    agent_registry.save_agent(config)
    return json.dumps({"status": "created", "name": name, "capabilities": caps})


# --- Decision Log Tools ---


@mcp.tool()
async def log_decision(
    title: str,
    description: str = "",
    context: str = "",
    decided_by: str = "",
    owner: str = "",
    status: str = "pending_execution",
    follow_up_date: str = "",
    tags: str = "",
    source: str = "",
) -> str:
    """Log a decision for tracking and follow-up.

    Args:
        title: Short title of the decision (required)
        description: Detailed description of what was decided
        context: Background context or rationale
        decided_by: Who made the decision
        owner: Who is responsible for execution
        status: Decision status (default: pending_execution)
        follow_up_date: Date to follow up (YYYY-MM-DD)
        tags: Comma-separated tags for categorization
        source: Where the decision was made (e.g. meeting name, email)
    """
    memory_store = _state["memory_store"]
    decision = Decision(
        title=title,
        description=description,
        context=context,
        decided_by=decided_by,
        owner=owner,
        status=status,
        follow_up_date=follow_up_date or None,
        tags=tags,
        source=source,
    )
    stored = memory_store.store_decision(decision)
    return json.dumps({
        "status": "logged",
        "id": stored.id,
        "title": stored.title,
        "decision_status": stored.status,
    })


@mcp.tool()
async def search_decisions(query: str = "", status: str = "") -> str:
    """Search decisions by text and/or filter by status.

    Args:
        query: Text to search in title, description, and tags
        status: Filter by decision status (e.g. pending_execution, executed, deferred)
    """
    memory_store = _state["memory_store"]

    if status and query:
        decisions = memory_store.search_decisions(query)
        decisions = [d for d in decisions if d.status == status]
    elif status:
        decisions = memory_store.list_decisions_by_status(status)
    elif query:
        decisions = memory_store.search_decisions(query)
    else:
        # Return all decisions
        decisions = memory_store.search_decisions("")

    if not decisions:
        return json.dumps({"message": "No decisions found.", "results": []})

    results = [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "owner": d.owner,
            "decided_by": d.decided_by,
            "follow_up_date": d.follow_up_date,
            "tags": d.tags,
            "created_at": d.created_at,
        }
        for d in decisions
    ]
    return json.dumps({"results": results})


@mcp.tool()
async def update_decision(decision_id: int, status: str = "", notes: str = "") -> str:
    """Update a decision's status or add notes.

    Args:
        decision_id: The ID of the decision to update
        status: New status value
        notes: Additional notes to append to the description
    """
    memory_store = _state["memory_store"]
    existing = memory_store.get_decision(decision_id)
    if not existing:
        return json.dumps({"error": f"Decision {decision_id} not found."})

    kwargs = {}
    if status:
        kwargs["status"] = status
    if notes:
        updated_desc = f"{existing.description}\n\n[Update] {notes}".strip()
        kwargs["description"] = updated_desc

    if not kwargs:
        return json.dumps({"error": "No fields to update. Provide status or notes."})

    updated = memory_store.update_decision(decision_id, **kwargs)
    return json.dumps({
        "status": "updated",
        "id": updated.id,
        "title": updated.title,
        "decision_status": updated.status,
    })


@mcp.tool()
async def list_pending_decisions() -> str:
    """List all decisions with status 'pending_execution'."""
    memory_store = _state["memory_store"]
    decisions = memory_store.list_decisions_by_status("pending_execution")

    if not decisions:
        return json.dumps({"message": "No pending decisions.", "results": []})

    results = [
        {
            "id": d.id,
            "title": d.title,
            "owner": d.owner,
            "follow_up_date": d.follow_up_date,
            "created_at": d.created_at,
        }
        for d in decisions
    ]
    return json.dumps({"results": results})


# --- Delegation Tracker Tools ---


@mcp.tool()
async def add_delegation(
    task: str,
    delegated_to: str,
    description: str = "",
    due_date: str = "",
    priority: str = "medium",
    source: str = "",
) -> str:
    """Create a new delegation to track a task assigned to someone.

    Args:
        task: Short description of the delegated task (required)
        delegated_to: Who the task is delegated to (required)
        description: Detailed description of expectations
        due_date: Due date (YYYY-MM-DD)
        priority: Priority level (low, medium, high, critical)
        source: Where the delegation originated
    """
    memory_store = _state["memory_store"]
    delegation = Delegation(
        task=task,
        delegated_to=delegated_to,
        description=description,
        due_date=due_date or None,
        priority=priority,
        source=source,
    )
    stored = memory_store.store_delegation(delegation)
    return json.dumps({
        "status": "created",
        "id": stored.id,
        "task": stored.task,
        "delegated_to": stored.delegated_to,
        "due_date": stored.due_date,
    })


@mcp.tool()
async def list_delegations(status: str = "", delegated_to: str = "") -> str:
    """List delegations with optional filters.

    Args:
        status: Filter by status (active, completed, cancelled)
        delegated_to: Filter by who the task is delegated to
    """
    memory_store = _state["memory_store"]
    delegations = memory_store.list_delegations(
        status=status or None,
        delegated_to=delegated_to or None,
    )

    if not delegations:
        return json.dumps({"message": "No delegations found.", "results": []})

    results = [
        {
            "id": d.id,
            "task": d.task,
            "delegated_to": d.delegated_to,
            "status": d.status,
            "priority": d.priority,
            "due_date": d.due_date,
            "created_at": d.created_at,
        }
        for d in delegations
    ]
    return json.dumps({"results": results})


@mcp.tool()
async def update_delegation(delegation_id: int, status: str = "", notes: str = "") -> str:
    """Update a delegation's status or add notes.

    Args:
        delegation_id: The ID of the delegation to update
        status: New status value (active, completed, cancelled)
        notes: Additional notes
    """
    memory_store = _state["memory_store"]
    existing = memory_store.get_delegation(delegation_id)
    if not existing:
        return json.dumps({"error": f"Delegation {delegation_id} not found."})

    kwargs = {}
    if status:
        kwargs["status"] = status
    if notes:
        updated_notes = f"{existing.notes}\n{notes}".strip()
        kwargs["notes"] = updated_notes

    if not kwargs:
        return json.dumps({"error": "No fields to update. Provide status or notes."})

    updated = memory_store.update_delegation(delegation_id, **kwargs)
    return json.dumps({
        "status": "updated",
        "id": updated.id,
        "task": updated.task,
        "delegation_status": updated.status,
    })


@mcp.tool()
async def check_overdue_delegations() -> str:
    """Return all active delegations that are past their due date."""
    memory_store = _state["memory_store"]
    overdue = memory_store.list_overdue_delegations()

    if not overdue:
        return json.dumps({"message": "No overdue delegations.", "results": []})

    results = [
        {
            "id": d.id,
            "task": d.task,
            "delegated_to": d.delegated_to,
            "due_date": d.due_date,
            "priority": d.priority,
        }
        for d in overdue
    ]
    return json.dumps({"results": results})


# --- Alert Tools ---


@mcp.tool()
async def create_alert_rule(
    name: str,
    alert_type: str,
    description: str = "",
    condition: str = "",
    enabled: bool = True,
) -> str:
    """Create or update an alert rule.

    Args:
        name: Unique name for the alert rule (required)
        alert_type: Type of alert: overdue_delegation, pending_decision, upcoming_deadline (required)
        description: Human-readable description of what this alert checks
        condition: Machine-readable condition expression
        enabled: Whether the rule is active (default: True)
    """
    memory_store = _state["memory_store"]
    rule = AlertRule(
        name=name,
        description=description,
        alert_type=alert_type,
        condition=condition,
        enabled=enabled,
    )
    stored = memory_store.store_alert_rule(rule)
    return json.dumps({
        "status": "created",
        "id": stored.id,
        "name": stored.name,
        "alert_type": stored.alert_type,
        "enabled": stored.enabled,
    })


@mcp.tool()
async def list_alert_rules(enabled_only: bool = False) -> str:
    """List all alert rules.

    Args:
        enabled_only: If True, only return enabled rules
    """
    memory_store = _state["memory_store"]
    rules = memory_store.list_alert_rules(enabled_only=enabled_only)

    if not rules:
        return json.dumps({"message": "No alert rules configured.", "results": []})

    results = [
        {
            "id": r.id,
            "name": r.name,
            "alert_type": r.alert_type,
            "description": r.description,
            "enabled": r.enabled,
        }
        for r in rules
    ]
    return json.dumps({"results": results})


@mcp.tool()
async def check_alerts() -> str:
    """Run alert checks: overdue delegations, stale pending decisions (>7 days), and upcoming deadlines (within 3 days)."""
    from datetime import date, timedelta

    memory_store = _state["memory_store"]
    alerts = {"overdue_delegations": [], "stale_decisions": [], "upcoming_deadlines": []}

    # 1. Overdue delegations
    overdue = memory_store.list_overdue_delegations()
    for d in overdue:
        alerts["overdue_delegations"].append({
            "id": d.id,
            "task": d.task,
            "delegated_to": d.delegated_to,
            "due_date": d.due_date,
        })

    # 2. Pending decisions older than 7 days
    pending = memory_store.list_decisions_by_status("pending_execution")
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    for d in pending:
        if d.created_at and d.created_at[:10] < cutoff:
            alerts["stale_decisions"].append({
                "id": d.id,
                "title": d.title,
                "created_at": d.created_at,
            })

    # 3. Delegations due within 3 days
    today = date.today()
    soon = (today + timedelta(days=3)).isoformat()
    today_str = today.isoformat()
    active = memory_store.list_delegations(status="active")
    for d in active:
        if d.due_date and today_str <= d.due_date <= soon:
            alerts["upcoming_deadlines"].append({
                "id": d.id,
                "task": d.task,
                "delegated_to": d.delegated_to,
                "due_date": d.due_date,
            })

    total = sum(len(v) for v in alerts.values())
    return json.dumps({"total_alerts": total, "alerts": alerts})


@mcp.tool()
async def dismiss_alert(rule_id: int) -> str:
    """Disable an alert rule so it no longer triggers.

    Args:
        rule_id: The ID of the alert rule to disable
    """
    memory_store = _state["memory_store"]
    existing = memory_store.get_alert_rule(rule_id)
    if not existing:
        return json.dumps({"error": f"Alert rule {rule_id} not found."})

    updated = memory_store.update_alert_rule(rule_id, enabled=False)
    return json.dumps({
        "status": "dismissed",
        "id": updated.id,
        "name": updated.name,
        "enabled": updated.enabled,
    })


# --- Calendar Tools ---


def _parse_date(date_str: str) -> datetime:
    """Parse ISO date string to datetime."""
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        # Handle date-only format
        return datetime.strptime(date_str, "%Y-%m-%d")


@mcp.tool()
async def list_calendars() -> str:
    """List all calendars available on this Mac (including Exchange/Outlook synced ones)."""
    calendar_store = _state["calendar_store"]
    try:
        calendars = calendar_store.list_calendars()
        return json.dumps({"results": calendars})
    except Exception as e:
        return json.dumps({"error": f"Failed to list calendars: {e}"})


@mcp.tool()
async def get_calendar_events(start_date: str, end_date: str, calendar_name: str = "") -> str:
    """Get events in a date range. Dates in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). Optional calendar filter.

    Args:
        start_date: Start date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        end_date: End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        calendar_name: Optional calendar name to filter by
    """
    calendar_store = _state["calendar_store"]
    try:
        start_dt = _parse_date(start_date)
        end_dt = _parse_date(end_date)
        calendar_names = [calendar_name] if calendar_name else None
        events = calendar_store.get_events(start_dt, end_dt, calendar_names=calendar_names)
        return json.dumps({"results": events})
    except Exception as e:
        return json.dumps({"error": f"Failed to get events: {e}"})


@mcp.tool()
async def create_calendar_event(
    title: str,
    start_date: str,
    end_date: str,
    calendar_name: str = "",
    location: str = "",
    notes: str = "",
    is_all_day: bool = False,
) -> str:
    """Create a new calendar event.

    Args:
        title: Event title (required)
        start_date: Start date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        end_date: End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        calendar_name: Calendar to create the event in (uses default if empty)
        location: Event location
        notes: Event notes/description
        is_all_day: Whether this is an all-day event (default: False)
    """
    calendar_store = _state["calendar_store"]
    try:
        start_dt = _parse_date(start_date)
        end_dt = _parse_date(end_date)
        result = calendar_store.create_event(
            title=title,
            start_dt=start_dt,
            end_dt=end_dt,
            calendar_name=calendar_name or None,
            location=location or None,
            notes=notes or None,
            is_all_day=is_all_day,
        )
        return json.dumps({"status": "created", "event": result})
    except Exception as e:
        return json.dumps({"error": f"Failed to create event: {e}"})


@mcp.tool()
async def update_calendar_event(
    event_uid: str,
    calendar_name: str,
    title: str = "",
    start_date: str = "",
    end_date: str = "",
    location: str = "",
    notes: str = "",
) -> str:
    """Update an existing calendar event by UID.

    Args:
        event_uid: The unique identifier of the event (required)
        calendar_name: Calendar the event belongs to (required)
        title: New event title
        start_date: New start date in ISO format
        end_date: New end date in ISO format
        location: New event location
        notes: New event notes
    """
    calendar_store = _state["calendar_store"]
    try:
        kwargs = {}
        if title:
            kwargs["title"] = title
        if start_date:
            kwargs["start_dt"] = _parse_date(start_date)
        if end_date:
            kwargs["end_dt"] = _parse_date(end_date)
        if location:
            kwargs["location"] = location
        if notes:
            kwargs["notes"] = notes
        result = calendar_store.update_event(event_uid, calendar_name=calendar_name, **kwargs)
        return json.dumps({"status": "updated", "event": result})
    except Exception as e:
        return json.dumps({"error": f"Failed to update event: {e}"})


@mcp.tool()
async def delete_calendar_event(event_uid: str, calendar_name: str) -> str:
    """Delete a calendar event by UID and calendar name.

    Args:
        event_uid: The unique identifier of the event (required)
        calendar_name: Calendar the event belongs to (required)
    """
    calendar_store = _state["calendar_store"]
    try:
        result = calendar_store.delete_event(event_uid, calendar_name=calendar_name)
        if result is True:
            return json.dumps({"status": "deleted", "event_uid": event_uid})
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Failed to delete event: {e}"})


@mcp.tool()
async def search_calendar_events(query: str, start_date: str = "", end_date: str = "") -> str:
    """Search events by title text. Defaults to +/- 30 days if no dates provided.

    Args:
        query: Text to search for in event titles (required)
        start_date: Start date in ISO format (defaults to 30 days ago)
        end_date: End date in ISO format (defaults to 30 days from now)
    """
    from datetime import timedelta

    calendar_store = _state["calendar_store"]
    try:
        now = datetime.now()
        start_dt = _parse_date(start_date) if start_date else now - timedelta(days=30)
        end_dt = _parse_date(end_date) if end_date else now + timedelta(days=30)
        events = calendar_store.search_events(query, start_dt, end_dt)
        return json.dumps({"results": events})
    except Exception as e:
        return json.dumps({"error": f"Failed to search events: {e}"})


# --- Resources ---


@mcp.resource("memory://facts")
async def get_all_facts() -> str:
    """All stored facts about the user, organized by category."""
    memory_store = _state["memory_store"]
    categories = ["personal", "preference", "work", "relationship"]
    result = {}
    for cat in categories:
        facts = memory_store.get_facts_by_category(cat)
        if facts:
            result[cat] = [{"key": f.key, "value": f.value, "confidence": f.confidence} for f in facts]
    return json.dumps(result, indent=2) if result else json.dumps({"message": "No facts stored yet."})


@mcp.resource("memory://facts/{category}")
async def get_facts_by_category(category: str) -> str:
    """Facts for a specific category (personal, preference, work, relationship)."""
    memory_store = _state["memory_store"]
    facts = memory_store.get_facts_by_category(category)
    result = [{"key": f.key, "value": f.value, "confidence": f.confidence} for f in facts]
    return json.dumps(result, indent=2)


@mcp.resource("agents://list")
async def get_agents_list() -> str:
    """All available expert agents and their descriptions."""
    agent_registry = _state["agent_registry"]
    agents = agent_registry.list_agents()
    result = [
        {"name": a.name, "description": a.description, "capabilities": a.capabilities}
        for a in agents
    ]
    return json.dumps(result, indent=2) if result else json.dumps({"message": "No agents configured yet."})


# --- Entry point ---


def main():
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
