"""Delivery adapters for scheduled task results.

Each adapter delivers task execution results to a specific channel
(email, iMessage, macOS notification). Delivery failures are logged
but never block task execution.
"""

from __future__ import annotations

import logging
from datetime import datetime
from string import Template
from typing import Optional

from humanizer.rules import humanize

logger = logging.getLogger(__name__)

# Valid delivery channel names
VALID_CHANNELS = frozenset({"email", "imessage", "notification", "teams"})

# Keys that signal the result_text is daily-brief JSON
_BRIEF_KEYS = {"date", "calendar", "action_items", "conflicts", "email_highlights", "personal"}


def _maybe_format_brief(result_text: str) -> str:
    """If result_text is JSON with daily-brief keys, render via formatter.

    Returns the original text unchanged if it's not brief-like JSON.
    """
    import json as _json
    try:
        data = _json.loads(result_text)
    except (ValueError, TypeError):
        return result_text

    if not isinstance(data, dict) or not (_BRIEF_KEYS & set(data.keys())):
        return result_text

    try:
        from formatter.brief import render_daily
        rendered = render_daily(**data, mode="plain")
        return rendered if rendered else result_text
    except Exception:
        logger.debug("Failed to format brief, using raw text", exc_info=True)
        return result_text


class DeliveryAdapter:
    """Base class for delivery adapters."""

    def deliver(self, result_text: str, config: dict, task_name: str = "") -> dict:
        """Deliver a result message. Returns dict with status and details."""
        raise NotImplementedError


class EmailDeliveryAdapter(DeliveryAdapter):
    """Deliver task results via Apple Mail."""

    def deliver(self, result_text: str, config: dict, task_name: str = "") -> dict:
        from apple_mail.mail import MailStore

        to = config.get("to", [])
        if not to:
            return {"status": "error", "error": "No recipients in delivery_config.to"}

        template_vars = _build_template_vars(result_text, task_name)

        subject_template = config.get("subject_template", "Scheduled task: $task_name")
        subject = Template(subject_template).safe_substitute(template_vars)

        body_template = config.get("body_template", "$result")
        body = Template(body_template).safe_substitute(template_vars)

        mail = MailStore()
        result = mail.send_message(
            to=to,
            subject=subject,
            body=body,
            confirm_send=True,
        )
        return {"status": "delivered", "channel": "email", "detail": result}


class IMessageDeliveryAdapter(DeliveryAdapter):
    """Deliver task results via iMessage."""

    def deliver(self, result_text: str, config: dict, task_name: str = "") -> dict:
        from apple_messages.messages import MessageStore

        recipient = config.get("recipient", "")
        chat_identifier = config.get("chat_identifier", "")
        if not recipient and not chat_identifier:
            return {"status": "error", "error": "No recipient or chat_identifier in delivery_config"}

        template_vars = _build_template_vars(result_text, task_name)
        body_template = config.get("body_template", "$result")
        body = Template(body_template).safe_substitute(template_vars)

        store = MessageStore()
        result = store.send_message(
            to=recipient,
            body=body,
            confirm_send=True,
            chat_identifier=chat_identifier,
        )
        return {"status": "delivered", "channel": "imessage", "detail": result}


class NotificationDeliveryAdapter(DeliveryAdapter):
    """Deliver task results via macOS notification."""

    def deliver(self, result_text: str, config: dict, task_name: str = "") -> dict:
        from apple_notifications.notifier import Notifier

        template_vars = _build_template_vars(result_text, task_name)

        title_template = config.get("title_template", "Task: $task_name")
        title = Template(title_template).safe_substitute(template_vars)

        body_template = config.get("body_template", "$result")
        body = Template(body_template).safe_substitute(template_vars)
        # Truncate for notification display
        if len(body) > 200:
            body = body[:197] + "..."

        sound = config.get("sound", "default")

        result = Notifier.send(title=title, message=body, sound=sound)
        return {"status": "delivered", "channel": "notification", "detail": result}


class TeamsDeliveryAdapter(DeliveryAdapter):
    """Deliver task results via Microsoft Teams (Playwright browser)."""

    def _get_poster(self):
        from browser.teams_poster import PlaywrightTeamsPoster
        from browser.manager import TeamsBrowserManager
        return PlaywrightTeamsPoster(manager=TeamsBrowserManager())

    def deliver(self, result_text: str, config: dict, task_name: str = "") -> dict:
        target = config.get("target", "")
        if not target:
            return {"status": "error", "error": "No target in delivery_config.target"}

        template_vars = _build_template_vars(result_text, task_name)
        body_template = config.get("body_template", "$result")
        body = Template(body_template).safe_substitute(template_vars)

        auto_send = config.get("auto_send", True)
        poster = self._get_poster()
        result = poster.prepare_message(target=target, message=body)
        if auto_send:
            result = poster.send_prepared()
        return {"status": "delivered", "channel": "teams", "detail": result}


_ADAPTERS: dict[str, type[DeliveryAdapter]] = {
    "email": EmailDeliveryAdapter,
    "imessage": IMessageDeliveryAdapter,
    "notification": NotificationDeliveryAdapter,
    "teams": TeamsDeliveryAdapter,
}


def get_delivery_adapter(channel_name: str) -> Optional[DeliveryAdapter]:
    """Get a delivery adapter instance for the given channel name.

    Returns None if the channel is not recognized.
    """
    cls = _ADAPTERS.get(channel_name)
    if cls is None:
        return None
    return cls()


def deliver_result(
    channel: str,
    config: dict,
    result_text: str,
    task_name: str = "",
) -> Optional[dict]:
    """Deliver a task result to the specified channel.

    Returns delivery result dict, or None if no delivery needed.
    Catches all exceptions so delivery failures never propagate.
    """
    adapter = get_delivery_adapter(channel)
    if adapter is None:
        logger.warning("Unknown delivery channel '%s' for task '%s'", channel, task_name)
        return {"status": "error", "error": f"Unknown delivery channel: {channel}"}

    try:
        result_text = _maybe_format_brief(result_text)
        result_text = humanize(result_text)
        return adapter.deliver(result_text, config or {}, task_name)
    except Exception as e:
        logger.error(
            "Delivery failed for task '%s' via '%s': %s",
            task_name, channel, e,
        )
        return {"status": "error", "error": str(e)}


def _build_template_vars(result_text: str, task_name: str) -> dict[str, str]:
    """Build the variable dict for string.Template substitution."""
    return {
        "result": result_text,
        "task_name": task_name,
        "timestamp": datetime.now().isoformat(),
    }
