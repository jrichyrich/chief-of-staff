# Remediation Plan — Teams Messaging via Graph API

---

## Priority 1 — Fix Wrong Endpoints (breaks features silently)

### Fix BUG-1: `update_chat_topic` endpoint
**File**: `connectors/graph_client.py:798`  
**Change**: `f"/me/chats/{safe_id}"` → `f"/chats/{safe_id}"`  
**Test to add**: `test_update_chat_topic_uses_correct_endpoint` — assert the PATCH URL does NOT contain `/me/` prefix  
**Effort**: 1 line + 1 test

### Fix BUG-2: `reply_to_chat_message` endpoint  
**File**: `connectors/graph_client.py:677`  
**Change**: `f"/me/chats/{safe_chat}/messages/{safe_msg}/replies"` → `f"/chats/{safe_chat}/messages/{safe_msg}/replies"`  
**Test to update**: `test_reply_to_chat_message_basic` — assert URL uses `/chats/` not `/me/chats/`  
**Effort**: 1 line, update 2 tests

---

## Priority 2 — Fix Silent Failures

### Fix BUG-3: New-chat no-ID path
**File**: `mcp_tools/teams_browser_tools.py:264-268`  
**Change**:
```python
# Before:
if new_chat_id:
    await graph_client.send_chat_message(...)
return {"status": "sent", ...}

# After:
if not new_chat_id:
    raise GraphAPIError("create_chat returned no id — message not sent")
await graph_client.send_chat_message(new_chat_id, message, ...)
return {"status": "sent", ...}
```
**Test to add**: `test_graph_send_message_create_chat_no_id_raises` — mock `create_chat` returning `{}`, assert fallback triggers (not "sent")  
**Effort**: 3 lines + 1 test

### Fix ISSUE-8: Surface @mention resolution failures
**File**: `mcp_tools/teams_browser_tools.py:415-430, 683-698`  
**Change**: Track failed mention emails, include in response:
```python
failed_mentions = [email for email in mention_emails if email not in resolved]
# Add to result: "unresolved_mentions": failed_mentions
```
**Effort**: ~8 lines, no test required (additive)

---

## Priority 3 — Fix Functional Bugs

### Fix BUG-4: URL-encode OData filter values
**File**: `connectors/graph_client.py:710-713, 730-733`  
**Change**:
```python
# Before:
safe_name = display_name.replace("'", "''")
f"/users?$filter=displayName eq '{safe_name}'..."

# After:
from urllib.parse import quote as _quote
safe_name = display_name.replace("'", "''")
encoded = _quote(safe_name, safe="")
f"/users?$filter=displayName+eq+'{encoded}'..."
```
**Note**: The cleaner fix is to use httpx `params={"$filter": f"displayName eq '{safe_name}'"}` which handles encoding automatically. Both work.  
**Test to add**: `test_resolve_user_email_name_with_ampersand` and `test_get_user_by_email_with_special_chars`  
**Effort**: 4 lines + 2 tests

### Fix ISSUE-6: Mention display order reversed
**File**: `mcp_tools/teams_browser_tools.py:415-430, 683-698`  
**Change**: Collect all mention tags first, then append to end of message:
```python
mention_tags = []
for idx, email in enumerate(mention_emails):
    user = await graph_client.get_user_by_email(email)
    if user:
        display_name = user["displayName"]
        mentions.append({...})
        mention_tags.append(f'<at id="{idx}">{display_name}</at>')
if mention_tags:
    message = " ".join(mention_tags) + " " + message
```
**Effort**: ~5 lines change in 2 places

---

## Priority 4 — Performance & Dead Code

### Fix ISSUE-7: Cap parallel chat fetching
**File**: `mcp_tools/teams_browser_tools.py:565-573`  
**Change**: Add semaphore to limit concurrency:
```python
sem = asyncio.Semaphore(10)
async def _fetch_with_sem(cid):
    async with sem:
        return await graph_client.get_chat_messages(cid, limit=25)
tasks = [_fetch_with_sem(chat["id"]) for chat in chats if chat.get("id")]
```
**Effort**: ~6 lines

### Fix ISSUE-5: Remove dead `_is_confidential` / `_auth_code_flow`
**File**: `connectors/graph_client.py:142, 283-404`  
**Options**:
- Option A: Delete `_is_confidential` flag, `_auth_code_flow` method, and the `if self._is_confidential:` branch (~85 lines removed)
- Option B: Wire it up: set `_is_confidential = True` when `_confidential_app` is constructed and intended for interactive auth  
**Recommendation**: Option A (remove) unless auth code flow for confidential clients is a planned feature  
**Effort**: Delete ~85 lines + update 2 tests that manually set the flag

---

## Ordered Work Packages

| Order | Item | Effort | Risk |
|-------|------|--------|------|
| 1 | Fix BUG-1: update_chat_topic endpoint | tiny | Low |
| 2 | Fix BUG-2: reply_to_chat_message endpoint | tiny | Low |
| 3 | Fix BUG-3: new-chat silent non-send | small | Low |
| 4 | Fix BUG-4: OData URL encoding | small | Low |
| 5 | Fix ISSUE-6: mention order | small | Low |
| 6 | Fix ISSUE-8: surface unresolved mentions | small | Additive only |
| 7 | Fix ISSUE-7: cap parallel fetch | medium | Low |
| 8 | Fix ISSUE-5: remove dead auth code flow | medium | Needs test update |

**Recommended first action**: Fix BUG-1 and BUG-2 in a single commit — they're 1-liner changes each, zero risk, and restore two broken features immediately.
