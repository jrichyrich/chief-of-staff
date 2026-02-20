"""Self-authoring skill tools for the Chief of Staff MCP server."""

import json
import logging

from memory.models import SkillSuggestion
from .state import _retry_on_transient

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register skill tools with the FastMCP server."""

    @mcp.tool()
    async def record_tool_usage(tool_name: str, query_pattern: str) -> str:
        """Record a tool usage pattern for skill analysis.

        Args:
            tool_name: Name of the tool that was used (e.g. 'query_memory', 'search_calendar_events')
            query_pattern: Description of the query or usage pattern (e.g. 'weekly team meeting lookup')
        """
        memory_store = state.memory_store
        try:
            _retry_on_transient(memory_store.record_skill_usage, tool_name, query_pattern)
            return json.dumps({"status": "recorded", "tool_name": tool_name, "query_pattern": query_pattern})
        except Exception as e:
            logger.exception("Error recording tool usage")
            return json.dumps({"error": f"Failed to record usage: {e}"})

    @mcp.tool()
    async def analyze_skill_patterns() -> str:
        """Analyze recorded tool usage patterns and generate skill suggestions.

        Scans usage data for repeated patterns that could benefit from a
        specialized agent. Creates suggestions for patterns exceeding the
        configured frequency and confidence thresholds.
        """
        from config import SKILL_MIN_OCCURRENCES, SKILL_SUGGESTION_THRESHOLD
        from skills.pattern_detector import PatternDetector

        memory_store = state.memory_store
        try:
            detector = PatternDetector(memory_store)
            patterns = detector.detect_patterns(
                min_occurrences=SKILL_MIN_OCCURRENCES,
                confidence_threshold=SKILL_SUGGESTION_THRESHOLD,
            )
            if not patterns:
                return json.dumps({"message": "No significant patterns detected.", "suggestions_created": 0})

            created = 0
            for pattern in patterns:
                suggestion = SkillSuggestion(
                    description=pattern["description"],
                    suggested_name=pattern["tool_name"].replace(" ", "_") + "_specialist",
                    suggested_capabilities=pattern["tool_name"],
                    confidence=pattern["confidence"],
                )
                _retry_on_transient(memory_store.store_skill_suggestion, suggestion)
                created += 1

            return json.dumps({"suggestions_created": created, "patterns": patterns})
        except Exception as e:
            logger.exception("Error analyzing skill patterns")
            return json.dumps({"error": f"Failed to analyze patterns: {e}"})

    @mcp.tool()
    async def list_skill_suggestions(status: str = "pending") -> str:
        """List skill suggestions filtered by status.

        Args:
            status: Filter by status — 'pending', 'accepted', or 'rejected' (default: 'pending')
        """
        memory_store = state.memory_store
        try:
            suggestions = _retry_on_transient(memory_store.list_skill_suggestions, status)
            if not suggestions:
                return json.dumps({"message": f"No {status} skill suggestions.", "results": []})
            results = [
                {
                    "id": s.id,
                    "description": s.description,
                    "suggested_name": s.suggested_name,
                    "suggested_capabilities": s.suggested_capabilities,
                    "confidence": s.confidence,
                    "status": s.status,
                    "created_at": s.created_at,
                }
                for s in suggestions
            ]
            return json.dumps({"results": results})
        except Exception as e:
            logger.exception("Error listing skill suggestions")
            return json.dumps({"error": f"Failed to list suggestions: {e}"})

    @mcp.tool()
    async def auto_create_skill(suggestion_id: int) -> str:
        """Accept a skill suggestion and create an agent from it using AgentFactory.

        Args:
            suggestion_id: The ID of the skill suggestion to accept
        """
        from agents.factory import AgentFactory

        memory_store = state.memory_store
        agent_registry = state.agent_registry
        try:
            suggestion = memory_store.get_skill_suggestion(suggestion_id)
            if not suggestion:
                return json.dumps({"error": f"Suggestion {suggestion_id} not found."})
            if suggestion.status != "pending":
                return json.dumps({"error": f"Suggestion {suggestion_id} is already {suggestion.status}."})

            factory = AgentFactory(agent_registry)
            config = factory.create_agent(suggestion.description)

            _retry_on_transient(
                memory_store.update_skill_suggestion_status, suggestion_id, "accepted"
            )
            return json.dumps({
                "status": "created",
                "agent_name": config.name,
                "description": config.description,
                "capabilities": config.capabilities,
                "suggestion_id": suggestion_id,
            })
        except Exception as e:
            logger.exception("Error auto-creating skill")
            return json.dumps({"error": f"Failed to create skill: {e}"})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.record_tool_usage = record_tool_usage
    module.analyze_skill_patterns = analyze_skill_patterns
    module.list_skill_suggestions = list_skill_suggestions
    module.auto_create_skill = auto_create_skill
