# Chunk Audit: Mail & Notifications

**User-facing feature**: Inbox search, email send/reply, macOS notification delivery
**Risk Level**: Medium
**Files Audited**:
- `apple_mail/__init__.py` (empty)
- `apple_mail/mail.py` (487 lines)
- `apple_notifications/__init__.py` (empty)
- `apple_notifications/notifier.py` (72 lines)
- `mcp_tools/mail_tools.py` (277 lines)
**Status**: Complete

## Purpose (as understood from reading the code)

This chunk provides email read/search/management via Apple Mail (AppleScript/osascript) and email send/reply via either Apple Mail or Microsoft Graph API (configurable). Notifications are delivered via macOS `display notification` through `Notifier.send()`. The MCP tool layer in `mail_tools.py` wraps the Apple backend with a Graph API routing layer for send operations only — read operations always use Apple Mail.

## Runtime Probe Results

- **Tests found**: Yes — `tests/test_apple_mail.py`, `tests/test_mcp_mail.py`, `tests/test_mail_graph.py`
- **Tests run**: 104 passed, 0 failed (all three test files)
- **Import/load check**: OK — all five files compile cleanly (`py_compile` passes)
- **Type check**: Not run (no mypy/pyright configured)
- **Edge case probes**: Skipped for send/reply/move — all have external side effects. Pure function probe run on `escape_osascript`: double quotes, backslashes, newlines, and carriage returns are correctly escaped. Null bytes pass through unescaped (not an exploitable path in practice given how Apple Mail handles message IDs).
- **Key observation**: All 104 tests pass cleanly. The Graph fallback path is well-covered by `test_mail_graph.py`.

## Dimension Assessments

### Implemented

All documented functions are fully implemented with real logic:
- `MailStore`: `list_mailboxes`, `get_messages`, `get_message`, `search_messages`, `mark_read`, `mark_flagged`, `move_message`, `reply_message`, `send_message`
- `Notifier`: `send`, `send_alert`
- MCP tools: `send_notification`, `list_mailboxes`, `get_mail_messages`, `get_mail_message`, `search_mail`, `mark_mail_read`, `mark_mail_flagged`, `move_mail_message`, `reply_to_email`, `send_email`

No stubs, TODOs, or unimplemented markers found. All functions contain substantive logic.

### Correct

The main happy paths execute correctly. Key traces:

- `send_email` / `reply_to_email`: `confirm_send` guard fires before any backend routing — correct. Graph path tried first, Apple Mail fallback on any exception.
- `get_message` (line 171): body retrieved from Mail as AppleScript text, then passed to `do shell script "printf '%s' " & quoted form of bodyText & " | base64"`. The use of AppleScript's `quoted form` protects against shell injection from email body content — correct.
- `escape_osascript`: properly escapes `"`, `\`, `\n`, `\r`, `\t`. Confirmed via runtime probe. No escaping of null bytes, but null bytes in Apple Mail message IDs are not realistic.
- `_parse_fields` / `_parse_records`: correctly split on `|||` and `~~~RECORD~~~`. Field count checks (`len(fields) >= 6`) prevent index errors on malformed output.

One logic ambiguity: `get_messages` iterates `from 1 to maxMsg` in AppleScript. In Apple Mail's AppleScript model, message index 1 is the **oldest** message in the mailbox, not the newest. For an INBOX with 500 messages and `limit=25`, this returns the 25 oldest, not the 25 most recent. This is likely a latent correctness issue — but it does not crash and the behavior is consistent. See Findings.

### Efficient

`list_mailboxes` iterates over all accounts and all mailboxes recursively with a single AppleScript call — no N+1. The 15-second default timeout is appropriate.

`get_message` performs a full scan of all accounts/mailboxes to find a message by ID (lines 144–155). For mailboxes with many sub-folders this can be slow, but it is protected by the 15-second timeout and is the only correct way to find a message by ID via AppleScript.

`search_messages` has the same full-scan characteristic but is gated by the inbox filter at the AppleScript level — results are filtered server-side. No efficiency concerns at expected scale.

### Robust

**Inconsistent retry coverage**: `list_mailboxes` and `get_mail_messages` call `_retry_on_transient(...)` in `mail_tools.py` (lines 65, 79). `get_mail_message`, `search_mail`, `mark_mail_read`, `mark_mail_flagged`, `move_mail_message`, `reply_to_email`, and `send_email` call the store methods **directly without retry**. If Mail.app is briefly unresponsive during a `search_mail` call, it fails immediately with no retry. The inconsistency is a minor robustness gap rather than a critical failure path.

**Graph permanent-error fallback**: In `send_email` and `reply_to_email` (lines 196–198, 248–250), any Graph exception triggers silent fallback to Apple Mail — including `GraphAuthError` (permanent credential failure). If a user has configured `EMAIL_SEND_BACKEND=graph` and their Graph token is invalid, every send silently routes through Apple Mail instead. This is logged at WARNING but not surfaced to the caller. For an explicit backend choice, a permanent auth error should probably propagate as an error rather than silently rerouting.

**Notifier return value ignored**: In `mail.py` lines 413–419 and 480–486, `Notifier.send()` is called inside a try/except that catches `(subprocess.SubprocessError, OSError)`. However, `Notifier.send()` catches its own exceptions and returns a dict with `{"error": ...}` — it never raises. The outer try/except will never fire. The return value of `Notifier.send()` is discarded. This is a silent no-op when notifications fail, which is the desired behavior (not blocking send on notification failure), but the try/except is misleading dead code.

**Error result propagation from list_mailboxes**: `list_mailboxes()` in `mail.py` returns `[result]` where result is an error dict if the script fails (line 75). The MCP tool layer wraps this in `{"results": [...]}`, so the caller receives `{"results": [{"error": "..."}]}`. This is an inconsistent error format — other tools return a top-level `{"error": ...}` when something fails. Not critical since callers check the response, but subtly inconsistent.

### Architecture

**Graph vs. Apple routing asymmetry**: Read operations (`get_mail_messages`, `search_mail`, `get_mail_message`) always use Apple Mail — there is no Graph path for reading. Send/reply operations route through Graph when configured. This is architecturally correct given the intent (Graph write, Apple read) but is not documented inline in `mail_tools.py`, making it easy to miss.

**Notifier used as notification-after-send**: The `Notifier` dependency is imported and used directly in `apple_mail/mail.py` for post-send desktop notifications. This creates a direct coupling between the mail layer and the notification layer. A minor but real layering inversion — the mail layer should not depend on the notification layer.

**`cc_list` expression ambiguity** (lines 182, 233–234 in `mail_tools.py`): `cc_list = _split_addresses(cc) or None if cc else None`. Python parses this as `(_split_addresses(cc) or None) if cc else None`. The behavior is correct in practice, but the expression reads as if the ternary has precedence over `or`. This should be `_split_addresses(cc) if cc else None` for clarity and correctness.

**Module-level tool exposure pattern** (lines 265–277): Tool functions defined inside `register()` are re-exported via `sys.modules[__name__]` to support test imports. This is a project-wide pattern and works, but it is opaque — test files must import `mcp_server` first to trigger registration, which is documented in CLAUDE.md.

## Findings

### 🔴 Critical

None.

### 🟡 Warning

- **`apple_mail/mail.py:105`** — `get_messages` iterates `from 1 to maxMsg` in AppleScript, which in Apple Mail's message model returns the **oldest** messages first, not the newest. With `limit=25` on a large inbox, the user gets the oldest 25 messages, not the most recent 25. The fix is to iterate from `msgCount` down to `msgCount - limit + 1`. Not confirmed as broken on all macOS/Mail versions since ordering can vary by mailbox type, but it is a likely behavioral defect for the primary use case (reading recent email).

- **`mcp_tools/mail_tools.py:196–198, 248–250`** — Graph permanent auth failures (`GraphAuthError`) are caught by the broad `except Exception` and silently fall back to Apple Mail. If the Graph backend is configured and its auth is broken, every send succeeds via Apple Mail without the user knowing the configured backend is non-functional. Should distinguish transient vs. permanent errors and surface permanent ones to the caller.

### 🟢 Note

- **`apple_mail/mail.py:413–419, 480–486`** — The `try/except (subprocess.SubprocessError, OSError)` around `Notifier.send()` is dead code — `Notifier.send()` catches its own exceptions and returns a dict rather than raising. The try/except can be removed for clarity; the silent-failure behavior is correct and can be achieved by simply calling `Notifier.send()` without a try/except.

- **`mcp_tools/mail_tools.py:65, 79`** — `_retry_on_transient` is applied to `list_mailboxes` and `get_mail_messages` but not to `search_mail`, `get_mail_message`, `mark_mail_read`, `mark_mail_flagged`, or `move_mail_message`. Consider applying consistently or documenting the intentional asymmetry.

- **`mcp_tools/mail_tools.py:75`** — Error return from `MailStore.list_mailboxes()` is wrapped as `{"results": [{"error": "..."}]}` rather than a top-level error. Minor inconsistency with other tools that return `{"error": "..."}` at the top level.

- **`mcp_tools/mail_tools.py:182, 233`** — `cc_list = _split_addresses(cc) or None if cc else None` is correct but ambiguous. Use `_split_addresses(cc) if cc else None` for clarity.

- **`apple_mail/mail.py:7`** — `Notifier` imported and used directly for post-send notifications. Minor layering inversion (mail layer depends on notifications layer). Consider inverting to a callback or removing the notification side-effect from the mail layer entirely.

## Verdict

This chunk is implemented and substantially working. All 104 tests pass and the core email paths (send, reply, read, search, flag, move) function correctly through both Apple Mail and Graph API backends. The most important issue to verify is the message ordering in `get_messages` — if Apple Mail returns oldest-first in the AppleScript model, every "get recent messages" call returns the wrong emails. The Graph auth fallback silently rerouting on permanent errors is a secondary concern that could mask misconfiguration in production.
