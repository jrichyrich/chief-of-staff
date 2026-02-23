"""MCP resources for exposing data endpoints."""

import json


def register(mcp, state):
    """Register MCP resources with the server."""

    @mcp.resource("memory://facts")
    async def get_all_facts() -> str:
        """All stored facts about the user, organized by category."""
        memory_store = state.memory_store
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
        memory_store = state.memory_store
        facts = memory_store.get_facts_by_category(category)
        result = [{"key": f.key, "value": f.value, "confidence": f.confidence} for f in facts]
        return json.dumps(result, indent=2)

    @mcp.resource("agents://list")
    async def get_agents_list() -> str:
        """All available expert agents and their descriptions."""
        agent_registry = state.agent_registry
        agents = agent_registry.list_agents()
        result = [
            {"name": a.name, "description": a.description, "capabilities": a.capabilities}
            for a in agents
        ]
        return json.dumps(result, indent=2) if result else json.dumps({"message": "No agents configured yet."})

    @mcp.resource("session://context")
    async def get_session_context() -> str:
        """Proactive session context: today's calendar, pending tasks, suggestions."""
        from datetime import datetime, timedelta
        from proactive.engine import ProactiveSuggestionEngine

        context = {"today": datetime.now().strftime("%Y-%m-%d")}

        # Calendar: today's events
        try:
            calendar_store = state.calendar_store
            if calendar_store is not None:
                now = datetime.now()
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1)
                events = calendar_store.get_events(start, end, provider_preference="both")
                if events:
                    context["calendar_today"] = [
                        {k: v for k, v in e.items() if k in ("title", "start", "end", "location", "calendar")}
                        for e in events[:15]
                    ]
        except Exception:
            pass

        # Pending delegations
        try:
            delegations = state.memory_store.list_delegations(status="active")
            if delegations:
                context["pending_delegations"] = [
                    {"task": d.task, "delegated_to": d.delegated_to, "due_date": d.due_date or "", "priority": d.priority}
                    for d in delegations[:10]
                ]
        except Exception:
            pass

        # Overdue delegations
        try:
            overdue = state.memory_store.list_overdue_delegations()
            if overdue:
                from datetime import date
                today = date.today()
                context["overdue_delegations"] = [
                    {
                        "task": d.task,
                        "delegated_to": d.delegated_to,
                        "due_date": d.due_date or "",
                        "days_overdue": (today - date.fromisoformat(d.due_date)).days if d.due_date else 0,
                    }
                    for d in overdue[:10]
                ]
        except Exception:
            pass

        # Pending decisions
        try:
            decisions = state.memory_store.list_decisions_by_status("pending_execution")
            if decisions:
                context["pending_decisions"] = [
                    {"title": d.title, "status": d.status, "created_at": d.created_at or ""}
                    for d in decisions[:10]
                ]
        except Exception:
            pass

        # Due reminders
        try:
            reminder_store = state.reminder_store
            if reminder_store is not None:
                reminders = reminder_store.list_reminders(completed=False)
                if reminders:
                    context["due_reminders"] = [
                        {k: v for k, v in r.items() if k in ("title", "due_date", "priority", "list_name")}
                        for r in reminders[:10]
                    ]
        except Exception:
            pass

        # Unprocessed webhooks (count only)
        try:
            webhooks = state.memory_store.list_webhook_events(status="pending")
            if webhooks:
                context["unprocessed_webhooks"] = len(webhooks)
        except Exception:
            pass

        # Proactive suggestions
        try:
            engine = ProactiveSuggestionEngine(
                memory_store=state.memory_store,
                session_health=state.session_health,
                session_manager=state.session_manager,
            )
            suggestions = engine.generate_suggestions()
            if suggestions:
                context["proactive_suggestions"] = [
                    {"category": s.category, "priority": s.priority, "title": s.title, "action": s.action}
                    for s in suggestions[:5]
                ]
        except Exception:
            pass

        return json.dumps(context, indent=2, default=str)

    # Expose resource functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.get_all_facts = get_all_facts
    module.get_facts_by_category = get_facts_by_category
    module.get_agents_list = get_agents_list
    module.get_session_context = get_session_context
