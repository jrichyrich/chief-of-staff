"""Proactive suggestion tools for the Chief of Staff MCP server."""

import json
import logging
from datetime import datetime

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register proactive tools with the FastMCP server."""

    @mcp.tool()
    async def get_proactive_suggestions() -> str:
        """Run the proactive suggestion engine and return prioritized suggestions.

        Checks for: overdue delegations, upcoming deadlines, stale decisions,
        pending skill suggestions, and unprocessed webhook events.
        Returns suggestions sorted by priority (high > medium > low).
        """
        from proactive.engine import ProactiveSuggestionEngine

        memory_store = state.memory_store
        try:
            engine = ProactiveSuggestionEngine(
                memory_store,
                session_health=state.session_health,
                session_manager=getattr(state, "session_manager", None),
                session_brain=getattr(state, "session_brain", None),
            )
            suggestions = engine.generate_suggestions()

            # Filter out previously dismissed suggestions
            try:
                dismissed_facts = memory_store.search_facts("dismissed_suggestion:")
                dismissed_keys = {f.key for f in dismissed_facts}
                suggestions = [
                    s for s in suggestions
                    if f"dismissed_suggestion:{s.category}:{s.title}" not in dismissed_keys
                ]
            except Exception:
                logger.debug("Could not filter dismissed suggestions", exc_info=True)

            if not suggestions:
                return json.dumps({"message": "No suggestions at this time.", "suggestions": []})
            results = [
                {
                    "category": s.category,
                    "priority": s.priority,
                    "title": s.title,
                    "description": s.description,
                    "action": s.action,
                    "created_at": s.created_at,
                }
                for s in suggestions
            ]
            return json.dumps({"suggestions": results, "total": len(results)})
        except Exception as e:
            logger.exception("Error generating proactive suggestions")
            return json.dumps({"error": f"Failed to generate suggestions: {e}"})

    @mcp.tool()
    async def dismiss_suggestion(category: str, title: str) -> str:
        """Dismiss a proactive suggestion so it doesn't reappear.

        Args:
            category: The suggestion category (skill, webhook, delegation, decision, deadline)
            title: The title of the suggestion to dismiss
        """
        from memory.models import Fact

        memory_store = state.memory_store
        try:
            fact = Fact(
                category="preference",
                key=f"dismissed_suggestion:{category}:{title}",
                value=json.dumps({"category": category, "title": title, "dismissed_at": datetime.now().isoformat()}),
                confidence=1.0,
                source="proactive_dismiss",
            )
            memory_store.store_fact(fact)
        except Exception as e:
            logger.warning("Failed to persist suggestion dismissal: %s", e)
            return json.dumps({
                "status": "dismissed",
                "category": category,
                "title": title,
                "message": f"Suggestion dismissed but persistence failed: {e}",
            })

        return json.dumps({
            "status": "dismissed",
            "category": category,
            "title": title,
        })

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.get_proactive_suggestions = get_proactive_suggestions
    module.dismiss_suggestion = dismiss_suggestion
