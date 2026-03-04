"""API usage tracking query tools for the Chief of Staff MCP server."""

import json
import logging

from .state import _retry_on_transient

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register API usage query tools with the FastMCP server."""

    @mcp.tool()
    async def get_api_usage_summary(
        since: str = "", agent_name: str = "", model: str = ""
    ) -> str:
        """Get aggregated API usage totals grouped by model and agent.

        Returns call counts, total tokens (input/output/cache), and average
        duration for each model+agent combination, plus grand totals.

        Args:
            since: ISO date string to filter from (e.g. '2026-03-01'). Empty for all time.
            agent_name: Filter to a specific agent name. Empty for all agents.
            model: Filter to a specific model ID. Empty for all models.
        """
        memory_store = state.memory_store
        try:
            rows = _retry_on_transient(
                memory_store.get_api_usage_summary,
                since=since or None,
                agent_name=agent_name or None,
                model=model or None,
            )
            grand_totals = {
                "total_calls": sum(r["call_count"] for r in rows),
                "total_input_tokens": sum(r["total_input_tokens"] for r in rows),
                "total_output_tokens": sum(r["total_output_tokens"] for r in rows),
                "total_cache_creation": sum(r["total_cache_creation"] for r in rows),
                "total_cache_read": sum(r["total_cache_read"] for r in rows),
            }
            return json.dumps({
                "grand_totals": grand_totals,
                "by_group": rows,
            })
        except Exception as e:
            logger.exception("Error getting API usage summary")
            return json.dumps({"error": f"Failed to get API usage summary: {e}"})

    @mcp.tool()
    async def get_api_usage_log(
        since: str = "",
        agent_name: str = "",
        model: str = "",
        caller: str = "",
        limit: int = 50,
    ) -> str:
        """Get raw API usage log entries, newest first.

        Each entry shows model, tokens, duration, agent, and caller for a
        single Anthropic API call made by Jarvis.

        Args:
            since: ISO date string to filter from (e.g. '2026-03-01'). Empty for all time.
            agent_name: Filter to a specific agent name. Empty for all agents.
            model: Filter to a specific model ID. Empty for all models.
            caller: Filter by caller type (e.g. 'base_agent', 'synthesis', 'triage', 'factory', 'imessage'). Empty for all.
            limit: Maximum number of entries to return (default 50, max 500).
        """
        memory_store = state.memory_store
        try:
            capped_limit = min(max(limit, 1), 500)
            rows = _retry_on_transient(
                memory_store.get_api_usage_log,
                since=since or None,
                agent_name=agent_name or None,
                model=model or None,
                caller=caller or None,
                limit=capped_limit,
            )
            return json.dumps({"count": len(rows), "entries": rows})
        except Exception as e:
            logger.exception("Error getting API usage log")
            return json.dumps({"error": f"Failed to get API usage log: {e}"})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.get_api_usage_summary = get_api_usage_summary
    module.get_api_usage_log = get_api_usage_log
