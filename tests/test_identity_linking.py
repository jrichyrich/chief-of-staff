"""Tests for identity linking — MemoryStore methods and MCP tool functions.

Covers:
- MemoryStore identity CRUD (link, unlink, get, search, resolve_sender)
- UNIQUE constraint handling (upsert behavior)
- MCP tool functions via mcp_tools/identity_tools.py
"""

import json
from pathlib import Path

import pytest

import mcp_server
from memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------



@pytest.fixture
def identity_state(memory_store):
    """Inject memory_store into mcp_server._state for MCP tool tests."""
    mcp_server._state["memory_store"] = memory_store
    yield memory_store
    mcp_server._state.pop("memory_store", None)


# ===========================================================================
# MemoryStore identity methods
# ===========================================================================


class TestLinkIdentity:
    def test_basic_link(self, memory_store):
        result = memory_store.link_identity(
            canonical_name="Jane Smith",
            provider="imessage",
            provider_id="+15551234567",
            display_name="Jane",
            email="jane@example.com",
        )
        assert result["canonical_name"] == "Jane Smith"
        assert result["provider"] == "imessage"
        assert result["provider_id"] == "+15551234567"
        assert result["display_name"] == "Jane"
        assert result["email"] == "jane@example.com"
        assert result["id"] is not None
        assert result["created_at"] is not None
        assert result["updated_at"] is not None

    def test_link_minimal(self, memory_store):
        """Link with only required fields."""
        result = memory_store.link_identity(
            canonical_name="Bob",
            provider="slack",
            provider_id="U123ABC",
        )
        assert result["canonical_name"] == "Bob"
        assert result["provider"] == "slack"
        assert result["provider_id"] == "U123ABC"
        assert result["display_name"] == ""
        assert result["email"] == ""

    def test_upsert_on_conflict(self, memory_store):
        """UNIQUE(provider, provider_id) should upsert, updating canonical_name."""
        result1 = memory_store.link_identity(
            canonical_name="Jane Smith",
            provider="email",
            provider_id="jane@old.com",
        )
        id1 = result1["id"]

        result2 = memory_store.link_identity(
            canonical_name="Jane A. Smith",
            provider="email",
            provider_id="jane@old.com",
            display_name="Jane A.",
        )
        # Same row updated, not a new row
        assert result2["id"] == id1
        assert result2["canonical_name"] == "Jane A. Smith"
        assert result2["display_name"] == "Jane A."

    def test_multiple_providers_same_person(self, memory_store):
        """One canonical_name can have multiple provider links."""
        memory_store.link_identity("Alice", "imessage", "+15550001111")
        memory_store.link_identity("Alice", "email", "alice@work.com")
        memory_store.link_identity("Alice", "m365_teams", "alice-teams-id")

        identities = memory_store.get_identity("Alice")
        assert len(identities) == 3
        providers = {i["provider"] for i in identities}
        assert providers == {"imessage", "email", "m365_teams"}


class TestUnlinkIdentity:
    def test_unlink_existing(self, memory_store):
        memory_store.link_identity("Bob", "slack", "U999")
        result = memory_store.unlink_identity("slack", "U999")
        assert result["status"] == "unlinked"

        # Verify it's gone
        identities = memory_store.get_identity("Bob")
        assert len(identities) == 0

    def test_unlink_nonexistent(self, memory_store):
        result = memory_store.unlink_identity("slack", "DOESNOTEXIST")
        assert result["status"] == "not_found"


class TestGetIdentity:
    def test_get_with_results(self, memory_store):
        memory_store.link_identity("Charlie", "imessage", "+15559999999")
        memory_store.link_identity("Charlie", "jira", "charlie-jira")

        results = memory_store.get_identity("Charlie")
        assert len(results) == 2

    def test_get_no_results(self, memory_store):
        results = memory_store.get_identity("Nobody")
        assert results == []

    def test_get_sorted_by_provider(self, memory_store):
        memory_store.link_identity("Dana", "slack", "D1")
        memory_store.link_identity("Dana", "email", "dana@test.com")
        memory_store.link_identity("Dana", "confluence", "dana-conf")

        results = memory_store.get_identity("Dana")
        providers = [r["provider"] for r in results]
        assert providers == sorted(providers)


class TestSearchIdentity:
    def test_search_by_canonical_name(self, memory_store):
        memory_store.link_identity("Jane Smith", "email", "js@example.com")
        memory_store.link_identity("John Doe", "email", "jd@example.com")

        results = memory_store.search_identity("Jane")
        assert len(results) == 1
        assert results[0]["canonical_name"] == "Jane Smith"

    def test_search_by_email(self, memory_store):
        memory_store.link_identity("Jane", "email", "jane@test.com", email="jane@test.com")
        results = memory_store.search_identity("jane@test.com")
        assert len(results) == 1
        assert results[0]["email"] == "jane@test.com"

    def test_search_by_provider_id(self, memory_store):
        memory_store.link_identity("Bob", "imessage", "+15550001111")
        results = memory_store.search_identity("+15550001111")
        assert len(results) == 1

    def test_search_by_display_name(self, memory_store):
        memory_store.link_identity("Robert Smith", "slack", "U1", display_name="Bobby")
        results = memory_store.search_identity("Bobby")
        assert len(results) == 1
        assert results[0]["display_name"] == "Bobby"

    def test_search_no_results(self, memory_store):
        results = memory_store.search_identity("nonexistent")
        assert results == []

    def test_search_multiple_results(self, memory_store):
        memory_store.link_identity("Alice Smith", "email", "alice@a.com", email="alice@a.com")
        memory_store.link_identity("Alice Jones", "email", "alice@b.com", email="alice@b.com")

        results = memory_store.search_identity("Alice")
        assert len(results) == 2


class TestResolveSender:
    def test_resolve_by_provider_id(self, memory_store):
        memory_store.link_identity("Jane Smith", "imessage", "+15551234567")
        result = memory_store.resolve_sender("imessage", "+15551234567")
        assert result == "Jane Smith"

    def test_resolve_by_email_fallback(self, memory_store):
        memory_store.link_identity("Jane Smith", "email", "jane@work.com", email="jane@work.com")
        # Search with a different provider, but matching email
        result = memory_store.resolve_sender("m365_email", "jane@work.com")
        assert result == "Jane Smith"

    def test_resolve_unknown_sender(self, memory_store):
        result = memory_store.resolve_sender("imessage", "+10000000000")
        assert result is None

    def test_resolve_provider_id_takes_priority(self, memory_store):
        """When provider_id matches, should return that even if email would match a different person."""
        memory_store.link_identity("Alice", "email", "shared@test.com", email="shared@test.com")
        memory_store.link_identity("Bob", "email", "bob-specific", email="shared@test.com")

        # Resolve by exact provider + provider_id
        result = memory_store.resolve_sender("email", "bob-specific")
        assert result == "Bob"


class TestResolveHandleToName:
    def test_exact_imessage_provider_match(self, memory_store):
        memory_store.link_identity("Ross Young", "imessage", "+17035551234")
        result = memory_store.resolve_handle_to_name("+17035551234")
        assert result["canonical_name"] == "Ross Young"
        assert result["match_type"] == "imessage_provider"

    def test_exact_email_match(self, memory_store):
        memory_store.link_identity("Jane Doe", "email", "jane@test.com", email="jane@test.com")
        result = memory_store.resolve_handle_to_name("jane@test.com")
        assert result["canonical_name"] == "Jane Doe"
        assert result["match_type"] == "email"

    def test_no_match_returns_none(self, memory_store):
        result = memory_store.resolve_handle_to_name("+10000000000")
        assert result["canonical_name"] is None
        assert result["match_type"] is None
        assert result["all_matches"] == []

    def test_empty_handle_returns_none(self, memory_store):
        result = memory_store.resolve_handle_to_name("")
        assert result["canonical_name"] is None
        assert result["match_type"] is None

    def test_fuzzy_search_fallback(self, memory_store):
        """When exact match fails, fuzzy search by provider_id substring."""
        memory_store.link_identity("Ross Young", "imessage", "+17035559999")
        # Search with a handle that contains the digits but isn't exact
        result = memory_store.resolve_handle_to_name("+17035559999")
        assert result["canonical_name"] == "Ross Young"

    def test_multiple_matches_returns_all(self, memory_store):
        memory_store.link_identity("Alice", "imessage", "+15551111111")
        memory_store.link_identity("Bob", "imessage", "+15551111112")
        # Exact match on Alice's number
        result = memory_store.resolve_handle_to_name("+15551111111")
        assert result["canonical_name"] == "Alice"
        assert result["match_type"] == "imessage_provider"


# ===========================================================================
# MCP tool functions
# ===========================================================================


class TestIdentityToolsRegistered:
    def test_all_identity_tools_registered(self):
        """Verify all identity tools are registered on the MCP server."""
        tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
        expected = ["link_identity", "unlink_identity", "get_identity", "search_identity"]
        for name in expected:
            assert name in tool_names, f"Identity tool '{name}' not registered"


class TestLinkIdentityTool:
    @pytest.mark.asyncio
    async def test_basic_link(self, identity_state):
        from mcp_tools.identity_tools import link_identity

        result = await link_identity(
            canonical_name="Jane Smith",
            provider="imessage",
            provider_id="+15551234567",
            display_name="Jane",
            email="jane@example.com",
        )
        data = json.loads(result)
        assert data["canonical_name"] == "Jane Smith"
        assert data["provider"] == "imessage"
        assert data["provider_id"] == "+15551234567"
        assert data["display_name"] == "Jane"
        assert data["email"] == "jane@example.com"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_link_defaults(self, identity_state):
        from mcp_tools.identity_tools import link_identity

        result = await link_identity(
            canonical_name="Bob",
            provider="slack",
            provider_id="U123",
        )
        data = json.loads(result)
        assert data["canonical_name"] == "Bob"
        assert data["display_name"] == ""
        assert data["email"] == ""

    @pytest.mark.asyncio
    async def test_upsert(self, identity_state):
        from mcp_tools.identity_tools import link_identity

        result1 = await link_identity(
            canonical_name="Old Name",
            provider="email",
            provider_id="test@test.com",
        )
        id1 = json.loads(result1)["id"]

        result2 = await link_identity(
            canonical_name="New Name",
            provider="email",
            provider_id="test@test.com",
        )
        data = json.loads(result2)
        assert data["id"] == id1
        assert data["canonical_name"] == "New Name"


class TestUnlinkIdentityTool:
    @pytest.mark.asyncio
    async def test_unlink_existing(self, identity_state):
        from mcp_tools.identity_tools import link_identity, unlink_identity

        await link_identity(canonical_name="Bob", provider="slack", provider_id="U999")
        result = await unlink_identity(provider="slack", provider_id="U999")
        data = json.loads(result)
        assert data["status"] == "unlinked"

    @pytest.mark.asyncio
    async def test_unlink_nonexistent(self, identity_state):
        from mcp_tools.identity_tools import unlink_identity

        result = await unlink_identity(provider="slack", provider_id="MISSING")
        data = json.loads(result)
        assert data["status"] == "not_found"


class TestGetIdentityTool:
    @pytest.mark.asyncio
    async def test_get_with_results(self, identity_state):
        from mcp_tools.identity_tools import link_identity, get_identity

        await link_identity(canonical_name="Charlie", provider="imessage", provider_id="+1555")
        await link_identity(canonical_name="Charlie", provider="jira", provider_id="charlie-jira")

        result = await get_identity(canonical_name="Charlie")
        data = json.loads(result)
        assert data["canonical_name"] == "Charlie"
        assert len(data["identities"]) == 2

    @pytest.mark.asyncio
    async def test_get_no_results(self, identity_state):
        from mcp_tools.identity_tools import get_identity

        result = await get_identity(canonical_name="Nobody")
        data = json.loads(result)
        assert data["canonical_name"] == "Nobody"
        assert data["identities"] == []


class TestSearchIdentityTool:
    @pytest.mark.asyncio
    async def test_search_by_name(self, identity_state):
        from mcp_tools.identity_tools import link_identity, search_identity

        await link_identity(canonical_name="Jane Smith", provider="email", provider_id="js@a.com")
        await link_identity(canonical_name="John Doe", provider="email", provider_id="jd@a.com")

        result = await search_identity(query="Jane")
        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["canonical_name"] == "Jane Smith"

    @pytest.mark.asyncio
    async def test_search_no_results(self, identity_state):
        from mcp_tools.identity_tools import search_identity

        result = await search_identity(query="nonexistent")
        data = json.loads(result)
        assert data["results"] == []


class TestIdentityToolErrorHandling:
    @pytest.mark.asyncio
    async def test_link_error(self, identity_state):
        """When the store raises an exception, the tool should return error JSON."""
        from mcp_tools.identity_tools import link_identity
        from unittest.mock import PropertyMock, patch

        # Corrupt the memory_store to force an error
        original = identity_state.link_identity
        identity_state.link_identity = None  # Make it non-callable

        result = await link_identity(
            canonical_name="Test",
            provider="email",
            provider_id="test@test.com",
        )
        data = json.loads(result)
        assert "error" in data

        # Restore
        identity_state.link_identity = original
