# Chunk Audit: Teams Send/Read Routing

**Files audited:**
- `/Users/jasricha/Documents/GitHub/chief_of_staff/mcp_tools/teams_browser_tools.py`
- `/Users/jasricha/Documents/GitHub/chief_of_staff/tests/test_teams_graph.py`

**Audit date:** 2026-03-12

---

## Dimension Scores

| Dimension       | Score | Notes |
|-----------------|-------|-------|
| Correctness     | 3/5   | Routing works, but display-name resolution has ambiguity bugs and fallback branches are logically identical |
| Reliability     | 3/5   | Fallback chain exists, but read path has O(N) API call scaling and no short-circuit for fatal errors |
| Security        | 3/5   | No message content sanitization for Graph HTML injection; display-name matching enables misdirection |
| Testability     | 4/5   | Good coverage of happy paths and fallback triggers; gaps in ambiguity, scaling, and dual-failure scenarios |
| Maintainability | 3/5   | Deprecated `_get_backend()` still in use; identical exception branches are confusing dead code |

**Overall: 3.2/5**

---

## Findings

### F-01: Identical if/else exception branches in `post_teams_message`
- **File:** `teams_browser_tools.py`, lines 318-330
- **Severity:** Medium
- **Status:** Confirmed
- **Issue:** The `except Exception as exc` block checks `isinstance(exc, _graph_exceptions)` in the `if` branch and has an `else` branch, but both branches execute the exact same log statement with the exact same format string and arguments. This is a copy-paste artifact. The likely intent was to differentiate behavior: known transient/auth errors should fall back silently, but unexpected exceptions (e.g., `ValueError`, `KeyError`) should either re-raise or log at a higher severity instead of silently falling through to the browser path.
- **Impact:** Any exception whatsoever (including programming bugs like `TypeError` or `AttributeError` inside `_graph_send_message`) silently falls back to the browser, masking real bugs. A developer reading this code cannot determine whether the identical branches are intentional.
- **Fix:** For the `else` branch, either re-raise unexpected exceptions or log at `ERROR` level with `exc_info=True` to distinguish real bugs from expected transient failures.

### F-02: Identical if/else exception branches in `read_teams_messages`
- **File:** `teams_browser_tools.py`, lines 471-483
- **Severity:** Medium
- **Status:** Confirmed
- **Issue:** Same pattern as F-01. Both branches of the `isinstance` check log the identical message. Unexpected exceptions (programming errors) silently fall through to the m365-bridge, hiding bugs.
- **Fix:** Same as F-01.

### F-03: Display-name target resolution matches first substring hit
- **File:** `teams_browser_tools.py`, lines 156-174 (`_graph_send_message`)
- **Severity:** High
- **Status:** Confirmed
- **Issue:** The display-name search uses `target_lower in display` (substring containment) and returns the first match. This means:
  - Target `"Al"` matches `"Alice Smith"`, `"Allan Jones"`, and `"Albert Brown"` — message goes to whichever chat appears first in the API response.
  - Target `"Smith"` matches any chat with any member whose name contains "Smith".
  - A chat topic containing the target string is matched before member names, which may be unexpected (e.g., target `"Project Alpha"` matches a channel named "Project Alpha Review" even if the intent was a person).
  - There is no disambiguation: no warning, no multiple-match detection, no confidence threshold.
- **Impact:** Messages can be silently delivered to the wrong recipient. This is the highest-risk finding for a messaging tool.
- **Fix:** (1) Prefer exact match over substring. (2) If multiple chats match, return an error listing the ambiguous matches and ask the user to clarify. (3) Consider requiring email for programmatic sends.

### F-04: `read_teams_messages` Graph path makes O(N) sequential API calls
- **File:** `teams_browser_tools.py`, lines 424-464
- **Severity:** Medium
- **Status:** Confirmed
- **Issue:** The read path calls `graph_client.list_chats(limit=50)` then iterates every chat, calling `graph_client.get_chat_messages()` for each one. With 50 chats, this is 51 sequential HTTP requests (1 list + 50 message fetches). Graph API rate limits (per-app, per-user) are typically ~10K requests per 10 minutes, but latency alone makes this slow: 50 requests at ~200ms each = ~10 seconds.
- **Impact:** Slow response times for users with many chats. No parallelism. The `limit` parameter only limits total messages returned, not API calls made -- if the user asks for 5 messages but they all happen to be in the last chat, 49 chats are queried for nothing.
- **Fix:** (1) Use `asyncio.gather` to fetch messages from multiple chats concurrently. (2) If `query` is provided, use the Graph `/me/chats/getAllMessages` or Teams message search endpoint instead of client-side filtering. (3) Consider a "recently active chats" sort to front-load likely hits.

### F-05: `_get_backend()` references deprecated `TEAMS_POSTER_BACKEND`
- **File:** `teams_browser_tools.py`, lines 44-46
- **Severity:** Low
- **Status:** Confirmed
- **Issue:** `_get_backend()` imports `TEAMS_POSTER_BACKEND` from config. Config line 178 shows `TEAMS_POSTER_BACKEND` defaults to `"agent-browser"` regardless of Graph configuration, while `TEAMS_SEND_BACKEND` (line 170) defaults to `"graph"` when Graph is enabled. `_get_backend()` is still used by `_get_poster()` (line 86), `open_teams_browser` (line 258), and `close_teams_browser` (line 380). This creates a split: `post_teams_message` uses `_get_send_backend()` to decide Graph vs browser, but when it falls back to browser, `_get_poster()` uses `_get_backend()` (the deprecated one) to decide which browser implementation. If someone sets `TEAMS_SEND_BACKEND=agent-browser` expecting agent-browser everywhere, but `TEAMS_POSTER_BACKEND` defaults to `"agent-browser"`, it happens to work -- but the indirection is confusing and fragile.
- **Impact:** Low immediate risk (defaults align), but a maintenance trap. The two config paths will diverge if either default changes.
- **Fix:** Migrate `_get_poster()`, `open_teams_browser`, and `close_teams_browser` to derive browser choice from `TEAMS_SEND_BACKEND` (falling back to `TEAMS_POSTER_BACKEND` for backward compat only). Then deprecate `_get_backend()`.

### F-06: No sanitization of message content sent via Graph API
- **File:** `teams_browser_tools.py`, line 195; `connectors/graph_client.py`, line 480
- **Severity:** Medium
- **Status:** Confirmed
- **Issue:** `send_chat_message` sends `contentType: "text"` with the raw message string. Graph API with `contentType: "text"` does treat it as plain text (no HTML rendering), so XSS is not directly exploitable. However, `create_chat` on line 178 also sends the message through `send_chat_message`, and if `contentType` is ever changed to `"html"` (e.g., for rich formatting), there is no sanitization layer to prevent HTML/script injection.
- **Impact:** Low today (`contentType: "text"` is safe). Medium if the content type is ever changed without adding sanitization.
- **Fix:** Add a comment documenting the `contentType: "text"` safety assumption, or add a sanitization pass that strips HTML tags regardless of content type.

### F-07: `find_chat_by_members` uses `issubset` -- matches chats with extra members
- **File:** `connectors/graph_client.py`, lines 498-499
- **Severity:** Medium
- **Status:** Confirmed
- **Issue:** `target.issubset(chat_emails)` means searching for `alice@example.com` matches a 1:1 chat with Alice, a group chat with Alice+Bob+Charlie, and a 50-person team channel that includes Alice. The first matching chat is returned. For `_graph_send_message`, this means a message intended for Alice 1:1 could land in a group chat.
- **Impact:** Message delivered to unintended audience. Combined with F-03 (first-match-wins), this compounds the misdirection risk.
- **Fix:** For single-email targets, prefer `oneOnOne` chat type. Sort matches by member count ascending (fewer members = more specific). Or require exact member set match for non-group sends.

### F-08: ISO datetime comparison is string-based
- **File:** `teams_browser_tools.py`, line 445
- **Severity:** Low
- **Status:** Confirmed
- **Issue:** `if after_datetime and timestamp and timestamp < after_datetime` performs lexicographic string comparison. This works correctly for ISO 8601 timestamps only when both strings use the same format (e.g., both have `Z` suffix, same precision). If Graph returns `2026-03-12T10:00:00.0000000Z` and the user passes `2026-03-12T10:00:00Z`, the comparison may be incorrect because `.0000000Z` < `Z` lexicographically (`.` < `Z` in ASCII).
- **Impact:** Edge case: some messages that should be filtered might slip through or be incorrectly excluded.
- **Fix:** Parse both timestamps with `datetime.fromisoformat()` before comparing, or normalize to a common format.

### F-09: Test cleanup relies on manual state reset
- **File:** `tests/test_teams_graph.py`, throughout (e.g., lines 80, 101, 124, 161, 188, etc.)
- **Severity:** Low
- **Status:** Confirmed
- **Issue:** Every test manually sets `mcp_server._state.graph_client = None` and `mcp_server._state.m365_bridge = None` at the end. If a test fails before reaching the cleanup line, subsequent tests may see stale state. This is a classic fixture anti-pattern.
- **Fix:** Use a pytest fixture with `yield` or `addCleanup` to ensure state is always reset, even on failure.

### F-10: Missing test -- both Graph and browser/bridge fail
- **File:** `tests/test_teams_graph.py`
- **Severity:** Medium
- **Status:** Suspected gap
- **Issue:** There is no test for the scenario where Graph fails AND the browser fallback also fails (or m365-bridge is None when Graph read fails). The current `test_read_teams_messages_no_bridge_returns_error` tests bridge=None with backend=m365-bridge, but does not test the Graph-fails-then-bridge-also-fails path. Similarly, no test for `post_teams_message` where Graph fails AND the browser poster raises an exception.
- **Impact:** Unknown behavior when both backends fail. The `@tool_errors` decorator likely catches and wraps the exception, but this is untested.
- **Fix:** Add tests for: (1) Graph send fails + browser poster raises. (2) Graph read fails + bridge is None (with backend="graph"). (3) Graph read fails + bridge._invoke_structured returns error.

### F-11: Missing test -- display-name ambiguity in `_graph_send_message`
- **File:** `tests/test_teams_graph.py`
- **Severity:** Medium
- **Status:** Confirmed gap
- **Issue:** No test verifies what happens when multiple chats match a display name. The test `test_post_teams_message_graph_display_name_match` uses a single chat, so first-match behavior is never exercised with ambiguous input.
- **Fix:** Add a test with multiple chats where the target name substring-matches members in more than one chat, and verify which chat wins (or that ambiguity is reported).

---

## Summary of Recommended Actions

| Priority | Action |
|----------|--------|
| **High** | F-03, F-07: Add disambiguation to display-name and member-based chat resolution. Prefer exact match, detect multiple matches, prefer `oneOnOne` chat type for single recipients. |
| **Medium** | F-01, F-02: Differentiate the identical exception branches -- re-raise or escalate unexpected errors instead of silently falling back. |
| **Medium** | F-04: Parallelize chat message fetching or use server-side search endpoint. |
| **Medium** | F-10, F-11: Add missing test scenarios for dual-backend failure and ambiguous target resolution. |
| **Low** | F-05: Consolidate deprecated `_get_backend()` into `_get_send_backend()`. |
| **Low** | F-08: Use proper datetime parsing for timestamp comparison. |
| **Low** | F-09: Convert manual test cleanup to pytest fixtures. |
| **Low** | F-06: Document `contentType: "text"` safety assumption. |
