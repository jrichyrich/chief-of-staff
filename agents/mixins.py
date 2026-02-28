"""Domain-specific handler mixins for BaseExpertAgent.

Each mixin provides tool handlers for a single domain.  The base class
composes all mixins via multiple inheritance and wires them into the
dispatch table.
"""

from datetime import datetime, timedelta
from typing import Any

from tools import lifecycle as lifecycle_tools
from utils.text import split_addresses as _split_addresses


# ---------------------------------------------------------------------------
# Lifecycle: decisions, delegations, alert rules
# ---------------------------------------------------------------------------

class LifecycleMixin:
    """Handlers for decision, delegation, and alert rule tools."""

    memory_store: Any  # provided by BaseExpertAgent.__init__
    name: str

    # --- Decisions ---

    def _handle_create_decision(self, tool_input: dict) -> Any:
        return lifecycle_tools.create_decision(
            self.memory_store,
            title=tool_input["title"],
            description=tool_input.get("description", ""),
            context=tool_input.get("context", ""),
            decided_by=tool_input.get("decided_by", ""),
            owner=tool_input.get("owner", ""),
            status=tool_input.get("status", "pending_execution"),
            follow_up_date=tool_input.get("follow_up_date", ""),
            tags=tool_input.get("tags", ""),
            source=tool_input.get("source", self.name),
        )

    def _handle_search_decisions(self, tool_input: dict) -> Any:
        return lifecycle_tools.search_decisions(
            self.memory_store,
            query=tool_input.get("query", ""),
            status=tool_input.get("status", ""),
        )

    def _handle_update_decision(self, tool_input: dict) -> Any:
        return lifecycle_tools.update_decision(
            self.memory_store,
            decision_id=tool_input["decision_id"],
            status=tool_input.get("status", ""),
            notes=tool_input.get("notes", ""),
        )

    def _handle_list_pending_decisions(self, tool_input: dict = None) -> Any:
        return lifecycle_tools.list_pending_decisions(self.memory_store)

    def _handle_delete_decision(self, tool_input: dict) -> Any:
        return lifecycle_tools.delete_decision(
            self.memory_store,
            decision_id=tool_input["decision_id"],
        )

    # --- Delegations ---

    def _handle_create_delegation(self, tool_input: dict) -> Any:
        return lifecycle_tools.create_delegation(
            self.memory_store,
            task=tool_input["task"],
            delegated_to=tool_input["delegated_to"],
            description=tool_input.get("description", ""),
            due_date=tool_input.get("due_date", ""),
            priority=tool_input.get("priority", "medium"),
            source=tool_input.get("source", self.name),
        )

    def _handle_list_delegations(self, tool_input: dict) -> Any:
        return lifecycle_tools.list_delegations(
            self.memory_store,
            status=tool_input.get("status", ""),
            delegated_to=tool_input.get("delegated_to", ""),
        )

    def _handle_update_delegation(self, tool_input: dict) -> Any:
        return lifecycle_tools.update_delegation(
            self.memory_store,
            delegation_id=tool_input["delegation_id"],
            status=tool_input.get("status", ""),
            notes=tool_input.get("notes", ""),
        )

    def _handle_check_overdue_delegations(self, tool_input: dict = None) -> Any:
        return lifecycle_tools.check_overdue_delegations(self.memory_store)

    def _handle_delete_delegation(self, tool_input: dict) -> Any:
        return lifecycle_tools.delete_delegation(
            self.memory_store,
            delegation_id=tool_input["delegation_id"],
        )

    # --- Alert rules ---

    def _handle_create_alert_rule(self, tool_input: dict) -> Any:
        return lifecycle_tools.create_alert_rule(
            self.memory_store,
            name=tool_input["name"],
            alert_type=tool_input["alert_type"],
            description=tool_input.get("description", ""),
            condition=tool_input.get("condition", ""),
            enabled=tool_input.get("enabled", True),
        )

    def _handle_list_alert_rules(self, tool_input: dict) -> Any:
        return lifecycle_tools.list_alert_rules(
            self.memory_store,
            enabled_only=tool_input.get("enabled_only", False),
        )

    def _handle_check_alerts(self, tool_input: dict = None) -> Any:
        return lifecycle_tools.check_alerts(self.memory_store)

    def _handle_dismiss_alert(self, tool_input: dict) -> Any:
        return lifecycle_tools.dismiss_alert(
            self.memory_store,
            rule_id=tool_input["rule_id"],
        )


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

class CalendarMixin:
    """Handlers for calendar tools."""

    calendar_store: Any  # provided by BaseExpertAgent.__init__

    def _handle_calendar_get_events(self, tool_input: dict) -> Any:
        if self.calendar_store is None:
            return {"error": "Calendar not available (macOS only)"}
        start_dt = datetime.fromisoformat(tool_input["start_date"])
        end_dt = datetime.fromisoformat(tool_input["end_date"])
        calendar_names = [tool_input["calendar_name"]] if tool_input.get("calendar_name") else None
        return self.calendar_store.get_events(
            start_dt,
            end_dt,
            calendar_names=calendar_names,
            provider_preference=tool_input.get("provider_preference", "auto"),
            source_filter=tool_input.get("source_filter", ""),
        )

    def _handle_calendar_search(self, tool_input: dict) -> Any:
        if self.calendar_store is None:
            return {"error": "Calendar not available (macOS only)"}
        now = datetime.now()
        start_dt = datetime.fromisoformat(tool_input["start_date"]) if tool_input.get("start_date") else now - timedelta(days=30)
        end_dt = datetime.fromisoformat(tool_input["end_date"]) if tool_input.get("end_date") else now + timedelta(days=30)
        return self.calendar_store.search_events(
            tool_input["query"],
            start_dt,
            end_dt,
            provider_preference=tool_input.get("provider_preference", "auto"),
            source_filter=tool_input.get("source_filter", ""),
        )


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

class ReminderMixin:
    """Handlers for reminder tools."""

    reminder_store: Any  # provided by BaseExpertAgent.__init__

    def _handle_reminder_list(self, tool_input: dict) -> Any:
        if self.reminder_store is None:
            return {"error": "Reminders not available (macOS only)"}
        return self.reminder_store.list_reminders(
            list_name=tool_input.get("list_name"),
            completed=tool_input.get("completed"),
        )

    def _handle_reminder_search(self, tool_input: dict) -> Any:
        if self.reminder_store is None:
            return {"error": "Reminders not available (macOS only)"}
        return self.reminder_store.search_reminders(
            query=tool_input["query"],
            include_completed=tool_input.get("include_completed", False),
        )

    def _handle_reminder_create(self, tool_input: dict) -> Any:
        if self.reminder_store is None:
            return {"error": "Reminders not available (macOS only)"}
        return self.reminder_store.create_reminder(
            title=tool_input["title"],
            list_name=tool_input.get("list_name"),
            due_date=tool_input.get("due_date"),
            priority=tool_input.get("priority"),
            notes=tool_input.get("notes"),
        )

    def _handle_reminder_complete(self, tool_input: dict) -> Any:
        if self.reminder_store is None:
            return {"error": "Reminders not available (macOS only)"}
        return self.reminder_store.complete_reminder(tool_input["reminder_id"])


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class NotificationMixin:
    """Handler for notification tools."""

    notifier: Any  # provided by BaseExpertAgent.__init__

    def _handle_send_notification(self, tool_input: dict) -> Any:
        if self.notifier is None:
            return {"error": "Notifications not available (macOS only)"}
        return self.notifier.send(
            title=tool_input["title"],
            message=tool_input["message"],
            subtitle=tool_input.get("subtitle"),
            sound=tool_input.get("sound", "default"),
        )


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------

class MailMixin:
    """Handlers for mail tools."""

    mail_store: Any  # provided by BaseExpertAgent.__init__

    def _handle_mail_get_messages(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.get_messages(
            mailbox=tool_input.get("mailbox", "INBOX"),
            account=tool_input.get("account", ""),
            limit=tool_input.get("limit", 25),
        )

    def _handle_mail_get_message(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.get_message(tool_input["message_id"])

    def _handle_mail_search(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.search_messages(
            query=tool_input["query"],
            mailbox=tool_input.get("mailbox", "INBOX"),
            account=tool_input.get("account", ""),
            limit=tool_input.get("limit", 25),
        )

    def _handle_mail_get_unread_count(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        mailbox = tool_input.get("mailbox", "INBOX")
        account = tool_input.get("account", "")
        mailboxes = self.mail_store.list_mailboxes()
        for mb in mailboxes:
            if isinstance(mb, dict) and mb.get("name") == mailbox:
                if account and mb.get("account") != account:
                    continue
                return {"mailbox": mailbox, "unread_count": mb.get("unread_count", 0)}
        return {"mailbox": mailbox, "unread_count": 0}

    def _handle_mail_send(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        to_list = _split_addresses(tool_input["to"])
        cc_list = _split_addresses(tool_input.get("cc", "")) or None
        bcc_list = _split_addresses(tool_input.get("bcc", "")) or None
        return self.mail_store.send_message(
            to=to_list,
            subject=tool_input["subject"],
            body=tool_input["body"],
            cc=cc_list,
            bcc=bcc_list,
            confirm_send=False,  # Agents must never auto-send
        )

    def _handle_mail_mark_read(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.mark_read(
            message_id=tool_input["message_id"],
            read=tool_input.get("read", True),
        )

    def _handle_mail_mark_flagged(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.mark_flagged(
            message_id=tool_input["message_id"],
            flagged=tool_input.get("flagged", True),
        )

    def _handle_mail_move_message(self, tool_input: dict) -> Any:
        if self.mail_store is None:
            return {"error": "Mail not available (macOS only)"}
        return self.mail_store.move_message(
            message_id=tool_input["message_id"],
            target_mailbox=tool_input["target_mailbox"],
            target_account=tool_input.get("target_account", ""),
        )
