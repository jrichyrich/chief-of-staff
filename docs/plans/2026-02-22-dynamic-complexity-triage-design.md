# Dynamic Complexity Triage Before Agent Dispatch — Design

**Date**: 2026-02-22
**Status**: Approved
**Backlog**: jarvis_backlog_014_dynamic_complexity_triage

## Problem

All 35 sonnet-tier agents use the same model regardless of task complexity. A webhook delivering a simple status change gets the same expensive model as one requiring deep analysis. Static YAML config (from backlog 013) handles per-agent defaults but can't adapt to the specific task at hand.

## Design

### Triage Module: `agents/triage.py`

New module with two functions:

**`classify_complexity(task_text, agent_config, client=None) -> str`**

Makes a single Haiku call with a tight classification prompt:

```
Given this task and agent description, classify the reasoning depth required.
Agent: {name} — {description}
Task: {task_text[:1000]}
Reply with exactly one word: simple, standard, or complex.
```

Returns `"simple"`, `"standard"`, or `"complex"`. On any error (API failure, timeout, unexpected response), returns `"standard"` (safe fallback = no model change).

**`classify_and_resolve(agent_config, task_text, client=None) -> AgentConfig`**

Wrapper that:
1. Skips triage if agent is already on `"haiku"` (nothing to downgrade to)
2. Calls `classify_complexity`
3. If `"simple"` → returns a copy of the config with `model="haiku"`
4. Otherwise → returns the original config unchanged

Never mutates the original config. Never upgrades beyond the configured tier.

### Model Override Resolution

| Classification | Agent on sonnet | Agent on haiku | Agent on opus |
|---|---|---|---|
| `simple` | → haiku | skip (already cheapest) | keep opus |
| `standard` | keep sonnet | skip | keep opus |
| `complex` | keep sonnet | skip | keep opus |

Opus agents are never downgraded (reserved for high-stakes judgment).

### Integration: `EventDispatcher._dispatch_single`

After loading the agent config but before creating `BaseExpertAgent`:

```python
from agents.triage import classify_and_resolve
effective_config = classify_and_resolve(agent_config, agent_input)
agent = BaseExpertAgent(config=effective_config, ...)
```

### Triage Prompt

Kept minimal to ensure fast, cheap classification:
- Task text truncated to 1000 chars
- Response expected: single word
- Haiku model used (~$0.001 per call)
- max_tokens=10 to prevent long responses

### Error Handling

- API errors → return `"standard"` (no model change)
- Unexpected response (not one of the three words) → return `"standard"`
- Timeout → return `"standard"`
- Triage failure never blocks agent dispatch

### Exclusions

- No triage on direct MCP agent calls (interactive sessions use static config)
- No triage on scheduler handlers (they don't use expert agents)
- No new DB tables or schema changes
- No caching of triage results
- No triage for haiku or opus agents

## Files Modified

| File | Change |
|------|--------|
| `agents/triage.py` | New module: `classify_complexity`, `classify_and_resolve` |
| `webhook/dispatcher.py` | Call `classify_and_resolve` before creating agent |
| `tests/test_triage.py` | Tests for classification, resolution, error handling |
| `tests/test_event_dispatcher.py` | Test triage integration in dispatch flow |

## Cost Impact

- Triage call: ~$0.001 per dispatch (Haiku, ~50 input tokens, ~1 output token)
- Savings per downgrade: ~$0.01-0.05 (Haiku vs Sonnet)
- Break-even: >1 in 10 dispatches classified as simple
- Net: significant savings on high-frequency webhook dispatches with simple payloads
