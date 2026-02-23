# Intelligent Model Routing for Expert Agents

**Date**: 2026-02-22
**Status**: Approved
**Backlog**: jarvis_backlog_013_intelligent_model_routing

## Problem

All 44 expert agents use a single hardcoded model (`claude-sonnet-4-5-20250929`) regardless of task complexity. A JSON classifier (`inbox_triage`, 512 max_tokens) uses the same model as a deep analysis agent (`security_auditor`, 4096 max_tokens). This wastes cost and latency on simple tasks.

## Design

### Model Tier Mapping

Add a `MODEL_TIERS` dict to `config.py` mapping short tier names to full model IDs:

```python
MODEL_TIERS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
}
DEFAULT_MODEL_TIER = "sonnet"
```

When Anthropic releases new models, update one dict — not 44 YAML files.

### AgentConfig Schema Change

Add optional `model` field to `AgentConfig` dataclass in `agents/registry.py`:

```python
model: str = "sonnet"  # tier name resolved at API call time
```

Update `save_agent()` to persist the field and `_load_yaml()` to load it. Default is `"sonnet"` for backward compatibility — existing YAML configs without a `model` field continue working unchanged.

### API Call Resolution

In `agents/base.py`, `_call_api()` resolves the tier name to a model ID:

```python
model_id = app_config.MODEL_TIERS.get(
    self.config.model,
    app_config.MODEL_TIERS[app_config.DEFAULT_MODEL_TIER],
)
kwargs = {"model": model_id, ...}
```

If an agent config has an unrecognized tier name, it falls back to the default tier.

### Agent Factory

`agents/factory.py` uses `"haiku"` tier for generating agent configs. This is structured JSON output that doesn't require deep reasoning.

### Agent Classifications

**Haiku (9 agents)** — classifiers, formatters, structured review templates:
- `inbox_triage` (JSON classifier, temp 0.0, 512 tokens)
- `communications` (message relay, temp 0.2)
- `scheduler` (slot finding, mechanical)
- `project_review_architecture` (template-driven, temp 0.2)
- `project_review_board` (assembles specialist reviews, temp 0.2)
- `project_review_delivery` (checklist evaluation, temp 0.2)
- `project_review_product` (rubric scoring, temp 0.2)
- `project_review_reliability` (risk checklist, temp 0.2)
- `project_review_security` (threat model templates, temp 0.2)

**Sonnet (35 agents)** — analysis, synthesis, research. Default tier, no YAML change needed.

**Opus (0 agents for now)** — reserved for future judgment engine. `cto`, `architecture_reviewer`, and `daily_briefing` are candidates but stay on sonnet until Opus is validated for these use cases.

### Model Selection Strategy

Strict YAML-based: each agent uses exactly the model in its config. No auto-fallback, no runtime override. If Haiku isn't good enough for an agent, change its YAML.

### Backward Compatibility

- Existing YAML configs without `model` field default to `"sonnet"`
- `DEFAULT_MODEL` constant remains in config.py for any non-agent code that references it
- No breaking changes to any existing API or test

## Files Modified

| File | Change |
|------|--------|
| `config.py` | Add `MODEL_TIERS` dict and `DEFAULT_MODEL_TIER` |
| `agents/registry.py` | Add `model` field to `AgentConfig`, update save/load |
| `agents/base.py` | Resolve tier in `_call_api()` |
| `agents/factory.py` | Use `"haiku"` for config generation |
| 9 YAML configs | Add `model: haiku` |
| `tests/test_agent_base.py` | Test tier resolution, default fallback |
| `tests/test_agent_factory.py` | Test factory uses haiku |
| `tests/test_agent_registry.py` | Test model field round-trip |

## Cost Impact

- 9 simple agents: ~75-80% cost reduction per call (Haiku vs Sonnet)
- 35 standard agents: no change
- Factory calls: ~75-80% cost reduction
- Net: significant savings on high-frequency agents like inbox_triage and scheduler
