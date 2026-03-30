# Chunk Audit: Teams & Browser

**User-facing feature**: Teams message send/read, web browsing tools
**Risk Level**: Medium
**Files Audited**:
- `browser/__init__.py`
- `browser/ab_navigator.py`
- `browser/ab_poster.py`
- `browser/agent_browser.py`
- `browser/constants.py`
- `browser/manager.py`
- `browser/navigator.py`
- `browser/okta_auth.py`
- `browser/sharepoint_download.py`
- `browser/teams_poster.py`
- `mcp_tools/teams_browser_tools.py`
- `mcp_tools/web_browser_tools.py`

**Status**: Complete

## Purpose (as understood from reading the code)

This chunk implements Teams messaging and web automation via three send backends (Microsoft Graph API, agent-browser CLI, Playwright CDP) and a SharePoint download capability. It provides a unified MCP tool layer (`teams_browser_tools.py`, `web_browser_tools.py`) over two parallel navigation stacks: `TeamsNavigator` (Playwright/CSS selectors) and `ABNavigator` (agent-browser/accessibility-tree snapshots), selected at runtime via `TEAMS_SEND_BACKEND`.

## Runtime Probe Results

- **Tests found**: Yes — 12 test files covering this chunk
- **Tests run**: 180 passed, 0 failed (39.87s)
- **Import/load check**: All 12 files compile cleanly (`py_compile` OK)
- **Type check**: Not run (mypy not in venv)
- **Edge case probes**:
  - `_make_download_url("")` → `?action=download` (empty URL: produces a dangling relative URL with no base — benign since the caller would fail before reaching this with a valid manager)
  - `_extract_site_base("")` → `None` (correctly returns None for empty input)
  - `TeamsNavigator._match_chat_item("", ["Alice"])` → score=0 (correctly handles empty item text)
  - `_name_fallbacks` correctly strips middle names and returns first-name-only fallbacks
  - `_make_download_url` correctly prefers the `download.aspx?UniqueId=` endpoint when GUID is present
- **Key observation**: `RuntimeError` is included in `_TIMEOUT_ERRORS` causing any RuntimeError from download helpers (including "Downloaded file is empty") to trigger the strategy-2 fallback rather than hard-failing. This is semantically imprecise but functionally harmless.

## Dimension Assessments

### Implemented

All functions and classes described in the CLAUDE.md module map are present with real logic. There are no stubs, TODOs, or NotImplementedError markers across the entire chunk. Both Playwright and agent-browser backends are fully implemented. The Graph send path (`_graph_resolve_chat`, `_graph_send_to_chat`) is complete with five resolution strategies. The SharePoint download has two working strategies (direct URL and Excel Online UI via CDP). Web browser tools cover all 11 documented operations. Nothing is unimplemented.

### Correct

The happy paths work and the test suite confirms them. Several subtle issues were found:

1. **`manager.launch()` blocks the async event loop** (`manager.py:127-134`). This synchronous method calls `time.sleep(0.5)` and `is_alive()` (which calls `urllib.request.urlopen(timeout=2)`) up to 30 times — worst case 75 seconds of blocking. It is called directly from the async `open_teams_browser` tool handler at `teams_browser_tools.py:446`. The same applies to `manager.close()` (`manager.py:178-192`). These synchronous blocking operations should be `asyncio.get_event_loop().run_in_executor(None, ...)` calls.

2. **`_try_ui_download` leaves the downloaded file in `~/Downloads`** (`sharepoint_download.py:277`). The source file is copied to `destination` but never deleted. Over time this accumulates Excel files in `~/Downloads` with no cleanup mechanism.

3. **`read_teams_messages` fetches all messages before respecting the `limit`** (`teams_browser_tools.py:731-733`). Up to 50 chats × 25 messages = 1,250 message objects are fully fetched via `asyncio.gather()`, then filtered and truncated to `limit`. There is an early-exit check (`if len(messages) >= limit: break`) during the post-processing loop but not during the parallel fetch phase. A query with `limit=5` still issues 50 concurrent Graph API calls and processes up to 1,250 messages.

4. **`_cdp_send` loop (`sharepoint_download.py:168-171`) silently drains CDP push events**. The `while True` loop reads WebSocket messages until it finds one matching `current_id`. CDP sessions emit unsolicited events (Runtime.executionContextCreated, etc.). Each `ws.recv()` has a 30-second individual timeout, so if many events arrive before the response, they are drained correctly but the total wait could approach N_events × 30s in a pathological session. In practice the CDP session here is quiet, making this a low-probability issue.

5. **`_pending_graph_message` stores a live `graph_client` reference** (`teams_browser_tools.py:541-547`). This module-level global is not concurrency-safe: if two `post_teams_message` calls race (both in `confirm_required` state), the second call overwrites `_pending_graph_message` before the first is confirmed, losing the first message silently. Given the two-phase confirm flow this is unlikely in normal use, but the confirmation architecture doesn't prevent it.

### Efficient

The `read_teams_messages` over-fetching is the only real efficiency concern (see Correct, point 3). All other patterns are efficient: singleton browser instances, semaphore-limited parallelism for Graph calls, lazy initialization of backends. The `_match_chat_item` scoring loop is O(n × m) in participants and items but both are small. The accessibility-tree parsing in `ABNavigator` iterates snapshot lines twice in some paths, which is acceptable given snapshot sizes.

The sequential resolution of group chat member names (`teams_browser_tools.py:214`) in `_graph_resolve_chat` makes N serial API calls for N names. For a 5-person group chat this is 5 sequential `resolve_user_email` calls. A `gather()` pattern would be faster but the impact is minor for typical group sizes.

### Robust

1. **`manager.launch()` and `manager.close()` are sync-blocking in async context** — same as the correctness finding. The error case (Chromium found but CDP never responds) correctly returns an error dict. SIGTERM/SIGKILL escalation on close is handled.

2. **Okta auth timeout is 300 seconds (5 minutes)**. `_wait_for_okta_auth` polls every 2 seconds with no user notification beyond a single logger.info at the start. If the user doesn't see the browser or doesn't authenticate within 5 minutes, the tool silently times out and returns False. The caller surfaces an error but there is no progress indication during the 5-minute wait.

3. **`_try_ui_download` uses brittle element IDs** (`sharepoint_download.py:205-253`): `FileMenuFlyoutLauncher`, `FileMenuCreateACopySection`, `DownloadACopy`. These are hardcoded data-unique-id values from Excel Online's internal DOM. Microsoft Office Online is updated frequently; these element IDs could break silently. Errors are caught and raised as `RuntimeError` which then triggers the `auth_required` status — a misleading error message.

4. **`RuntimeError` over-inclusion in `_TIMEOUT_ERRORS`** (`sharepoint_download.py:30`). This tuple is used to catch both genuine timeouts and `RuntimeError("Downloaded file is empty")` and `RuntimeError("download.aspx endpoint non-responsive")`. All of these result in the `auth_required` status message even when authentication is not the issue. A user seeing "SharePoint authentication may have expired" when the actual cause was a 0-byte download would take the wrong remediation action.

5. **`web_state_save`/`web_state_load` have path traversal protection** (`web_browser_tools.py:197-205`). The sanitization is correct: checks for `/`, `\\`, `..`, and null bytes, then resolves the path and verifies the parent directory matches. This is properly implemented.

6. **Browser state file (`data/playwright/browser.json`) contains PID** (`manager.py:129`). If the system reboots and the PID is reused by another process, `manager.close()` would SIGTERM the wrong process. The `is_alive()` CDP check mitigates this partially (if the new process doesn't listen on port 9222) but a fully robust implementation would also store the process start time.

### Architecture

1. **Two parallel navigation stacks** (`TeamsNavigator`/Playwright vs `ABNavigator`/agent-browser) implement near-identical logic with different APIs. `search_and_navigate`, `create_group_chat`, `find_compose_box`, `detect_channel_name` all exist in both stacks. This is a deliberate architectural choice (migration from CSS selectors to accessibility tree) but creates significant duplication. The Playwright stack (`navigator.py`, `teams_poster.py`) appears to be the legacy path. A migration note or deprecation comment would clarify lifecycle intent.

2. **`mcp_tools/teams_browser_tools.py` is 938 lines** with four concerns: backend selection, Graph resolution (`_graph_resolve_chat` at 160 lines), Graph message sending, and browser fallback routing. The `_graph_resolve_chat` function alone is 160 lines with 3 nested loops, 5 resolution strategies, and inline type annotation comments. It would benefit from extraction to `connectors/` or a dedicated resolver module.

3. **Module-level singletons** (`_manager`, `_poster`, `_ab`, `_pending_graph_message`) in `teams_browser_tools.py` are created per-module-import, not per-request. The `_poster` singleton is locked to whichever `TEAMS_SEND_BACKEND` was active at the first call — a runtime config change does not reset it. This is by design but undocumented.

4. **`browser/constants.py`** correctly separates CSS selectors and URL patterns from navigation logic. The date of verification (`2026-02-26`) is noted inline which aids maintenance.

5. **`agent_browser.py` is a clean, thin subprocess wrapper** — each method maps 1:1 to a CLI subcommand. Error handling is consistent: `returncode != 0` raises `AgentBrowserError`, `FileNotFoundError` gives an actionable install message. Timeout handling properly kills the subprocess.

## Findings

### 🔴 Critical

- **`browser/manager.py:118-134` (called from `mcp_tools/teams_browser_tools.py:446`)** — `manager.launch()` is a synchronous method with `time.sleep(0.5)` and `urllib.request.urlopen(timeout=2)` called up to 30 times, run directly inside the async `open_teams_browser` MCP tool handler without `run_in_executor`. This blocks the entire asyncio event loop for up to 75 seconds during a slow Chromium startup. The same applies to `manager.close()` called from `close_teams_browser`. Any other concurrent MCP tool calls (memory queries, calendar lookups) are completely blocked during this window.

### 🟡 Warning

- **`browser/sharepoint_download.py:277`** — `_try_ui_download` copies the downloaded file to `destination` via `shutil.copy2()` but never deletes the source file from `~/Downloads`. Each SharePoint download via the UI fallback strategy permanently accumulates a file in the user's Downloads folder with no cleanup. For recurring OKR refreshes (weekly), this creates unbounded growth.

- **`mcp_tools/teams_browser_tools.py:706-788`** — `read_teams_messages` always fetches 50 chats × up to 25 messages = up to 1,250 message objects via `asyncio.gather()` regardless of the `limit` parameter. A `limit=5` call issues the same 50 Graph API requests as `limit=1250`. For users with many Teams chats, this is a significant over-fetch that increases latency and Graph API rate limit consumption. The early-exit only applies to the post-processing aggregation loop.

- **`browser/sharepoint_download.py:28-32`** — `_TIMEOUT_ERRORS = (TimeoutError, RuntimeError)` is overly broad. `RuntimeError("Downloaded file is empty (0 bytes)")` and `RuntimeError("Excel Online iframe not found")` are both caught by this tuple and result in the `auth_required` status message. The misleading error directs users to re-authenticate when the actual issue may be a bad download URL, an empty file, or the spreadsheet not being open. This should separate `PlaywrightTimeoutError`/`asyncio.TimeoutError` from generic `RuntimeError`.

- **`mcp_tools/teams_browser_tools.py:541-547` (module-level `_pending_graph_message`)** — Two concurrent `post_teams_message` calls (both going to the Graph path with `auto_send=False`) will overwrite `_pending_graph_message` — the second prepare silently discards the first staged message. Confirmed by inspecting the single global write at line 541 with no mutex. In an MCP server handling parallel tool calls this is reachable.

- **`browser/manager.py:129`** — The browser state file stores PID without process start time. After a system reboot, a recycled PID could cause `manager.close()` to SIGTERM an unrelated process. The `is_alive()` CDP check partially mitigates this (port 9222 must also be in use) but the combination is not fully safe.

### 🟢 Note

- `browser/sharepoint_download.py:165-170`: `_find_excel_iframe_ws()` uses a synchronous `urlopen` to probe CDP targets. This is only called from `_try_ui_download` which is already outside the `async with manager.connect()` block (after `pw.stop()` is called), so it doesn't block an active Playwright connection. Still, it runs on the asyncio thread; extracting it to `run_in_executor` would be cleaner.

- `browser/navigator.py` and `browser/ab_navigator.py` have 31 hardcoded `asyncio.sleep()` calls with fixed durations (1-3 seconds each). This is inherent to browser automation but makes total navigation time unpredictable (Teams load + search + compose detection can take 15-30+ seconds). Consider exposing a `navigation_timeout` parameter that scales individual sleeps for slow environments.

- `browser/okta_auth.py:43-52`: The 5-minute auth wait has no intermediate progress signal. Adding a periodic log message (e.g., every 30 seconds) would improve observability when auth hangs.

- `mcp_tools/teams_browser_tools.py:120-129`: `_get_poster()` is a singleton locked at first call. If `TEAMS_SEND_BACKEND` is changed at runtime (e.g., via environment variable update), the poster is not re-initialized. A brief comment or `assert` documenting this behavior would prevent confusion.

- `browser/constants.py` is clean, well-organized, and has in-line verification timestamps for selector accuracy. This is good practice for brittle browser selectors.

- `mcp_tools/web_browser_tools.py:197-205`: The `web_state_save`/`web_state_load` path traversal protection is correctly implemented with resolved path comparison.

## Verdict

The chunk is fully implemented with no stubs and a comprehensive 180-test suite, all passing. The primary production risk is `manager.launch()`/`manager.close()` blocking the asyncio event loop for up to 75 seconds synchronously — this would freeze all other concurrent MCP tool calls during browser startup or shutdown. The most actionable secondary issues are the `~/Downloads` accumulation on SharePoint UI downloads (unbounded disk growth for recurring workflows) and the misleading `auth_required` status from overly broad `RuntimeError` catching. The `read_teams_messages` over-fetch (1,250 API calls for a `limit=5` query) is an efficiency concern worth addressing before heavy use. The `_pending_graph_message` race condition is real but low-probability given the confirm-before-send UX pattern.
