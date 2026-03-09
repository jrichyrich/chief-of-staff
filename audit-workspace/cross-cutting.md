# Cross-Cutting Scan: find_my_open_slots Pipeline

## Code Quality Markers
- **No TODOs/FIXMEs/HACKs** found in any pipeline file
- **No empty pass bodies** except one: `m365_provider.py:52` silently swallows exceptions in connectivity checker

## Source/Test Ratio
- Source: 2,291 lines across 7 files
- Tests: 2,809 lines across 4 test files (1.2x test-to-source ratio — healthy)
- **Gap**: Only 4 tests for `find_my_open_slots` in test_mcp_calendar.py (basic, error+partial, error+no_partial, registration)
- **Gap**: 0 integration tests that verify end-to-end with real M365 data

## Test Coverage Gaps (Critical)
1. **No test verifies M365 bridge returns complete event sets** — the bridge is tested for JSON parsing, not data completeness
2. **No test for find_my_open_slots with mixed Apple+M365 events** — the dual-provider path is untested
3. **No test passes user_email** to find_my_open_slots — tentative scoping is untested in integration
4. **No test for M365 bridge event field variability** — what happens when showAs or isCancelled are missing?
5. **No test for deduplication correctness** — same event from Apple and M365 with different field shapes

## Hardcoded Values
- `connectivity_ttl_seconds=300` (5 min) — not configurable at MCP tool level
- `timeout_seconds=90` for M365 bridge — fixed in constructor
- Default soft keywords hardcoded: "focus", "focus time", "lunch", etc.
- Timezone hardcoded to "America/Denver" in find_my_open_slots

## Silent Failure Patterns
1. `m365_provider.py:52`: Connectivity check exception → silent pass, keeps stale state
2. `availability.py:349-353`: Unparseable event times → `logger.debug` (not warning) + skip
3. `availability.py:339-343`: Missing start/end → `logger.debug` + skip
4. `calendar_unified.py:214-216`: Provider exception → `logger.exception` + continue (correct for resilience)
5. `claude_m365_bridge.py:327-330`: All subprocess exceptions → return None (silent)

## Data Integrity Concerns
- M365 bridge prompt asks LLM to "convert UTC to local timezone" — non-deterministic
- M365 bridge structured output requires only ["title", "start", "end"] — everything else optional
- No validation that M365 events have timezone offsets in start/end strings
- Deduplication uses ical_uid first, then falls back to (title, start, end) — M365 bridge doesn't return ical_uid
