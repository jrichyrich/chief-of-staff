# Cross-Cutting Scan — Calendar Subsystem

## Code Hygiene
- **TODOs/FIXMEs/HACKs**: None found across all 9 calendar files
- **Empty pass statements**: None in calendar files (4 in graph_client.py, out of scope)
- **NotImplementedError stubs**: None

## Secrets & Credentials
- No hardcoded passwords, API keys, or secrets in any calendar file
- No hardcoded URLs in calendar files (all URLs are in graph_client.py, out of scope)

## Test Coverage
- **Source lines**: ~2,582 across 9 files
- **Test lines**: ~3,341 across 6 test files
- **Test:Source ratio**: 1.29:1 (healthy)
- **Test results**: 121 tests, ALL PASSING (1.96s)
- **Test files**:
  - `test_mcp_calendar.py` (902 lines) — MCP tool layer
  - `test_calendar_eventkit.py` (742 lines) — Apple EventKit
  - `test_calendar_unified.py` (620 lines) — Unified service
  - `test_connectors_router.py` (49 lines) — Provider router (THIN)
  - `test_claude_m365_bridge.py` (139 lines) — M365 bridge (THIN)
  - `test_providers_direct.py` (889 lines, in worktree) — Provider tests

## Test Coverage Gaps (Suspected)
- `test_connectors_router.py` is only 49 lines for a 140-line router with 15+ routing paths — likely undertested
- `test_claude_m365_bridge.py` is 139 lines for a 412-line bridge — moderate coverage
- No dedicated test file for `scheduler/availability.py` (523 lines) — may be tested indirectly via `test_mcp_calendar.py`
- No test for `connectors/providers/apple_provider.py` specifically (may be covered by `test_calendar_eventkit.py`)

## Dependency Analysis
- Calendar subsystem has clean dependency tree: MCP tools → Unified Service → Router → Providers
- No circular dependencies detected
- Single shared state: ownership SQLite DB (`calendar-routing.db`)
- `config.py` dependencies: USER_TIMEZONE, USER_EMAIL, CALENDAR_ALIASES, CLAUDE_BIN, CLAUDE_MCP_CONFIG

## Interface Consistency
- All providers implement `CalendarProvider` ABC consistently
- All public methods return plain dicts (good)
- Error convention: `{"error": "message"}` — consistent across all layers
