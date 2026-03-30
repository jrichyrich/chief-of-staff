# Chunk Audit: Agent System

**User-facing feature**: Agent dispatch, agent creation, agent memory
**Risk Level**: High
**Files Audited**:
- `agents/__init__.py`
- `agents/base.py`
- `agents/factory.py`
- `agents/registry.py`
- `agents/loop_detector.py`
- `agents/mixins.py`
- `agents/triage.py`
- `capabilities/__init__.py`
- `capabilities/registry.py`
- `mcp_tools/agent_tools.py`
- `mcp_tools/dispatch_tools.py`

**Status**: Complete

---

## Purpose (as understood from reading the code)

This chunk implements the full expert agent execution pipeline: a `BaseExpertAgent` runs an async Claude tool-use loop (up to 25 rounds) with capability-gated tool dispatch, a `LoopDetector` terminates repetitive patterns, `AgentFactory` uses Haiku to auto-generate YAML configs, and `AgentRegistry` loads/saves those configs. `dispatch_tools.py` is the MCP orchestration entry point that runs multiple agents in parallel with semaphore-bounded concurrency, optional Haiku triage (to downgrade simple tasks to haiku tier), and optional result synthesis. The stated purpose matches the actual implementation.

---

## Runtime Probe Results

- **Tests found**: Yes — 11 test files covering agents, dispatch, capabilities, loop detector, triage, and factory
- **Tests run**: 210 passed, 0 failed (across 7 test files covering this chunk directly)
- **Import/load check**: `agents.loop_detector` and `capabilities.registry` import OK; `agents.registry`, `agents.factory`, `agents.triage` require `yaml`/`anthropic` (expected — installed in venv but not base Python). No circular import issues.
- **Type check**: Not run (no mypy/pyright configured)
- **Edge case probes**:
  - `LoopDetector.record()` correctly returns `ok` → `warning` at call 3, `break` at call 5 for repeated identical calls
  - A-B-A-B alternation correctly produces `warning` at call 4, `break` at call 9 (counter accumulates independently)
  - `None` values in tool args hash correctly via `json.dumps(..., default=str)`
- **Key observation**: All 210 tests pass cleanly. Runtime behavior matches documented intent.

---

## Dimension Assessments

### Implemented

Every function in the intent map exists with real logic:
- `BaseExpertAgent.execute()` — full async tool-use loop with loop detection, truncation, and structured `AgentResult` return
- `BaseExpertAgent._handle_tool_call()` — capability enforcement + hook wiring + dispatch
- `_get_dispatch_table()` — 60+ tool handlers wired across all mixins
- `LoopDetector` — count-based and A-B-A-B pattern detection, fully implemented
- `AgentFactory.create_agent()` — real Haiku call, JSON parse, capability validation, registry persistence
- `AgentRegistry` — YAML-backed persistence with in-memory cache invalidation on write
- `dispatch_agents` MCP tool — parallel dispatch with semaphore, wall-clock timeout, triage integration, synthesis optional
- All mixin handlers (`CalendarMixin`, `MailMixin`, `ReminderMixin`, `NotificationMixin`, `LifecycleMixin`, `WebBrowserMixin`) — implemented, none stubbed

No stubs, TODOs, or placeholder implementations found.

### Correct

The main happy path is correct. However, several specific logic issues were found:

**1. `json.dumps(result)` at `base.py:174` has no exception handling.** If any tool handler returns a non-JSON-serializable object (e.g., a `datetime` not converted to string), `execute()` crashes with `TypeError` mid-loop, leaving the agent with no error result and no recovery path. Confirmed that `json.dumps` raises `TypeError` on `datetime` objects. While current handlers appear to return serializable types, this is an unchecked assumption — any new handler or a calendar provider returning raw datetime objects would produce an unhandled exception.

**2. `dispatch_tools.py:125-126` calls `classify_and_resolve(config, task)` without `memory_store=state.memory_store`.** The `classify_and_resolve` signature accepts `memory_store` as an optional parameter specifically for API call logging. Omitting it means every triage Haiku call is untracked — all triage API costs are invisible in usage reports. This is a logic correctness gap against the intended behavior (API tracking is explicitly built into triage at `triage.py:57-68`).

**3. `registry._load_yaml()` swallows all errors silently.** `agents/registry.py:113` catches `(yaml.YAMLError, KeyError, ValueError)` and returns `None` with no logging. A corrupted YAML file or one with an unknown capability causes the agent to silently disappear from `list_agents()` with no diagnostic trace. There is no logger in the registry module at all.

**4. After-hooks fire with a raw coroutine for async web browser tools.** `base.py:288-296` fires `after_tool_call` hooks *before* awaiting the result for async handlers, passing the coroutine object as `result`. The audit log hook (`hooks/builtin.py:41`) uses `str(result)`, which produces `<coroutine object _handle_web_open at 0x...>` — meaningless data. This is acknowledged in a comment but is a correctness gap in audit trail quality.

### Efficient

**`get_tools()` is called on every tool call in `_handle_tool_call()` (`base.py:268`).** `get_tools()` calls `get_tools_for_capabilities()`, which calls `validate_capabilities()` (list construction + dict lookup per cap), then builds a new list of tool schemas. With `MAX_TOOL_ROUNDS=25` and multiple tool calls per round, this can be called 50-100+ times per agent execution, rebuilding the same structure each time. An agent with 10 capabilities re-validates and re-builds tool lists on every permission check. The `_dispatch_cache` (dispatch table) *is* cached on the instance, but the capability-to-tools resolution is not. Given the agent instance lives only for a single `execute()` call, caching `get_tools()` at construction time would eliminate this redundant work.

No N+1 query patterns, no large dataset loads, no algorithmic complexity concerns elsewhere.

### Robust

**`json.dumps(result)` unguarded at `base.py:174`** — see Correct section. This crashes the agent's tool-use loop entirely if any handler returns non-serializable data.

**`AgentFactory.create_agent()` doesn't handle `validate_capabilities()` raising `ValueError`** when the LLM returns a capability name not in `CAPABILITY_DEFINITIONS`. At `factory.py:72`, `validate_capabilities(data.get("capabilities", ["memory_read"]))` can raise `ValueError` which propagates up uncaught within `create_agent()`. The MCP tool caller (`mcp_tools/agent_tools.py`) does *not* call `AgentFactory.create_agent()` — it uses `AgentRegistry.save_agent()` directly. The factory is invoked via `auto_create_skill` handler in `mcp_tools/skill_tools.py`. Whether that caller catches `ValueError` is outside this chunk's scope, but the factory itself should defensively catch and re-raise with a clear message.

**`_load_yaml` silent failure** — see Correct section. No observability for broken YAML files.

**Empty text response from Claude** (`base.py:200`): if Claude returns `stop_reason != "tool_use"` but produces no text block, the agent returns `AgentResult("", success)`. Callers won't distinguish this from a genuine empty response. Low probability but could lead to empty results being silently accepted.

**Wall-clock timeout in `dispatch_tools.py:202`** is correctly handled with `asyncio.wait_for`. Individual agent timeout (`AGENT_TIMEOUT_SECONDS=60` from config) is not enforced per-agent — only the overall wall-clock. An agent that hangs for the full wall-clock period blocks the entire batch if concurrency limit is hit.

### Architecture

**Dispatch table is defined inline in `_get_dispatch_table()`** — a ~100-line dict literal at `base.py:305-401`. This creates a tight coupling where adding a new tool requires changes in three places: (1) the mixin method, (2) the dispatch table dict, (3) the capabilities registry. There is no registration mechanism — the table is manually maintained. A test (`TestDispatchTable::test_dispatch_table_contains_all_known_tools`) catches missing entries, which partially mitigates this.

**`MailMixin._handle_mail_send()` hardcodes `confirm_send=True`** at `mixins.py:288`. The comment says "Agents are autonomous; dispatch is the confirm gate" — this is a documented architectural decision and not a bug, but it means agents can send email without any further confirmation check beyond the capability gate. Worth noting for security review.

**`AgentFactory` is a standalone class** but is only used by `auto_create_skill` in `skill_tools.py` (outside this chunk). It is fully decoupled from `AgentRegistry` aside from accepting one in its constructor. This is clean separation.

**`triage.py` uses synchronous `anthropic.Anthropic`** while `base.py` uses `asyncio.AsyncAnthropic`. Dispatch wraps the sync triage call in `asyncio.to_thread()` — correct. However, the triage Haiku call creates its own `anthropic.Anthropic` client instance per call (no connection pooling). Under high dispatch frequency this could be inefficient.

**`capabilities/registry.py` is 1,155 lines** — almost entirely data (TOOL_SCHEMAS dict + CAPABILITY_DEFINITIONS dict + 4 small functions). This is effectively a large static config file masquerading as a module. It is clean and correct but could be split into a YAML/JSON data file + a thin loader to reduce review surface and support external tooling.

---

## Findings

### 🔴 Critical

- **`agents/base.py:174`** — `json.dumps(result)` has no try/except. If any mixin handler returns a non-JSON-serializable value (e.g., a raw `datetime` from a new calendar provider), the entire agent `execute()` loop crashes with an unhandled `TypeError`, with no error result returned to the caller. This is a production crash risk for any handler that introduces non-primitive return types. Fix: wrap in `try/except (TypeError, ValueError)` and fall back to `str(result)`.

### 🟡 Warning

- **`mcp_tools/dispatch_tools.py:125-126`** — `classify_and_resolve(config, task)` called without `memory_store`. Every triage API call (one per dispatched agent when `use_triage=True`) is untracked. With `use_triage=True` as default, all production triage costs are invisible in `get_api_usage_summary`. Fix: pass `memory_store=state.memory_store` as a keyword argument.

- **`agents/registry.py:113`** — `_load_yaml()` silently returns `None` on any parse/validation error with no log output. A YAML file corrupted by a bad edit or an agent config with a newly-invalid capability name disappears from the registry invisibly. Fix: add `logger.warning("Skipping %s: %s", path, e)` in the except clause. Registry module has zero logging — add `logger = logging.getLogger(__name__)`.

- **`agents/base.py:268`** — `get_tools()` called on every tool call for capability enforcement, rebuilding the schema list from scratch each time. Over 25 rounds with multiple tool calls per round, this is 50-100+ redundant list constructions per agent execution. Fix: cache the result of `get_tools()` at `execute()` start alongside `_system_prompt_cache`, reuse throughout the loop.

- **`agents/factory.py:72`** — `validate_capabilities()` can raise `ValueError` if the LLM hallucinates an unknown capability name. The exception propagates uncaught from `create_agent()`. The AGENT_CREATION_PROMPT lists valid capabilities, but LLM non-compliance is a real failure mode. Fix: catch `ValueError` at line 72 and re-raise as a descriptive error, or filter unknowns instead of raising.

### 🟢 Note

- `base.py:284-296`: After-hooks fire with raw coroutine object as `result` for async (web browser) tool handlers. Acknowledged in a code comment. The audit log records `<coroutine object ...>` instead of the actual result. Low severity but worth resolving if audit trail fidelity matters — move hook fire to after the `await result` in `execute()`.

- `capabilities/registry.py` is 1,155 lines of mostly static data. No functional issue, but migrating `TOOL_SCHEMAS` and `CAPABILITY_DEFINITIONS` to a YAML file would reduce the review surface and allow non-Python tooling to consume capability definitions.

- `triage.py` creates a new `anthropic.Anthropic` client per call (no pooling). Under bursty dispatch this creates N new HTTP clients for N agents triaged. Low impact at current scale, worth noting if dispatch frequency increases.

- `MailMixin._handle_mail_send()` (`mixins.py:288`) hardcodes `confirm_send=True`, bypassing the boolean guard in the underlying mail store. This is intentional and documented — agents are trusted at the capability layer — but it merits a security note that `mail_write` capability is effectively unconditional.

- `LoopDetector` A-B-A-B detection escalates to `break` at count 5 (same as the single-key threshold), not via a separate ABAB counter. This means two alternating tools that have each been called 5 times individually would break even if the ABAB pattern only appeared recently. Behavior is reasonable but may over-terminate in some edge cases.

---

## Verdict

The agent system is fully implemented, well-tested (210 tests, all passing), and architecturally sound. The main production risk is the unguarded `json.dumps(result)` at `base.py:174` — any tool handler returning a non-serializable type crashes the agent's execution loop with no recovery. The triage API call not passing `memory_store` is a secondary concern that silently corrupts cost tracking. The registry's silent failure on corrupted YAML is a operability gap. All three issues are straightforward one-line fixes.
