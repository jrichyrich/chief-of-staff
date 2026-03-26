# Chunk Audit: mcp-tool-layer

**User-facing feature**: All calendar features via MCP (list, get, create, update, delete, search, availability)
**Risk Level**: Medium
**Files Audited**: `mcp_tools/calendar_tools.py` (495 lines)
**Status**: Complete

## Purpose (as understood from reading the code)

Thin MCP tool registration layer that exposes 8 calendar operations as JSON-returning async tool handlers. Each tool validates/parses inputs, delegates to `UnifiedCalendarService` (via `state.calendar_store`) or the availability engine, and serializes results to JSON. The `find_group_availability` tool is a guidance-only tool that returns workflow instructions rather than performing the operation itself.

No divergence from intent map description.

## Runtime Probe Results

- **Tests found**: Yes (`tests/test_mcp_calendar.py`)
- **Tests run**: 43 passed, 0 failed (1.57s)
- **Import/load check**: OK (py_compile passed)
- **Type check**: Not applicable (no mypy in project CI)
- **Edge case probes**: Skipped -- all tool functions have side effects (access calendar stores). Validated `_parse_date` and `_parse_alerts` behavior manually via Python REPL.
- **Key observation**: No runtime issues detected. Test coverage is thorough, including alert validation edge cases (negative, too large, non-numeric, too many, non-list, empty string) and availability error/partial-failure paths.

## Dimension Assessments

### Implemented

All 8 tools from the intent map are fully implemented with real logic:

| Tool | Lines | Status |
|------|-------|--------|
| `list_calendars` | 50-64 | Complete |
| `get_calendar_events` | 66-94 | Complete |
| `create_calendar_event` | 96-150 | Complete |
| `update_calendar_event` | 152-208 | Complete |
| `delete_calendar_event` | 210-233 | Complete |
| `search_calendar_events` | 235-265 | Complete |
| `find_my_open_slots` | 267-401 | Complete |
| `find_group_availability` | 403-483 | Complete (guidance-only by design) |

Two private helpers: `_parse_date` (line 23) and `_parse_alerts` (line 31). Both complete.

Module-level test exposure at lines 486-495 correctly exports all tools.

No stubs, no TODOs, no `NotImplementedError`.

### Correct

**Happy paths trace correctly.** Each tool follows the same pattern: get store from state, parse inputs, delegate to `calendar_store` method via `_retry_on_transient`, serialize result to JSON.

**`_parse_date` dead code branch (line 28-29):** On Python 3.11+, `datetime.fromisoformat()` already handles date-only strings like `"2026-03-18"`, so the `except ValueError` fallback to `strptime` is never reached. Not a bug -- the fallback is harmless and provides backward compatibility if the code ever runs on Python 3.10 or earlier.

**`update_calendar_event` cannot clear fields (lines 182-198):** The truthiness checks (`if title:`, `if location:`, `if notes:`) mean you cannot set a field to an empty string to clear it. Passing `title=""` is indistinguishable from not providing a title. This is a design limitation for an MCP tool with string-defaulted optional params. Low practical impact since clearing a title to empty is rare, but worth noting.

**`_parse_alerts` returns a union type (line 31):** Returns `list[int] | str` where the `str` case is a JSON error. Callers at lines 130-132 and 193-196 correctly check `isinstance(parsed, str)` before proceeding. The pattern works but is unconventional -- an exception would be more Pythonic.

**Timezone consistency:** `_parse_date` always returns naive datetimes. `search_calendar_events` (line 256) computes `now` as timezone-aware (via `ZoneInfo`), then constructs defaults as aware datetimes. These aware defaults only apply when the user omits dates. When the user provides dates, they pass through `_parse_date` as naive. The downstream `UnifiedCalendarService` must handle both -- this is a boundary concern at the service layer, not a bug here.

### Efficient

No efficiency concerns. This is a thin delegation layer. Each tool makes exactly one call to the calendar store. No loops, no redundant work, no data loaded into memory unnecessarily. The `find_my_open_slots` function is the most complex at ~130 lines but does no redundant work -- it fetches events once, runs the slot finder once, formats once.

### Robust

**Error handling is solid.** The `@tool_errors` decorator catches `_EXPECTED = (OSError, subprocess.SubprocessError, TimeoutError, ValueError)` and returns structured JSON errors. Unexpected exceptions are logged with full traceback and return a safe message.

**`_retry_on_transient` provides retry for SQLite/OS-level transient failures.** All store calls go through this wrapper.

**Input validation present for:**
- `duration_minutes < 1` (line 307-312) -- returns error JSON
- Alert validation: type check, count limit (10), range check (0-40320)
- Working hours parsing -- `ValueError` from `int()` on bad format is caught by decorator

**`find_my_open_slots` partial failure handling (lines 355-376):** Gracefully degrades when one provider fails -- uses partial results if available, returns structured error with provider details if not. Routing fallback is logged as a warning.

**No validation for:** `provider_preference` values -- an invalid string like `"foobar"` is passed through to the unified service. The service layer would need to validate or default. Low risk since the MCP tool docstrings document valid values and the caller is an LLM.

### Architecture

**Clean separation of concerns.** This module is purely a translation layer: MCP parameters in, JSON strings out. All business logic lives in the unified calendar service and availability engine. No database access, no direct provider calls, no business rules.

**Consistent patterns across all tools:** Each follows the same structure (get store, parse, build kwargs, delegate, serialize). The conditional kwargs pattern (`if provider_preference and provider_preference != "auto"`) is repeated 6 times across the tools -- a minor DRY opportunity but the repetition is simple and readable.

**`find_my_open_slots` is the longest function (~130 lines, lines 267-401).** It handles provider failure/fallback logic that arguably belongs in the service layer rather than the MCP tool layer. This is the only tool that accesses `get_events_with_routing` and interprets error payloads directly. The other tools simply pass through to the service and let errors propagate.

**`find_group_availability` is a guidance tool (lines 403-483)** that returns workflow instructions instead of executing. This is an intentional architectural decision documented in the docstring -- the MCP server cannot call another MCP server's tools directly.

**Testability is excellent.** The module-level export pattern (lines 486-495) enables direct test imports. All 43 tests pass with mocked stores, confirming the tool functions are testable in isolation.

## Findings

### Critical

No critical findings.

### Warning

- **[calendar_tools.py:182-198]** -- `update_calendar_event` cannot clear fields to empty string. The `if title:` / `if location:` / `if notes:` truthiness checks mean passing `""` is treated as "don't update this field". If a user ever needs to clear a location or notes field, this tool cannot do it. **Impact**: Low -- rare operation, but a correctness gap if needed.

- **[calendar_tools.py:355-376]** -- Error payload inspection logic in `find_my_open_slots` (checking `events[0].get("error")`) puts provider-failure interpretation in the MCP tool layer rather than the service layer. If the error payload format changes in `UnifiedCalendarService`, this code breaks silently (would treat error events as real events). **Impact**: Medium -- coupling to an undocumented return format convention.

### Note

- **[calendar_tools.py:28-29]** -- `_parse_date` fallback to `strptime` for date-only format is dead code on Python 3.11+ since `fromisoformat` handles it natively. Harmless but could be removed for clarity.

- **[calendar_tools.py:31-46]** -- `_parse_alerts` returns a union of `list[int] | str` rather than raising an exception on validation failure. The callers handle it correctly, but this is an unconventional pattern that requires careful isinstance checks at every call site.

- **[calendar_tools.py:59,89,260,335]** -- The `if provider_preference and provider_preference != "auto"` pattern is repeated 6 times across tools. Could be extracted to a helper, but the repetition is simple enough that it does not harm readability.

- No validation of `provider_preference` enum values at the tool layer. Invalid values pass through to the service layer silently.

### Nothing to flag

- **Efficiency**: Clean single-delegation pattern throughout. No concerns.
- **Test coverage**: 43 tests covering happy paths, error paths, validation edge cases, and partial failures. Excellent.

## Verdict

This chunk is well-implemented, correct, and clean. It functions as a thin, well-structured MCP tool registration layer that properly delegates to the calendar service and availability engine. The two warnings are minor: the inability to clear event fields via empty strings is a rare edge case, and the error-payload inspection in `find_my_open_slots` is a coupling concern rather than a current bug. All 43 tests pass. No critical issues found.
