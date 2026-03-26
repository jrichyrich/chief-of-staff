# Chunk Audit: MCP Tool Layer — Teams Send/Read/Reply/Manage

## 1. Correctness

### BUG: New-chat creation path returns "sent" even when create_chat returns no ID
- **Severity: High**
- `_graph_send_message` lines 259-268: when no existing chat found and `target_emails` is set, it calls `create_chat` then checks `if new_chat_id:` before sending.
- If `create_chat` returns `{}` or a response without `"id"`, `new_chat_id` is None, the message is silently NOT sent, but the function returns `{"status": "sent", ...}` anyway.
- Callers (including the MCP tool user) believe the message was sent.
- Fix: Raise `GraphAPIError` when `create_chat` returns no ID, so caller knows the operation failed.

### ISSUE: Multiple @mention prepend reverses display order
- **Severity: Low**
- `post_teams_message` lines 415-430 and `reply_to_teams_message` lines 683-698:
  - `message = f'<at id="{idx}">{display_name}</at> ' + message` PREPENDS each mention
  - With 3 mentions (Alice=0, Bob=1, Charlie=2): result is `<at2>Charlie <at1>Bob <at0>Alice original_message`
  - The `id` values match the `mentions` array correctly, so Teams renders @mentions correctly
  - But the visual order of the @mention tags is reversed from the `mention_emails` input order
  - Fix: Build mentions list first, then append to message end rather than prepend

### ISSUE: `read_teams_messages` fetches all chats in parallel before applying limit
- **Severity: Medium**
- Lines 565-573: `asyncio.gather(*tasks)` fires up to 50 concurrent requests before any limit check
- Each request fetches 25 messages — up to 50×25=1250 messages fetched to return `limit=25`
- Rate limit risk: the parallel burst may trigger 429 responses, partially failing `asyncio.gather`
- The 429 retry logic in `_request` does handle it, but adds latency
- Fix: Fetch chats sequentially up to `limit`, or reduce parallelism with `asyncio.Semaphore`

## 2. Completeness
- confirmed: `_graph_send_message` handles direct chat ID (starts with `19:`), email targets, display name exact match, display name substring match, comma-separated names, and group chat creation. Comprehensive. ✓
- confirmed: `prefer_backend` parameter correctly forces graph-only or browser-only paths, surfaces error cleanly. ✓
- confirmed: Browser fallback is triggered on all `GraphAPIError`, `GraphTransientError`, `GraphAuthError` subtypes. Non-Graph exceptions are re-raised (not silently swallowed). ✓
- confirmed: `reply_to_teams_message` correctly requires Graph (no browser fallback — threading requires chat_id + message_id which are only available from Graph). ✓
- confirmed: `manage_teams_chat` with invalid `action` returns error string instead of raising — caller gets informative message. ✓

## 3. Data Flow
- confirmed: `mention_emails` flow: email → `get_user_by_email` → user.id and displayName → mentions array + message mutation. Correct structure for Graph API. ✓
- confirmed: Fallback path correctly passes `graph_error_msg` into browser result for observability. ✓
- confirmed: `_read_via_m365_bridge` sanitizes query via `bridge._sanitize_for_prompt` before putting in LLM prompt. ✓

## 4. Error Handling
- confirmed: `reply_to_teams_message` wraps Graph call in try/except and returns `{"error": ...}` — safe. ✓
- confirmed: `manage_teams_chat` wraps all actions in try/except. ✓
- issue: `_graph_send_message` mention resolution loop (`get_user_by_email` returns None for unknown emails) silently skips unknown users — mention is not added but no error is raised. Caller doesn't know the @mention failed.

## 5. Security
- confirmed: No user-controlled input is passed to shell commands or `eval`. ✓
- confirmed: Module-level singletons (`_manager`, `_poster`, `_ab`) are only accessible via controlled getter functions. ✓
