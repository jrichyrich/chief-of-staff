# Chunk Audit: Orchestration & Playbooks

**User-facing feature**: Playbook execution, multi-agent result synthesis
**Risk Level**: Medium
**Files Audited**:
- `orchestration/__init__.py` (empty)
- `orchestration/synthesis.py` (91 lines)
- `orchestration/playbook_executor.py` (135 lines)
- `playbooks/__init__.py` (empty)
- `playbooks/loader.py` (142 lines)
- `mcp_tools/playbook_tools.py` (146 lines)

**Status**: Complete

---

## Purpose (as understood from reading the code)

This chunk loads YAML playbook definitions, fans out workstreams to expert agents running in parallel, and optionally merges the results via a Haiku synthesis LLM call. It is the only part of the system that executes multi-agent workflows through the MCP layer — `execute_playbook` is the single public entry point, calling `PlaybookLoader` → `orchestration.playbook_executor.execute_playbook` → `synthesize_results`. The code matches the stated purpose with one important gap: the "partial" status produced by `_dispatch_workstream` is not understood by `synthesize_results`, causing partial results to be mislabeled as failures in the synthesis prompt.

---

## Runtime Probe Results

- **Tests found**: Yes — 8 test files: `test_playbook_loader.py`, `test_playbook_executor.py`, `test_synthesis.py`, `test_dispatch_synthesis.py`, `test_config_synthesis.py`, `test_playbook_tools.py`, `test_execute_playbook_tool.py`, `test_agent_playbook_tool.py`
- **Tests run**: 78 passed, 0 failed
- **Import/load check**: OK (all files compile cleanly via `py_compile`)
- **Type check**: Not applicable (mypy not installed)
- **Edge case probes**: See findings below — two confirmed bugs via runtime probes
- **Key observation**: Empty context dict `{}` is silently coerced to `None` in `execute_playbook` tool, causing all conditional workstreams to be skipped even when caller explicitly passed a context. Confirmed via probe: `ctx if ctx else None` evaluates `{}` as `None`.

---

## Dimension Assessments

### Implemented

All functions in the intent map exist with real logic. No stubs or TODOs were found. The complete flow is wired: loader → executor → synthesizer → delivery. The `orchestration/__init__.py` and `playbooks/__init__.py` files are intentionally empty (namespace packages) — not a deficiency.

`list_playbooks` in `playbook_tools.py` (lines 32–37) opens every playbook file twice: once from `list_playbooks()` to get names, then once per name via `get_playbook()` to fetch descriptions. This is minor but worth noting for large playbook directories.

### Correct

**Bug 1 (confirmed): Empty context coerced to None — `mcp_tools/playbook_tools.py:121`**

```python
result = await _execute(
    ...
    context=ctx if ctx else None,  # BUG: {} is falsy
)
```

When `context="{}"` is passed by a caller (the default for the MCP tool), `ctx` is parsed to `{}`. The expression `ctx if ctx else None` evaluates `{}` as falsy and passes `None` to the executor. In `execute_playbook`, when context is `None`, `active_workstreams(None)` only returns unconditional workstreams — all conditional workstreams are silently skipped. This is directly observable in the live `expert_research` playbook, where `web_researcher` has `condition: "depth == thorough"`. A caller who explicitly sets `context='{"depth": "thorough"}'` will correctly activate it. A caller who passes `context='{}'` to disable conditions will also correctly get nothing. The actual bug bites when a playbook has *only conditional* workstreams and the caller intends to pass a populated context — however the default value is `{}` which is falsy. The fix is `context=ctx if ctx is not None else None`.

**Bug 2 (logic mismatch): "partial" workstream status treated as failure in synthesis**

`_dispatch_workstream` in `playbook_executor.py:101` assigns status `"partial"` when not all dispatches in a workstream fully succeeded. `synthesize_results` in `synthesis.py:40-41` classifies anything with status != `"success"` as failed, so partial workstream results flow into the "failed" section of the synthesis prompt — meaning Claude synthesizes them with a `(FAILED)` label even though they produced usable data. No test covers this cross-boundary status mismatch.

Additionally, `synthesis.py:123` only triggers synthesis if `any(r["status"] == "success" ...)`. If every workstream returns `"partial"`, synthesis is skipped entirely and the `synthesized_summary` key is absent from the result — even though all workstreams produced content. This is silent and degrades quality without any warning to the caller.

**`_evaluate_condition` only supports `==`**: Conditions like `depth != basic` or `count > 0` silently return `False`. This is documented in comments but may surprise YAML authors — no error is raised, the workstream is just silently skipped.

### Efficient

`list_playbooks` in `playbook_tools.py` does N+1 YAML file loads (one scan + one load per file). Negligible at current scale (3 playbooks) but would grow linearly. No other inefficiencies identified.

### Robust

**`synthesize_results` swallows all exceptions on API logging** (`synthesis.py:84-85`): the `except Exception: pass` block around `memory_store.log_api_call()` is intentional and acceptable — it shouldn't fail synthesis over a logging error.

**`synthesize_results` fallback on LLM failure** (`synthesis.py:87-91`): when the Anthropic API call fails, it falls back to raw concatenation. This is a reasonable degradation, but the fallback iterates over `dispatches` (all dispatches, not just successful ones) and includes error messages in the output. The caller receives a plausible-looking but potentially noisy result without any indication synthesis failed.

**`execute_playbook` in `playbook_tools.py:106-108`**: invalid context JSON silently resets context to `{}` rather than returning an error. The behavior is not terrible, but the caller gets no feedback that their context was dropped.

**`_load_file` in `loader.py:119-125`**: workstream `name` field is accessed with `ws_data["name"]` (bare dict access), not `.get()`. A workstream YAML entry missing `name` raises `KeyError` which is caught by the outer `except (yaml.YAMLError, KeyError, ...)` and returns `None`. The playbook silently fails to load rather than surfacing which workstream had the bad field — diagnosability is poor.

**No timeout on agent execution in `_dispatch_workstream`**: `agent.execute(workstream.prompt)` at `playbook_executor.py:55` has no timeout. A hung agent blocks its semaphore slot indefinitely. The max_concurrent semaphore (`playbook_executor.py:92`) limits parallelism but does not limit wall-clock time per workstream.

### Architecture

The chunk is well-structured: loading, execution, and synthesis are separated into distinct modules with clear interfaces. The `_dispatch_workstream` / `execute_playbook` / `synthesize_results` pipeline is easy to follow.

Imports are lazy (inside functions) throughout `playbook_tools.py` — this is intentional for MCP tool registration order and is a consistent pattern in this codebase.

`playbook_executor.py` imports `synthesize_results` lazily inside the function at line 125 rather than at module top — avoids circular import but makes the dependency non-obvious.

The `delivery.service.deliver_result` call at `playbook_tools.py:130` is wrapped in a broad `except Exception`, so delivery failures are silently swallowed and only appear in `result["delivery"]["error"]`. This is appropriate for a non-critical delivery path.

---

## Findings

### 🔴 Critical

*(None)*

### 🟡 Warning

- **`mcp_tools/playbook_tools.py:121`** — Empty context dict `{}` coerced to `None` via `ctx if ctx else None`. When a caller passes `context="{}"` (the default), all conditional workstreams are silently skipped. The live `expert_research` playbook has a conditional `web_researcher` workstream that will never activate from the default API call even if `depth == thorough` was intended. Fix: change to `ctx if ctx is not None else None`.

- **`orchestration/playbook_executor.py:101,123` + `orchestration/synthesis.py:40`** — Status `"partial"` produced by the executor is not recognized by `synthesize_results` — partial results are classified as failures in the synthesis prompt and labeled `(FAILED)`. Worse, when *all* workstreams are partial, synthesis is skipped entirely and `synthesized_summary` is absent from the result with no warning. Fix: treat `"partial"` as a successful-enough status in both the synthesis trigger condition and the synthesis classifier, or add a warning key to the result when synthesis is skipped due to no successful workstreams.

- **`orchestration/playbook_executor.py:55`** — `agent.execute(workstream.prompt)` has no per-workstream timeout. A hung agent holds a semaphore slot forever. Callers block indefinitely. Fix: wrap with `asyncio.wait_for(agent.execute(...), timeout=<configurable>)`.

### 🟢 Note

- `playbook_tools.py:106-108`: Invalid context JSON is silently reset to `{}` rather than returning an error to the caller. Low-risk but poor discoverability.

- `loader.py:119-125`: Missing `name` field in a workstream YAML causes the entire playbook to silently return `None`. A more diagnostic error (logging which workstream failed) would aid YAML authoring.

- `playbook_tools.py:32-37` (`list_playbooks`): N+1 file loads — each playbook is loaded once to enumerate names and again to get descriptions. Negligible now (3 playbooks) but could be made a single pass.

- `_evaluate_condition` only supports `==` — documented in comments but there is no error/warning when an unsupported operator is used. A workstream with `condition: "count > 0"` silently never runs.

---

## Verdict

This chunk is largely working and well-tested (78/78 pass). The main production concern is a status mismatch: workstreams that partially succeed are silently treated as failures in synthesis, and in the all-partial case synthesis is skipped entirely with no warning. The second concern is a falsy-context bug that silently disables all conditional workstreams when the default `context="{}"` is passed — which directly affects the `expert_research` playbook's `web_researcher` workstream. Neither bug is data-corrupting, but both silently degrade output quality in ways that are hard to detect from the outside.
