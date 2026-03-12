# Chunk Audit: Email Send/Reply Routing

**Files audited:**
- `/Users/jasricha/Documents/GitHub/chief_of_staff/mcp_tools/mail_tools.py`
- `/Users/jasricha/Documents/GitHub/chief_of_staff/tests/test_mail_graph.py`

**Supporting files reviewed:**
- `/Users/jasricha/Documents/GitHub/chief_of_staff/connectors/graph_client.py` (lines 420-460, 541-577)
- `/Users/jasricha/Documents/GitHub/chief_of_staff/utils/text.py`

---

## Dimension Scores

| Dimension       | Score | Notes |
|----------------|-------|-------|
| Correctness    | 2/5   | BCC silently dropped on Graph send; reply_all/cc/bcc dropped on Graph reply |
| Reliability    | 2/5   | GraphAPIError and httpx exceptions escape unhandled, killing both paths |
| Security       | 4/5   | confirm_send gate is solid; no email validation is a minor gap |
| Testability    | 3/5   | Good coverage of happy path and fallback; missing tests for critical gaps |
| Maintainability| 3/5   | Clean structure; inline `import config` is slightly unusual but functional |

---

## Findings

### F1. `send_email` Graph path silently drops BCC recipients

- **File:** `mcp_tools/mail_tools.py`, line 232-238
- **Severity:** HIGH
- **Status:** CONFIRMED
- **Details:** `graph_client.send_mail()` is called with `to`, `subject`, `body`, `cc`, and `content_type` but `bcc` is never passed. The `bcc_list` computed on line 225 is unused in the Graph branch. `GraphClient.send_mail()` (graph_client.py:541) has no `bcc` parameter either, so the underlying API method also needs updating.
- **Impact:** When `EMAIL_SEND_BACKEND=graph`, any BCC recipients are silently discarded. The email sends successfully with no error or warning — the caller has no indication BCC was lost.
- **Fix:** Add `bcc` parameter to `GraphClient.send_mail()` and pass `bcc_list` from `send_email`. The Graph API supports `bccRecipients` on the message payload.

### F2. `reply_to_email` Graph path drops reply_all, cc, and bcc

- **File:** `mcp_tools/mail_tools.py`, lines 182-185
- **Severity:** HIGH
- **Status:** CONFIRMED
- **Details:** The Graph reply call only passes `message_id` and `body`. The `reply_all`, `cc_list`, and `bcc_list` parameters computed on lines 148-175 are not forwarded. `GraphClient.reply_mail()` (graph_client.py:571) only accepts `message_id` and `body`.
- **Impact:** When using Graph backend: (1) `reply_all=True` is ignored — reply always goes to sender only; (2) additional CC recipients are lost; (3) BCC recipients are lost. The Graph API supports `/reply` vs `/replyAll` endpoints and accepts `toRecipients`/`ccRecipients` in the reply body.
- **Fix:** Update `GraphClient.reply_mail()` to accept `reply_all`, `cc`, `bcc` and use the `/replyAll` endpoint when `reply_all=True`. Pass all three from `reply_to_email`.

### F3. `GraphAPIError` (non-transient) is not caught in fallback handler

- **File:** `mcp_tools/mail_tools.py`, lines 187, 240
- **Severity:** HIGH
- **Status:** CONFIRMED
- **Details:** The fallback `except` clause catches `(GraphTransientError, GraphAuthError)` but not the base `GraphAPIError`. The `_request` method in `graph_client.py` raises plain `GraphAPIError` on 4xx errors other than 401 (line 454). For example, a 400 Bad Request (malformed recipient) or 403 Forbidden raises `GraphAPIError`, which propagates unhandled through the `@tool_errors` decorator. Since `GraphAPIError` is not in `_MAIL_EXPECTED`, `@tool_errors` will catch it as an unexpected error.
- **Impact:** A 400/403/404 from Graph API will not fall back to Apple Mail. Instead it will be caught by `@tool_errors` and returned as a generic error. This is arguably correct (non-transient errors shouldn't retry on a different backend) but the behavior is inconsistent with the stated fallback design and is undocumented.
- **Recommendation:** Either (a) catch `GraphAPIError` (the base) to fall back on all Graph failures, or (b) document that only transient/auth errors trigger fallback and non-transient 4xx errors are terminal. Option (b) is likely correct — a 400 from Graph would also fail on Apple Mail.

### F4. Uncaught `httpx` exceptions bypass fallback entirely

- **File:** `mcp_tools/mail_tools.py`, lines 187, 240
- **Severity:** MEDIUM
- **Status:** CONFIRMED
- **Details:** If the Graph client raises `httpx.ConnectError`, `httpx.TimeoutException`, or any other `httpx` exception (e.g., network down, DNS failure), these are not `GraphTransientError` subclasses. They propagate up without triggering Apple Mail fallback. The `httpx.AsyncClient` timeout is 30s (graph_client.py:134), so a timeout raises `httpx.ReadTimeout`.
- **Impact:** Network-level failures to Graph API skip the fallback entirely. Since `httpx` errors are not in `_MAIL_EXPECTED`, `@tool_errors` will catch them as unexpected.
- **Fix:** Add `Exception` (or at minimum `httpx.HTTPError, OSError, ConnectionError`) to the except clause, or wrap the Graph call in a broader try/except that catches all exceptions and falls back.

### F5. Import guard `GraphTransientError is not None` conflates import availability with runtime readiness

- **File:** `mcp_tools/mail_tools.py`, lines 16-20, 180, 230
- **Severity:** MEDIUM
- **Status:** CONFIRMED
- **Details:** At module top (line 16-20), if `from connectors.graph_client import ...` fails, both sentinel classes are set to `None`. The routing guard `GraphTransientError is not None` then prevents entering the Graph branch. This is a reasonable import guard. However, the check conflates "could we import the exception classes" with "is Graph available". If `graph_client.py` is importable but `httpx` is not installed at runtime, `GraphClient.__init__` raises `ImportError` — so `state.graph_client` would be `None` and the `state.graph_client is not None` check would already cover it. The `GraphTransientError is not None` check is redundant when `state.graph_client is not None`.
- **Impact:** No functional bug, but confusing. A reader might wonder what scenario has `graph_client` present but `GraphTransientError` missing.
- **Fix:** Remove the `GraphTransientError is not None` check; the `state.graph_client is not None` check is sufficient. If you keep the import guard, add a comment explaining the edge case it protects against.

### F6. No email address validation

- **File:** `mcp_tools/mail_tools.py`, lines 223-225 (send_email), 174-175 (reply_to_email)
- **Severity:** LOW
- **Status:** CONFIRMED
- **Details:** `split_addresses` simply splits on commas and strips whitespace. No validation that results look like email addresses. Values like `"not an email"`, `""`, or `"  ,  ,  "` are passed through.
- **Impact:** Invalid addresses will fail at the backend (Graph returns 400, Apple Mail may silently fail or error). The error message will come from the backend, not from the tool. For `send_email`, `to_list` could be `[]` if the `to` string is all whitespace/commas — this would send to nobody.
- **Fix:** Add a basic validation check (at minimum, non-empty list for `to`) and optionally a regex check for `@` presence.

### F7. Operator precedence issue in `cc_list`/`bcc_list` ternary expressions

- **File:** `mcp_tools/mail_tools.py`, lines 174-175, 224-225
- **Severity:** LOW
- **Status:** CONFIRMED (no current bug, but fragile)
- **Details:** The expression `_split_addresses(cc) or None if cc else None` parses as `(_split_addresses(cc) or None) if cc else None` due to Python operator precedence. This works correctly: if `cc` is truthy, split it and return the list (or None if empty). But the `or None` is redundant — `_split_addresses` returns `[]` for empty input, and `[] or None` yields `None`. The expression is confusing and would break if someone refactored it to `_split_addresses(cc) or None if cc else []`, for example.
- **Fix:** Simplify to `_split_addresses(cc) if cc else None` or even `_split_addresses(cc) or None`.

---

## Test Coverage Gaps

### T1. No test for BCC on Graph path

- **File:** `tests/test_mail_graph.py`
- **Details:** `TestSendEmailGraphBackend.test_send_email_graph_with_cc` tests CC forwarding but there is no equivalent test for BCC. This gap masks finding F1.

### T2. No test for reply_all/cc/bcc on Graph reply path

- **File:** `tests/test_mail_graph.py`
- **Details:** `TestReplyEmailGraphBackend.test_reply_email_graph_backend` only tests basic reply. No test verifies `reply_all=True`, `cc`, or `bcc` behavior on Graph path. This gap masks finding F2.

### T3. No test for `GraphAPIError` (non-transient 4xx) behavior

- **File:** `tests/test_mail_graph.py`
- **Details:** Tests cover `GraphTransientError` and `GraphAuthError` fallback, but no test covers what happens when `GraphAPIError` (e.g., 400 Bad Request) is raised. This gap masks finding F3.

### T4. No test for network-level exceptions (httpx errors)

- **File:** `tests/test_mail_graph.py`
- **Details:** No test for `httpx.ConnectError` or `httpx.TimeoutException` during Graph calls.

### T5. No test for empty/invalid `to` addresses

- **File:** `tests/test_mail_graph.py`
- **Details:** No test passes empty strings, whitespace-only, or malformed addresses to `send_email`.

### T6. No test for `html_body` on Graph reply path

- **File:** `tests/test_mail_graph.py`
- **Details:** `reply_to_email` passes `html_body or body` to Graph, but no test verifies HTML is preferred when provided.

---

## Summary

The confirm_send safety gate is well-implemented and correctly positioned before any backend routing. The fallback architecture (Graph -> Apple Mail) is structurally sound.

The two critical gaps are **data loss bugs**: BCC is silently dropped on Graph send (F1), and reply_all/cc/bcc are all dropped on Graph reply (F2). Both are confirmed by reading the `GraphClient` method signatures, which simply don't accept these parameters. These are not edge cases — they affect every Graph-routed email that uses BCC or reply-all.

The exception handling gap (F3/F4) means certain failure modes skip the fallback entirely and return opaque errors instead of trying Apple Mail.

**Recommended priority:**
1. F1 + F2 (data loss) — fix `GraphClient` API surface and wire parameters through
2. F4 (reliability) — broaden the except clause to catch network errors
3. F3 (decide and document fallback policy for non-transient errors)
4. F6 (input validation)
5. F5, F7 (code clarity)
