"""Tests for formatted output in MCP tool responses."""

import json
import pytest
from unittest.mock import MagicMock, patch

import mcp_server  # noqa: F401 — trigger register() calls
from mcp_tools.lifecycle_tools import list_delegations, list_pending_decisions, check_alerts
from mcp_tools.okr_tools import query_okr_status


@pytest.fixture
def lifecycle_state():
    """Set up memory_store on mcp_server._state for lifecycle tools."""
    mock_store = MagicMock()
    mcp_server._state.memory_store = mock_store
    yield mock_store
    mcp_server._state.memory_store = None


class TestListDelegationsFormatted:
    @pytest.mark.asyncio
    async def test_includes_formatted_key(self, lifecycle_state):
        """list_delegations response includes a formatted table string."""
        with patch("tools.lifecycle.list_delegations") as mock_fn:
            mock_fn.return_value = {
                "results": [
                    {"task": "Review RBAC", "delegated_to": "Shawn", "priority": "high", "status": "active", "due_date": "2026-03-01"},
                ]
            }
            result = await list_delegations()
            parsed = json.loads(result)
            assert "formatted" in parsed
            assert "Review RBAC" in parsed["formatted"]
            assert "Shawn" in parsed["formatted"]

    @pytest.mark.asyncio
    async def test_empty_delegations_no_formatted(self, lifecycle_state):
        with patch("tools.lifecycle.list_delegations") as mock_fn:
            mock_fn.return_value = {"results": []}
            result = await list_delegations()
            parsed = json.loads(result)
            assert parsed.get("formatted", "") == ""


class TestListPendingDecisionsFormatted:
    @pytest.mark.asyncio
    async def test_includes_formatted_key(self, lifecycle_state):
        with patch("tools.lifecycle.list_pending_decisions") as mock_fn:
            mock_fn.return_value = {
                "results": [
                    {"title": "Approve rollout", "status": "pending_execution", "owner": "Jason", "follow_up_date": "2026-03-01"},
                ]
            }
            result = await list_pending_decisions()
            parsed = json.loads(result)
            assert "formatted" in parsed
            assert "Approve rollout" in parsed["formatted"]


class TestCheckAlertsFormatted:
    @pytest.mark.asyncio
    async def test_includes_formatted_key(self, lifecycle_state):
        with patch("tools.lifecycle.check_alerts") as mock_fn:
            mock_fn.return_value = {
                "alerts": [
                    {"type": "overdue_delegation", "message": "Review RBAC is overdue"},
                ],
                "count": 1,
            }
            result = await check_alerts()
            parsed = json.loads(result)
            assert "formatted" in parsed
            assert "overdue" in parsed["formatted"].lower() or "RBAC" in parsed["formatted"]

    @pytest.mark.asyncio
    async def test_empty_alerts_no_formatted(self, lifecycle_state):
        with patch("tools.lifecycle.check_alerts") as mock_fn:
            mock_fn.return_value = {"alerts": [], "count": 0}
            result = await check_alerts()
            parsed = json.loads(result)
            assert parsed.get("formatted", "") == ""


class TestQueryOkrFormatted:
    @pytest.mark.asyncio
    async def test_includes_formatted_key(self):
        mock_store = MagicMock()
        mock_store.query.return_value = {
            "results": [
                {"initiative": "RBAC rollout", "team": "IAM", "status": "At Risk", "progress": "5%"},
            ]
        }
        mcp_server._state.okr_store = mock_store
        try:
            result = await query_okr_status(query="RBAC")
            parsed = json.loads(result)
            assert "formatted" in parsed
            assert "RBAC" in parsed["formatted"]
        finally:
            mcp_server._state.okr_store = None

    @pytest.mark.asyncio
    async def test_empty_results_no_formatted(self):
        mock_store = MagicMock()
        mock_store.query.return_value = {"results": []}
        mcp_server._state.okr_store = mock_store
        try:
            result = await query_okr_status(query="nothing")
            parsed = json.loads(result)
            assert parsed.get("formatted", "") == ""
        finally:
            mcp_server._state.okr_store = None
