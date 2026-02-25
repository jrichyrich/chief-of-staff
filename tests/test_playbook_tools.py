"""Tests for playbook MCP tools."""

import json
import pytest
from pathlib import Path

import mcp_server
from mcp_tools.playbook_tools import list_playbooks, get_playbook


@pytest.fixture
def playbook_dir(tmp_path):
    d = tmp_path / "playbooks"
    d.mkdir()
    (d / "test_playbook.yaml").write_text(
        "name: test_playbook\n"
        "description: A test playbook\n"
        "inputs:\n"
        "  - topic\n"
        "workstreams:\n"
        "  - name: researcher\n"
        '    prompt: "Research $topic"\n'
        "synthesis:\n"
        '  prompt: "Summarize findings about $topic"\n'
        "delivery:\n"
        "  default: inline\n"
    )
    return d


class TestListPlaybooks:
    @pytest.mark.asyncio
    async def test_lists_available_playbooks(self, playbook_dir, monkeypatch):
        import mcp_tools.playbook_tools as mod
        monkeypatch.setattr(mod, "_get_loader_dir", lambda: playbook_dir)
        result = json.loads(await list_playbooks())
        assert "test_playbook" in result["playbooks"]
        assert result["count"] >= 1
        assert "test_playbook" in result["descriptions"]

    @pytest.mark.asyncio
    async def test_empty_directory(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        import mcp_tools.playbook_tools as mod
        monkeypatch.setattr(mod, "_get_loader_dir", lambda: empty)
        result = json.loads(await list_playbooks())
        assert result["count"] == 0
        assert result["playbooks"] == []


class TestGetPlaybook:
    @pytest.mark.asyncio
    async def test_get_existing_playbook(self, playbook_dir, monkeypatch):
        import mcp_tools.playbook_tools as mod
        monkeypatch.setattr(mod, "_get_loader_dir", lambda: playbook_dir)
        result = json.loads(await get_playbook("test_playbook"))
        assert result["name"] == "test_playbook"
        assert len(result["workstreams"]) == 1
        assert result["inputs"] == ["topic"]
        assert result["delivery_default"] == "inline"

    @pytest.mark.asyncio
    async def test_get_nonexistent_playbook(self, playbook_dir, monkeypatch):
        import mcp_tools.playbook_tools as mod
        monkeypatch.setattr(mod, "_get_loader_dir", lambda: playbook_dir)
        result = json.loads(await get_playbook("nonexistent"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_playbook_includes_synthesis(self, playbook_dir, monkeypatch):
        import mcp_tools.playbook_tools as mod
        monkeypatch.setattr(mod, "_get_loader_dir", lambda: playbook_dir)
        result = json.loads(await get_playbook("test_playbook"))
        assert "Summarize" in result["synthesis_prompt"]
