"""Contextual tool chaining — person enrichment via parallel data fetching."""

import asyncio
import json
import logging

logger = logging.getLogger("jarvis-enrichment")


def register(mcp, state):
    """Register enrichment tools with the MCP server."""

    @mcp.tool()
    async def enrich_person(name: str, days_back: int = 7) -> str:
        """Get a consolidated profile for a person: identities, facts, delegations, decisions, recent messages, and emails.

        Fetches from 6 data sources in parallel. Much faster than calling each tool separately.
        Empty sections are omitted. If a data source is unavailable, that section is silently skipped.

        Args:
            name: Person's name to search for (canonical name or partial match)
            days_back: How many days back to search communications (default 7)
        """
        context = {"name": name}
        minutes = days_back * 1440

        async def fetch_identities():
            try:
                results = state.memory_store.search_identity(name)
                if results:
                    return ("identities", results[:10])
            except Exception as e:
                logger.debug("enrich_person: identities failed: %s", e)
            return None

        async def fetch_facts():
            try:
                results = state.memory_store.search_facts(name)
                if results:
                    facts = [
                        {"category": f.category, "key": f.key, "value": f.value, "confidence": f.confidence}
                        for f in results[:10]
                    ]
                    if facts:
                        return ("facts", facts)
            except Exception as e:
                logger.debug("enrich_person: facts failed: %s", e)
            return None

        async def fetch_delegations():
            try:
                results = state.memory_store.list_delegations(delegated_to=name)
                if results:
                    delegations = [
                        {"task": d.task, "delegated_to": d.delegated_to, "due_date": d.due_date or "", "priority": d.priority, "status": d.status}
                        for d in results[:10]
                    ]
                    if delegations:
                        return ("delegations", delegations)
            except Exception as e:
                logger.debug("enrich_person: delegations failed: %s", e)
            return None

        async def fetch_decisions():
            try:
                results = state.memory_store.search_decisions(name)
                if results:
                    decisions = [
                        {"title": d.title, "status": d.status, "created_at": d.created_at or ""}
                        for d in results[:10]
                    ]
                    if decisions:
                        return ("decisions", decisions)
            except Exception as e:
                logger.debug("enrich_person: decisions failed: %s", e)
            return None

        async def fetch_imessages():
            try:
                messages_store = state.messages_store
                if messages_store is None:
                    return None
                results = messages_store.search_messages(name, minutes=minutes)
                if results:
                    return ("recent_messages", results[:10])
            except Exception as e:
                logger.debug("enrich_person: imessages failed: %s", e)
            return None

        async def fetch_emails():
            try:
                mail_store = state.mail_store
                if mail_store is None:
                    return None
                results = mail_store.search_messages(name, limit=10)
                if results:
                    return ("recent_emails", results[:10])
            except Exception as e:
                logger.debug("enrich_person: emails failed: %s", e)
            return None

        results = await asyncio.gather(
            fetch_identities(),
            fetch_facts(),
            fetch_delegations(),
            fetch_decisions(),
            fetch_imessages(),
            fetch_emails(),
        )

        for result in results:
            if result is not None:
                key, value = result
                context[key] = value

        return json.dumps(context, indent=2, default=str)

    # Expose at module level for testing
    import sys
    module = sys.modules[__name__]
    module.enrich_person = enrich_person
