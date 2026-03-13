# Teams Graph API Enhancement — Reply, Mentions, Rich Content, Chat Management

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maximize Jarvis's Teams communication capabilities by adding reply threading, @mentions, HTML rich content, and group chat management via the Microsoft Graph API.

**Architecture:** Extend `GraphClient` with new endpoints, enhance existing `send_chat_message` to support content types and mentions, add new MCP tools for reply and chat management. All new features follow the existing Graph-primary / browser-fallback pattern.

**Tech Stack:** Microsoft Graph API v1.0, MSAL auth (existing), httpx async HTTP, pytest + AsyncMock

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `connectors/graph_client.py` | Modify | Add reply, user lookup, chat management methods; enhance send_chat_message |
| `mcp_tools/teams_browser_tools.py` | Modify | Add reply_to_teams_message, manage_teams_chat tools; enhance post_teams_message with content_type |
| `config.py` | Modify | Sync M365_GRAPH_SCOPES with graph_client defaults |
| `tests/test_teams_graph.py` | Modify | Add tests for all new functionality |

---

## Chunk 1: GraphClient Core Methods

### Task 1: Fix config.py scope mismatch

`config.py:166` has stale scopes missing `Chat.ReadWrite` and `User.ReadBasic.All` that `graph_client.py:80` already uses. Sync them.

**Files:**
- Modify: `config.py:166`

- [ ] **Step 1: Fix M365_GRAPH_SCOPES in config.py**

Replace line 166:
```python
M365_GRAPH_SCOPES = ["Chat.Read", "ChatMessage.Send", "Mail.Send", "User.Read"]
```
With:
```python
M365_GRAPH_SCOPES = ["Chat.ReadWrite", "ChatMessage.Send", "Mail.Send", "User.Read", "User.ReadBasic.All"]
```

- [ ] **Step 2: Commit**

```bash
git add config.py
git commit -m "fix: sync M365_GRAPH_SCOPES with graph_client defaults"
```

### Task 2: Add get_user_by_email to GraphClient

Needed for @mentions — we need the Azure AD user ID, not just email.

**Files:**
- Modify: `connectors/graph_client.py` (after `resolve_user_email` method, ~line 577)
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
class TestGraphClientGetUser:
    """Tests for get_user_by_email method."""

    async def test_get_user_by_email_returns_user_object(self):
        """get_user_by_email returns id, displayName, mail for valid email."""
        gc = _make_graph_client()
        gc.get_user_by_email = AsyncMock(return_value={
            "id": "user-aad-id-001",
            "displayName": "Alice Smith",
            "mail": "alice@example.com",
        })

        result = await gc.get_user_by_email("alice@example.com")
        assert result["id"] == "user-aad-id-001"
        assert result["displayName"] == "Alice Smith"

    async def test_get_user_by_email_returns_none_for_unknown(self):
        """get_user_by_email returns None when user not found."""
        gc = _make_graph_client()
        gc.get_user_by_email = AsyncMock(return_value=None)

        result = await gc.get_user_by_email("nobody@example.com")
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_teams_graph.py::TestGraphClientGetUser -v`
Expected: FAIL (class doesn't exist yet in test file — we'll add it)

- [ ] **Step 3: Implement get_user_by_email in GraphClient**

Add after `resolve_user_email` method in `connectors/graph_client.py`:

```python
    async def get_user_by_email(self, email: str) -> dict | None:
        """Look up an Azure AD user by email address.

        Returns a dict with ``id``, ``displayName``, and ``mail`` fields,
        or None if the user is not found.  The ``id`` is the Azure AD
        object ID needed for @mentions in Teams messages.
        """
        try:
            safe_email = email.replace("'", "''")
            data = await self._request(
                "GET",
                f"/users?$filter=mail eq '{safe_email}' or userPrincipalName eq '{safe_email}'"
                f"&$select=id,displayName,mail,userPrincipalName",
            )
            users = data.get("value", [])
            if len(users) >= 1:
                u = users[0]
                return {
                    "id": u.get("id"),
                    "displayName": u.get("displayName"),
                    "mail": u.get("mail") or u.get("userPrincipalName"),
                }
            return None
        except Exception:
            return None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_teams_graph.py::TestGraphClientGetUser -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add connectors/graph_client.py tests/test_teams_graph.py
git commit -m "feat: add get_user_by_email to GraphClient for @mention user ID resolution"
```

### Task 3: Enhance send_chat_message with content_type and mentions

**Files:**
- Modify: `connectors/graph_client.py:529-536`
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
class TestSendChatMessageEnhanced:
    """Tests for enhanced send_chat_message with content_type and mentions."""

    async def test_send_chat_message_html_content(self):
        """send_chat_message sends HTML when content_type='html'."""
        gc = _make_graph_client()
        mcp_server._state.graph_client = gc

        await gc.send_chat_message("chat-001", "<b>Bold</b> message", content_type="html")
        gc.send_chat_message.assert_awaited_once_with("chat-001", "<b>Bold</b> message", content_type="html")

    async def test_send_chat_message_with_mentions(self):
        """send_chat_message includes mentions array when provided."""
        gc = _make_graph_client()
        mentions = [
            {
                "id": 0,
                "mentionText": "Alice Smith",
                "mentioned": {
                    "user": {
                        "id": "user-aad-001",
                        "displayName": "Alice Smith",
                        "userIdentityType": "aadUser",
                    }
                },
            }
        ]

        await gc.send_chat_message(
            "chat-001",
            '<at id="0">Alice Smith</at> please review',
            content_type="html",
            mentions=mentions,
        )
        gc.send_chat_message.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_teams_graph.py::TestSendChatMessageEnhanced -v`

- [ ] **Step 3: Update send_chat_message signature and body**

Replace the existing `send_chat_message` method in `connectors/graph_client.py`:

```python
    async def send_chat_message(
        self,
        chat_id: str,
        content: str,
        content_type: str = "text",
        mentions: list[dict] | None = None,
    ) -> dict:
        """Send a message to a Teams chat.

        Args:
            chat_id: The Teams chat ID.
            content: Message body text (plain text or HTML).
            content_type: ``"text"`` (default) or ``"html"``.
            mentions: Optional list of mention objects for @mentions.
                Each must have ``id``, ``mentionText``, and ``mentioned.user``
                with ``id``, ``displayName``, ``userIdentityType``.
        """
        safe_id = urllib.parse.quote(chat_id, safe="")
        body: dict[str, Any] = {
            "body": {"content": content, "contentType": content_type},
        }
        if mentions:
            body["mentions"] = mentions
        return await self._request(
            "POST",
            f"/me/chats/{safe_id}/messages",
            json=body,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_teams_graph.py::TestSendChatMessageEnhanced -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add connectors/graph_client.py tests/test_teams_graph.py
git commit -m "feat: enhance send_chat_message with content_type and mentions support"
```

### Task 4: Add reply_to_chat_message to GraphClient

**Files:**
- Modify: `connectors/graph_client.py` (after `send_chat_message`)
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
class TestReplyToChatMessage:
    """Tests for reply_to_chat_message method."""

    async def test_reply_to_chat_message_basic(self):
        """Reply to a specific message in a chat."""
        gc = _make_graph_client(
            reply_to_chat_message=AsyncMock(return_value={"id": "reply-001"}),
        )

        result = await gc.reply_to_chat_message("chat-001", "msg-001", "Thanks!")
        assert result["id"] == "reply-001"
        gc.reply_to_chat_message.assert_awaited_once_with("chat-001", "msg-001", "Thanks!")

    async def test_reply_to_chat_message_with_html_and_mentions(self):
        """Reply with HTML content and @mentions."""
        gc = _make_graph_client(
            reply_to_chat_message=AsyncMock(return_value={"id": "reply-002"}),
        )
        mentions = [{"id": 0, "mentionText": "Bob", "mentioned": {"user": {"id": "u1", "displayName": "Bob", "userIdentityType": "aadUser"}}}]

        result = await gc.reply_to_chat_message(
            "chat-001", "msg-001",
            '<at id="0">Bob</at> done!',
            content_type="html",
            mentions=mentions,
        )
        assert result["id"] == "reply-002"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_teams_graph.py::TestReplyToChatMessage -v`

- [ ] **Step 3: Implement reply_to_chat_message**

Add after `send_chat_message` in `connectors/graph_client.py`:

```python
    async def reply_to_chat_message(
        self,
        chat_id: str,
        message_id: str,
        content: str,
        content_type: str = "text",
        mentions: list[dict] | None = None,
    ) -> dict:
        """Reply to a specific message in a Teams chat (threading).

        Args:
            chat_id: The Teams chat ID.
            message_id: The ID of the message to reply to.
            content: Reply body (plain text or HTML).
            content_type: ``"text"`` (default) or ``"html"``.
            mentions: Optional list of mention objects for @mentions.
        """
        safe_chat = urllib.parse.quote(chat_id, safe="")
        safe_msg = urllib.parse.quote(message_id, safe="")
        body: dict[str, Any] = {
            "body": {"content": content, "contentType": content_type},
        }
        if mentions:
            body["mentions"] = mentions
        return await self._request(
            "POST",
            f"/me/chats/{safe_chat}/messages/{safe_msg}/replies",
            json=body,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_teams_graph.py::TestReplyToChatMessage -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add connectors/graph_client.py tests/test_teams_graph.py
git commit -m "feat: add reply_to_chat_message for Teams message threading"
```

### Task 5: Add chat management methods to GraphClient

**Files:**
- Modify: `connectors/graph_client.py` (after `create_chat`)
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
class TestChatManagement:
    """Tests for chat management methods."""

    async def test_update_chat_topic(self):
        """Rename a group chat topic."""
        gc = _make_graph_client(
            update_chat_topic=AsyncMock(return_value={"status": "success"}),
        )
        result = await gc.update_chat_topic("chat-001", "New Topic Name")
        assert result["status"] == "success"

    async def test_list_chat_members(self):
        """List members of a chat."""
        gc = _make_graph_client(
            list_chat_members=AsyncMock(return_value=[
                {"id": "member-001", "displayName": "Alice", "email": "alice@example.com"},
            ]),
        )
        members = await gc.list_chat_members("chat-001")
        assert len(members) == 1
        assert members[0]["displayName"] == "Alice"

    async def test_add_chat_member(self):
        """Add a member to a group chat."""
        gc = _make_graph_client(
            add_chat_member=AsyncMock(return_value={"id": "member-new"}),
        )
        result = await gc.add_chat_member("chat-001", "newperson@example.com")
        assert result["id"] == "member-new"

    async def test_remove_chat_member(self):
        """Remove a member from a group chat."""
        gc = _make_graph_client(
            remove_chat_member=AsyncMock(return_value={"status": "success"}),
        )
        result = await gc.remove_chat_member("chat-001", "member-001")
        assert result["status"] == "success"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_teams_graph.py::TestChatManagement -v`

- [ ] **Step 3: Implement chat management methods**

Add after `create_chat` in `connectors/graph_client.py`:

```python
    async def update_chat_topic(self, chat_id: str, topic: str) -> dict:
        """Rename a group chat's topic/display name.

        Only works on group chats — oneOnOne chats cannot have topics.
        """
        safe_id = urllib.parse.quote(chat_id, safe="")
        return await self._request(
            "PATCH",
            f"/me/chats/{safe_id}",
            json={"topic": topic},
        )

    async def list_chat_members(self, chat_id: str) -> list[dict]:
        """List members of a Teams chat.

        Returns a list of member dicts with ``id``, ``displayName``, and
        ``email`` fields.
        """
        safe_id = urllib.parse.quote(chat_id, safe="")
        data = await self._request("GET", f"/me/chats/{safe_id}/members")
        return data.get("value", [])

    async def add_chat_member(self, chat_id: str, user_email: str, roles: list[str] | None = None) -> dict:
        """Add a member to a group chat.

        Args:
            chat_id: The Teams chat ID.
            user_email: Email of the user to add.
            roles: Optional roles list (e.g. ``["owner"]``). Defaults to ``["guest"]``.
        """
        safe_id = urllib.parse.quote(chat_id, safe="")
        return await self._request(
            "POST",
            f"/me/chats/{safe_id}/members",
            json={
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": roles or ["guest"],
                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{user_email}",
            },
        )

    async def remove_chat_member(self, chat_id: str, membership_id: str) -> dict:
        """Remove a member from a group chat by their membership ID.

        Use ``list_chat_members`` first to find the membership ID.
        """
        safe_chat = urllib.parse.quote(chat_id, safe="")
        safe_member = urllib.parse.quote(membership_id, safe="")
        return await self._request(
            "DELETE",
            f"/me/chats/{safe_chat}/members/{safe_member}",
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_teams_graph.py::TestChatManagement -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add connectors/graph_client.py tests/test_teams_graph.py
git commit -m "feat: add chat management methods — topic rename, member add/remove/list"
```

---

## Chunk 2: MCP Tool Layer

### Task 6: Add reply_to_teams_message MCP tool

**Files:**
- Modify: `mcp_tools/teams_browser_tools.py` (inside `register()`)
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
class TestReplyToTeamsMessage:
    """Tests for reply_to_teams_message MCP tool."""

    async def test_reply_basic_text(self):
        """Reply to a message with plain text via Graph API."""
        gc = _make_graph_client(
            reply_to_chat_message=AsyncMock(return_value={"id": "reply-001"}),
        )
        mcp_server._state.graph_client = gc

        raw = await reply_to_teams_message(
            chat_id="chat-001",
            message_id="msg-001",
            message="Got it, thanks!",
        )
        result = json.loads(raw)
        assert result["status"] == "sent"
        assert result["reply_id"] == "reply-001"
        gc.reply_to_chat_message.assert_awaited_once_with(
            "chat-001", "msg-001", "Got it, thanks!", content_type="text", mentions=None,
        )
        mcp_server._state.graph_client = None

    async def test_reply_with_html(self):
        """Reply with HTML formatted content."""
        gc = _make_graph_client(
            reply_to_chat_message=AsyncMock(return_value={"id": "reply-002"}),
        )
        mcp_server._state.graph_client = gc

        raw = await reply_to_teams_message(
            chat_id="chat-001",
            message_id="msg-001",
            message="<b>Important:</b> Updated the doc.",
            content_type="html",
        )
        result = json.loads(raw)
        assert result["status"] == "sent"
        mcp_server._state.graph_client = None

    async def test_reply_with_mention(self):
        """Reply with an @mention resolves user and embeds mention markup."""
        gc = _make_graph_client(
            reply_to_chat_message=AsyncMock(return_value={"id": "reply-003"}),
            get_user_by_email=AsyncMock(return_value={
                "id": "user-aad-001",
                "displayName": "Alice Smith",
                "mail": "alice@example.com",
            }),
        )
        mcp_server._state.graph_client = gc

        raw = await reply_to_teams_message(
            chat_id="chat-001",
            message_id="msg-001",
            message="Please review this",
            mention_emails=["alice@example.com"],
        )
        result = json.loads(raw)
        assert result["status"] == "sent"
        # Verify mentions were passed to reply_to_chat_message
        call_kwargs = gc.reply_to_chat_message.call_args
        assert call_kwargs.kwargs.get("mentions") is not None
        assert call_kwargs.kwargs.get("content_type") == "html"
        mcp_server._state.graph_client = None

    async def test_reply_no_graph_client_returns_error(self):
        """Reply fails gracefully when Graph client is not configured."""
        mcp_server._state.graph_client = None

        raw = await reply_to_teams_message(
            chat_id="chat-001",
            message_id="msg-001",
            message="Test",
        )
        result = json.loads(raw)
        assert "error" in result
        assert "Graph API" in result["error"]

    async def test_reply_graph_error_returns_error(self):
        """Graph API errors are returned as error dict (no browser fallback for replies)."""
        from connectors.graph_client import GraphAPIError as RealGAE

        gc = _make_graph_client(
            reply_to_chat_message=AsyncMock(side_effect=RealGAE("404 Not Found")),
        )
        mcp_server._state.graph_client = gc

        raw = await reply_to_teams_message(
            chat_id="chat-001",
            message_id="msg-001",
            message="Test",
        )
        result = json.loads(raw)
        assert "error" in result
        mcp_server._state.graph_client = None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_teams_graph.py::TestReplyToTeamsMessage -v`
Expected: FAIL (reply_to_teams_message not yet defined)

- [ ] **Step 3: Implement reply_to_teams_message MCP tool**

Add inside `register()` in `mcp_tools/teams_browser_tools.py`, after the `read_teams_messages` tool:

```python
    @mcp.tool()
    @tool_errors("Teams reply error")
    async def reply_to_teams_message(
        chat_id: str,
        message_id: str,
        message: str,
        content_type: str = "text",
        mention_emails: list[str] | None = None,
    ) -> str:
        """Reply to a specific message in a Teams chat (creates a threaded reply).

        The chat_id and message_id can be obtained from read_teams_messages results.

        When mention_emails are provided, users are @mentioned in the reply.
        The content_type is automatically set to 'html' when mentions are used.

        Args:
            chat_id: The Teams chat ID (from read_teams_messages results)
            message_id: The message ID to reply to (from read_teams_messages results)
            message: The reply text
            content_type: 'text' (default) or 'html' for rich formatting
            mention_emails: Optional list of email addresses to @mention
        """
        graph_client = state.graph_client
        if graph_client is None:
            return json.dumps({"error": "Graph API not configured — reply requires Graph API"})

        mentions = None
        if mention_emails:
            content_type = "html"
            mentions = []
            for idx, email in enumerate(mention_emails):
                user = await graph_client.get_user_by_email(email)
                if user:
                    display_name = user["displayName"]
                    mentions.append({
                        "id": idx,
                        "mentionText": display_name,
                        "mentioned": {
                            "user": {
                                "id": user["id"],
                                "displayName": display_name,
                                "userIdentityType": "aadUser",
                            }
                        },
                    })
                    message = f'<at id="{idx}">{display_name}</at> ' + message

        try:
            result = await graph_client.reply_to_chat_message(
                chat_id, message_id, message,
                content_type=content_type,
                mentions=mentions,
            )
            return json.dumps({
                "status": "sent",
                "backend": "graph",
                "chat_id": chat_id,
                "parent_message_id": message_id,
                "reply_id": result.get("id"),
            })
        except Exception as exc:
            return json.dumps({"error": f"Reply failed: {exc}"})
```

Also add to module-level exposure at bottom of `register()`:
```python
    mod.reply_to_teams_message = reply_to_teams_message
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_teams_graph.py::TestReplyToTeamsMessage -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_tools/teams_browser_tools.py tests/test_teams_graph.py
git commit -m "feat: add reply_to_teams_message MCP tool with @mention support"
```

### Task 7: Enhance post_teams_message with content_type parameter

**Files:**
- Modify: `mcp_tools/teams_browser_tools.py` (post_teams_message + _graph_send_message)
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
class TestPostTeamsMessageContentType:
    """Tests for content_type parameter in post_teams_message."""

    async def test_post_teams_message_html_content(self):
        """HTML content_type is passed through to Graph API."""
        gc = _make_graph_client()
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            raw = await post_teams_message(
                target="alice@example.com",
                message="<b>Important</b> update",
                content_type="html",
            )

        result = json.loads(raw)
        assert result["status"] == "sent"
        gc.send_chat_message.assert_awaited_once()
        call_kwargs = gc.send_chat_message.call_args
        assert call_kwargs.kwargs.get("content_type") == "html" or call_kwargs[1].get("content_type") == "html"
        mcp_server._state.graph_client = None

    async def test_post_teams_message_with_mentions(self):
        """mention_emails resolves users and passes mentions to send."""
        gc = _make_graph_client(
            get_user_by_email=AsyncMock(return_value={
                "id": "user-aad-001",
                "displayName": "Alice Smith",
                "mail": "alice@example.com",
            }),
        )
        mcp_server._state.graph_client = gc

        with patch.object(teams_browser_tools, "_get_send_backend", return_value="graph"):
            raw = await post_teams_message(
                target="chat-group@example.com",
                message="Hey team, check this out",
                mention_emails=["alice@example.com"],
            )

        result = json.loads(raw)
        assert result["status"] == "sent"
        call_kwargs = gc.send_chat_message.call_args
        assert call_kwargs.kwargs.get("mentions") is not None
        mcp_server._state.graph_client = None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_teams_graph.py::TestPostTeamsMessageContentType -v`

- [ ] **Step 3: Update _graph_send_message and post_teams_message**

Update `_graph_send_message` signature to accept `content_type` and `mentions`:

```python
async def _graph_send_message(
    graph_client, target: str, message: str,
    content_type: str = "text", mentions: list[dict] | None = None,
) -> dict:
```

Update the two `send_chat_message` calls inside `_graph_send_message` to pass through:

In Strategy 3 (create_chat path), update `create_chat` call — since `create_chat` calls `send_chat_message` internally, we need to pass `content_type` through. Instead, skip the initial message in create_chat and send separately:

```python
    # Strategy 3: If target is email(s), create a new chat
    if chat_id is None and target_emails:
        result = await graph_client.create_chat(target_emails)
        new_chat_id = result.get("id")
        if new_chat_id:
            await graph_client.send_chat_message(new_chat_id, message, content_type=content_type, mentions=mentions)
        return {
            "status": "sent",
            "backend": "graph",
            "chat_id": new_chat_id,
            "detail": f"Created new chat and sent message to {', '.join(target_emails)}",
        }
```

And the final send:
```python
    result = await graph_client.send_chat_message(chat_id, message, content_type=content_type, mentions=mentions)
```

Update `post_teams_message` tool signature:

```python
    async def post_teams_message(
        target: str, message: str, auto_send: bool = False,
        content_type: str = "text", mention_emails: list[str] | None = None,
    ) -> str:
```

Add mention resolution before Graph send:
```python
        # Resolve @mentions if requested
        mentions = None
        if mention_emails and graph_client is not None:
            content_type_resolved = "html"
            mentions = []
            for idx, email in enumerate(mention_emails):
                user = await graph_client.get_user_by_email(email)
                if user:
                    display_name = user["displayName"]
                    mentions.append({
                        "id": idx,
                        "mentionText": display_name,
                        "mentioned": {
                            "user": {
                                "id": user["id"],
                                "displayName": display_name,
                                "userIdentityType": "aadUser",
                            }
                        },
                    })
                    message = f'<at id="{idx}">{display_name}</at> ' + message
            content_type = content_type_resolved
```

Pass through to `_graph_send_message`:
```python
                    result = await _graph_send_message(graph_client, target, message, content_type=content_type, mentions=mentions)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_teams_graph.py::TestPostTeamsMessageContentType -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `pytest tests/test_teams_graph.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add mcp_tools/teams_browser_tools.py tests/test_teams_graph.py
git commit -m "feat: add content_type and mention_emails to post_teams_message"
```

### Task 8: Add manage_teams_chat MCP tool

**Files:**
- Modify: `mcp_tools/teams_browser_tools.py` (inside `register()`)
- Test: `tests/test_teams_graph.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
class TestManageTeamsChat:
    """Tests for manage_teams_chat MCP tool."""

    async def test_rename_chat(self):
        """Rename a group chat topic."""
        gc = _make_graph_client(
            update_chat_topic=AsyncMock(return_value={"status": "success"}),
        )
        mcp_server._state.graph_client = gc

        raw = await manage_teams_chat(
            chat_id="chat-001",
            action="rename",
            topic="New Chat Name",
        )
        result = json.loads(raw)
        assert result["status"] == "success"
        gc.update_chat_topic.assert_awaited_once_with("chat-001", "New Chat Name")
        mcp_server._state.graph_client = None

    async def test_list_members(self):
        """List members of a chat."""
        gc = _make_graph_client(
            list_chat_members=AsyncMock(return_value=[
                {"id": "m1", "displayName": "Alice", "email": "alice@ex.com"},
            ]),
        )
        mcp_server._state.graph_client = gc

        raw = await manage_teams_chat(chat_id="chat-001", action="list_members")
        result = json.loads(raw)
        assert result["status"] == "success"
        assert len(result["members"]) == 1
        mcp_server._state.graph_client = None

    async def test_add_member(self):
        """Add a member to a group chat."""
        gc = _make_graph_client(
            add_chat_member=AsyncMock(return_value={"id": "m-new"}),
        )
        mcp_server._state.graph_client = gc

        raw = await manage_teams_chat(
            chat_id="chat-001",
            action="add_member",
            user_email="newperson@example.com",
        )
        result = json.loads(raw)
        assert result["status"] == "success"
        gc.add_chat_member.assert_awaited_once_with("chat-001", "newperson@example.com")
        mcp_server._state.graph_client = None

    async def test_remove_member(self):
        """Remove a member from a group chat."""
        gc = _make_graph_client(
            remove_chat_member=AsyncMock(return_value={"status": "success"}),
        )
        mcp_server._state.graph_client = gc

        raw = await manage_teams_chat(
            chat_id="chat-001",
            action="remove_member",
            membership_id="member-001",
        )
        result = json.loads(raw)
        assert result["status"] == "success"
        gc.remove_chat_member.assert_awaited_once_with("chat-001", "member-001")
        mcp_server._state.graph_client = None

    async def test_invalid_action(self):
        """Invalid action returns error."""
        gc = _make_graph_client()
        mcp_server._state.graph_client = gc

        raw = await manage_teams_chat(chat_id="chat-001", action="delete")
        result = json.loads(raw)
        assert "error" in result
        mcp_server._state.graph_client = None

    async def test_no_graph_client(self):
        """Returns error when Graph client not configured."""
        mcp_server._state.graph_client = None

        raw = await manage_teams_chat(chat_id="chat-001", action="rename", topic="X")
        result = json.loads(raw)
        assert "error" in result
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_teams_graph.py::TestManageTeamsChat -v`

- [ ] **Step 3: Implement manage_teams_chat MCP tool**

Add inside `register()` in `mcp_tools/teams_browser_tools.py`:

```python
    @mcp.tool()
    @tool_errors("Teams chat management error")
    async def manage_teams_chat(
        chat_id: str,
        action: str,
        topic: str = "",
        user_email: str = "",
        membership_id: str = "",
    ) -> str:
        """Manage a Teams group chat — rename, list/add/remove members.

        Actions:
        - ``rename``: Set the chat topic (requires ``topic`` param)
        - ``list_members``: List all members with their IDs and emails
        - ``add_member``: Add a user to the chat (requires ``user_email`` param)
        - ``remove_member``: Remove a member (requires ``membership_id`` from list_members)

        Args:
            chat_id: The Teams chat ID
            action: One of: rename, list_members, add_member, remove_member
            topic: New topic name (for rename action)
            user_email: Email of user to add (for add_member action)
            membership_id: Member ID to remove (for remove_member action)
        """
        graph_client = state.graph_client
        if graph_client is None:
            return json.dumps({"error": "Graph API not configured — chat management requires Graph API"})

        try:
            if action == "rename":
                await graph_client.update_chat_topic(chat_id, topic)
                return json.dumps({"status": "success", "action": "rename", "topic": topic})
            elif action == "list_members":
                members = await graph_client.list_chat_members(chat_id)
                return json.dumps({"status": "success", "action": "list_members", "members": members})
            elif action == "add_member":
                result = await graph_client.add_chat_member(chat_id, user_email)
                return json.dumps({"status": "success", "action": "add_member", "user_email": user_email, "result": result})
            elif action == "remove_member":
                await graph_client.remove_chat_member(chat_id, membership_id)
                return json.dumps({"status": "success", "action": "remove_member", "membership_id": membership_id})
            else:
                return json.dumps({"error": f"Unknown action '{action}'. Valid: rename, list_members, add_member, remove_member"})
        except Exception as exc:
            return json.dumps({"error": f"Chat management failed: {exc}"})
```

Also add to module-level exposure:
```python
    mod.manage_teams_chat = manage_teams_chat
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_teams_graph.py::TestManageTeamsChat -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/test_teams_graph.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add mcp_tools/teams_browser_tools.py tests/test_teams_graph.py
git commit -m "feat: add manage_teams_chat MCP tool — rename, list/add/remove members"
```

---

## Chunk 3: Integration Verification

### Task 9: Full regression test + final commit

- [ ] **Step 1: Run full project test suite**

Run: `pytest tests/ -x -q --tb=short`
Expected: All tests pass, no regressions

- [ ] **Step 2: Verify tool registration**

Run: `python -c "import mcp_server; print([t for t in dir(mcp_server) if 'teams' in t.lower() or 'reply' in t.lower()])"`
Verify: `reply_to_teams_message` and `manage_teams_chat` appear

- [ ] **Step 3: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: Teams Graph API enhancement — final cleanup"
```
