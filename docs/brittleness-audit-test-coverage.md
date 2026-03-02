# Brittleness Audit: Test Coverage Gaps

**Date**: 2026-02-27
**Status**: Complete
**Test Suite**: ~1723 tests across 75 files
**Blocks**: Task #6 (Synthesis report)

---

## Executive Summary

The test suite provides strong **unit test coverage** (~1400 unit tests) but critical **integration and failure scenario gaps** allow brittleness to hide. Key findings:

1. **770+ tests are heavily mocked** — mocking hides real failure modes
2. **Zero conftest.py files** — test isolation is per-file, causing duplicate setup and missed shared-state issues
3. **No shell script testing** at all — 8 production shell scripts are untested
4. **Platform integrations only test happy paths** — no permission denial, timeout, or I/O error scenarios
5. **SQLite concurrency configured correctly (WAL mode)** but never tested under concurrent load
6. **Retry logic exists but barely tested** — only 2 files test exponential backoff
7. **Error paths inconsistently tested** — some modules have rigorous error tests, others none
8. **Minimal integration tests** — only `test_e2e_integration.py` (55 tests) exercises end-to-end workflows
9. **No timing/flakiness detection** — only 2 tests use `time.sleep()` explicitly (mocked)

---

## Test Coverage Gap Analysis

### 1. Platform Integrations: All Mocked, No Failure Scenarios

#### Status: HIGH BRITTLENESS RISK

**Files**:
- `apple_mail/mail.py` → `tests/test_apple_mail.py` (55 tests)
- `apple_calendar/eventkit.py` → `tests/test_calendar_eventkit.py` (32 tests)
- `apple_reminders/eventkit.py` → `tests/test_apple_reminders.py` (31 tests)
- `apple_messages/messages.py` → `tests/test_apple_messages.py` (24 tests)

**Problem**: All AppleScript/EventKit calls are mocked via `@patch`. Tests never invoke:
- Real `osascript` commands
- Real SQLite reads (mail, reminders)
- Real permission checks
- Real system failures

**What's Missing**:
- ❌ Permission denied scenarios (`Calendar access denied`)
- ❌ AppleScript parse errors / syntax failures
- ❌ Timeout behavior when Mail.app is hung
- ❌ SQLite lock contentions from concurrent reads
- ❌ Attribute parsing failures (e.g., corrupt calendar entries)

**Example from test_apple_mail.py:85-87**:
```python
@patch("apple_mail.mail._run_applescript")
def test_timeout(self, mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired("osascript", 15)
    result = _run_applescript("some script")  # Mocked timeout, not real
```

Real timeout behavior (5+ seconds lag in Mail.app) is never exercised.

**Likely Failure Mode**: When Mail.app is unresponsive, `_run_applescript` will hang for 15+ seconds (configured in `apple_mail/mail.py:_DEFAULT_TIMEOUT`), but tests never verify this timeout is respected or that the system recovers.

---

### 2. No Shell Script Testing

#### Status: CRITICAL BRITTLENESS RISK

**Untested Scripts** (8 total):
- `scripts/inbox-monitor.sh` — watches ~/Documents/Jarvis/Inbox, no tests
- `scripts/jarvis-backup.sh` — backs up memory.db, no error handling test
- `scripts/communicate.sh` — sends iMessages, no tests for invalid phone numbers
- `scripts/fetch_url.sh` — downloads URLs, no timeout/404 tests
- `scripts/install-plists.sh` — installs launchd configs, no permission tests
- `scripts/organize_documents.sh` — file operations, no disk-full/permission tests
- `hooks/scripts/session-start.sh` — called on session init, no tests
- `hooks/scripts/post-tool-checkpoint-reminder.sh` — background task, no tests

**Missing Tests**:
- ❌ Network failures during `fetch_url.sh`
- ❌ Permission denied when writing to `~/Documents/`
- ❌ Disk full when backing up to `~/Library/`
- ❌ Invalid paths in `organize_documents.sh`
- ❌ Invalid phone numbers in `communicate.sh`
- ❌ Launchd errors during `install-plists.sh`

**Real Risk**: A failed `inbox-monitor.sh` runs silently in cron. Users don't notice inbox stops being processed until a manual inspection. No alerting.

---

### 3. Minimal Integration Tests

#### Status: MEDIUM BRITTLENESS RISK

**File**: `tests/test_e2e_integration.py` (55 tests)

**Coverage**:
- ✓ Webhook ingest → MemoryStore (3 tests)
- ✓ Channel adapter normalization (basic, 3 tests)
- ✓ Proactive suggestion engine (3 tests)
- ✓ Scheduler task dispatch (basic, 3 tests)

**Missing**:
- ❌ Full workflow: Apple Mail → MCP tool → MemoryStore → Agent dispatch
- ❌ Concurrent webhook ingestion + scheduler dispatch
- ❌ Permission changes mid-workflow (e.g., calendar access revoked)
- ❌ Database lock contentions
- ❌ Network recovery (M365 timeout → fallback to Apple Calendar)

**Real Risk**: A complex workflow like "new email → trigger agent → store result → schedule follow-up" is never tested as a single unit. Failures between steps hide until production.

---

### 4. Connectors: Minimal Testing

#### Status: MEDIUM BRITTLENESS RISK

**File**: `connectors/` (4 test files)

**testrouter.py (4 tests)**:
- Only tests routing decisions (happy path)
- No tests for provider unavailability
- No tests for fallback behavior when both providers fail

**test_calendar_unified.py (4 tests)**:
- Only tests successful calendar operations
- No tests for permission denied on one provider but not the other
- No tests for mismatched event ownership across providers

**test_claude_m365_bridge.py**:
- Mock of Claude CLI subprocess
- Never tests real subprocess timeouts or crashes
- No tests for M365 token expiration handling

**Real Risk**: When M365 Bridge times out (configured `timeout_seconds=90`), fallback to Apple Calendar is untested. Users see blank calendars for 90+ seconds.

---

### 5. Scheduler: Partial Coverage

#### Status: MEDIUM BRITTLENESS RISK

**Files**:
- `tests/test_scheduler_engine.py` (80+ tests) — cron parsing well-tested
- `tests/test_daemon.py` (basic tests only)

**What's Tested**:
- ✓ Cron expression parsing (comprehensive)
- ✓ Next-run calculation
- ✓ Task execution for `alert_eval` handler

**What's Missing**:
- ❌ Handler execution when database is locked
- ❌ Graceful recovery when delivery channel (email, iMessage) fails
- ❌ Multiple tasks due at same time (race conditions)
- ❌ Daemon shutdown during active task
- ❌ Out-of-memory during large result serialization

**Real Risk**: If 2 tasks run simultaneously (daemon tick runs 2 due tasks), SQLite WAL may have lock contention. Never tested.

---

### 6. Webhook & Event Dispatcher: Limited Error Testing

#### Status: MEDIUM BRITTLENESS RISK

**Files**:
- `tests/test_webhook_tools.py` (10 tests)
- `tests/test_event_dispatcher.py` (20 tests)

**Missing**:
- ❌ Malformed JSON in webhook payload
- ❌ Webhook event with missing required fields
- ❌ Dispatcher unable to find matching event rule
- ❌ Agent dispatch timeout (configured `DISPATCH_AGENTS_WALL_CLOCK_TIMEOUT=300s`)
- ❌ Disk full when writing webhook results

**Real Risk**: A GitHub webhook arrives with unexpected format. Dispatcher silently fails, event stays in `pending` status forever.

---

### 7. Concurrent Access: Untested

#### Status: MEDIUM BRITTLENESS RISK

**SQLite Configuration** (`memory/store.py:18-20`):
```python
self.conn = sqlite3.connect(str(db_path))
self.conn.execute("PRAGMA journal_mode=WAL")  # ✓ Configured correctly
self.conn.execute("PRAGMA foreign_keys=ON")
```

**But No Tests For**:
- ❌ Multiple MCP tool calls updating same fact simultaneously
- ❌ Scheduler tick + webhook dispatcher both updating same scheduled_task
- ❌ Concurrent agent_memory writes for same agent
- ❌ ChromaDB vector index under high volume (no locks tested)

**Real Risk**: When 2 tools write to the same fact key at the exact same millisecond, the `UNIQUE(category, key)` constraint may cause a silent failure or error that's never caught by tests.

---

### 8. Retry & Error Handling: Sparse

#### Status: MEDIUM BRITTLENESS RISK

**Found Retry Logic**:
- ✓ `mcp_tools/state.py:101-110` — `_retry_on_transient()` with exponential backoff
- ✓ `utils/retry_api_call()` — Anthropic API retries

**But Test Coverage**:
- ❌ `_retry_on_transient` tested only indirectly in `test_memory_store.py`
- ❌ Exponential backoff timing never verified
- ❌ No tests for max retries exceeded scenarios
- ❌ No tests for permanent vs transient errors

**Real Risk**: A transient database error occurs, but test never exercises the `time.sleep(0.5 * (attempt + 1))` backoff. In production, a locked database doesn't retry fast enough, causing timeouts.

---

### 9. Test Isolation Issues

#### Status: MEDIUM BRITTLENESS RISK

**No conftest.py files found** in tests/

**Implications**:
- Each test file defines its own fixtures (e.g., `memory_store`, `calendar_store`)
- Duplicate setup code across 75 test files
- Shared state via module globals is never caught
- Temporary files created in `tmp_path` are never cleaned up centrally

**Example**: `test_apple_mail.py` and `test_mcp_mail.py` both create MailStore but with different isolation.

---

## Brittleness Risk by Module

| Module | Category | Risk | Key Gap | Test File |
|--------|----------|------|---------|-----------|
| `apple_mail/mail.py` | Platform | HIGH | No real osascript/timeout tests | test_apple_mail.py (55 tests, all mocked) |
| `apple_calendar/eventkit.py` | Platform | HIGH | No permission denied tests | test_calendar_eventkit.py (32 tests, all mocked) |
| `apple_messages/messages.py` | Platform | HIGH | No chat.db lock tests | test_apple_messages.py (24 tests) |
| `apple_reminders/eventkit.py` | Platform | HIGH | No real EventKit failures | test_apple_reminders.py (31 tests, mocked) |
| `connectors/claude_m365_bridge.py` | Integration | MEDIUM | No real subprocess timeout | test_claude_m365_bridge.py (mocked) |
| `scheduler/daemon.py` | Core | MEDIUM | No concurrent task tests | test_daemon.py (basic only) |
| `webhook/dispatcher.py` | Integration | MEDIUM | No malformed payload tests | test_event_dispatcher.py (20 tests) |
| `scripts/inbox-monitor.sh` | Shell | CRITICAL | Completely untested | (no test file) |
| `scripts/jarvis-backup.sh` | Shell | CRITICAL | No error recovery | (no test file) |
| `documents/store.py` | Core | MEDIUM | No ChromaDB concurrency | test_document_store.py |
| `memory/store.py` | Core | MEDIUM | No concurrent writes | test_memory_store.py |

---

## Specific Test Deficiencies

### A. Permission/Access Denied Scenarios

**Not Tested**:
- Calendar permission denied (EventKit)
- Mail permission denied (AppleScript)
- Read-only directory when saving
- iMessage permission denied

**Impact**: Feature gracefully fails but tests never verify the error message is user-friendly.

### B. Timeout Scenarios

**Only Mocked**:
- Mail.app timeout (osascript hangs)
- M365 API timeout (90-second threshold)
- EventKit timeout (event store lock)

**Impact**: Actual timeout handling is untested. System may hang instead of recovering.

### C. Network/API Failure Recovery

**Not Tested**:
- M365 Calendar temporarily unavailable → fallback to Apple Calendar
- M365 Email search fails → retry with exponential backoff
- GitHub webhook delivery fails → retry vs permanent failure

**Impact**: Cascading failures when one provider is down.

### D. Concurrent Database Access

**Not Tested**:
- 2 tools updating same memory fact simultaneously
- Scheduler reading while webhook writer updates event_rules
- Agent memory writes from multiple agents at once

**Impact**: Silent data loss or constraint violations.

### E. Shell Script Robustness

**Not Tested**:
- Network failures in `fetch_url.sh`
- Disk full in `jarvis-backup.sh`
- Permission denied in `organize_documents.sh`
- Launchd misconfiguration in `install-plists.sh`

**Impact**: Silent failures in background tasks.

---

## Test Count Summary

| Category | Count | Notes |
|----------|-------|-------|
| Total Tests | ~1723 | Per pytest --co |
| Unit Tests | ~1400 | Happy path + basic error cases |
| Integration Tests | ~55 | E2E workflow tests only |
| Mocked Tests | ~770 | Platform, API, subprocess calls |
| Shell Script Tests | 0 | CRITICAL GAP |
| Concurrent Access Tests | 0 | MEDIUM GAP |
| Timeout/Failure Tests | ~30 | Only platform-level; no end-to-end |

---

## Recommendations (Prioritized)

### TIER 1: Critical (Before Production Release)

1. **Add shell script testing** (`scripts/`, `hooks/`)
   - Use `bats` shell testing framework
   - Test error cases: network failure, permission denied, timeout

2. **Add end-to-end timeout scenarios**
   - Mail.app hangs for 15+ seconds
   - M365 API times out at 90 seconds
   - Verify system recovers vs hangs

3. **Test SQLite concurrent writes**
   - Parallel fact updates to same key
   - Scheduler + webhook concurrent updates
   - Verify no silent data loss

### TIER 2: Important (Before Next Release)

4. **Add real permission-denied tests** for platform integrations
   - Mock EventKit to deny calendar access
   - Mock osascript to return permission errors
   - Verify user-friendly error messages

5. **Test connector fallback behavior**
   - M365 unavailable → fallback to Apple Calendar
   - Both providers fail → graceful degradation

6. **Add malformed webhook payload tests**
   - Missing required fields
   - Invalid JSON
   - Oversized payloads

### TIER 3: Nice-to-Have

7. **Add conftest.py** for shared fixtures across test files
   - Centralize MemoryStore setup
   - Centralize temp directory cleanup
   - Reduce duplicate code

8. **Profile test execution times**
   - Identify flaky tests that timeout
   - Optimize slow tests (currently no timing data)

---

## Evidence & File References

### High-Risk Files (Platform Integrations)

| File | Tests | Mocked? | Failure Scenarios? | Risk |
|------|-------|---------|-------------------|------|
| `apple_mail/mail.py` | 55 | YES (100%) | NO | HIGH |
| `apple_calendar/eventkit.py` | 32 | YES (100%) | NO | HIGH |
| `apple_messages/messages.py` | 24 | YES (100%) | NO | HIGH |
| `apple_reminders/eventkit.py` | 31 | YES (100%) | NO | HIGH |

### Integration Test Gaps

| Area | Test File | Tests | Coverage |
|------|-----------|-------|----------|
| E2E Workflow | test_e2e_integration.py | 55 | Minimal |
| Connectors | test_connectors_router.py | 4 | Happy path only |
| Scheduler | test_scheduler_engine.py | 80 | Cron parsing only |
| Webhook | test_webhook_tools.py | 10 | Basic ingestion |
| Event Dispatch | test_event_dispatcher.py | 20 | No malformed data |

### Missing Test Areas

| Area | File | Tests | Gap |
|------|------|-------|-----|
| Shell Scripts | scripts/*.sh | 0 | ALL 8 SCRIPTS UNTESTED |
| Concurrent Access | memory/store.py | 0 | Zero concurrency tests |
| Timeout Scenarios | All connectors | ~5 | Mostly mocked |
| Permission Denied | apple_* | 0 | Zero permission tests |
| Network Failure | All API calls | ~2 | Minimal coverage |

---

## Root Causes

1. **Mocking hides reality** — 770+ tests mock external systems, so real failures (timeouts, permissions) never get caught
2. **No shared test infrastructure** — No conftest.py means isolated, duplicate setup; shared-state issues hide
3. **No shell script testing** — Shell scripts run in background, failures are silent
4. **Platform-specific testing skipped** — EventKit, AppleScript, osascript are mocked, not tested on macOS
5. **No concurrency testing** — Tests run serially; concurrent scenarios are unexplored

---

## Impact on Brittleness

**High-Risk Scenarios Not Tested**:
1. Mail.app becomes unresponsive → `_run_applescript` hangs, user sees frozen app
2. M365 API times out → calendar appears blank for 90+ seconds, no retry indication
3. Calendar permissions revoked mid-workflow → agent fails with cryptic error
4. Webhook payload is malformed → event silently stays in `pending` forever
5. Disk full during backup → `jarvis-backup.sh` fails silently
6. Two scheduled tasks run simultaneously → database lock contentions cause one to fail

---

**Status**: AUDIT COMPLETE

**Next**: Awaiting Task #6 (Synthesis report) for prioritized remediation plan.
