# Chunk Audit: GraphClient — Teams Methods

## 1. Correctness

### BUG: update_chat_topic uses wrong endpoint
- **Severity: High**
- confirmed: `update_chat_topic` at line 798 uses `PATCH /me/chats/{safe_id}`
- The Microsoft Graph v1.0 documented endpoint for updating a chat is `PATCH /chats/{chat-id}` — NOT `/me/chats/{chat-id}`
- `/me/chats` is documented only for GET. PATCH on this path returns 405 Method Not Allowed.
- The `manage_teams_chat(action="rename")` MCP tool calls this method — feature is broken silently.
- Fix: `f"/me/chats/{safe_id}"` → `f"/chats/{safe_id}"`

### BUG: reply_to_chat_message suspected wrong endpoint
- **Severity: High (suspected)**
- Line 677: `POST /me/chats/{safe_chat}/messages/{safe_msg}/replies`
- Documented Graph v1.0 endpoint: `POST /chats/{chat-id}/messages/{chatMessage-id}/replies`
- The `/me/chats/` prefix for reply threading is not in the official docs. Suspected to fail with 404 or 405.
- Fix: `f"/me/chats/{safe_chat}/messages/{safe_msg}/replies"` → `f"/chats/{safe_chat}/messages/{safe_msg}/replies"`

### BUG: OData filter values not URL-encoded
- **Severity: Medium**
- Lines 712-713 (`resolve_user_email`) and 730-733 (`get_user_by_email`):
  - `safe_name = display_name.replace("'", "''")` — only OData quote-escaping applied
  - String embedded directly in URL path: `f"/users?$filter=displayName eq '{safe_name}'..."`
  - Characters like `&`, `%`, `#`, `+` in display names will break URL parsing at the httpx layer
  - Example: name `"Dev & Ops"` → URL `...eq 'Dev & Ops'` → httpx splits at `&`, `$filter` is truncated
  - Fix: URL-encode the filter value, or build the URL via httpx params dict

## 2. Completeness
- confirmed: `find_chat_by_members` only fetches 50 chats and uses `issubset`. Users with >50 chats will miss matches. Documented limitation acceptable.
- confirmed: `create_chat` for group chats auto-adds the authenticated user — correctly handles the Graph API requirement. ✓
- suspected: `send_chat_message` with `content_type="html"` — no sanitization of the HTML body. User-provided HTML is passed directly. The Graph API accepts arbitrary HTML in the message body. Low risk (no injection surface for external users), but worth noting.

## 3. Data Flow
- confirmed: All chat_id values passed to URL paths are `urllib.parse.quote(id, safe="")` encoded. ✓
- confirmed: `find_chat_by_members` resolves emails case-insensitively. ✓

## 4. Error Handling
- confirmed: `resolve_user_email` and `get_user_by_email` wrap entire body in try/except and return None on any error — callers can distinguish "not found" from "API error". This is correct. ✓

## 5. Security
- confirmed: OData single-quote injection is handled by `replace("'", "''")` — this is the correct OData escaping technique. ✓
- confirmed: URL path injection mitigated by `urllib.parse.quote(chat_id, safe="")` on all IDs used in paths. ✓
