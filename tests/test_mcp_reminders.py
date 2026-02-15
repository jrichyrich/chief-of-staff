# tests/test_mcp_reminders.py
"""Tests for the MCP reminder and notification tool functions in mcp_server.py.

Follows the same pattern as tests/test_mcp_calendar.py: inject a mock
ReminderStore into mcp_server._state["reminder_store"] and call the
async tool functions directly.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_reminder_store():
    """Return a MagicMock that quacks like ReminderStore."""
    store = MagicMock()
    store.list_reminder_lists.return_value = []
    store.get_reminders.return_value = []
    store.create_reminder.return_value = {}
    store.complete_reminder.return_value = {}
    store.delete_reminder.return_value = True
    store.search_reminders.return_value = []
    return store


@pytest.fixture
def reminder_state(mock_reminder_store):
    """Inject mock reminder store into mcp_server._state, then clean up."""
    import mcp_server

    mcp_server._state["reminder_store"] = mock_reminder_store
    yield mock_reminder_store
    mcp_server._state.pop("reminder_store", None)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestReminderToolsRegistered:
    def test_reminder_tools_registered(self):
        """Verify all reminder tools are registered on the MCP server."""
        import mcp_server

        tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
        expected = [
            "list_reminder_lists",
            "get_reminders",
            "create_reminder",
            "complete_reminder",
            "delete_reminder",
            "search_reminders",
        ]
        for name in expected:
            assert name in tool_names, f"Reminder tool '{name}' not registered"

    def test_notification_tools_registered(self):
        """Verify notification tool is registered on the MCP server."""
        import mcp_server

        tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
        assert "send_notification" in tool_names


# ---------------------------------------------------------------------------
# list_reminder_lists
# ---------------------------------------------------------------------------


class TestListReminderListsTool:
    @pytest.mark.asyncio
    async def test_list_reminder_lists(self, reminder_state):
        from mcp_server import list_reminder_lists

        reminder_state.list_reminder_lists.return_value = [
            {"name": "Reminders", "source": "iCloud", "color": "#0000ff"},
            {"name": "Shopping", "source": "iCloud", "color": "#ff0000"},
        ]

        result = await list_reminder_lists()
        data = json.loads(result)

        assert "results" in data
        assert len(data["results"]) == 2
        assert data["results"][0]["name"] == "Reminders"
        assert data["results"][1]["name"] == "Shopping"
        reminder_state.list_reminder_lists.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_reminder_lists_empty(self, reminder_state):
        from mcp_server import list_reminder_lists

        reminder_state.list_reminder_lists.return_value = []

        result = await list_reminder_lists()
        data = json.loads(result)

        assert data["results"] == []


# ---------------------------------------------------------------------------
# get_reminders
# ---------------------------------------------------------------------------


class TestGetRemindersTool:
    @pytest.mark.asyncio
    async def test_get_all_reminders(self, reminder_state):
        from mcp_server import get_reminders

        reminder_state.get_reminders.return_value = [
            {"id": "R1", "title": "Buy milk", "completed": False, "list_name": "Reminders"},
        ]

        result = await get_reminders()
        data = json.loads(result)

        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["id"] == "R1"
        reminder_state.get_reminders.assert_called_once_with(
            list_name=None, completed=None
        )

    @pytest.mark.asyncio
    async def test_get_reminders_filtered_by_list(self, reminder_state):
        from mcp_server import get_reminders

        reminder_state.get_reminders.return_value = [
            {"id": "R2", "title": "Buy bread", "completed": False, "list_name": "Shopping"},
        ]

        result = await get_reminders(list_name="Shopping")
        data = json.loads(result)

        assert len(data["results"]) == 1
        reminder_state.get_reminders.assert_called_once_with(
            list_name="Shopping", completed=None
        )

    @pytest.mark.asyncio
    async def test_get_reminders_completed_filter(self, reminder_state):
        from mcp_server import get_reminders

        reminder_state.get_reminders.return_value = [
            {"id": "R3", "title": "Done", "completed": True, "list_name": "Reminders"},
        ]

        result = await get_reminders(completed="true")
        data = json.loads(result)

        assert len(data["results"]) == 1
        reminder_state.get_reminders.assert_called_once_with(
            list_name=None, completed=True
        )

    @pytest.mark.asyncio
    async def test_get_reminders_incomplete_filter(self, reminder_state):
        from mcp_server import get_reminders

        reminder_state.get_reminders.return_value = []

        result = await get_reminders(completed="false")
        data = json.loads(result)

        reminder_state.get_reminders.assert_called_once_with(
            list_name=None, completed=False
        )


# ---------------------------------------------------------------------------
# create_reminder
# ---------------------------------------------------------------------------


class TestCreateReminderTool:
    @pytest.mark.asyncio
    async def test_create_reminder_basic(self, reminder_state):
        from mcp_server import create_reminder

        reminder_state.create_reminder.return_value = {
            "id": "NEW-1",
            "title": "New task",
            "completed": False,
            "list_name": "Reminders",
        }

        result = await create_reminder(title="New task")
        data = json.loads(result)

        assert data["status"] == "created"
        assert data["reminder"]["id"] == "NEW-1"
        assert data["reminder"]["title"] == "New task"
        reminder_state.create_reminder.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_reminder_with_all_fields(self, reminder_state):
        from mcp_server import create_reminder

        reminder_state.create_reminder.return_value = {
            "id": "NEW-2",
            "title": "Full reminder",
            "priority": 1,
            "list_name": "Work",
        }

        result = await create_reminder(
            title="Full reminder",
            list_name="Work",
            due_date="2025-03-15T14:00:00",
            priority=1,
            notes="Important notes",
        )
        data = json.loads(result)

        assert data["status"] == "created"
        call_kwargs = reminder_state.create_reminder.call_args[1]
        assert call_kwargs["title"] == "Full reminder"
        assert call_kwargs["list_name"] == "Work"
        assert call_kwargs["due_date"] == "2025-03-15T14:00:00"
        assert call_kwargs["priority"] == 1
        assert call_kwargs["notes"] == "Important notes"

    @pytest.mark.asyncio
    async def test_create_reminder_error_from_store(self, reminder_state):
        from mcp_server import create_reminder

        reminder_state.create_reminder.return_value = {
            "error": "Reminder list 'NonExistent' not found"
        }

        result = await create_reminder(title="Bad", list_name="NonExistent")
        data = json.loads(result)

        assert "reminder" in data or "error" in data


# ---------------------------------------------------------------------------
# complete_reminder
# ---------------------------------------------------------------------------


class TestCompleteReminderTool:
    @pytest.mark.asyncio
    async def test_complete_reminder(self, reminder_state):
        from mcp_server import complete_reminder

        reminder_state.complete_reminder.return_value = {
            "id": "COMP-1",
            "title": "Done task",
            "completed": True,
        }

        result = await complete_reminder(reminder_id="COMP-1")
        data = json.loads(result)

        assert data["status"] == "completed"
        assert data["reminder"]["id"] == "COMP-1"
        reminder_state.complete_reminder.assert_called_once_with("COMP-1")

    @pytest.mark.asyncio
    async def test_complete_reminder_not_found(self, reminder_state):
        from mcp_server import complete_reminder

        reminder_state.complete_reminder.return_value = {
            "error": "Reminder not found: MISSING-1"
        }

        result = await complete_reminder(reminder_id="MISSING-1")
        data = json.loads(result)

        # The tool wraps the result
        assert data["status"] == "completed"
        assert "error" in data["reminder"]


# ---------------------------------------------------------------------------
# delete_reminder
# ---------------------------------------------------------------------------


class TestDeleteReminderTool:
    @pytest.mark.asyncio
    async def test_delete_reminder(self, reminder_state):
        from mcp_server import delete_reminder

        reminder_state.delete_reminder.return_value = True

        result = await delete_reminder(reminder_id="DEL-1")
        data = json.loads(result)

        assert data["status"] == "deleted"
        assert data["reminder_id"] == "DEL-1"
        reminder_state.delete_reminder.assert_called_once_with("DEL-1")

    @pytest.mark.asyncio
    async def test_delete_reminder_not_found(self, reminder_state):
        from mcp_server import delete_reminder

        reminder_state.delete_reminder.return_value = {
            "error": "Reminder not found: MISSING-1"
        }

        result = await delete_reminder(reminder_id="MISSING-1")
        data = json.loads(result)

        assert "error" in data
        assert "not found" in data["error"]


# ---------------------------------------------------------------------------
# search_reminders
# ---------------------------------------------------------------------------


class TestSearchRemindersTool:
    @pytest.mark.asyncio
    async def test_search_reminders(self, reminder_state):
        from mcp_server import search_reminders

        reminder_state.search_reminders.return_value = [
            {"id": "S1", "title": "Buy groceries", "completed": False},
        ]

        result = await search_reminders(query="groceries")
        data = json.loads(result)

        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Buy groceries"
        reminder_state.search_reminders.assert_called_once_with(
            "groceries", include_completed=False
        )

    @pytest.mark.asyncio
    async def test_search_reminders_include_completed(self, reminder_state):
        from mcp_server import search_reminders

        reminder_state.search_reminders.return_value = []

        result = await search_reminders(query="task", include_completed=True)
        data = json.loads(result)

        assert data["results"] == []
        reminder_state.search_reminders.assert_called_once_with(
            "task", include_completed=True
        )

    @pytest.mark.asyncio
    async def test_search_reminders_no_results(self, reminder_state):
        from mcp_server import search_reminders

        reminder_state.search_reminders.return_value = []

        result = await search_reminders(query="nonexistent")
        data = json.loads(result)

        assert data["results"] == []


# ---------------------------------------------------------------------------
# send_notification (MCP tool)
# ---------------------------------------------------------------------------


class TestSendNotificationTool:
    @pytest.mark.asyncio
    async def test_send_notification_basic(self):
        from mcp_server import send_notification

        with patch("mcp_server.Notifier") as mock_notifier:
            mock_notifier.send.return_value = {
                "status": "sent",
                "title": "Test",
                "message": "Hello",
            }

            result = await send_notification(title="Test", message="Hello")
            data = json.loads(result)

            assert data["status"] == "sent"
            assert data["title"] == "Test"
            assert data["message"] == "Hello"
            mock_notifier.send.assert_called_once_with(
                title="Test", message="Hello", subtitle=None, sound="default"
            )

    @pytest.mark.asyncio
    async def test_send_notification_with_subtitle(self):
        from mcp_server import send_notification

        with patch("mcp_server.Notifier") as mock_notifier:
            mock_notifier.send.return_value = {"status": "sent", "title": "T", "message": "M"}

            result = await send_notification(
                title="T", message="M", subtitle="Sub"
            )
            data = json.loads(result)

            assert data["status"] == "sent"
            mock_notifier.send.assert_called_once_with(
                title="T", message="M", subtitle="Sub", sound="default"
            )

    @pytest.mark.asyncio
    async def test_send_notification_no_sound(self):
        from mcp_server import send_notification

        with patch("mcp_server.Notifier") as mock_notifier:
            mock_notifier.send.return_value = {"status": "sent", "title": "T", "message": "M"}

            result = await send_notification(
                title="T", message="M", sound=""
            )
            data = json.loads(result)

            assert data["status"] == "sent"
            mock_notifier.send.assert_called_once_with(
                title="T", message="M", subtitle=None, sound=None
            )

    @pytest.mark.asyncio
    async def test_send_notification_error(self):
        from mcp_server import send_notification

        with patch("mcp_server.Notifier") as mock_notifier:
            mock_notifier.send.return_value = {
                "error": "Notifications are only available on macOS"
            }

            result = await send_notification(title="Test", message="Hello")
            data = json.loads(result)

            assert "error" in data

    @pytest.mark.asyncio
    async def test_send_notification_exception(self):
        from mcp_server import send_notification

        with patch("mcp_server.Notifier") as mock_notifier:
            mock_notifier.send.side_effect = RuntimeError("Unexpected error")

            result = await send_notification(title="Test", message="Hello")
            data = json.loads(result)

            assert "error" in data
            assert "Unexpected error" in data["error"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestReminderToolErrorHandling:
    @pytest.mark.asyncio
    async def test_reminder_tool_error_propagation(self, reminder_state):
        """When the store returns an error dict, the tool should propagate it."""
        from mcp_server import list_reminder_lists

        reminder_state.list_reminder_lists.return_value = [
            {"error": "EventKit is only available on macOS with PyObjC installed."}
        ]

        result = await list_reminder_lists()
        data = json.loads(result)

        assert "results" in data
        assert data["results"][0]["error"] == "EventKit is only available on macOS with PyObjC installed."

    @pytest.mark.asyncio
    async def test_reminder_tool_exception_handling(self, reminder_state):
        """When the store raises an exception, the tool should catch it."""
        from mcp_server import get_reminders

        reminder_state.get_reminders.side_effect = RuntimeError("Connection failed")

        result = await get_reminders()
        data = json.loads(result)

        assert "error" in data
        assert "Connection failed" in data["error"]
