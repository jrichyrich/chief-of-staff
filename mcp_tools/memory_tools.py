"""Memory and location tools for the Chief of Staff MCP server."""

import json
import logging
import sqlite3
from datetime import datetime

from memory.models import ContextEntry, Fact, Location

from .decorators import tool_errors
from .state import _retry_on_transient

logger = logging.getLogger("jarvis-mcp")

_EXPECTED = (sqlite3.OperationalError, ValueError, KeyError)


def register(mcp, state):
    """Register memory tools with the FastMCP server."""
    from config import VALID_FACT_CATEGORIES as VALID_CATEGORIES

    @mcp.tool()
    @tool_errors("Database error", expected=_EXPECTED)
    async def store_fact(category: str, key: str, value: str, confidence: float = 1.0, pinned: bool = False) -> str:
        """Store a fact about the user in long-term memory. Overwrites if category+key already exists.

        Args:
            category: One of 'personal', 'preference', 'work', 'relationship'
            key: Short label for the fact (e.g. 'name', 'favorite_color', 'job_title')
            value: The fact value
            confidence: Confidence score from 0.0 to 1.0 (default 1.0)
            pinned: If True, this fact never decays over time (default False)
        """
        if category not in VALID_CATEGORIES:
            return json.dumps({
                "error": f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
            })
        memory_store = state.memory_store
        fact = Fact(category=category, key=key, value=value, confidence=confidence, pinned=pinned)
        stored = _retry_on_transient(memory_store.store_fact, fact)
        return json.dumps({
            "status": "stored",
            "category": stored.category,
            "key": stored.key,
            "value": stored.value,
        })

    @mcp.tool()
    @tool_errors("Database error", expected=_EXPECTED)
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
        memory_store = state.memory_store
        deleted = memory_store.delete_fact(category, key)
        if deleted:
            return json.dumps({"status": "deleted", "category": category, "key": key})
        return json.dumps({"status": "not_found", "message": f"No fact found with category='{category}', key='{key}'"})

    @mcp.tool()
    @tool_errors("Database error", expected=_EXPECTED)
    async def query_memory(query: str, category: str = "", diverse: bool = True, half_life_days: int = 90) -> str:
        """Search stored facts about the user. Returns matching facts ranked by relevance (recency + confidence).

        Args:
            query: Search term to match against fact keys and values
            category: Optional — filter to a specific category (personal, preference, work, relationship). Leave empty to search all.
            diverse: Apply MMR re-ranking to reduce redundant results (default True).
            half_life_days: Number of days for temporal decay half-life (default 90). Lower = faster decay of old facts.
        """
        memory_store = state.memory_store

        if category:
            facts = _retry_on_transient(memory_store.get_facts_by_category, category)
            if query:
                q = query.lower()
                facts = [f for f in facts if q in f.value.lower() or q in f.key.lower()]
            scored = memory_store.rank_facts(facts, half_life_days=float(half_life_days))
        else:
            scored = _retry_on_transient(memory_store.search_facts_hybrid, query, diverse=diverse, half_life_days=float(half_life_days))

        if not scored:
            return json.dumps({"message": f"No facts found for query '{query}'.", "results": []})

        results = [
            {
                "category": f.category,
                "key": f.key,
                "value": f.value,
                "confidence": f.confidence,
                "relevance_score": round(score, 3),
                "updated_at": f.updated_at,
            }
            for f, score in scored
        ]
        return json.dumps({"results": results})

    @mcp.tool()
    @tool_errors("Database error", expected=_EXPECTED)
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
        memory_store = state.memory_store
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
    @tool_errors("Database error", expected=_EXPECTED)
    async def list_locations() -> str:
        """List all stored locations."""
        memory_store = state.memory_store
        locations = memory_store.list_locations()
        if not locations:
            return json.dumps({"message": "No locations stored yet.", "results": []})
        results = [{"name": l.name, "address": l.address, "notes": l.notes} for l in locations]
        return json.dumps({"results": results})

    @mcp.tool()
    @tool_errors("Database error", expected=_EXPECTED)
    async def checkpoint_session(summary: str, key_facts: str = "", session_id: str = "",
                                 auto_checkpoint: bool = False) -> str:
        """Save important session context to persistent memory before context compaction.

        Call this when important decisions, facts, or context have emerged during
        a conversation that should persist across sessions. Recommended before
        long conversations approach context limits.

        Args:
            summary: Concise summary of the current session's key context and outcomes
            key_facts: Optional comma-separated key facts to persist as individual memory facts
            session_id: Optional session identifier for organizing context entries
            auto_checkpoint: If True, marks this as an automatic (system-triggered) checkpoint
        """
        if not summary or not summary.strip():
            return json.dumps({"error": "Summary must not be empty."})

        effective_summary = f"[Auto] {summary.strip()}" if auto_checkpoint else summary.strip()

        memory_store = state.memory_store

        # If SessionManager is available, use it for richer extraction
        session_manager = state.session_manager
        enriched_facts = 0
        if session_manager is not None and session_manager.interaction_count > 0:
            extracted = session_manager.extract_structured_data()
            now_ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            for i, decision in enumerate(extracted.get("decisions", [])):
                fact = Fact(
                    category="work",
                    key=f"checkpoint_decision_{now_ts}_{i}",
                    value=decision,
                    confidence=0.9,
                    source="session_checkpoint",
                )
                _retry_on_transient(memory_store.store_fact, fact)
                enriched_facts += 1
            for i, action in enumerate(extracted.get("action_items", [])):
                fact = Fact(
                    category="work",
                    key=f"checkpoint_action_{now_ts}_{i}",
                    value=action,
                    confidence=0.85,
                    source="session_checkpoint",
                )
                _retry_on_transient(memory_store.store_fact, fact)
                enriched_facts += 1

        entry = ContextEntry(
            topic="session_checkpoint",
            summary=effective_summary,
            session_id=session_id or None,
            agent="jarvis",
        )
        stored_entry = _retry_on_transient(memory_store.store_context, entry)

        facts_stored = 0
        if key_facts and key_facts.strip():
            now = datetime.now()
            timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
            for i, raw_fact in enumerate(key_facts.split(",")):
                fact_value = raw_fact.strip()
                if not fact_value:
                    continue
                fact_key = f"checkpoint_{timestamp}_{i}"
                fact = Fact(
                    category="work",
                    key=fact_key,
                    value=fact_value,
                    confidence=0.8,
                    source="session_checkpoint",
                )
                _retry_on_transient(memory_store.store_fact, fact)
                facts_stored += 1

        state.session_health.record_checkpoint()

        return json.dumps({
            "status": "checkpoint_saved",
            "context_id": stored_entry.id,
            "facts_stored": facts_stored,
            "enriched_facts": enriched_facts,
            "auto_checkpoint": auto_checkpoint,
        })

    @mcp.tool()
    @tool_errors("Database error", expected=_EXPECTED)
    async def get_session_health() -> str:
        """Return session activity metrics: tool call count, session start time, last checkpoint.

        Use this to decide whether a checkpoint_session call is needed before
        context compaction. A high tool_call_count with no recent checkpoint
        suggests important context may be lost.
        """
        health = state.session_health
        mins = health.minutes_since_checkpoint()
        minutes_since_checkpoint = None if mins == float('inf') else round(mins, 1)

        return json.dumps({
            **health.to_dict(),
            "minutes_since_checkpoint": minutes_since_checkpoint,
            "checkpoint_recommended": (
                health.tool_call_count >= 50
                and (minutes_since_checkpoint is None or minutes_since_checkpoint >= 30)
            ),
        })

    @mcp.tool()
    @tool_errors("Database error", expected=_EXPECTED)
    async def list_facts(prefix: str = "", category: str = "", limit: int = 100) -> str:
        """List facts by key prefix and/or category — deterministic, no ranking.

        Unlike query_memory (semantic search), this returns exact matches
        using SQL prefix filtering. Use this when you know the key naming
        pattern (e.g. prefix="isp_" returns all ISP org facts).

        Args:
            prefix: Key prefix filter (e.g. "isp_team_", "okr_investment_"). Empty = all keys.
            category: Filter by category (personal, preference, work, relationship). Empty = all.
            limit: Max facts to return (default 100).
        """
        memory_store = state.memory_store
        facts = memory_store.list_facts(
            prefix=prefix or None,
            category=category or None,
            limit=limit,
        )
        return json.dumps({
            "count": len(facts),
            "facts": [
                {
                    "category": f.category,
                    "key": f.key,
                    "value": f.value,
                    "confidence": f.confidence,
                    "pinned": f.pinned,
                    "updated_at": f.updated_at,
                }
                for f in facts
            ],
        })

    @mcp.tool()
    @tool_errors("Database error", expected=_EXPECTED)
    async def list_fact_keys(prefix: str = "", category: str = "") -> str:
        """List all fact keys, optionally filtered by prefix and/or category.

        Returns just the key names — useful for discovering what's stored
        before fetching full facts with list_facts.

        Args:
            prefix: Key prefix filter (e.g. "isp_", "okr_"). Empty = all keys.
            category: Filter by category. Empty = all.
        """
        memory_store = state.memory_store
        keys = memory_store.list_fact_keys(
            prefix=prefix or None,
            category=category or None,
        )
        return json.dumps({"count": len(keys), "keys": keys})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.store_fact = store_fact
    module.delete_fact = delete_fact
    module.query_memory = query_memory
    module.store_location = store_location
    module.list_locations = list_locations
    module.checkpoint_session = checkpoint_session
    module.get_session_health = get_session_health
    module.list_facts = list_facts
    module.list_fact_keys = list_fact_keys
