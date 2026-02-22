"""Identity linking tools for MCP server."""

import json


def register(mcp, state):
    """Register identity linking tools with the MCP server."""

    @mcp.tool()
    async def link_identity(
        canonical_name: str,
        provider: str,
        provider_id: str,
        display_name: str = "",
        email: str = "",
    ) -> str:
        """Link a provider identity to a canonical person name.

        Maps a person's account on a specific provider (iMessage, email, Teams, etc.)
        to their canonical name, enabling cross-channel identity resolution.

        Args:
            canonical_name: The person's canonical name (e.g. "Jane Smith")
            provider: Provider name: imessage, email, m365_teams, m365_email, slack, jira, confluence
            provider_id: Unique ID on the provider (phone number, email, user ID, etc.)
            display_name: Optional display name on the provider
            email: Optional email address associated with this identity
        """
        try:
            result = state.memory_store.link_identity(
                canonical_name=canonical_name,
                provider=provider,
                provider_id=provider_id,
                display_name=display_name,
                email=email,
            )
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def unlink_identity(provider: str, provider_id: str) -> str:
        """Remove an identity link for a specific provider account.

        Args:
            provider: Provider name (e.g. imessage, email, m365_teams)
            provider_id: Unique ID on the provider
        """
        try:
            result = state.memory_store.unlink_identity(
                provider=provider,
                provider_id=provider_id,
            )
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_identity(canonical_name: str) -> str:
        """Get all linked accounts for a person by their canonical name.

        Args:
            canonical_name: The person's canonical name (e.g. "Jane Smith")
        """
        try:
            identities = state.memory_store.get_identity(canonical_name)
            return json.dumps({"canonical_name": canonical_name, "identities": identities})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def search_identity(query: str) -> str:
        """Search identities by name, email, or provider ID.

        Args:
            query: Search text to match against canonical_name, display_name, email, or provider_id
        """
        try:
            results = state.memory_store.search_identity(query)
            return json.dumps({"results": results})
        except Exception as e:
            return json.dumps({"error": str(e)})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.link_identity = link_identity
    module.unlink_identity = unlink_identity
    module.get_identity = get_identity
    module.search_identity = search_identity
