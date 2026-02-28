# tests/test_dispatch_smoke.py
"""Smoke tests for the BaseExpertAgent dispatch table.

Validates every handler in _get_dispatch_table:
 - Does not crash with minimal valid input
 - Returns expected types (dict or list)
 - Stays in sync with TOOL_SCHEMAS in capabilities/registry.py
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.base import BaseExpertAgent
from agents.registry import AgentConfig
from capabilities.registry import TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def full_config():
    """Agent config with ALL capabilities so dispatch table is fully populated."""
    return AgentConfig(
        name="smoke-agent",
        description="Smoke test agent with all capabilities",
        system_prompt="Test.",
        capabilities=[
            "memory_read", "memory_write", "document_search",
            "decision_read", "decision_write",
            "delegation_read", "delegation_write",
            "alerts_read", "alerts_write",
            "calendar_read", "reminders_read", "reminders_write",
            "notifications", "mail_read", "mail_write",
        ],
    )


@pytest.fixture
def calendar_store():
    mock = MagicMock()
    mock.get_events.return_value = []
    mock.search_events.return_value = []
    return mock


@pytest.fixture
def reminder_store():
    mock = MagicMock()
    mock.list_reminders.return_value = []
    mock.search_reminders.return_value = []
    mock.create_reminder.return_value = {"status": "created", "id": "r-1"}
    mock.complete_reminder.return_value = {"status": "completed"}
    return mock


@pytest.fixture
def notifier():
    mock = MagicMock()
    mock.send.return_value = {"status": "sent"}
    return mock


@pytest.fixture
def mail_store():
    mock = MagicMock()
    mock.get_messages.return_value = []
    mock.get_message.return_value = {"id": "m-1", "subject": "Test"}
    mock.search_messages.return_value = []
    mock.list_mailboxes.return_value = [
        {"name": "INBOX", "account": "test", "unread_count": 5}
    ]
    mock.send_message.return_value = {"status": "draft_created"}
    mock.mark_read.return_value = {"status": "ok"}
    mock.mark_flagged.return_value = {"status": "ok"}
    mock.move_message.return_value = {"status": "moved"}
    return mock


@pytest.fixture
def agent(full_config, memory_store, document_store,
          calendar_store, reminder_store, notifier, mail_store):
    return BaseExpertAgent(
        config=full_config,
        memory_store=memory_store,
        document_store=document_store,
        client=AsyncMock(),
        calendar_store=calendar_store,
        reminder_store=reminder_store,
        notifier=notifier,
        mail_store=mail_store,
    )


# ---------------------------------------------------------------------------
# Schema sync: dispatch table <-> TOOL_SCHEMAS
# ---------------------------------------------------------------------------


class TestSchemaSync:
    def test_all_dispatch_tools_have_schemas(self, agent):
        """Every tool in the dispatch table must have a TOOL_SCHEMAS entry."""
        table = agent._get_dispatch_table()
        missing = set(table.keys()) - set(TOOL_SCHEMAS.keys())
        assert missing == set(), f"Dispatch table has tools without schemas: {missing}"

    def test_dispatch_table_not_empty(self, agent):
        table = agent._get_dispatch_table()
        assert len(table) > 0

    def test_dispatch_table_is_cached(self, agent):
        t1 = agent._get_dispatch_table()
        t2 = agent._get_dispatch_table()
        assert t1 is t2


# ---------------------------------------------------------------------------
# Memory & document tools (real stores from conftest)
# ---------------------------------------------------------------------------


class TestMemoryToolsSmoke:
    def test_query_memory(self, agent):
        result = agent._dispatch_tool("query_memory", {"query": "test"})
        assert isinstance(result, list)

    def test_query_memory_with_category(self, agent):
        result = agent._dispatch_tool("query_memory", {
            "query": "test", "category": "personal"
        })
        assert isinstance(result, list)

    def test_store_memory(self, agent):
        result = agent._dispatch_tool("store_memory", {
            "category": "work", "key": "project", "value": "chief-of-staff"
        })
        assert isinstance(result, dict)
        assert result["status"] == "stored"

    def test_store_memory_invalid_category(self, agent):
        result = agent._dispatch_tool("store_memory", {
            "category": "INVALID", "key": "k", "value": "v"
        })
        assert isinstance(result, dict)
        assert "error" in result

    def test_search_documents(self, agent):
        result = agent._dispatch_tool("search_documents", {"query": "test"})
        assert isinstance(result, list)

    def test_search_documents_with_top_k(self, agent):
        result = agent._dispatch_tool("search_documents", {
            "query": "test", "top_k": 3
        })
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Lifecycle — decisions (real memory_store)
# ---------------------------------------------------------------------------


class TestDecisionToolsSmoke:
    def test_create_decision(self, agent):
        result = agent._dispatch_tool("create_decision", {
            "title": "Smoke test decision"
        })
        assert isinstance(result, dict)
        assert result["status"] == "logged"
        assert "id" in result

    def test_create_decision_with_all_fields(self, agent):
        result = agent._dispatch_tool("create_decision", {
            "title": "Full decision",
            "description": "desc",
            "context": "ctx",
            "decided_by": "team",
            "owner": "alice",
            "status": "pending_execution",
            "follow_up_date": "2026-04-01",
            "tags": "smoke,test",
            "source": "test-suite",
        })
        assert isinstance(result, dict)
        assert result["status"] == "logged"

    def test_search_decisions(self, agent):
        result = agent._dispatch_tool("search_decisions", {"query": "test"})
        assert isinstance(result, dict)
        assert "results" in result

    def test_search_decisions_by_status(self, agent):
        result = agent._dispatch_tool("search_decisions", {
            "status": "pending_execution"
        })
        assert isinstance(result, dict)

    def test_update_decision(self, agent):
        created = agent._dispatch_tool("create_decision", {"title": "To update"})
        result = agent._dispatch_tool("update_decision", {
            "decision_id": created["id"], "status": "executed"
        })
        assert isinstance(result, dict)
        assert result.get("status") == "updated"

    def test_update_decision_not_found(self, agent):
        result = agent._dispatch_tool("update_decision", {"decision_id": 99999})
        assert isinstance(result, dict)
        assert "error" in result

    def test_list_pending_decisions(self, agent):
        result = agent._dispatch_tool("list_pending_decisions", {})
        assert isinstance(result, dict)
        assert "results" in result

    def test_delete_decision(self, agent):
        created = agent._dispatch_tool("create_decision", {"title": "To delete"})
        result = agent._dispatch_tool("delete_decision", {
            "decision_id": created["id"]
        })
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Lifecycle — delegations (real memory_store)
# ---------------------------------------------------------------------------


class TestDelegationToolsSmoke:
    def test_create_delegation(self, agent):
        result = agent._dispatch_tool("create_delegation", {
            "task": "Write docs", "delegated_to": "Alice"
        })
        assert isinstance(result, dict)

    def test_create_delegation_with_all_fields(self, agent):
        result = agent._dispatch_tool("create_delegation", {
            "task": "Review PR",
            "delegated_to": "Bob",
            "description": "Review the dispatch refactor PR",
            "due_date": "2026-03-15",
            "priority": "high",
            "source": "test-suite",
        })
        assert isinstance(result, dict)

    def test_list_delegations(self, agent):
        result = agent._dispatch_tool("list_delegations", {})
        assert isinstance(result, dict)

    def test_list_delegations_with_filters(self, agent):
        result = agent._dispatch_tool("list_delegations", {
            "status": "active", "delegated_to": "Alice"
        })
        assert isinstance(result, dict)

    def test_update_delegation(self, agent):
        created = agent._dispatch_tool("create_delegation", {
            "task": "Review PR", "delegated_to": "Bob"
        })
        result = agent._dispatch_tool("update_delegation", {
            "delegation_id": created["id"], "status": "completed"
        })
        assert isinstance(result, dict)

    def test_check_overdue_delegations(self, agent):
        result = agent._dispatch_tool("check_overdue_delegations", {})
        assert isinstance(result, dict)

    def test_delete_delegation(self, agent):
        created = agent._dispatch_tool("create_delegation", {
            "task": "Old task", "delegated_to": "Charlie"
        })
        result = agent._dispatch_tool("delete_delegation", {
            "delegation_id": created["id"]
        })
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Lifecycle — alerts (real memory_store)
# ---------------------------------------------------------------------------


class TestAlertToolsSmoke:
    def test_create_alert_rule(self, agent):
        result = agent._dispatch_tool("create_alert_rule", {
            "name": "smoke-alert", "alert_type": "custom"
        })
        assert isinstance(result, dict)

    def test_create_alert_rule_with_all_fields(self, agent):
        result = agent._dispatch_tool("create_alert_rule", {
            "name": "full-alert",
            "alert_type": "deadline",
            "description": "Alert when deadline approaches",
            "condition": '{"days_before": 3}',
            "enabled": True,
        })
        assert isinstance(result, dict)

    def test_list_alert_rules(self, agent):
        result = agent._dispatch_tool("list_alert_rules", {})
        assert isinstance(result, dict)

    def test_list_alert_rules_enabled_only(self, agent):
        result = agent._dispatch_tool("list_alert_rules", {"enabled_only": True})
        assert isinstance(result, dict)

    def test_check_alerts(self, agent):
        result = agent._dispatch_tool("check_alerts", {})
        assert isinstance(result, dict)

    def test_dismiss_alert(self, agent):
        created = agent._dispatch_tool("create_alert_rule", {
            "name": "dismiss-me", "alert_type": "custom"
        })
        result = agent._dispatch_tool("dismiss_alert", {"rule_id": created["id"]})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Calendar tools (MagicMock store)
# ---------------------------------------------------------------------------


class TestCalendarToolsSmoke:
    def test_get_calendar_events(self, agent, calendar_store):
        result = agent._dispatch_tool("get_calendar_events", {
            "start_date": "2026-03-01", "end_date": "2026-03-02"
        })
        assert isinstance(result, list)
        calendar_store.get_events.assert_called_once()

    def test_get_calendar_events_with_calendar_name(self, agent, calendar_store):
        agent._dispatch_tool("get_calendar_events", {
            "start_date": "2026-03-01", "end_date": "2026-03-02",
            "calendar_name": "Work"
        })
        call_kwargs = calendar_store.get_events.call_args
        assert call_kwargs[1]["calendar_names"] == ["Work"]

    def test_get_calendar_events_with_provider(self, agent, calendar_store):
        agent._dispatch_tool("get_calendar_events", {
            "start_date": "2026-03-01", "end_date": "2026-03-02",
            "provider_preference": "apple",
        })
        call_kwargs = calendar_store.get_events.call_args
        assert call_kwargs[1]["provider_preference"] == "apple"

    def test_search_calendar_events(self, agent, calendar_store):
        result = agent._dispatch_tool("search_calendar_events", {
            "query": "standup"
        })
        assert isinstance(result, list)
        calendar_store.search_events.assert_called_once()

    def test_search_calendar_events_with_dates(self, agent, calendar_store):
        agent._dispatch_tool("search_calendar_events", {
            "query": "standup",
            "start_date": "2026-03-01",
            "end_date": "2026-03-31",
        })
        calendar_store.search_events.assert_called_once()

    def test_calendar_none_returns_error(self, full_config, memory_store, document_store):
        """Agent without calendar_store returns an error dict."""
        no_cal_agent = BaseExpertAgent(
            config=full_config,
            memory_store=memory_store,
            document_store=document_store,
            client=AsyncMock(),
            calendar_store=None,
        )
        result = no_cal_agent._dispatch_tool("get_calendar_events", {
            "start_date": "2026-03-01", "end_date": "2026-03-02"
        })
        assert isinstance(result, dict)
        assert "error" in result

    def test_calendar_search_none_returns_error(self, full_config, memory_store, document_store):
        no_cal_agent = BaseExpertAgent(
            config=full_config,
            memory_store=memory_store,
            document_store=document_store,
            client=AsyncMock(),
            calendar_store=None,
        )
        result = no_cal_agent._dispatch_tool("search_calendar_events", {
            "query": "test"
        })
        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# Reminder tools (MagicMock store)
# ---------------------------------------------------------------------------


class TestReminderToolsSmoke:
    def test_list_reminders(self, agent, reminder_store):
        result = agent._dispatch_tool("list_reminders", {})
        assert isinstance(result, list)
        reminder_store.list_reminders.assert_called_once()

    def test_list_reminders_with_filters(self, agent, reminder_store):
        agent._dispatch_tool("list_reminders", {
            "list_name": "Groceries", "completed": False
        })
        reminder_store.list_reminders.assert_called_once()

    def test_search_reminders(self, agent, reminder_store):
        result = agent._dispatch_tool("search_reminders", {"query": "buy milk"})
        assert isinstance(result, list)
        reminder_store.search_reminders.assert_called_once()

    def test_create_reminder(self, agent, reminder_store):
        result = agent._dispatch_tool("create_reminder", {"title": "Test reminder"})
        assert isinstance(result, dict)
        reminder_store.create_reminder.assert_called_once()

    def test_create_reminder_with_all_fields(self, agent, reminder_store):
        agent._dispatch_tool("create_reminder", {
            "title": "Full reminder",
            "list_name": "Work",
            "due_date": "2026-04-01",
            "priority": 1,
            "notes": "Important",
        })
        call_kwargs = reminder_store.create_reminder.call_args[1]
        assert call_kwargs["title"] == "Full reminder"
        assert call_kwargs["list_name"] == "Work"

    def test_complete_reminder(self, agent, reminder_store):
        result = agent._dispatch_tool("complete_reminder", {"reminder_id": "r-42"})
        assert isinstance(result, dict)
        reminder_store.complete_reminder.assert_called_once_with("r-42")

    def test_reminder_none_returns_error(self, full_config, memory_store, document_store):
        no_rem_agent = BaseExpertAgent(
            config=full_config,
            memory_store=memory_store,
            document_store=document_store,
            client=AsyncMock(),
            reminder_store=None,
        )
        for tool_name, tool_input in [
            ("list_reminders", {}),
            ("search_reminders", {"query": "x"}),
            ("create_reminder", {"title": "x"}),
            ("complete_reminder", {"reminder_id": "x"}),
        ]:
            result = no_rem_agent._dispatch_tool(tool_name, tool_input)
            assert isinstance(result, dict), f"{tool_name} should return dict"
            assert "error" in result, f"{tool_name} should contain error"


# ---------------------------------------------------------------------------
# Notification tool (MagicMock notifier)
# ---------------------------------------------------------------------------


class TestNotificationToolSmoke:
    def test_send_notification(self, agent, notifier):
        result = agent._dispatch_tool("send_notification", {
            "title": "Alert", "message": "Test notification"
        })
        assert isinstance(result, dict)
        notifier.send.assert_called_once()

    def test_send_notification_with_optional_fields(self, agent, notifier):
        agent._dispatch_tool("send_notification", {
            "title": "Alert", "message": "Body",
            "subtitle": "Sub", "sound": "ping"
        })
        call_kwargs = notifier.send.call_args[1]
        assert call_kwargs["subtitle"] == "Sub"
        assert call_kwargs["sound"] == "ping"

    def test_notifier_none_returns_error(self, full_config, memory_store, document_store):
        no_notif_agent = BaseExpertAgent(
            config=full_config,
            memory_store=memory_store,
            document_store=document_store,
            client=AsyncMock(),
            notifier=None,
        )
        result = no_notif_agent._dispatch_tool("send_notification", {
            "title": "Test", "message": "msg"
        })
        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# Mail tools (MagicMock store)
# ---------------------------------------------------------------------------


class TestMailToolsSmoke:
    def test_get_mail_messages(self, agent, mail_store):
        result = agent._dispatch_tool("get_mail_messages", {})
        assert isinstance(result, list)
        mail_store.get_messages.assert_called_once()

    def test_get_mail_messages_with_params(self, agent, mail_store):
        agent._dispatch_tool("get_mail_messages", {
            "mailbox": "Sent", "account": "work", "limit": 10
        })
        mail_store.get_messages.assert_called_once_with(
            mailbox="Sent", account="work", limit=10
        )

    def test_get_mail_message(self, agent, mail_store):
        result = agent._dispatch_tool("get_mail_message", {"message_id": "msg-123"})
        assert isinstance(result, dict)
        mail_store.get_message.assert_called_once_with("msg-123")

    def test_search_mail(self, agent, mail_store):
        result = agent._dispatch_tool("search_mail", {"query": "invoice"})
        assert isinstance(result, list)
        mail_store.search_messages.assert_called_once()

    def test_search_mail_with_params(self, agent, mail_store):
        agent._dispatch_tool("search_mail", {
            "query": "budget",
            "mailbox": "Archive",
            "account": "work",
            "limit": 5,
        })
        call_kwargs = mail_store.search_messages.call_args[1]
        assert call_kwargs["query"] == "budget"
        assert call_kwargs["mailbox"] == "Archive"

    def test_get_unread_count(self, agent, mail_store):
        result = agent._dispatch_tool("get_unread_count", {})
        assert isinstance(result, dict)
        assert result["unread_count"] == 5

    def test_get_unread_count_no_match(self, agent, mail_store):
        result = agent._dispatch_tool("get_unread_count", {
            "mailbox": "NonExistent"
        })
        assert isinstance(result, dict)
        assert result["unread_count"] == 0

    def test_send_email(self, agent, mail_store):
        result = agent._dispatch_tool("send_email", {
            "to": "alice@example.com",
            "subject": "Test",
            "body": "Hello",
        })
        assert isinstance(result, dict)
        # Verify confirm_send=False safety (agents must never auto-send)
        call_kwargs = mail_store.send_message.call_args[1]
        assert call_kwargs["confirm_send"] is False

    def test_send_email_with_cc_bcc(self, agent, mail_store):
        agent._dispatch_tool("send_email", {
            "to": "a@b.com, c@d.com",
            "subject": "Test",
            "body": "Hi",
            "cc": "x@y.com",
            "bcc": "z@w.com",
        })
        call_kwargs = mail_store.send_message.call_args[1]
        assert call_kwargs["to"] == ["a@b.com", "c@d.com"]
        assert call_kwargs["cc"] == ["x@y.com"]
        assert call_kwargs["bcc"] == ["z@w.com"]

    def test_mark_mail_read(self, agent, mail_store):
        result = agent._dispatch_tool("mark_mail_read", {"message_id": "msg-1"})
        assert isinstance(result, dict)
        mail_store.mark_read.assert_called_once()

    def test_mark_mail_flagged(self, agent, mail_store):
        result = agent._dispatch_tool("mark_mail_flagged", {"message_id": "msg-1"})
        assert isinstance(result, dict)
        mail_store.mark_flagged.assert_called_once()

    def test_move_mail_message(self, agent, mail_store):
        result = agent._dispatch_tool("move_mail_message", {
            "message_id": "msg-1", "target_mailbox": "Archive"
        })
        assert isinstance(result, dict)
        mail_store.move_message.assert_called_once()

    def test_mail_none_returns_error(self, full_config, memory_store, document_store):
        """All mail tools return error dict when mail_store is None."""
        no_mail_agent = BaseExpertAgent(
            config=full_config,
            memory_store=memory_store,
            document_store=document_store,
            client=AsyncMock(),
            mail_store=None,
        )
        cases = [
            ("get_mail_messages", {}),
            ("get_mail_message", {"message_id": "x"}),
            ("search_mail", {"query": "x"}),
            ("get_unread_count", {}),
            ("send_email", {"to": "a@b.com", "subject": "s", "body": "b"}),
            ("mark_mail_read", {"message_id": "x"}),
            ("mark_mail_flagged", {"message_id": "x"}),
            ("move_mail_message", {"message_id": "x", "target_mailbox": "y"}),
        ]
        for tool_name, tool_input in cases:
            result = no_mail_agent._dispatch_tool(tool_name, tool_input)
            assert isinstance(result, dict), f"{tool_name} should return dict"
            assert "error" in result, f"{tool_name} should contain error"


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestUnknownTool:
    def test_unknown_tool_returns_error(self, agent):
        result = agent._dispatch_tool("nonexistent_tool", {})
        assert isinstance(result, dict)
        assert "error" in result
        assert "Unknown tool" in result["error"]


# ---------------------------------------------------------------------------
# Return type sweep — every handler returns dict or list
# ---------------------------------------------------------------------------


class TestReturnTypes:
    """Verify that every dispatch handler returns a dict or list."""

    TOOL_INPUTS = {
        "query_memory": {"query": "test"},
        "store_memory": {"category": "work", "key": "k", "value": "v"},
        "search_documents": {"query": "test"},
        "create_decision": {"title": "test"},
        "search_decisions": {},
        "update_decision": {"decision_id": -1},  # returns error dict
        "list_pending_decisions": {},
        "delete_decision": {"decision_id": -1},
        "create_delegation": {"task": "t", "delegated_to": "x"},
        "list_delegations": {},
        "update_delegation": {"delegation_id": -1},
        "check_overdue_delegations": {},
        "delete_delegation": {"delegation_id": -1},
        "create_alert_rule": {"name": "sweep-alert", "alert_type": "test"},
        "list_alert_rules": {},
        "check_alerts": {},
        "dismiss_alert": {"rule_id": -1},
        "get_calendar_events": {"start_date": "2026-03-01", "end_date": "2026-03-02"},
        "search_calendar_events": {"query": "test"},
        "list_reminders": {},
        "search_reminders": {"query": "test"},
        "create_reminder": {"title": "test"},
        "complete_reminder": {"reminder_id": "r-1"},
        "send_notification": {"title": "t", "message": "m"},
        "get_mail_messages": {},
        "get_mail_message": {"message_id": "x"},
        "search_mail": {"query": "test"},
        "get_unread_count": {},
        "send_email": {"to": "a@b.com", "subject": "s", "body": "b"},
        "mark_mail_read": {"message_id": "x"},
        "mark_mail_flagged": {"message_id": "x"},
        "move_mail_message": {"message_id": "x", "target_mailbox": "Archive"},
    }

    def test_all_handlers_return_dict_or_list(self, agent):
        table = agent._get_dispatch_table()
        for tool_name in table:
            tool_input = self.TOOL_INPUTS.get(tool_name, {})
            result = agent._dispatch_tool(tool_name, tool_input)
            assert isinstance(result, (dict, list)), (
                f"{tool_name} returned {type(result).__name__}, expected dict or list"
            )

    def test_all_dispatch_tools_covered(self, agent):
        """Ensure TOOL_INPUTS covers every key in the dispatch table."""
        table = agent._get_dispatch_table()
        missing = set(table.keys()) - set(self.TOOL_INPUTS.keys())
        assert not missing, f"TOOL_INPUTS missing coverage for: {missing}"
