# Teams Message Routing Fix — Design Spec

**Date:** 2026-03-12
**Status:** Approved
**Problem:** `post_teams_message` with a display name target can route to a group chat instead of the intended 1:1 DM. No way to explicitly target a specific group chat by ID.

## Context

The `_graph_send_message()` function in `mcp_tools/teams_browser_tools.py` resolves a target string (name, email, or comma-separated names) to a Teams chat ID. Two routing paths exist:

- **Email path** (`find_chat_by_members()` in `connectors/graph_client.py`): Sorts chats by member count ascending, so 1:1 chats match before group chats. Works correctly.
- **Display name path** (Strategy 2 in `_graph_send_message()`): Iterates chats in arbitrary order. First match wins regardless of chat type. This is the bug — "Dean Lythgoe" can match a group chat before the 1:1 DM.

## Design

### Change 1: Accept chat IDs as direct targets

At the top of `_graph_send_message()`, before any resolution:

```python
if target.startswith("19:"):
    chat_id = target
```

Skip all resolution and send directly. Zero ambiguity.

### Change 2: Add `resolve_user_email()` to `GraphClient`

New method in `connectors/graph_client.py`:

```python
async def resolve_user_email(self, display_name: str) -> str | None:
```

- Calls `GET /users?$filter=displayName eq '{display_name}'&$select=mail,userPrincipalName`
- Returns email if exactly 1 result, `None` otherwise
- Handles Graph API errors gracefully (returns `None` on failure)

### Change 3: Display name → email resolution in `_graph_send_message()`

When target is a single display name (no `@`, no commas, doesn't start with `19:`):

1. Call `graph_client.resolve_user_email(target)`
2. If email resolved → feed into `find_chat_by_members([email])` which already prefers 1:1
3. If resolution fails → fall through to Strategy 2

### Change 4: Sort Strategy 2 matches by member count

Both Pass 1 (exact match) and Pass 2 (substring match) in Strategy 2 should prefer 1:1 chats:

- **Pass 1**: Collect all exact matches, sort by member count, pick the one with fewest members
- **Pass 2**: Already collects substring matches in a list. Sort by member count ascending before selecting.

This requires storing member count alongside chat_id in the match tuples.

### Change 5: Enrich `read_teams_messages` results

Each message in the response from the Jarvis `read_teams_messages` tool should include:

- `chat_id` — the `19:...` identifier
- `chat_type` — derived from ID suffix:
  - `@unq.gbl.spaces` → `"oneOnOne"`
  - `@thread.v2` → `"group"`
  - `@thread.tacv2` → `"channel"`
- `chat_topic` — group chat display name (null for 1:1)
- `chat_members` — list of member display names

This enables informed targeting: see a message from a group chat → grab its `chat_id` → pass directly to `post_teams_message`.

## Resolution Priority (Final)

1. **Chat ID** (`19:...`) → direct send, no resolution
2. **Email** (`@` in target) → `find_chat_by_members()` → 1:1 preferred
3. **Display name** → `resolve_user_email()` → `find_chat_by_members()` → 1:1 preferred
4. **Display name fallback** → Strategy 2 with member-count sort → 1:1 preferred
5. **Create new chat** → only if email target and no existing chat found

## Files Changed

| File | Change |
|------|--------|
| `connectors/graph_client.py` | Add `resolve_user_email(display_name)` method |
| `mcp_tools/teams_browser_tools.py` | Chat ID detection at top of `_graph_send_message()` |
| `mcp_tools/teams_browser_tools.py` | Display name → email resolution before Strategy 2 |
| `mcp_tools/teams_browser_tools.py` | Sort Strategy 2 matches by member count ascending |
| `mcp_tools/teams_browser_tools.py` | Enrich `read_teams_messages` response with chat context |
| `tests/test_teams_routing.py` | New test file covering all routing paths |

## No Breaking Changes

- Existing email targets work identically
- Display name targets now route more reliably (1:1 preferred)
- Chat ID is a new input type that wasn't previously accepted
- `read_teams_messages` adds new fields without removing existing ones

## Test Cases

1. `target="19:abc..."` → sends directly to that chat ID
2. `target="dean.lythgoe@chghealthcare.com"` → finds 1:1 DM (existing behavior)
3. `target="Dean Lythgoe"` → resolves to email → finds 1:1 DM (fixed behavior)
4. `target="Dean Lythgoe"` when Graph `/users` fails → falls back to Strategy 2 with 1:1 sort
5. `target="Alice, Bob"` → creates/finds group chat (existing behavior)
6. `read_teams_messages` → each message includes `chat_id`, `chat_type`, `chat_topic`, `chat_members`
