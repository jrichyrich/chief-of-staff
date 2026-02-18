# tests/test_providers_direct.py
from datetime import datetime
from unittest.mock import MagicMock, Mock

import pytest

from connectors.claude_m365_bridge import ClaudeM365Bridge
from connectors.providers.apple_provider import AppleCalendarProvider
from connectors.providers.m365_provider import Microsoft365CalendarProvider


@pytest.fixture
def mock_calendar_store():
    """Mock CalendarStore for AppleCalendarProvider tests."""
    return MagicMock()


@pytest.fixture
def mock_m365_bridge():
    """Mock ClaudeM365Bridge for M365CalendarProvider tests."""
    return MagicMock(spec=ClaudeM365Bridge)


class TestAppleCalendarProvider:
    def test_is_connected(self, mock_calendar_store):
        provider = AppleCalendarProvider(mock_calendar_store)
        assert provider.is_connected() is True

    def test_list_calendars_success(self, mock_calendar_store):
        mock_calendar_store.list_calendars.return_value = [
            {"name": "Work", "source": "iCloud", "color": "blue"},
            {"name": "Personal", "source": "Local", "color": "red"},
        ]

        provider = AppleCalendarProvider(mock_calendar_store)
        result = provider.list_calendars()

        assert len(result) == 2
        assert result[0]["name"] == "Work"
        assert result[0]["provider"] == "apple"
        assert result[0]["source_account"] == "iCloud"
        assert result[0]["calendar_id"] == "Work"

        assert result[1]["name"] == "Personal"
        assert result[1]["source_account"] == "Local"

    def test_list_calendars_with_error(self, mock_calendar_store):
        mock_calendar_store.list_calendars.return_value = [
            {"error": "Failed to access EventKit"}
        ]

        provider = AppleCalendarProvider(mock_calendar_store)
        result = provider.list_calendars()

        assert len(result) == 1
        assert "error" in result[0]

    def test_get_events_success(self, mock_calendar_store):
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        mock_calendar_store.get_events.return_value = [
            {
                "uid": "event-123",
                "title": "Team meeting",
                "start": "2026-02-17T10:00:00",
                "end": "2026-02-17T11:00:00",
                "calendar": "Work",
                "location": "Room 401",
            },
            {
                "uid": "event-456",
                "title": "Lunch",
                "start": "2026-02-17T12:00:00",
                "end": "2026-02-17T13:00:00",
                "calendar": "Personal",
            },
        ]

        provider = AppleCalendarProvider(mock_calendar_store)
        # Populate calendar source map
        mock_calendar_store.list_calendars.return_value = [
            {"name": "Work", "source": "iCloud"},
            {"name": "Personal", "source": "Local"},
        ]
        provider.list_calendars()

        result = provider.get_events(start, end)

        assert len(result) == 2
        assert result[0]["uid"] == "event-123"
        assert result[0]["title"] == "Team meeting"
        assert result[0]["provider"] == "apple"
        assert result[0]["calendar_id"] == "Work"
        assert result[0]["source_account"] == "iCloud"
        assert result[0]["native_id"] == "event-123"
        assert result[0]["unified_uid"] == "apple:event-123"

        assert result[1]["calendar_id"] == "Personal"
        assert result[1]["source_account"] == "Local"

    def test_get_events_with_calendar_filter(self, mock_calendar_store):
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        mock_calendar_store.get_events.return_value = [
            {"uid": "event-123", "title": "Meeting", "calendar": "Work"}
        ]

        provider = AppleCalendarProvider(mock_calendar_store)
        provider.get_events(start, end, calendar_names=["Work"])

        mock_calendar_store.get_events.assert_called_once_with(
            start, end, calendar_names=["Work"]
        )

    def test_get_events_with_error(self, mock_calendar_store):
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        mock_calendar_store.get_events.return_value = [
            {"error": "Calendar access denied"}
        ]

        provider = AppleCalendarProvider(mock_calendar_store)
        result = provider.get_events(start, end)

        assert len(result) == 1
        assert "error" in result[0]

    def test_get_events_empty_results(self, mock_calendar_store):
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        mock_calendar_store.get_events.return_value = []

        provider = AppleCalendarProvider(mock_calendar_store)
        result = provider.get_events(start, end)

        assert result == []

    def test_create_event_success(self, mock_calendar_store):
        start = datetime(2026, 2, 20, 10, 0)
        end = datetime(2026, 2, 20, 11, 0)

        mock_calendar_store.create_event.return_value = {
            "status": "created",
            "uid": "new-event-789",
            "title": "New meeting",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "calendar": "Work",
        }

        provider = AppleCalendarProvider(mock_calendar_store)
        # Populate calendar source map
        mock_calendar_store.list_calendars.return_value = [
            {"name": "Work", "source": "iCloud"}
        ]
        provider.list_calendars()

        result = provider.create_event(
            title="New meeting",
            start_dt=start,
            end_dt=end,
            calendar_name="Work",
            location="Room 101",
            notes="Important meeting",
        )

        assert result["status"] == "created"
        assert result["provider"] == "apple"
        assert result["native_id"] == "new-event-789"
        assert result["unified_uid"] == "apple:new-event-789"

        mock_calendar_store.create_event.assert_called_once_with(
            title="New meeting",
            start_dt=start,
            end_dt=end,
            calendar_name="Work",
            location="Room 101",
            notes="Important meeting",
            is_all_day=False,
        )

    def test_create_event_with_error(self, mock_calendar_store):
        start = datetime(2026, 2, 20, 10, 0)
        end = datetime(2026, 2, 20, 11, 0)

        mock_calendar_store.create_event.return_value = {
            "error": "Calendar not found"
        }

        provider = AppleCalendarProvider(mock_calendar_store)
        result = provider.create_event(
            title="Test",
            start_dt=start,
            end_dt=end,
        )

        assert "error" in result
        assert result["error"] == "Calendar not found"

    def test_update_event_success(self, mock_calendar_store):
        mock_calendar_store.update_event.return_value = {
            "status": "updated",
            "uid": "event-123",
            "title": "Updated title",
            "calendar": "Work",
        }

        provider = AppleCalendarProvider(mock_calendar_store)
        # Populate calendar source map
        mock_calendar_store.list_calendars.return_value = [
            {"name": "Work", "source": "iCloud"}
        ]
        provider.list_calendars()

        result = provider.update_event(
            event_uid="event-123",
            calendar_name="Work",
            title="Updated title",
        )

        assert result["status"] == "updated"
        assert result["provider"] == "apple"
        assert result["unified_uid"] == "apple:event-123"

    def test_delete_event_success(self, mock_calendar_store):
        mock_calendar_store.delete_event.return_value = {
            "status": "deleted",
        }

        provider = AppleCalendarProvider(mock_calendar_store)
        result = provider.delete_event("event-123", calendar_name="Work")

        assert result["status"] == "deleted"
        assert result["provider"] == "apple"
        assert result["native_id"] == "event-123"
        assert result["unified_uid"] == "apple:event-123"

    def test_search_events_success(self, mock_calendar_store):
        start = datetime(2026, 2, 1, 0, 0)
        end = datetime(2026, 2, 28, 23, 59)

        mock_calendar_store.search_events.return_value = [
            {"uid": "event-111", "title": "Team standup", "calendar": "Work"},
            {"uid": "event-222", "title": "Team retro", "calendar": "Work"},
        ]

        provider = AppleCalendarProvider(mock_calendar_store)
        # Populate calendar source map
        mock_calendar_store.list_calendars.return_value = [
            {"name": "Work", "source": "iCloud"}
        ]
        provider.list_calendars()

        result = provider.search_events("Team", start, end)

        assert len(result) == 2
        assert result[0]["title"] == "Team standup"
        assert result[0]["provider"] == "apple"
        assert result[1]["title"] == "Team retro"

        mock_calendar_store.search_events.assert_called_once_with("Team", start, end)

    def test_tag_event_lazy_calendar_refresh(self, mock_calendar_store):
        """Test that provider refreshes calendar map if not already loaded."""
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        mock_calendar_store.get_events.return_value = [
            {"uid": "event-123", "title": "Meeting", "calendar": "Work"}
        ]

        mock_calendar_store.list_calendars.return_value = [
            {"name": "Work", "source": "iCloud"}
        ]

        provider = AppleCalendarProvider(mock_calendar_store)
        # Don't call list_calendars first
        result = provider.get_events(start, end)

        # Provider should lazily refresh calendar map
        assert result[0]["source_account"] == "iCloud"
        assert mock_calendar_store.list_calendars.called


class TestMicrosoft365CalendarProvider:
    def test_is_connected_when_not_connected(self):
        provider = Microsoft365CalendarProvider(connected=False)
        assert provider.is_connected() is False

    def test_is_connected_when_connected(self):
        provider = Microsoft365CalendarProvider(connected=True)
        assert provider.is_connected() is True

    def test_set_connected(self):
        provider = Microsoft365CalendarProvider(connected=False)
        assert provider.is_connected() is False

        provider.set_connected(True)
        assert provider.is_connected() is True

    def test_list_calendars_not_connected_error(self):
        provider = Microsoft365CalendarProvider(connected=False)
        result = provider.list_calendars()

        assert len(result) == 1
        assert "error" in result[0]
        assert "not connected" in result[0]["error"]

    def test_list_calendars_not_configured_error(self):
        provider = Microsoft365CalendarProvider(connected=True)
        result = provider.list_calendars()

        assert len(result) == 1
        assert "error" in result[0]
        assert "no adapter hook" in result[0]["error"]

    def test_list_calendars_success(self):
        def mock_list_calendars():
            return [
                {"name": "Calendar", "calendar_id": "cal-1", "source_account": "M365"},
                {"name": "Other", "calendar_id": "cal-2"},
            ]

        provider = Microsoft365CalendarProvider(
            connected=True,
            list_calendars_fn=mock_list_calendars,
        )
        result = provider.list_calendars()

        assert len(result) == 2
        assert result[0]["name"] == "Calendar"
        assert result[0]["provider"] == "microsoft_365"
        assert result[0]["source_account"] == "M365"
        assert result[0]["calendar_id"] == "cal-1"

        # Second calendar uses fallback source_account
        assert result[1]["source_account"] == "Microsoft 365"

    def test_get_events_not_connected_error(self):
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        provider = Microsoft365CalendarProvider(connected=False)
        result = provider.get_events(start, end)

        assert len(result) == 1
        assert "error" in result[0]

    def test_get_events_not_configured_error(self):
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        provider = Microsoft365CalendarProvider(connected=True)
        result = provider.get_events(start, end)

        assert len(result) == 1
        assert "error" in result[0]
        assert "no adapter hook" in result[0]["error"]

    def test_get_events_success(self):
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        def mock_get_events(start_dt, end_dt, calendar_names):
            return [
                {
                    "uid": "m365-123",
                    "native_id": "m365-123",
                    "title": "Meeting",
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                    "calendar": "Calendar",
                    "calendar_id": "cal-1",
                    "source_account": "M365",
                }
            ]

        provider = Microsoft365CalendarProvider(
            connected=True,
            get_events_fn=mock_get_events,
        )
        result = provider.get_events(start, end, calendar_names=["Calendar"])

        assert len(result) == 1
        assert result[0]["title"] == "Meeting"
        assert result[0]["provider"] == "microsoft_365"
        assert result[0]["native_id"] == "m365-123"
        assert result[0]["unified_uid"] == "microsoft_365:m365-123"
        assert result[0]["source_account"] == "M365"

    def test_get_events_empty_results(self):
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        def mock_get_events(start_dt, end_dt, calendar_names):
            return []

        provider = Microsoft365CalendarProvider(
            connected=True,
            get_events_fn=mock_get_events,
        )
        result = provider.get_events(start, end)

        assert result == []

    def test_create_event_not_connected_error(self):
        start = datetime(2026, 2, 20, 10, 0)
        end = datetime(2026, 2, 20, 11, 0)

        provider = Microsoft365CalendarProvider(connected=False)
        result = provider.create_event("Test", start, end)

        assert "error" in result

    def test_create_event_success(self):
        start = datetime(2026, 2, 20, 10, 0)
        end = datetime(2026, 2, 20, 11, 0)

        def mock_create_event(**kwargs):
            return {
                "uid": "new-m365-789",
                "native_id": "new-m365-789",
                "title": kwargs["title"],
                "start": kwargs["start_dt"].isoformat(),
                "end": kwargs["end_dt"].isoformat(),
                "calendar_id": "cal-1",
                "source_account": "M365",
            }

        provider = Microsoft365CalendarProvider(
            connected=True,
            create_event_fn=mock_create_event,
        )
        result = provider.create_event(
            title="New meeting",
            start_dt=start,
            end_dt=end,
            calendar_name="Calendar",
            location="Room 101",
        )

        assert result["title"] == "New meeting"
        assert result["provider"] == "microsoft_365"
        assert result["unified_uid"] == "microsoft_365:new-m365-789"

    def test_create_event_with_hook_error(self):
        start = datetime(2026, 2, 20, 10, 0)
        end = datetime(2026, 2, 20, 11, 0)

        def mock_create_event(**kwargs):
            return {"error": "Calendar not found"}

        provider = Microsoft365CalendarProvider(
            connected=True,
            create_event_fn=mock_create_event,
        )
        result = provider.create_event("Test", start, end)

        assert "error" in result
        assert result["error"] == "Calendar not found"

    def test_update_event_success(self):
        def mock_update_event(**kwargs):
            return {
                "uid": "m365-123",
                "native_id": "m365-123",
                "title": "Updated",
                "calendar_id": "cal-1",
            }

        provider = Microsoft365CalendarProvider(
            connected=True,
            update_event_fn=mock_update_event,
        )
        result = provider.update_event("m365-123", title="Updated")

        assert result["title"] == "Updated"
        assert result["provider"] == "microsoft_365"
        assert result["unified_uid"] == "microsoft_365:m365-123"

    def test_delete_event_success(self):
        def mock_delete_event(**kwargs):
            return {"status": "deleted"}

        provider = Microsoft365CalendarProvider(
            connected=True,
            delete_event_fn=mock_delete_event,
        )
        result = provider.delete_event("m365-123")

        assert result["status"] == "deleted"
        assert result["provider"] == "microsoft_365"
        assert result["native_id"] == "m365-123"
        assert result["unified_uid"] == "microsoft_365:m365-123"

    def test_search_events_success(self):
        start = datetime(2026, 2, 1, 0, 0)
        end = datetime(2026, 2, 28, 23, 59)

        def mock_search_events(query, start_dt, end_dt):
            return [
                {"uid": "m365-111", "native_id": "m365-111", "title": "Team meeting"},
            ]

        provider = Microsoft365CalendarProvider(
            connected=True,
            search_events_fn=mock_search_events,
        )
        result = provider.search_events("Team", start, end)

        assert len(result) == 1
        assert result[0]["title"] == "Team meeting"
        assert result[0]["provider"] == "microsoft_365"


class TestClaudeM365Bridge:
    def test_is_connector_connected_true(self):
        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            proc.stdout = "Microsoft 365: connected"
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        assert bridge.is_connector_connected() is True

    def test_is_connector_connected_false_not_found(self):
        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            proc.stdout = "Some other output"
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        assert bridge.is_connector_connected() is False

    def test_is_connector_connected_false_command_failed(self):
        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 1
            proc.stdout = ""
            proc.stderr = "Command not found"
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        assert bridge.is_connector_connected() is False

    def test_is_connector_connected_timeout(self):
        def mock_run(args, **kwargs):
            return None

        bridge = ClaudeM365Bridge(runner=mock_run)
        assert bridge.is_connector_connected() is False

    def test_list_calendars_success(self):
        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            proc.stdout = '{"structured_output": {"results": [{"name": "Calendar", "calendar_id": "cal-1"}]}}'
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge.list_calendars()

        assert len(result) == 1
        assert result[0]["name"] == "Calendar"
        assert result[0]["calendar_id"] == "cal-1"

    def test_list_calendars_command_failed(self):
        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 1
            proc.stdout = ""
            proc.stderr = "API error"
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge.list_calendars()

        assert len(result) == 1
        assert "error" in result[0]

    def test_get_events_success(self):
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            proc.stdout = '{"structured_output": {"results": [{"uid": "evt-1", "title": "Meeting"}]}}'
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge.get_events(start, end)

        assert len(result) == 1
        assert result[0]["title"] == "Meeting"

    def test_get_events_with_calendar_filter(self):
        start = datetime(2026, 2, 17, 9, 0)
        end = datetime(2026, 2, 17, 17, 0)

        def mock_run(args, **kwargs):
            # Verify that the prompt includes calendar filter
            prompt = args[2]  # -p <prompt>
            assert "Work" in prompt
            proc = Mock()
            proc.returncode = 0
            proc.stdout = '{"structured_output": {"results": []}}'
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        bridge.get_events(start, end, calendar_names=["Work"])

    def test_search_events_success(self):
        start = datetime(2026, 2, 1, 0, 0)
        end = datetime(2026, 2, 28, 23, 59)

        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            proc.stdout = '{"structured_output": {"results": [{"uid": "evt-1", "title": "Team sync"}]}}'
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge.search_events("Team", start, end)

        assert len(result) == 1
        assert result[0]["title"] == "Team sync"

    def test_create_event_success(self):
        start = datetime(2026, 2, 20, 10, 0)
        end = datetime(2026, 2, 20, 11, 0)

        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            proc.stdout = '{"structured_output": {"result": {"uid": "new-1", "title": "New meeting"}}}'
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge.create_event(
            title="New meeting",
            start_dt=start,
            end_dt=end,
            calendar_name="Calendar",
        )

        assert result["title"] == "New meeting"
        assert result["uid"] == "new-1"

    def test_create_event_invalid_response(self):
        start = datetime(2026, 2, 20, 10, 0)
        end = datetime(2026, 2, 20, 11, 0)

        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            proc.stdout = '{"structured_output": {"result": "not a dict"}}'
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge.create_event("Test", start, end)

        assert "error" in result
        assert "Invalid create_event response" in result["error"]

    def test_update_event_success(self):
        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            proc.stdout = '{"structured_output": {"result": {"uid": "evt-1", "title": "Updated"}}}'
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge.update_event("evt-1", title="Updated")

        assert result["title"] == "Updated"

    def test_update_event_with_datetime_conversion(self):
        start = datetime(2026, 2, 20, 10, 0)

        def mock_run(args, **kwargs):
            # Verify datetime is converted to ISO string in prompt
            prompt = args[2]
            assert "2026-02-20T10:00:00" in prompt
            proc = Mock()
            proc.returncode = 0
            proc.stdout = '{"structured_output": {"result": {"uid": "evt-1"}}}'
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        bridge.update_event("evt-1", start_dt=start)

    def test_delete_event_success(self):
        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            proc.stdout = '{"structured_output": {"status": "deleted", "event_uid": "evt-1"}}'
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge.delete_event("evt-1", calendar_name="Calendar")

        assert result["status"] == "deleted"
        assert result["event_uid"] == "evt-1"

    def test_invoke_structured_invalid_json(self):
        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            proc.stdout = "not valid json"
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge._invoke_structured("test", {"type": "object"})

        assert "error" in result

    def test_invoke_structured_parses_embedded_json_in_structured_output(self):
        """Test that the bridge can extract JSON from structured_output string."""
        def mock_run(args, **kwargs):
            proc = Mock()
            proc.returncode = 0
            # Valid JSON envelope with embedded JSON in structured_output field
            proc.stdout = '{"structured_output": "Here is the data: {\\"results\\": [{\\"value\\": 1}]}"}'
            proc.stderr = ""
            return proc

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge._invoke_structured("test", {"type": "object"})

        # The _parse_first_json_object should successfully extract from structured_output string
        assert result == {"results": [{"value": 1}]}

    def test_invoke_structured_timeout_handling(self):
        def mock_run(args, **kwargs):
            return None

        bridge = ClaudeM365Bridge(runner=mock_run)
        result = bridge._invoke_structured("test", {"type": "object"})

        assert "error" in result
        assert "Failed to invoke" in result["error"]

    def test_custom_configuration(self):
        bridge = ClaudeM365Bridge(
            claude_bin="/custom/claude",
            mcp_config="/custom/config.json",
            model="opus",
            timeout_seconds=120,
            detect_timeout_seconds=10,
        )

        assert bridge.claude_bin == "/custom/claude"
        assert bridge.mcp_config == "/custom/config.json"
        assert bridge.model == "opus"
        assert bridge.timeout_seconds == 120
        assert bridge.detect_timeout_seconds == 10
