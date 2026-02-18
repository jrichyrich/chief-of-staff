"""Memory and location tools for the Chief of Staff MCP server."""

import json
import logging
import sqlite3

from memory.models import Fact, Location
from .state import _retry_on_transient

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register memory tools with the FastMCP server."""
    from config import VALID_FACT_CATEGORIES as VALID_CATEGORIES

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
        memory_store = state.memory_store
        try:
            fact = Fact(category=category, key=key, value=value, confidence=confidence)
            stored = _retry_on_transient(memory_store.store_fact, fact)
            return json.dumps({
                "status": "stored",
                "category": stored.category,
                "key": stored.key,
                "value": stored.value,
            })
        except (sqlite3.OperationalError, ValueError, KeyError) as e:
            return json.dumps({"error": f"Database error storing fact: {e}"})
        except Exception as e:
            logger.exception("Unexpected error in store_fact")
            return json.dumps({"error": f"Unexpected error: {e}"})

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
        memory_store = state.memory_store
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
        memory_store = state.memory_store

        try:
            if category:
                facts = _retry_on_transient(memory_store.get_facts_by_category, category)
                # Filter by query text within the category results
                if query:
                    q = query.lower()
                    facts = [f for f in facts if q in f.value.lower() or q in f.key.lower()]
            else:
                facts = _retry_on_transient(memory_store.search_facts, query)

            if not facts:
                return json.dumps({"message": f"No facts found for query '{query}'.", "results": []})

            results = [{"category": f.category, "key": f.key, "value": f.value, "confidence": f.confidence} for f in facts]
            return json.dumps({"results": results})
        except (sqlite3.OperationalError, ValueError, KeyError) as e:
            return json.dumps({"error": f"Database error querying memory: {e}"})
        except Exception as e:
            logger.exception("Unexpected error in query_memory")
            return json.dumps({"error": f"Unexpected error: {e}"})

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
    async def list_locations() -> str:
        """List all stored locations."""
        memory_store = state.memory_store
        locations = memory_store.list_locations()
        if not locations:
            return json.dumps({"message": "No locations stored yet.", "results": []})
        results = [{"name": l.name, "address": l.address, "notes": l.notes} for l in locations]
        return json.dumps({"results": results})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.store_fact = store_fact
    module.delete_fact = delete_fact
    module.query_memory = query_memory
    module.store_location = store_location
    module.list_locations = list_locations
