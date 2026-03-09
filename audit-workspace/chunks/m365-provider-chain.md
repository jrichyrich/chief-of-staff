# Chunk Audit: m365-provider-chain

**User-facing feature**: Microsoft 365 calendar integration
**Risk Level**: Critical (LLM-in-the-loop, non-deterministic output)
**Files Audited**:
- `/Users/jasricha/Documents/GitHub/chief_of_staff/connectors/providers/m365_provider.py` (189 lines)
- `/Users/jasricha/Documents/GitHub/chief_of_staff/connectors/claude_m365_bridge.py` (379 lines)

**Status**: Complete (fully implemented, functional, but architecturally fragile)

## Purpose (as understood from reading the code)

`ClaudeM365Bridge` spawns a Claude CLI subprocess with M365 MCP connector access, passes a natural-language prompt requesting calendar data, and parses the structured JSON output. `Microsoft365CalendarProvider` wraps the bridge as a `CalendarProvider` adapter, adding connectivity checks (with TTL-based caching) and consistent event tagging. Together they let the unified calendar system read/write Outlook events without native M365 SDK integration. This matches the intent map description.

## Runtime Probe Results

- **Tests found**: Yes (`tests/test_claude_m365_bridge.py`, plus M365-specific tests in `tests/test_providers_direct.py`)
- **Tests run**: 5 passed, 0 failed (bridge tests only; provider tests not isolated)
- **Import/load check**: OK for both modules
- **Type check**: Not applicable (no mypy/pyright in dev deps)
- **Edge case probes**:
  - `_sanitize_for_prompt(None)` returns `""` correctly
  - `_sanitize_for_prompt` strips control chars and truncates at 500+`...` correctly
  - `_parse_first_json_object` handles null, empty, embedded, nested, and braces-in-strings correctly
  - `_parse_output_json` rejects non-dict (list) top-level JSON correctly
- **Key observation**: The JSON parsing fallback chain is robust for well-formed output, but no test verifies behavior when the LLM returns a truncated event list (the primary production concern).

## Dimension Assessments

### Implemented

All `CalendarProvider` abstract methods are implemented in `Microsoft365CalendarProvider` with real logic: `list_calendars`, `get_events`, `create_event`, `update_event`, `delete_event`, `search_events`. All corresponding bridge methods exist in `ClaudeM365Bridge`. No stubs, no TODOs, no unimplemented methods.

The connectivity checker, sanitization, tagging, and multi-fallback JSON parsing are all fully implemented.

### Correct

**Happy path is correct** for both files. The bridge constructs prompts, invokes Claude CLI with `--output-format json --json-schema`, and parses the response through a 4-level fallback chain (`structured_output` dict -> `structured_output` string -> `result` dict -> `result` string -> raw stdout). The provider correctly delegates to hooks and tags results.

**Suspected correctness issues:**

1. **No event count validation (bridge:70-127)** -- The bridge asks the LLM for events in a date range but has no way to verify completeness. If the M365 connector returns 200 events but the LLM's structured output only includes 150 (due to token limits or summarization behavior), the caller gets 150 with no warning. There is no `total_count` or pagination mechanism.

2. **Timezone conversion is LLM-dependent (bridge:117-118)** -- The prompt says "convert UTC to local timezone or include Z suffix" but the LLM may not do this consistently. Some invocations may return `2026-03-10T15:00:00Z`, others `2026-03-10T09:00:00-06:00`, and others `2026-03-10T09:00:00` (no offset at all). The downstream code does no timezone normalization.

3. **`is_connected` initial state is one-shot (mcp_server.py:79)** -- The provider is initialized with `connected=m365_bridge.is_connector_connected()` at startup. The `connectivity_checker` callback is NOT wired (no `connectivity_checker=` arg in `mcp_server.py:78-86`). This means the 300s TTL refresh logic in `is_connected()` never fires. If M365 connectivity drops after startup, the provider still reports connected and sends bridge calls that will fail. Conversely, if M365 was temporarily down at startup, it stays disconnected forever until server restart.

4. **`_tag_event` double-tagging (m365_provider:181-189 and calendar_unified:127-140)** -- Both the provider and the unified service apply `_tag_event`. The provider sets `provider`, `source_account`, `calendar_id`, `native_id`, `unified_uid`. Then `UnifiedCalendarService._read_from_providers` with `tag_events=True` overwrites some of these. This is harmless but wasteful -- the unified service's tagging is the authoritative one.

### Efficient

- **Subprocess per operation** -- Every calendar read/write spawns a full Claude CLI process (fork + exec + LLM inference). This is inherently expensive (~5-30 seconds per call, 90s timeout). Acceptable for the use case but means any "list then detail" pattern is extremely slow.
- **No batching** -- If the caller needs events from multiple date ranges, each is a separate subprocess. No way to batch.
- **`_parse_first_json_object` is O(n^2) worst case (bridge:344-378)** -- The outer loop restarts from `i+1` after a failed parse at position `i`. For pathological input with many `{` characters that don't form valid JSON, this scans the same substring repeatedly. Unlikely to matter in practice (output is typically <100KB).

### Robust

1. **Timeout handling is solid (bridge:308-330)** -- `run_with_cleanup` uses process groups and SIGTERM. The `_run` method catches `TimeoutExpired`, `FileNotFoundError`, and generic `Exception`, returning `None` in all cases. `_invoke_structured` converts `None` to an error dict.

2. **Connectivity checker exception swallowed silently (m365_provider:51-52)** -- `except Exception: pass` keeps the last known state. This is documented but means network errors, DNS failures, etc. are invisible. Should at minimum log the exception.

3. **`run_with_cleanup` can raise `ProcessLookupError` (utils/subprocess.py:22)** -- If the process exits between `TimeoutExpired` and `os.killpg()`, `os.getpgid()` or `os.killpg()` raises `ProcessLookupError`. This propagates uncaught. The bridge's `_run` catches generic `Exception` at line 329, so it returns `None` -- but the timeout semantics change (it looks like "unknown error" instead of timeout).

4. **`proc.wait(timeout=5)` can raise `TimeoutExpired` again (utils/subprocess.py:23)** -- If SIGTERM doesn't kill the process group within 5s, a second `TimeoutExpired` is raised. This is also caught by the bridge's generic handler, but it means the zombie process tree is not cleaned up (no SIGKILL escalation).

5. **No retry on transient bridge failures** -- If the Claude CLI subprocess fails due to a transient API error (rate limit, network hiccup), the error propagates directly. The caller (`_read_from_providers`) skips the provider and potentially returns a dual-read policy error. No retry is attempted at any layer.

6. **Prompt injection surface (bridge prompts)** -- Calendar names and search queries are embedded in prompts via `_sanitize_for_prompt`, which strips control chars and truncates. XML-style tags (`<user_calendar_names>`, `<user_query>`, etc.) provide some structural delineation. This is reasonable defense-in-depth but not airtight -- a calendar name containing `</user_calendar_names>` would break the tag boundary.

### Architecture

1. **Clean separation of concerns** -- The provider adapter pattern is well-designed. `ClaudeM365Bridge` handles subprocess/LLM concerns, `Microsoft365CalendarProvider` handles the `CalendarProvider` contract, and `UnifiedCalendarService` handles routing/deduplication. Each is independently testable.

2. **Hook-based dependency injection (m365_provider)** -- The provider accepts callable hooks for each operation, making it easy to test and swap implementations. Well-architected.

3. **JSON parsing fallback chain is over-complex (bridge:258-306)** -- Four levels of fallback parsing is a code smell indicating the bridge output format is unreliable. This is inherent to the LLM-subprocess architecture, not a code quality issue per se.

4. **Schema duplication (bridge:75-101 and bridge:130-155)** -- The `get_events` and `search_events` methods define identical JSON schemas. Should be extracted to a module-level constant.

5. **No structured logging** -- Bridge operations (especially timing data captured at line 120-126) are not logged. The `elapsed_ms` is only included in error payloads, not success payloads. This makes production debugging difficult.

## Findings

### Critical

- **[mcp_server.py:78-86]** -- `Microsoft365CalendarProvider` is initialized WITHOUT a `connectivity_checker` callback. The TTL-based refresh logic in `is_connected()` (m365_provider.py:46-53) is dead code in production. If M365 connectivity changes after startup, the provider's connected state is permanently stale. This means: (a) if M365 was down at startup, all M365 calendar operations fail silently for the entire session with no auto-recovery, and (b) if M365 goes down mid-session, the bridge keeps getting invoked and failing with subprocess errors instead of returning the clean "not connected" error.

- **[claude_m365_bridge.py:70-127]** -- No event count validation or completeness check. The LLM may silently drop events due to token limits, context window constraints, or summarization behavior. A busy day with 20+ events could return only 10-15, with no indication that data was lost. This is the most likely root cause for missing events in production. Mitigation would require the prompt to request a total count and compare against results length, or pagination.

### Warning

- **[claude_m365_bridge.py:117-118]** -- Timezone handling is delegated entirely to the LLM via prompt instruction. The bridge does no post-processing validation or normalization of datetime strings. Events may arrive with inconsistent timezone offsets (some UTC, some local, some bare) depending on LLM behavior. Downstream code (`find_my_open_slots`, availability calculations) that parses these strings may misinterpret bare datetimes.

- **[utils/subprocess.py:22-23]** -- `os.killpg()` can raise `ProcessLookupError` if the process already exited, and `proc.wait(timeout=5)` can raise a second `TimeoutExpired` if SIGTERM doesn't work. Neither is handled. The bridge's generic `except Exception` at line 329 catches both, but with loss of timeout semantics and potential zombie processes.

- **[m365_provider.py:51-52]** -- Connectivity checker exceptions are swallowed with `pass` and no logging. Network errors, DNS failures, and authentication issues during connectivity refresh are completely invisible.

- **[claude_m365_bridge.py:75-101 vs 130-155]** -- Identical JSON schema definition duplicated between `get_events` and `search_events`. Should be a shared constant to prevent divergence.

- **[claude_m365_bridge.py:258-306]** -- The 4-level JSON parsing fallback chain (structured_output dict, structured_output string, result dict, result string, raw stdout) indicates the Claude CLI output format is unreliable. If the CLI's `--output-format json --json-schema` contract changes, all four fallback levels need updating.

### Note

- Success responses from `get_events` include no timing metadata. Only error responses get `elapsed_ms` and `operation` (bridge:122-126). Adding timing to success responses would help identify slow bridge calls in production.
- The `_parse_first_json_object` brace-matching parser (bridge:344-378) is a hand-rolled JSON finder. It correctly handles escaped characters and nested braces. The O(n^2) worst case is theoretical and unlikely to matter in practice.
- Double-tagging of events between provider (m365_provider:181-189) and unified service (calendar_unified:127-140) is redundant but harmless.

## Verdict

This chunk is fully implemented and the code quality is good -- clean separation of concerns, proper input sanitization, robust subprocess cleanup, and thorough error handling. However, the architecture has two critical production reliability gaps: (1) the connectivity checker is dead code because `mcp_server.py` doesn't wire it, so M365 availability changes are never detected, and (2) the LLM-mediated event fetching has no completeness guarantee -- events can be silently dropped with no warning. The second issue is the most likely explanation for missing events in production and is an inherent limitation of the "LLM as data bridge" pattern. A deterministic fallback or count-verification mechanism is needed to make this chain trustworthy for availability calculations.
