"""Tests for Session Brain MCP tools."""

import json
import pytest

import mcp_server
from mcp_tools.brain_tools import get_session_brain, update_session_brain
from session.brain import SessionBrain


@pytest.fixture
def brain(tmp_path):
    return SessionBrain(tmp_path / "session_brain.md")


class TestGetSessionBrain:
    @pytest.mark.asyncio
    async def test_returns_empty_brain(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await get_session_brain())
        assert result["workstreams"] == []
        assert result["action_items"] == []

    @pytest.mark.asyncio
    async def test_returns_populated_brain(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        brain.add_workstream("Project X", "active", "Phase 1")
        brain.add_action_item("Fix bug")
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await get_session_brain())
        assert len(result["workstreams"]) == 1
        assert len(result["action_items"]) == 1


class TestUpdateSessionBrain:
    @pytest.mark.asyncio
    async def test_add_workstream(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="add_workstream",
            data=json.dumps({"name": "Project X", "status": "active", "context": "Phase 1"}),
        ))
        assert result["status"] == "updated"
        assert len(brain.workstreams) == 1

    @pytest.mark.asyncio
    async def test_add_action_item(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="add_action_item",
            data=json.dumps({"text": "Fix the bug", "source": "email"}),
        ))
        assert result["status"] == "updated"
        assert len(brain.action_items) == 1

    @pytest.mark.asyncio
    async def test_complete_action_item(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        brain.add_action_item("Fix bug")
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="complete_action_item",
            data=json.dumps({"text": "Fix bug"}),
        ))
        assert result["status"] == "updated"
        assert brain.action_items[0]["done"] is True

    @pytest.mark.asyncio
    async def test_add_decision(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="add_decision",
            data=json.dumps({"summary": "Use Approach C"}),
        ))
        assert result["status"] == "updated"
        assert len(brain.decisions) == 1

    @pytest.mark.asyncio
    async def test_add_person(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="add_person",
            data=json.dumps({"name": "Alice", "context": "Engineer"}),
        ))
        assert result["status"] == "updated"
        assert len(brain.people) == 1

    @pytest.mark.asyncio
    async def test_add_handoff_note(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="add_handoff_note",
            data=json.dumps({"note": "M365 write not available"}),
        ))
        assert result["status"] == "updated"
        assert len(brain.handoff_notes) == 1

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="invalid_action",
            data="{}",
        ))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="add_workstream",
            data="not json",
        ))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_brain_returns_error(self, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: None)
        result = json.loads(await get_session_brain())
        assert "error" in result
