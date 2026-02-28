"""Tests for proactive MCP tools."""

import json
from datetime import date, timedelta

import pytest

import mcp_server  # noqa: F401 — triggers register() calls
from memory.models import Decision, Delegation, SkillSuggestion, WebhookEvent
from memory.store import MemoryStore
from mcp_tools.proactive_tools import dismiss_suggestion, get_proactive_suggestions



@pytest.fixture(autouse=True)
def wire_state(memory_store):
    """Inject test memory_store into MCP server state."""
    mcp_server._state.memory_store = memory_store
    yield
    mcp_server._state.memory_store = None


class TestGetProactiveSuggestions:
    @pytest.mark.asyncio
    async def test_empty_state(self):
        result = json.loads(await get_proactive_suggestions())
        assert result["suggestions"] == []
        assert "No suggestions" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_suggestions(self, memory_store):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        memory_store.store_delegation(Delegation(
            task="overdue task", delegated_to="alice", due_date=yesterday,
        ))
        result = json.loads(await get_proactive_suggestions())
        assert result["total"] >= 1
        assert any(s["category"] == "delegation" for s in result["suggestions"])

    @pytest.mark.asyncio
    async def test_returns_correct_fields(self, memory_store):
        memory_store.store_skill_suggestion(SkillSuggestion(
            description="test pattern", suggested_name="test_specialist",
        ))
        result = json.loads(await get_proactive_suggestions())
        s = result["suggestions"][0]
        assert "category" in s
        assert "priority" in s
        assert "title" in s
        assert "description" in s
        assert "action" in s
        assert "created_at" in s

    @pytest.mark.asyncio
    async def test_multiple_categories(self, memory_store):
        # Add items across multiple categories
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        memory_store.store_delegation(Delegation(
            task="overdue", delegated_to="bob", due_date=yesterday,
        ))
        memory_store.store_webhook_event(WebhookEvent(
            source="github", event_type="push",
        ))
        memory_store.store_skill_suggestion(SkillSuggestion(
            description="pattern", suggested_name="specialist",
        ))
        result = json.loads(await get_proactive_suggestions())
        categories = {s["category"] for s in result["suggestions"]}
        assert "delegation" in categories
        assert "webhook" in categories
        assert "skill" in categories


class TestDismissSuggestion:
    @pytest.mark.asyncio
    async def test_dismiss_returns_acknowledgment(self):
        result = json.loads(await dismiss_suggestion("skill", "Some suggestion"))
        assert result["status"] == "dismissed"
        assert result["category"] == "skill"
        assert result["title"] == "Some suggestion"

    @pytest.mark.asyncio
    async def test_dismiss_any_category(self):
        for cat in ("skill", "webhook", "delegation", "decision", "deadline"):
            result = json.loads(await dismiss_suggestion(cat, f"test {cat}"))
            assert result["status"] == "dismissed"
            assert result["category"] == cat
