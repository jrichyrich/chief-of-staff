# Graph API Teams Messaging Fixes

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Graph API Teams messaging so 1:1, group chats, and display-name resolution all work reliably, with proper browser fallback when Graph fails.

**Architecture:** Five focused changes across two files (`graph_client.py` and `teams_browser_tools.py`). Each task is independently testable. The core issues are: (1) missing scopes, (2) group chat creation missing authenticated user as member, (3) `_graph_send_message` doesn't resolve comma-separated display names, (4) `GraphAPIError` exceptions don't trigger browser fallback, (5) soft error dicts bypass fallback.

**Tech Stack:** Python 3.13, pytest, asyncio, Microsoft Graph API v1.0, MSAL

---

## File Map

| File | Changes |
|------|---------|
| `connectors/graph_client.py` | Add scopes, add `get_authenticated_email()`, fix `create_chat` to include self in group |
| `mcp_tools/teams_browser_tools.py` | Import `GraphAPIError`, add to fallback tuple, resolve comma-separated names, raise on soft errors |
| `tests/test_graph_client.py` | Tests for `create_chat`, `get_authenticated_email`, `resolve_user_email`, scope changes |
| `tests/test_teams_graph.py` | Tests for `GraphAPIError` fallback, group name resolution, soft error fallback |

---

## Chunk 1: GraphClient Fixes

### Task 1: Add Missing Scopes

**Files:**
- Modify: `connectors/graph_client.py:80`
- Test: `tests/test_graph_client.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_graph_client.py, add after the imports

def test_default_scopes_include_chat_readwrite():
    """_DEFAULT_SCOPES must include Chat.ReadWrite for chat creation."""
    from connectors.graph_client import _DEFAULT_SCOPES
    assert "Chat.ReadWrite" in _DEFAULT_SCOPES

def test_default_scopes_include_user_read_basic_all():
    """_DEFAULT_SCOPES must include User.ReadBasic.All for user resolution."""
    from connectors.graph_client import _DEFAULT_SCOPES
    assert "User.ReadBasic.All" in _DEFAULT_SCOPES
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph_client.py::test_default_scopes_include_chat_readwrite tests/test_graph_client.py::test_default_scopes_include_user_read_basic_all -v`
Expected: FAIL — current scopes are `["Chat.Read", "ChatMessage.Send", "Mail.Send", "User.Read"]`

- [ ] **Step 3: Update the scopes**

In `connectors/graph_client.py:80`, change:
```python
_DEFAULT_SCOPES = ["Chat.Read", "ChatMessage.Send", "Mail.Send", "User.Read"]
```
to:
```python
_DEFAULT_SCOPES = ["Chat.ReadWrite", "ChatMessage.Send", "Mail.Send", "User.Read", "User.ReadBasic.All"]
```

Note: `Chat.ReadWrite` replaces `Chat.Read` (ReadWrite is a superset). `User.ReadBasic.All` is added for org-wide `/users?$filter=` queries.

- [ ] **Step 4: Update the test fixture scope list to match**

In `tests/test_graph_client.py:51`, the `client` fixture hardcodes scopes. Update to:
```python
gc._scopes = ["Chat.ReadWrite", "ChatMessage.Send", "Mail.Send", "User.Read", "User.ReadBasic.All"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_graph_client.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add connectors/graph_client.py tests/test_graph_client.py
git commit -m "fix: add Chat.ReadWrite and User.ReadBasic.All to Graph scopes

Chat.ReadWrite is required for POST /chats (create_chat).
User.ReadBasic.All is required for /users?$filter= (resolve_user_email).
Without these, group chat creation returns 403 and user resolution fails."
```

---

### Task 2: Add `get_authenticated_email()` and Fix `create_chat` for Group Chats

**Files:**
- Modify: `connectors/graph_client.py:232-260` (ensure_authenticated area), `connectors/graph_client.py:569-601` (create_chat)
- Test: `tests/test_graph_client.py`

- [ ] **Step 1: Write failing tests**

```python
# In tests/test_graph_client.py

@pytest.mark.asyncio
async def test_get_authenticated_email(client, mock_msal_app):
    """get_authenticated_email returns the cached account username."""
    result = await client.get_authenticated_email()
    assert result == "user@example.com"

@pytest.mark.asyncio
async def test_get_authenticated_email_no_accounts(client, mock_msal_app):
    """get_authenticated_email returns None when no accounts cached."""
    mock_msal_app.get_accounts.return_value = []
    result = await client.get_authenticated_email()
    assert result is None

@pytest.mark.asyncio
async def test_create_chat_group_includes_self(client):
    """create_chat for group (2+ members) includes authenticated user."""
    client._http.request.return_value = _make_response(201, {"id": "chat-group-1"})
    client._app.get_accounts.return_value = [{"username": "me@example.com"}]

    result = await client.create_chat(["alice@example.com", "bob@example.com"])
    assert result == {"id": "chat-group-1"}

    call_args = client._http.request.call_args
    payload = call_args[1]["json"]
    assert payload["chatType"] == "group"
    member_bindings = [m["user@odata.bind"] for m in payload["members"]]
    assert "https://graph.microsoft.com/v1.0/users/me@example.com" in member_bindings
    assert "https://graph.microsoft.com/v1.0/users/alice@example.com" in member_bindings
    assert "https://graph.microsoft.com/v1.0/users/bob@example.com" in member_bindings

@pytest.mark.asyncio
async def test_create_chat_oneOnOne_does_not_duplicate_self(client):
    """create_chat for 1:1 does NOT add self — Graph handles it automatically."""
    client._http.request.return_value = _make_response(201, {"id": "chat-1on1"})

    result = await client.create_chat(["alice@example.com"])
    assert result == {"id": "chat-1on1"}

    call_args = client._http.request.call_args
    payload = call_args[1]["json"]
    assert payload["chatType"] == "oneOnOne"
    assert len(payload["members"]) == 1  # Only Alice, not self
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph_client.py::test_get_authenticated_email tests/test_graph_client.py::test_get_authenticated_email_no_accounts tests/test_graph_client.py::test_create_chat_group_includes_self tests/test_graph_client.py::test_create_chat_oneOnOne_does_not_duplicate_self -v`
Expected: FAIL — `get_authenticated_email` doesn't exist, `create_chat` doesn't include self

- [ ] **Step 3: Add `get_authenticated_email` method**

In `connectors/graph_client.py`, add after `ensure_authenticated` (after line ~260):

```python
    async def get_authenticated_email(self) -> str | None:
        """Return the authenticated user's email from MSAL account cache.

        Returns None if no account is cached (not yet authenticated).
        """
        accounts = self._app.get_accounts()
        if accounts:
            return accounts[0].get("username")
        return None
```

- [ ] **Step 4: Fix `create_chat` to include self in group chats**

In `connectors/graph_client.py`, replace the `create_chat` method (lines 569-601) with:

```python
    async def create_chat(
        self,
        member_emails: list[str],
        message: str | None = None,
    ) -> dict:
        """Create a new Teams chat with the given members.

        Uses oneOnOne for a single member, group for multiple.
        For group chats, the authenticated user is explicitly added as an owner
        (required by Graph API). For oneOnOne, Graph auto-includes the caller.
        """
        chat_type = "oneOnOne" if len(member_emails) == 1 else "group"

        members = [
            {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{email}",
            }
            for email in member_emails
        ]

        # Group chats require the caller to be explicitly listed as a member
        if chat_type == "group":
            my_email = await self.get_authenticated_email()
            if my_email and my_email.lower() not in {e.lower() for e in member_emails}:
                members.insert(0, {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{my_email}",
                })

        body: dict[str, Any] = {
            "chatType": chat_type,
            "members": members,
        }

        result = await self._request("POST", "/chats", json=body)

        # Optionally send an initial message
        if message and result.get("id"):
            await self.send_chat_message(result["id"], message)

        return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_graph_client.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add connectors/graph_client.py tests/test_graph_client.py
git commit -m "fix: add authenticated user to group chat members in create_chat

Graph API requires the caller to be explicitly listed as a member in group
chats (unlike oneOnOne where the caller is auto-included). Without this,
group chat creation returns 400 Bad Request.

Also adds get_authenticated_email() to retrieve the cached MSAL account."
```

---

## Chunk 2: Fallback and Resolution Fixes in teams_browser_tools

### Task 3: Add `GraphAPIError` to Fallback Exceptions

**Files:**
- Modify: `mcp_tools/teams_browser_tools.py:32-55`
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_teams_graph.py, add to TestPostTeamsMessageGraphFallback class

    async def test_post_teams_message_graph_api_error_triggers_fallback(self):
        """GraphAPIError (4xx like 400/403) triggers fallback to browser."""
        from connectors.graph_client import GraphAPIError as RealGAE

        gc = AsyncMock()
        gc.find_chat_by_members = AsyncMock(side_effect=RealGAE("400 Bad Request"))
        mcp_server._state.graph_client = gc

        mock_poster = AsyncMock()
        mock_poster.send_message = AsyncMock(return_value={
            "status": "sent",
            "detected_channel": "Shawn Farnworth",
        })

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
                raw = await post_teams_message(
                    target="shawn@example.com", message="Test", auto_send=True
                )

        result = json.loads(raw)
        assert result["status"] == "sent"
        mock_poster.send_message.assert_awaited_once()

        mcp_server._state.graph_client = None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_teams_graph.py::TestPostTeamsMessageGraphFallback::test_post_teams_message_graph_api_error_triggers_fallback -v`
Expected: FAIL — `GraphAPIError` is not in `_GRAPH_FALLBACK_EXCEPTIONS`, so `@tool_errors` catches it instead of falling back

- [ ] **Step 3: Import `GraphAPIError` and add to fallback tuple**

In `mcp_tools/teams_browser_tools.py`, change lines 32-55:

```python
# Guarded import for Graph exceptions
try:
    from connectors.graph_client import GraphAPIError, GraphAuthError, GraphTransientError
except ImportError:
    GraphAPIError = None  # type: ignore[assignment,misc]
    GraphAuthError = None  # type: ignore[assignment,misc]
    GraphTransientError = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


def _chat_type_from_id(chat_id: str) -> str:
    """Derive the chat type from a Teams chat ID string."""
    if "@unq.gbl.spaces" in chat_id:
        return "oneOnOne"
    elif "@thread.tacv2" in chat_id:
        return "channel"
    elif "@thread.v2" in chat_id:
        return "group"
    return "unknown"

# Pre-compute Graph exception tuple once at import time (avoids per-call rebuild)
_GRAPH_FALLBACK_EXCEPTIONS: tuple = tuple(
    exc for exc in (GraphAPIError, GraphTransientError, GraphAuthError) if exc is not None
)
```

Key change: Added `GraphAPIError` to both the import and the fallback tuple. Since `GraphAPIError` is the base class for `GraphTransientError` and `GraphAuthError`, we could use just `GraphAPIError` alone, but listing all three is explicit and makes intent clear.

- [ ] **Step 4: Update the "unexpected exception" test**

The existing test `test_post_teams_message_graph_unexpected_exception_not_caught_as_fallback` uses `ValueError` — this should still NOT trigger fallback (only Graph exceptions should). Verify it still passes.

Also update `test_read_teams_messages_unexpected_exception_not_caught_as_fallback` — it uses `RuntimeError`, which should also still NOT trigger fallback.

Run: `pytest tests/test_teams_graph.py::TestPostTeamsMessageGraphFallback::test_post_teams_message_graph_unexpected_exception_not_caught_as_fallback tests/test_teams_graph.py::TestReadTeamsMessagesFallback::test_read_teams_messages_unexpected_exception_not_caught_as_fallback -v`
Expected: PASS — `ValueError` and `RuntimeError` are not `GraphAPIError` subclasses

- [ ] **Step 5: Run all teams_graph tests**

Run: `pytest tests/test_teams_graph.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add mcp_tools/teams_browser_tools.py tests/test_teams_graph.py
git commit -m "fix: add GraphAPIError to fallback exceptions for browser fallback

GraphAPIError (base class for 4xx errors like 400/403) was not in
_GRAPH_FALLBACK_EXCEPTIONS, so Graph failures from missing scopes or
bad requests would raise instead of falling back to the browser poster.

Now all Graph-originated errors (APIError, TransientError, AuthError)
trigger the browser fallback path. Non-Graph exceptions (ValueError,
RuntimeError, etc.) still raise through to @tool_errors."
```

---

### Task 4: Convert Soft Error Dicts to Raised Exceptions

**Files:**
- Modify: `mcp_tools/teams_browser_tools.py:146-262` (`_graph_send_message`)
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_teams_graph.py, add to TestPostTeamsMessageGraphFallback class

    async def test_post_teams_message_graph_unresolvable_target_falls_back(self):
        """When Graph can't resolve a display name, fall back to browser instead of returning error dict."""
        gc = _make_graph_client(
            find_chat_by_members=AsyncMock(return_value=None),
            resolve_user_email=AsyncMock(return_value=None),
            list_chats=AsyncMock(return_value=[]),  # no chats
        )
        mcp_server._state.graph_client = gc

        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "confirm_required",
            "detected_channel": "Jonas",
        }

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
                raw = await post_teams_message(target="Jonas", message="Hello")

        result = json.loads(raw)
        assert result["status"] == "confirm_required"
        mock_poster.prepare_message.assert_awaited_once()

        mcp_server._state.graph_client = None

    async def test_post_teams_message_graph_ambiguous_target_falls_back(self):
        """When Graph finds ambiguous matches, fall back to browser."""
        gc = _make_graph_client(
            find_chat_by_members=AsyncMock(return_value=None),
            resolve_user_email=AsyncMock(return_value=None),
            list_chats=AsyncMock(return_value=[
                {"id": "c1", "topic": None, "members": [{"displayName": "Alice Smith-Jones", "email": "asj@ex.com"}]},
                {"id": "c2", "topic": None, "members": [{"displayName": "Alice Smith-Brown", "email": "asb@ex.com"}]},
            ]),
        )
        mcp_server._state.graph_client = gc

        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "confirm_required",
            "detected_channel": "Alice Smith",
        }

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
                raw = await post_teams_message(target="Alice Smith", message="Hi")

        result = json.loads(raw)
        assert result["status"] == "confirm_required"
        mock_poster.prepare_message.assert_awaited_once()

        mcp_server._state.graph_client = None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_teams_graph.py::TestPostTeamsMessageGraphFallback::test_post_teams_message_graph_unresolvable_target_falls_back tests/test_teams_graph.py::TestPostTeamsMessageGraphFallback::test_post_teams_message_graph_ambiguous_target_falls_back -v`
Expected: FAIL — soft error dicts bypass fallback

- [ ] **Step 3: Convert error dicts to raised `GraphAPIError`**

In `mcp_tools/teams_browser_tools.py`, change `_graph_send_message` (lines 228-235 and 247-253).

Replace the ambiguous error return (lines 228-235):
```python
                    else:
                        match_names = [name for _, name, _ in substring_matches]
                        raise GraphAPIError(
                            f"Ambiguous target '{target}' matched multiple chats: {match_names}. "
                            "Please use a more specific name or an email address."
                        )
```

Replace the unresolvable error return (lines 247-253):
```python
    if chat_id is None:
        raise GraphAPIError(
            f"Could not resolve target '{target}' to a Teams chat. "
            "Try using an email address instead of a display name."
        )
```

Note: `GraphAPIError` is now imported (from Task 3). These raises will be caught by the fallback exception handler in `post_teams_message`, which triggers browser fallback.

- [ ] **Step 4: Remove the old ambiguous display name test**

The existing `test_post_teams_message_graph_ambiguous_display_name` method in `tests/test_teams_graph.py` (class `TestPostTeamsMessageGraphBackend`, lines 132-161) expects `result["status"] == "error"` returned from the Graph path. Now that ambiguous targets raise `GraphAPIError` and fall back to browser, this test is obsolete — replaced by the new `test_post_teams_message_graph_ambiguous_target_falls_back`.

Delete the entire method `test_post_teams_message_graph_ambiguous_display_name` (lines 132-161 of `tests/test_teams_graph.py`).

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_teams_graph.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add mcp_tools/teams_browser_tools.py tests/test_teams_graph.py
git commit -m "fix: convert _graph_send_message soft errors to exceptions for browser fallback

Previously, _graph_send_message returned {'status': 'error', ...} dicts
for ambiguous or unresolvable targets. These dicts were serialized as
successful results, bypassing the browser fallback path entirely.

Now these cases raise GraphAPIError, which is caught by the fallback
handler and routes to the browser poster."
```

---

### Task 5: Resolve Comma-Separated Display Names for Group Chats

**Files:**
- Modify: `mcp_tools/teams_browser_tools.py:146-262` (`_graph_send_message`)
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_teams_graph.py, add to TestPostTeamsMessageGraphBackend class

    async def test_post_teams_message_graph_comma_separated_names_resolved(self):
        """Comma-separated display names are resolved to emails and used for group chat."""
        gc = _make_graph_client(
            find_chat_by_members=AsyncMock(return_value=None),
            resolve_user_email=AsyncMock(side_effect=lambda name: {
                "Shawn Farnworth": "shawn@example.com",
                "Phil Chandler": "phil@example.com",
            }.get(name)),
            list_chats=AsyncMock(return_value=[]),
            create_chat=AsyncMock(return_value={"id": "chat-group-new"}),
        )
        gc.get_authenticated_email = AsyncMock(return_value="me@example.com")
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            raw = await post_teams_message(
                target="Shawn Farnworth, Phil Chandler",
                message="How did the Lumos meetings go?",
            )

        result = json.loads(raw)
        assert result["status"] == "sent"
        assert result["backend"] == "graph"
        gc.create_chat.assert_awaited_once()
        # Verify both resolved emails were passed
        call_args = gc.create_chat.call_args
        assert set(call_args[0][0]) == {"shawn@example.com", "phil@example.com"}

        mcp_server._state.graph_client = None

    async def test_post_teams_message_graph_comma_names_partial_resolve_falls_back(self):
        """If any comma-separated name can't be resolved, fall back to browser."""
        gc = _make_graph_client(
            find_chat_by_members=AsyncMock(return_value=None),
            resolve_user_email=AsyncMock(side_effect=lambda name: {
                "Shawn Farnworth": "shawn@example.com",
            }.get(name)),  # Phil not found
            list_chats=AsyncMock(return_value=[]),
        )
        mcp_server._state.graph_client = gc

        mock_poster = AsyncMock()
        mock_poster.prepare_message.return_value = {
            "status": "confirm_required",
        }

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            with patch.object(teams_browser_tools, "_get_poster", return_value=mock_poster):
                raw = await post_teams_message(
                    target="Shawn Farnworth, Phil Chandler",
                    message="Test",
                )

        result = json.loads(raw)
        # Should fall back to browser since we can't resolve all names
        assert result["status"] == "confirm_required"
        mock_poster.prepare_message.assert_awaited_once()

        mcp_server._state.graph_client = None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_teams_graph.py::TestPostTeamsMessageGraphBackend::test_post_teams_message_graph_comma_separated_names_resolved tests/test_teams_graph.py::TestPostTeamsMessageGraphBackend::test_post_teams_message_graph_comma_names_partial_resolve_falls_back -v`
Expected: FAIL

- [ ] **Step 3: Replace the entire `_graph_send_message` function**

In `mcp_tools/teams_browser_tools.py`, replace the entire `_graph_send_message` function (lines 146-262) with:

```python
async def _graph_send_message(graph_client, target: str, message: str) -> dict:
    """Send a Teams message via Graph API, resolving target to a chat.

    Resolution strategies (in order):
    0. Direct chat ID (starts with ``19:``)
    0.5. Comma-separated names → resolve each via /users, create group chat
    1. Email target(s) → find existing chat by member emails
    1.5. Single display name → resolve to email via /users → find chat
    2. Display name search across chat list (exact then substring)
    3. Create new chat if target is email(s) and no chat found

    Raises ``GraphAPIError`` on resolution failure so the caller can
    fall back to the browser poster.
    """
    # --- Parse target into emails and/or names ---
    target_emails: list[str] = []
    target_names: list[str] = []
    if "," in target:
        parts = [t.strip() for t in target.split(",") if t.strip()]
        target_emails = [p for p in parts if "@" in p]
        target_names = [p for p in parts if "@" not in p]
    elif "@" in target:
        target_emails = [target.strip()]
    else:
        target_names = [target.strip()]

    chat_id = None

    # Priority 0: Direct chat ID — skip all resolution
    if target.startswith("19:"):
        chat_id = target
    else:
        # Strategy 0.5: Resolve display names to emails
        if target_names:
            resolved_emails: list[str | None] = []
            for name in target_names:
                email = await graph_client.resolve_user_email(name)
                resolved_emails.append(email)

            if all(resolved_emails):
                # All names resolved — merge with any email targets
                target_emails = target_emails + [e for e in resolved_emails if e]
            elif len(target_names) > 1:
                # Group chat requires all names resolved — raise to trigger fallback
                failed = [n for n, e in zip(target_names, resolved_emails) if e is None]
                raise GraphAPIError(
                    f"Could not resolve group chat members: {', '.join(failed)}"
                )
            # Single unresolved name: fall through to Strategy 2 (display name search)

        # Strategy 1: Find chat by member email(s)
        if target_emails:
            chat_id = await graph_client.find_chat_by_members(target_emails)

        # Strategy 2: Search through chats by display name match
        # Only for single-name targets where email resolution failed
        if chat_id is None and len(target_names) == 1 and not target_emails:
            target_lower = target_names[0].lower()
            chats = await graph_client.list_chats(limit=50)
            substring_matches: list[tuple[str, str, int]] = []

            # Pass 1: exact match on topic or displayName
            exact_matches: list[tuple[str, int]] = []
            for chat in chats:
                topic = (chat.get("topic") or "").lower()
                members = chat.get("members", [])
                member_count = len(members)
                if topic and target_lower == topic:
                    exact_matches.append((chat.get("id", ""), member_count))
                    continue
                for m in members:
                    display = (m.get("displayName") or "").lower()
                    if target_lower == display:
                        exact_matches.append((chat.get("id", ""), member_count))
                        break

            if exact_matches:
                exact_matches.sort(key=lambda x: x[1])
                chat_id = exact_matches[0][0]

            # Pass 2: substring match (only if no exact match found)
            if chat_id is None:
                for chat in chats:
                    topic = (chat.get("topic") or "").lower()
                    members = chat.get("members", [])
                    member_count = len(members)
                    if topic and target_lower in topic:
                        substring_matches.append((chat.get("id", ""), chat.get("topic") or "", member_count))
                        continue
                    for m in members:
                        display = (m.get("displayName") or "").lower()
                        if target_lower in display:
                            substring_matches.append((chat.get("id", ""), m.get("displayName") or "", member_count))
                            break

                if len(substring_matches) == 1:
                    chat_id = substring_matches[0][0]
                elif len(substring_matches) > 1:
                    substring_matches.sort(key=lambda x: x[2])
                    if substring_matches[0][2] < substring_matches[1][2]:
                        chat_id = substring_matches[0][0]
                    else:
                        match_names = [name for _, name, _ in substring_matches]
                        raise GraphAPIError(
                            f"Ambiguous target '{target}' matched multiple chats: {match_names}. "
                            "Please use a more specific name or an email address."
                        )

    # Strategy 3: If target is email(s), create a new chat
    if chat_id is None and target_emails:
        result = await graph_client.create_chat(target_emails, message=message)
        return {
            "status": "sent",
            "backend": "graph",
            "chat_id": result.get("id"),
            "detail": f"Created new chat and sent message to {', '.join(target_emails)}",
        }

    if chat_id is None:
        raise GraphAPIError(
            f"Could not resolve target '{target}' to a Teams chat. "
            "Try using an email address instead of a display name."
        )

    # Send to the resolved chat
    result = await graph_client.send_chat_message(chat_id, message)
    return {
        "status": "sent",
        "backend": "graph",
        "chat_id": chat_id,
        "message_id": result.get("id"),
    }
```

Key changes from the original:
1. **Target parsing** now separates comma-separated input into `target_names` and `target_emails`
2. **Strategy 0.5** resolves display names to emails via `resolve_user_email`; raises `GraphAPIError` if any group chat member can't be resolved
3. **Strategy 1.5 removed** — its job is now done by Strategy 0.5 (single names are resolved there too)
4. **Strategy 2** only runs for single-name targets where email resolution failed (guards: `len(target_names) == 1 and not target_emails`)
5. **Ambiguous and unresolvable errors** now raise `GraphAPIError` instead of returning dicts, so the browser fallback in `post_teams_message` can catch them

Note: This replacement also covers Task 4's changes (soft error → raised exceptions), so Tasks 4 and 5 are combined in a single function replacement. Execute Task 4's tests first, then this replacement, then Task 5's tests.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_teams_graph.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_tools/teams_browser_tools.py tests/test_teams_graph.py
git commit -m "feat: resolve comma-separated display names for Graph group chats

Previously, 'Shawn Farnworth, Phil Chandler' couldn't be sent via Graph
because the names weren't resolved to emails. Now _graph_send_message
resolves each comma-separated name via resolve_user_email before
creating the group chat.

If any name can't be resolved, falls back to browser poster."
```

---

## Chunk 3: Fix `read_teams_messages` Chat Limit Bug

### Task 6: Fix `read_teams_messages` Using Message Limit to Cap Chats Scanned

**Files:**
- Modify: `mcp_tools/teams_browser_tools.py:491`
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_teams_graph.py, add to TestReadTeamsMessagesGraphBackend class

    async def test_read_teams_messages_scans_all_chats_not_limited_by_message_limit(self):
        """Message limit should not cap the number of chats scanned."""
        gc = _make_graph_client(
            list_chats=AsyncMock(return_value=[
                {"id": f"chat-{i}", "topic": f"Chat {i}", "members": []} for i in range(10)
            ]),
            get_chat_messages=AsyncMock(return_value=[
                {
                    "id": "msg-1",
                    "body": {"content": "Message from Alice", "contentType": "text"},
                    "createdDateTime": "2026-03-12T10:00:00Z",
                    "from": {"user": {"displayName": "Alice"}},
                }
            ]),  # each chat has 1 message
        )
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_read_backend", return_value="graph"):
            raw = await read_teams_messages(limit=3)

        result = json.loads(raw)
        assert result["count"] == 3  # Only 3 messages returned
        # But all 10 chats should have been scanned
        assert gc.get_chat_messages.await_count == 10

        mcp_server._state.graph_client = None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_teams_graph.py::TestReadTeamsMessagesGraphBackend::test_read_teams_messages_scans_all_chats_not_limited_by_message_limit -v`
Expected: FAIL — only `limit` (3) chats are scanned instead of all 10

- [ ] **Step 3: Fix the chat iteration**

In `mcp_tools/teams_browser_tools.py:491`, change:
```python
                    for chat in chats[:limit]:
```
to:
```python
                    for chat in chats:
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_teams_graph.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_tools/teams_browser_tools.py tests/test_teams_graph.py
git commit -m "fix: scan all chats in read_teams_messages, not just first N

The message limit parameter was incorrectly used to cap the number of
chats scanned (chats[:limit]). A user requesting 5 messages would only
scan 5 chats, potentially missing messages in other chats. Now all
chats are scanned and the limit only applies to total messages returned."
```

---

## Chunk 4: Integration Verification

### Task 7: Run Full Test Suite and Verify

- [ ] **Step 1: Run the full test suite for affected files**

Run: `pytest tests/test_graph_client.py tests/test_teams_graph.py tests/test_teams_browser_tools.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run broader test suite to check for regressions**

Run: `pytest tests/ -x --timeout=60`
Expected: ALL PASS (or at least no new failures)

- [ ] **Step 3: Final commit if any fixups needed**

Only if Step 2 revealed issues that need fixing.
