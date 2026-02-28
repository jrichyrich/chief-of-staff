import base64
import logging
import platform
import subprocess
from typing import Optional

from apple_notifications.notifier import Notifier
from utils.subprocess import run_with_cleanup

logger = logging.getLogger(__name__)

_IS_MACOS = platform.system() == "Darwin"
_PLATFORM_ERROR = {"error": "Mail is only available on macOS"}
_DEFAULT_TIMEOUT = 15
_SEND_TIMEOUT = 30
_FIELD_SEP = "|||"
_RECORD_SEP = "~~~RECORD~~~"


def _escape_osascript(text: str) -> str:
    """Escape text for safe use in AppleScript strings."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _run_applescript(script: str, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    """Execute AppleScript and return {'output': ...} or {'error': ...}."""
    if not _IS_MACOS:
        return _PLATFORM_ERROR
    try:
        result = run_with_cleanup(
            ["osascript", "-e", script],
            timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if result.returncode != 0:
            return {"error": f"osascript failed: {(result.stderr or '').strip()}"}
        return {"output": (result.stdout or "").strip()}
    except subprocess.TimeoutExpired:
        return {"error": "Mail operation timed out"}
    except FileNotFoundError:
        return {"error": "osascript not found — not running on macOS?"}


def _parse_records(raw_output: str) -> list[str]:
    """Split raw AppleScript output into individual records."""
    if not raw_output or not raw_output.strip():
        return []
    return [r.strip() for r in raw_output.split(_RECORD_SEP) if r.strip()]


def _parse_fields(record: str) -> list[str]:
    """Split a single record into its fields."""
    if not record:
        return []
    return [f.strip() for f in record.split(_FIELD_SEP)]


class MailStore:
    """Read, search, and manage Apple Mail via AppleScript."""

    def list_mailboxes(self) -> list[dict]:
        """List all mailboxes across all accounts with unread counts."""
        script = '''
tell application "Mail"
    set output to ""
    repeat with acct in accounts
        set acctName to name of acct
        repeat with mb in mailboxes of acct
            set mbName to name of mb
            set unread to unread count of mb
            set output to output & mbName & "|||" & acctName & "|||" & (unread as text) & return & "~~~RECORD~~~" & return
        end repeat
    end repeat
    return output
end tell
'''
        result = _run_applescript(script)
        if "error" in result:
            return [result]
        records = _parse_records(result["output"])
        mailboxes = []
        for rec in records:
            fields = _parse_fields(rec)
            if len(fields) >= 3:
                mailboxes.append({
                    "name": fields[0],
                    "account": fields[1],
                    "unread_count": int(fields[2]) if fields[2].isdigit() else 0,
                })
        return mailboxes

    def get_messages(self, mailbox: str = "INBOX", account: str = "", limit: int = 25) -> list[dict]:
        """Get recent messages (headers only) from a mailbox. Limit capped at 100."""
        limit = min(max(1, limit), 100)
        mailbox_esc = _escape_osascript(mailbox)
        if account:
            account_esc = _escape_osascript(account)
            mailbox_ref = f'mailbox "{mailbox_esc}" of account "{account_esc}"'
        else:
            mailbox_ref = f'mailbox "{mailbox_esc}" of account 1'
        script = f'''
tell application "Mail"
    set mb to {mailbox_ref}
    set msgCount to count of messages of mb
    if msgCount is 0 then return ""
    set maxMsg to msgCount
    if maxMsg > {limit} then set maxMsg to {limit}
    set output to ""
    repeat with i from 1 to maxMsg
        set msg to message i of mb
        set mid to message id of msg
        set subj to subject of msg
        set sndr to sender of msg
        set dt to date sent of msg as text
        set isRead to (read status of msg)
        set isFlagged to (flagged status of msg)
        set output to output & mid & "|||" & subj & "|||" & sndr & "|||" & dt & "|||" & (isRead as text) & "|||" & (isFlagged as text) & return & "~~~RECORD~~~" & return
    end repeat
    return output
end tell
'''
        result = _run_applescript(script)
        if "error" in result:
            return [result]
        records = _parse_records(result["output"])
        messages = []
        for rec in records:
            fields = _parse_fields(rec)
            if len(fields) >= 6:
                messages.append({
                    "message_id": fields[0],
                    "subject": fields[1],
                    "sender": fields[2],
                    "date": fields[3],
                    "read": fields[4] == "true",
                    "flagged": fields[5] == "true",
                    "mailbox": mailbox,
                    "account": account,
                })
        return messages

    def get_message(self, message_id: str) -> dict:
        """Get full message content by message ID, including decoded body."""
        mid_esc = _escape_osascript(message_id)
        script = f'''
tell application "Mail"
    set foundMsg to missing value
    repeat with acct in accounts
        repeat with mb in mailboxes of acct
            try
                set matchMsgs to (messages of mb whose message id is "{mid_esc}")
                if (count of matchMsgs) > 0 then
                    set foundMsg to item 1 of matchMsgs
                    exit repeat
                end if
            end try
        end repeat
        if foundMsg is not missing value then exit repeat
    end repeat
    if foundMsg is missing value then return "ERROR: Message not found"
    set subj to subject of foundMsg
    set sndr to sender of foundMsg
    set dt to date sent of foundMsg as text
    set isRead to (read status of foundMsg)
    set isFlagged to (flagged status of foundMsg)
    set toList to ""
    repeat with rcpt in to recipients of foundMsg
        set toList to toList & address of rcpt & ","
    end repeat
    set ccList to ""
    repeat with rcpt in cc recipients of foundMsg
        set ccList to ccList & address of rcpt & ","
    end repeat
    set bodyText to content of foundMsg
    set b64Body to do shell script "printf '%s' " & quoted form of bodyText & " | base64"
    return subj & "|||" & sndr & "|||" & dt & "|||" & isRead & "|||" & isFlagged & "|||" & toList & "|||" & ccList & "|||" & b64Body
end tell
'''
        result = _run_applescript(script)
        if "error" in result:
            return result
        output = result["output"]
        if output.startswith("ERROR:"):
            return {"error": output}
        fields = _parse_fields(output)
        if len(fields) < 8:
            return {"error": "Unexpected response format from Mail"}
        # Decode base64 body
        try:
            body = base64.b64decode(fields[7]).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError) as e:
            logger.warning("Failed to decode base64 body: %s", e)
            body = fields[7]
        return {
            "message_id": message_id,
            "subject": fields[0],
            "sender": fields[1],
            "date": fields[2],
            "read": fields[3] == "true",
            "flagged": fields[4] == "true",
            "to": [a for a in fields[5].split(",") if a],
            "cc": [a for a in fields[6].split(",") if a],
            "body": body,
        }

    def search_messages(self, query: str, mailbox: str = "INBOX", account: str = "", limit: int = 25) -> list[dict]:
        """Search messages by subject or sender text in a mailbox."""
        limit = min(max(1, limit), 100)
        query_esc = _escape_osascript(query)
        mailbox_esc = _escape_osascript(mailbox)
        if account:
            account_esc = _escape_osascript(account)
            mailbox_ref = f'mailbox "{mailbox_esc}" of account "{account_esc}"'
        else:
            mailbox_ref = f'mailbox "{mailbox_esc}" of account 1'
        script = f'''
tell application "Mail"
    set mb to {mailbox_ref}
    set matchMsgs to (messages of mb whose subject contains "{query_esc}" or sender contains "{query_esc}")
    set msgCount to count of matchMsgs
    if msgCount is 0 then return ""
    set maxMsg to msgCount
    if maxMsg > {limit} then set maxMsg to {limit}
    set output to ""
    repeat with i from 1 to maxMsg
        set msg to item i of matchMsgs
        set mid to message id of msg
        set subj to subject of msg
        set sndr to sender of msg
        set dt to date sent of msg as text
        set isRead to (read status of msg)
        set isFlagged to (flagged status of msg)
        set output to output & mid & "|||" & subj & "|||" & sndr & "|||" & dt & "|||" & (isRead as text) & "|||" & (isFlagged as text) & return & "~~~RECORD~~~" & return
    end repeat
    return output
end tell
'''
        result = _run_applescript(script)
        if "error" in result:
            return [result]
        records = _parse_records(result["output"])
        messages = []
        for rec in records:
            fields = _parse_fields(rec)
            if len(fields) >= 6:
                messages.append({
                    "message_id": fields[0],
                    "subject": fields[1],
                    "sender": fields[2],
                    "date": fields[3],
                    "read": fields[4] == "true",
                    "flagged": fields[5] == "true",
                    "mailbox": mailbox,
                    "account": account,
                })
        return messages

    def mark_read(self, message_id: str, read: bool = True) -> dict:
        """Mark a message as read or unread."""
        mid_esc = _escape_osascript(message_id)
        read_val = "true" if read else "false"
        script = f'''
tell application "Mail"
    repeat with acct in accounts
        repeat with mb in mailboxes of acct
            try
                set matchMsgs to (messages of mb whose message id is "{mid_esc}")
                if (count of matchMsgs) > 0 then
                    set read status of item 1 of matchMsgs to {read_val}
                    return "OK"
                end if
            end try
        end repeat
    end repeat
    return "ERROR: Message not found"
end tell
'''
        result = _run_applescript(script)
        if "error" in result:
            return result
        if result["output"].startswith("ERROR:"):
            return {"error": result["output"]}
        return {"status": "ok", "message_id": message_id, "read": read}

    def mark_flagged(self, message_id: str, flagged: bool = True) -> dict:
        """Mark a message as flagged or unflagged."""
        mid_esc = _escape_osascript(message_id)
        flag_val = "true" if flagged else "false"
        script = f'''
tell application "Mail"
    repeat with acct in accounts
        repeat with mb in mailboxes of acct
            try
                set matchMsgs to (messages of mb whose message id is "{mid_esc}")
                if (count of matchMsgs) > 0 then
                    set flagged status of item 1 of matchMsgs to {flag_val}
                    return "OK"
                end if
            end try
        end repeat
    end repeat
    return "ERROR: Message not found"
end tell
'''
        result = _run_applescript(script)
        if "error" in result:
            return result
        if result["output"].startswith("ERROR:"):
            return {"error": result["output"]}
        return {"status": "ok", "message_id": message_id, "flagged": flagged}

    def move_message(self, message_id: str, target_mailbox: str, target_account: str = "") -> dict:
        """Move a message to a different mailbox."""
        mid_esc = _escape_osascript(message_id)
        target_mb_esc = _escape_osascript(target_mailbox)
        if target_account:
            target_acct_esc = _escape_osascript(target_account)
            target_ref = f'mailbox "{target_mb_esc}" of account "{target_acct_esc}"'
        else:
            target_ref = f'mailbox "{target_mb_esc}" of account 1'
        script = f'''
tell application "Mail"
    set targetMb to {target_ref}
    repeat with acct in accounts
        repeat with mb in mailboxes of acct
            try
                set matchMsgs to (messages of mb whose message id is "{mid_esc}")
                if (count of matchMsgs) > 0 then
                    move item 1 of matchMsgs to targetMb
                    return "OK"
                end if
            end try
        end repeat
    end repeat
    return "ERROR: Message not found"
end tell
'''
        result = _run_applescript(script)
        if "error" in result:
            return result
        if result["output"].startswith("ERROR:"):
            return {"error": result["output"]}
        return {"status": "ok", "message_id": message_id, "moved_to": target_mailbox}

    def reply_message(
        self,
        message_id: str,
        body: str,
        reply_all: bool = False,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        html_body: Optional[str] = None,
        confirm_send: bool = False,
    ) -> dict:
        """Reply to an existing message in-thread. confirm_send must be True."""
        if not confirm_send:
            return {"error": "confirm_send must be True. Please confirm with the user before sending."}

        mid_esc = _escape_osascript(message_id)
        body_esc = _escape_osascript(body)

        if reply_all:
            reply_flag = "with opening window and reply to all"
        else:
            reply_flag = "with opening window without reply to all"

        # Build additional recipient blocks for extra CC/BCC
        cc_block = ""
        if cc:
            for addr in cc:
                addr_esc = _escape_osascript(addr)
                cc_block += f'\nmake new cc recipient at end of cc recipients of replyMsg with properties {{address:"{addr_esc}"}}'

        bcc_block = ""
        if bcc:
            for addr in bcc:
                addr_esc = _escape_osascript(addr)
                bcc_block += f'\nmake new bcc recipient at end of bcc recipients of replyMsg with properties {{address:"{addr_esc}"}}'

        # Build content line — include html content for multipart/alternative when provided
        html_line = ""
        if html_body:
            html_esc = _escape_osascript(html_body)
            html_line = f'\n    set html content of replyMsg to "{html_esc}"'

        script = f'''
tell application "Mail"
    set foundMsg to missing value
    repeat with acct in accounts
        repeat with mb in mailboxes of acct
            try
                set matchMsgs to (messages of mb whose message id is "{mid_esc}")
                if (count of matchMsgs) > 0 then
                    set foundMsg to item 1 of matchMsgs
                    exit repeat
                end if
            end try
        end repeat
        if foundMsg is not missing value then exit repeat
    end repeat
    if foundMsg is missing value then return "ERROR: Message not found"
    set replyMsg to reply foundMsg {reply_flag}
    set visible of replyMsg to false
    set content of replyMsg to "{body_esc}"{html_line}
{cc_block}
{bcc_block}
    send replyMsg
    return "OK"
end tell
'''
        result = _run_applescript(script, timeout=_SEND_TIMEOUT)
        if "error" in result:
            return result
        if result["output"].startswith("ERROR:"):
            return {"error": result["output"]}

        try:
            Notifier.send(
                title="Reply Sent",
                message=f"Replied to: {message_id[:30]}",
            )
        except (subprocess.SubprocessError, OSError):
            pass
        return {"status": "replied", "message_id": message_id, "reply_all": reply_all}

    def send_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        html_body: Optional[str] = None,
        confirm_send: bool = False,
    ) -> dict:
        """Compose and send an email. confirm_send must be True."""
        if not confirm_send:
            return {"error": "confirm_send must be True. Please confirm with the user before sending."}

        subject_esc = _escape_osascript(subject)
        body_esc = _escape_osascript(body)

        # Build message properties — include html content for multipart/alternative when provided
        if html_body:
            html_esc = _escape_osascript(html_body)
            msg_props = f'{{subject:"{subject_esc}", content:"{body_esc}", html content:"{html_esc}", visible:false}}'
        else:
            msg_props = f'{{subject:"{subject_esc}", content:"{body_esc}", visible:false}}'

        # Build recipient AppleScript blocks
        to_block = ""
        for addr in to:
            addr_esc = _escape_osascript(addr)
            to_block += f'\nmake new to recipient at end of to recipients with properties {{address:"{addr_esc}"}}'

        cc_block = ""
        if cc:
            for addr in cc:
                addr_esc = _escape_osascript(addr)
                cc_block += f'\nmake new cc recipient at end of cc recipients with properties {{address:"{addr_esc}"}}'

        bcc_block = ""
        if bcc:
            for addr in bcc:
                addr_esc = _escape_osascript(addr)
                bcc_block += f'\nmake new bcc recipient at end of bcc recipients with properties {{address:"{addr_esc}"}}'

        script = f'''
tell application "Mail"
    set newMsg to make new outgoing message with properties {msg_props}
    tell newMsg
{to_block}
{cc_block}
{bcc_block}
    end tell
    send newMsg
    return "OK"
end tell
'''
        result = _run_applescript(script, timeout=_SEND_TIMEOUT)
        if "error" in result:
            return result

        try:
            Notifier.send(
                title="Email Sent",
                message=f"To: {', '.join(to)} — {subject}",
            )
        except (subprocess.SubprocessError, OSError):
            pass  # Don't let notification failure mask successful send
        return {"status": "sent", "to": to, "subject": subject}
