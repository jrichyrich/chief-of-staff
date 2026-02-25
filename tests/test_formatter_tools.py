"""Tests for MCP formatter tool wrappers."""

import json
import pytest

import mcp_server  # noqa: F401 — trigger register() calls
from mcp_tools.formatter_tools import format_table, format_brief, format_dashboard, format_card


class TestFormatTable:
    @pytest.mark.asyncio
    async def test_format_table_returns_string(self):
        result = await format_table(
            title="Test",
            columns=json.dumps(["A", "B"]),
            rows=json.dumps([["1", "2"], ["3", "4"]]),
            mode="plain",
        )
        assert isinstance(result, str)
        assert "1" in result
        assert "A" in result

    @pytest.mark.asyncio
    async def test_format_table_empty_rows(self):
        result = await format_table(
            title="Empty",
            columns=json.dumps(["A"]),
            rows=json.dumps([]),
            mode="plain",
        )
        parsed = json.loads(result)
        assert parsed["result"] == ""

    @pytest.mark.asyncio
    async def test_format_table_invalid_json(self):
        result = await format_table(
            title="Bad",
            columns="not json",
            rows="[]",
            mode="plain",
        )
        parsed = json.loads(result)
        assert "error" in parsed


class TestFormatBrief:
    @pytest.mark.asyncio
    async def test_format_brief_returns_rendered(self):
        data = json.dumps({
            "date": "2026-02-25",
            "calendar": [{"time": "9 AM", "event": "Standup", "status": "Teams"}],
        })
        result = await format_brief(data=data, mode="plain")
        assert "Standup" in result

    @pytest.mark.asyncio
    async def test_format_brief_invalid_json(self):
        result = await format_brief(data="not json", mode="plain")
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_format_brief_empty_data(self):
        data = json.dumps({"date": "2026-02-25"})
        result = await format_brief(data=data, mode="plain")
        parsed = json.loads(result)
        assert parsed["result"] == ""


class TestFormatDashboard:
    @pytest.mark.asyncio
    async def test_format_dashboard_returns_rendered(self):
        panels = json.dumps([
            {"title": "Section A", "content": "Hello"},
            {"title": "Section B", "content": "World"},
        ])
        result = await format_dashboard(
            title="Test Dashboard",
            panels=panels,
            mode="plain",
        )
        assert "Test Dashboard" in result
        assert "Section A" in result

    @pytest.mark.asyncio
    async def test_format_dashboard_empty_panels(self):
        result = await format_dashboard(
            title="Empty",
            panels=json.dumps([]),
            mode="plain",
        )
        parsed = json.loads(result)
        assert parsed["result"] == ""


class TestFormatCard:
    @pytest.mark.asyncio
    async def test_format_card_returns_rendered(self):
        result = await format_card(
            title="Status",
            fields=json.dumps({"Owner": "Shawn", "Progress": "5%"}),
            status="yellow",
            mode="plain",
        )
        assert "Status" in result
        assert "Shawn" in result

    @pytest.mark.asyncio
    async def test_format_card_invalid_json(self):
        result = await format_card(
            title="Bad",
            fields="not json",
            mode="plain",
        )
        parsed = json.loads(result)
        assert "error" in parsed
