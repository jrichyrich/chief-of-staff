"""Mail and notification tools for MCP server."""

import json
import subprocess

from apple_notifications.notifier import Notifier

from .state import _retry_on_transient


def register(mcp, state):
    """Register mail and notification tools with the MCP server."""

    @mcp.tool()
    async def send_notification(
        title: str,
        message: str,
        subtitle: str = "",
        sound: str = "default",
    ) -> str:
        """Send a macOS notification.

        Args:
            title: Notification title (required)
            message: Notification body text (required)
            subtitle: Optional subtitle displayed below the title
            sound: Notification sound name (default: 'default', empty for silent)
        """
        try:
            result = Notifier.send(
                title=title,
                message=message,
                subtitle=subtitle or None,
                sound=sound or None,
            )
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": f"Failed to send notification: {e}"})

    @mcp.tool()
    async def list_mailboxes() -> str:
        """List all mailboxes across all Mail accounts with unread counts."""
        mail_store = state.mail_store
        try:
            mailboxes = _retry_on_transient(mail_store.list_mailboxes)
            return json.dumps({"results": mailboxes})
        except (OSError, subprocess.SubprocessError, TimeoutError) as e:
            return json.dumps({"error": f"Mail error listing mailboxes: {e}"})
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Unexpected error in list_mailboxes")
            return json.dumps({"error": f"Unexpected error: {e}"})

    @mcp.tool()
    async def get_mail_messages(mailbox: str = "INBOX", account: str = "", limit: int = 25) -> str:
        """Get recent messages (headers only) from a mailbox. Returns subject, sender, date, read/flagged status.

        Args:
            mailbox: Mailbox name to fetch from (default: INBOX)
            account: Mail account name (uses first account if empty)
            limit: Maximum number of messages to return (default: 25, max: 100)
        """
        mail_store = state.mail_store
        try:
            messages = _retry_on_transient(mail_store.get_messages, mailbox=mailbox, account=account, limit=limit)
            return json.dumps({"results": messages})
        except (OSError, subprocess.SubprocessError, TimeoutError) as e:
            return json.dumps({"error": f"Mail error getting messages: {e}"})
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Unexpected error in get_mail_messages")
            return json.dumps({"error": f"Unexpected error: {e}"})

    @mcp.tool()
    async def get_mail_message(message_id: str) -> str:
        """Get full message content by message ID, including body, to, and cc fields.

        Args:
            message_id: The unique message ID (required)
        """
        mail_store = state.mail_store
        try:
            message = mail_store.get_message(message_id)
            return json.dumps(message)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def search_mail(query: str, mailbox: str = "INBOX", account: str = "", limit: int = 25) -> str:
        """Search messages by subject or sender text in a mailbox.

        Args:
            query: Text to search for in subject and sender fields (required)
            mailbox: Mailbox to search in (default: INBOX)
            account: Mail account name (uses first account if empty)
            limit: Maximum number of results (default: 25, max: 100)
        """
        mail_store = state.mail_store
        try:
            messages = mail_store.search_messages(query=query, mailbox=mailbox, account=account, limit=limit)
            try:
                state.memory_store.record_skill_usage("search_mail", query)
            except Exception:
                pass
            return json.dumps({"results": messages})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def mark_mail_read(message_id: str, read: str = "true") -> str:
        """Mark a message as read or unread.

        Args:
            message_id: The unique message ID (required)
            read: Set to 'true' to mark as read, 'false' for unread (default: 'true')
        """
        mail_store = state.mail_store
        try:
            read_bool = read if isinstance(read, bool) else read.lower() == "true"
            result = mail_store.mark_read(message_id, read=read_bool)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def mark_mail_flagged(message_id: str, flagged: str = "true") -> str:
        """Mark a message as flagged or unflagged.

        Args:
            message_id: The unique message ID (required)
            flagged: Set to 'true' to flag, 'false' to unflag (default: 'true')
        """
        mail_store = state.mail_store
        try:
            flagged_bool = flagged if isinstance(flagged, bool) else flagged.lower() == "true"
            result = mail_store.mark_flagged(message_id, flagged=flagged_bool)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def move_mail_message(message_id: str, target_mailbox: str, target_account: str = "") -> str:
        """Move a message to a different mailbox.

        Args:
            message_id: The unique message ID (required)
            target_mailbox: Destination mailbox name (required)
            target_account: Destination account name (uses first account if empty)
        """
        mail_store = state.mail_store
        try:
            result = mail_store.move_message(message_id, target_mailbox=target_mailbox, target_account=target_account)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def reply_to_email(
        message_id: str,
        body: str,
        reply_all: bool = False,
        cc: str = "",
        bcc: str = "",
        confirm_send: bool = False,
    ) -> str:
        """Reply to an existing email within its thread. REQUIRES confirm_send=True after user explicitly confirms.

        This sends a proper threaded reply (not a new email), so the reply appears
        in the same conversation thread in the recipient's inbox.

        WARNING: This will send a real email reply. Always confirm with the user before calling with confirm_send=True.

        Args:
            message_id: The message ID of the email to reply to (required)
            body: Reply body text (required)
            reply_all: If True, replies to all recipients; if False, replies only to sender (default: False)
            cc: Comma-separated additional CC email addresses (optional)
            bcc: Comma-separated BCC email addresses (optional)
            confirm_send: Must be True to actually send. Set to False to preview only. (default: False)
        """
        mail_store = state.mail_store
        try:
            cc_list = [addr.strip() for addr in cc.split(",") if addr.strip()] if cc else None
            bcc_list = [addr.strip() for addr in bcc.split(",") if addr.strip()] if bcc else None
            result = mail_store.reply_message(
                message_id=message_id,
                body=body,
                reply_all=reply_all,
                cc=cc_list,
                bcc=bcc_list,
                confirm_send=confirm_send,
            )
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "", confirm_send: bool = False) -> str:
        """Compose and send an email. REQUIRES confirm_send=True after user explicitly confirms they want to send.

        WARNING: This will send a real email. Always confirm with the user before calling with confirm_send=True.

        Args:
            to: Comma-separated recipient email addresses (required)
            subject: Email subject line (required)
            body: Email body text (required)
            cc: Comma-separated CC email addresses (optional)
            bcc: Comma-separated BCC email addresses (optional)
            confirm_send: Must be True to actually send. Set to False to preview only. (default: False)
        """
        mail_store = state.mail_store
        try:
            to_list = [addr.strip() for addr in to.split(",") if addr.strip()]
            cc_list = [addr.strip() for addr in cc.split(",") if addr.strip()] if cc else None
            bcc_list = [addr.strip() for addr in bcc.split(",") if addr.strip()] if bcc else None
            result = mail_store.send_message(
                to=to_list,
                subject=subject,
                body=body,
                cc=cc_list,
                bcc=bcc_list,
                confirm_send=confirm_send,
            )
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.send_notification = send_notification
    module.list_mailboxes = list_mailboxes
    module.get_mail_messages = get_mail_messages
    module.get_mail_message = get_mail_message
    module.search_mail = search_mail
    module.mark_mail_read = mark_mail_read
    module.mark_mail_flagged = mark_mail_flagged
    module.move_mail_message = move_mail_message
    module.reply_to_email = reply_to_email
    module.send_email = send_email
