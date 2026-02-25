"""Tests for channel routing MCP tools."""

import json
import pytest

import mcp_server
from mcp_tools.routing_tools import route_message


class TestRouteMessage:
    @pytest.mark.asyncio
    async def test_self_recipient(self):
        result = json.loads(await route_message(
            recipient_type="self",
            urgency="informational",
        ))
        assert result["safety_tier"] == "auto_send"
        assert result["channel"] == "email"

    @pytest.mark.asyncio
    async def test_external_recipient(self):
        result = json.loads(await route_message(
            recipient_type="external",
        ))
        assert result["safety_tier"] == "draft_only"
        assert result["channel"] == "email"

    @pytest.mark.asyncio
    async def test_sensitive_bumps_tier(self):
        result = json.loads(await route_message(
            recipient_type="internal",
            sensitive=True,
        ))
        assert result["safety_tier"] == "draft_only"

    @pytest.mark.asyncio
    async def test_self_urgent(self):
        result = json.loads(await route_message(
            recipient_type="self",
            urgency="urgent",
        ))
        assert result["safety_tier"] == "auto_send"
        assert result["channel"] == "imessage"

    @pytest.mark.asyncio
    async def test_self_ephemeral(self):
        result = json.loads(await route_message(
            recipient_type="self",
            urgency="ephemeral",
        ))
        assert result["channel"] == "notification"

    @pytest.mark.asyncio
    async def test_override_auto(self):
        result = json.loads(await route_message(
            recipient_type="external",
            override="auto",
        ))
        assert result["safety_tier"] == "auto_send"

    @pytest.mark.asyncio
    async def test_result_includes_work_hours(self):
        result = json.loads(await route_message(
            recipient_type="self",
        ))
        assert "work_hours" in result
        assert isinstance(result["work_hours"], bool)
