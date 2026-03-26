# Chunk Audit: m365-bridge

**User-facing feature**: Outlook/Exchange calendar access
**Risk Level**: High
**Files Audited**: `connectors/claude_m365_bridge.py` (412 lines), `connectors/providers/m365_provider.py` (204 lines)
**Status**: Complete

## Purpose (as understood from reading the code)

`ClaudeM365Bridge` shells out to the Claude CLI (`claude -p`) with a structured JSON schema to execute Microsoft 365 calendar operations (list, get, search, create, update, delete). It parses the CLI's JSON output through a multi-layer fallback chain (structured_output -> result field -> raw stdout). `Microsoft365CalendarProvider` wraps the bridge as a pluggable `CalendarProvider` implementation with connectivity checking (TTL-cached), hook-based delegation, and event tagging with provider metadata.

No divergence from the intent map description.

## Runtime Probe Results

- **Tests found**: Yes -- `tests/test_claude_m365_bridge.py` (10 tests), `tests/test_providers_direct.py` (22 M365-related tests)
- **Tests run**: 32 passed, 0 failed
- **Import/load check**: OK (both modules)
- **Type check**: Not applicable (no mypy in environment)
- **Edge case probes**: `_sanitize_for_prompt` correctly handles None, empty string, XSS payloads, control characters, XML tag breakout attempts, and over-length strings. `_parse_first_json_object` correctly handles None, empty, no-JSON, embedded JSON, multiple objects, broken JSON, and strings containing braces.
- **Key observation**: No runtime issues detected. The sanitization and parsing functions are well-hardened.

## Dimension Assessments

### Implemented

All six calendar operations are fully implemented in both the bridge and provider:

| Operation | Bridge method | Provider method |
|-----------|--------------|-----------------|
| List calendars | `list_calendars` (L61-75) | `list_calendars` (L74-81) |
| Get events | `get_events` (L77-147) | `get_events` (L83-95) |
| Search events | `search_events` (L149-208) | `search_events` (L157-169) |
| Create event | `create_event` (L210-240) | `create_event` (L97-124) |
| Update event | `update_event` (L242-268) | `update_event` (L126-140) |
| Delete event | `delete_event` (L270-289) | `delete_event` (L142-155) |

Supporting infrastructure is also complete: `_invoke_structured` (L291-339), `_run` with process group cleanup (L341-363), `_parse_output_json` (L366-374), `_parse_first_json_object` (L377-412), `_sanitize_for_prompt` (L20-33), connectivity checking with TTL cache (provider L48-69).

No stubs, TODOs, or unreachable code found.

### Correct

The logic is correct for the stated purpose. Specific observations:

1. **Prompt sanitization** (bridge L20-33): Properly strips control characters, escapes XML metacharacters (`&`, `<`, `>`), and truncates to max_length. Edge case probes confirmed this handles injection attempts correctly.

2. **JSON parsing fallback chain** (bridge L291-339): Three-tier fallback (`structured_output` dict -> `result` field text -> raw stdout scan) correctly handles the various formats Claude CLI may emit. The `_parse_first_json_object` hand-rolled parser correctly handles nested braces, escaped characters, and string-embedded braces.

3. **Data completeness check** (bridge L140-146, L201-207): The `total_event_count` comparison correctly detects when Claude's structured output truncates results, and injects a `_bridge_warning` into each event dict.

4. **Connectivity TTL** (provider L48-69): Correctly caches the connectivity state and only re-checks after `connectivity_ttl_seconds` has elapsed. Exception during check correctly preserves the previous state.

5. **`alarms` parameter silently dropped**: Both `ClaudeM365Bridge.create_event` (L219) and `Microsoft365CalendarProvider.create_event` (L107) accept an `alarms` parameter from the ABC contract but neither uses it. The bridge prompt (L226-234) never mentions alarms, and the provider hook call (L113-121) omits it. This matches the ABC interface but is a silent contract violation -- callers passing alarms get no feedback that they are ignored.

### Efficient

No significant inefficiencies. Each operation makes exactly one subprocess call. The JSON parsing (`_parse_first_json_object`) is O(n) with a single pass. The connectivity check TTL avoids redundant subprocess calls for `claude mcp list`.

One minor note: `get_events` and `search_events` have nearly identical post-processing logic (L130-147 vs L191-208) -- ~18 lines duplicated. Not a performance issue, but a maintenance burden.

### Robust

1. **`_run` swallows all exceptions silently** (bridge L341-363): The bare `except Exception: return None` at L362-363 catches everything including `MemoryError`, `KeyboardInterrupt` (in Python 3 this is `BaseException` so actually not caught), and any unexpected errors. The caller (`_invoke_structured`) then returns `{"error": "Failed to invoke Claude CLI"}` which loses the actual exception. At minimum, the exception should be logged.

2. **`run_with_cleanup` can leave zombie processes** (utils/subprocess.py L22-24): If `os.killpg(SIGTERM)` succeeds but `proc.wait(timeout=5)` raises another `TimeoutExpired`, the process is orphaned. No SIGKILL escalation exists. This is in the dependency, not this chunk, but affects runtime reliability.

3. **No retry on transient subprocess failures**: If the Claude CLI hangs or crashes once, the operation fails permanently. There is no retry mechanism at the bridge level, unlike the `_retry_on_transient` pattern used elsewhere in the codebase for SQLite operations.

4. **Provider connectivity checker exception handling is correct** (provider L53-60): Exceptions during connectivity check are logged with traceback and the previous state is preserved. This is well done.

5. **Hook None-check before invocation** (provider L77-79, L91-93, etc.): Every provider method checks if the hook is None before calling it, returning a descriptive error. This is correct and prevents `TypeError`.

6. **Error dicts vs exceptions**: The entire chain uses error-dict returns (`{"error": "..."}`) rather than raising exceptions. This is consistent but means callers must check for error keys in every response -- there is no type-level distinction between success and failure. This is an intentional architectural choice, not a bug, but it does make it possible for callers to miss error checking.

### Architecture

1. **Clean separation of concerns**: The bridge handles subprocess execution and JSON parsing. The provider handles interface compliance, connectivity, and event tagging. This is well-layered.

2. **Dependency injection via hooks**: The provider uses callable hooks rather than direct bridge reference, making it fully testable with simple lambdas/mocks. This pattern is used effectively in tests.

3. **Prompt duplication**: The `get_events` and `search_events` methods contain nearly identical JSON schemas (L83-108 vs L151-176) and post-processing logic (L130-147 vs L191-208). A shared helper would reduce the maintenance surface.

4. **LLM-mediated data path**: The fundamental architecture routes structured data requests through a natural language LLM prompt. This means:
   - Output format depends on Claude's interpretation, not a deterministic API
   - The structured JSON schema enforcement mitigates this significantly
   - The multi-layer parsing fallback (L291-339) is a pragmatic adaptation to the non-deterministic output
   - This is an inherent architectural trade-off, not a defect

5. **Provider tagging** (provider L189-204): `_tag_event` and `_tag_calendar` consistently add `provider`, `source_account`, `calendar_id`, `native_id`, and `unified_uid` fields. The `delete_event` method (L151-155) manually tags instead of using `_tag_event` -- this is intentional since deletes return a status object, not a full event.

## Findings

### Critical

None.

### Warning

- **bridge:341-363** -- `_run()` bare `except Exception: return None` swallows all exceptions without logging. A subprocess crash, permission error, or corrupted environment produces the generic message "Failed to invoke Claude CLI" with no diagnostic information. Should at minimum `logger.exception()` before returning None.

- **bridge:210-240, provider:97-121** -- `alarms` parameter accepted but silently ignored in both layers. The ABC contract (`CalendarProvider.create_event`) declares `alarms: Optional[list[int]]` and both implementations accept it, but neither passes it through. Callers setting alarms get silent data loss. Should either implement alarm support or raise/log a warning when alarms are provided.

- **bridge:83-108 + 130-147 vs 151-176 + 191-208** -- The `get_events` and `search_events` schemas and post-processing blocks are duplicated (~50 lines total). A shared `_event_result_schema()` and `_process_event_results()` helper would reduce the surface for divergence bugs.

### Note

- `run_with_cleanup` (utils/subprocess.py:22-24) does not escalate to SIGKILL if SIGTERM + 5s wait fails. For long-running Claude CLI processes, this could leave orphans. This is in a dependency file outside this chunk's scope.

- The `_parse_first_json_object` hand-rolled JSON scanner (bridge:377-412) is correct but could be replaced by a simpler regex approach or `json.JSONDecoder.raw_decode()`. The current implementation handles all tested edge cases correctly, so this is a readability/maintenance observation, not a correctness issue.

- No tests exist for `create_event`, `update_event`, or `delete_event` at the bridge level (only at the provider level via mocked hooks). These write operations go through `_invoke_structured` which is tested via read paths, but direct bridge-level write tests would improve coverage.

### Nothing to flag

- **Implemented**: All operations fully implemented with no stubs.
- **Efficient**: No inefficiencies at production scale.

## Verdict

This chunk is fully implemented, correct, and well-architected. The bridge-to-provider separation is clean, the prompt sanitization is thorough, and the JSON parsing fallback chain handles the non-deterministic nature of LLM output pragmatically. The two actionable issues are: (1) the silent exception swallowing in `_run()` which will make production debugging difficult, and (2) the silently dropped `alarms` parameter which violates caller expectations. Both are straightforward fixes. The code/schema duplication between `get_events` and `search_events` is a maintenance hygiene issue worth addressing but not urgent.
