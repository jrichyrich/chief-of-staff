# Intelligent Model Routing — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-agent model tier selection so simple agents use Haiku, standard agents use Sonnet, and the system is ready for Opus when needed.

**Architecture:** A `MODEL_TIERS` dict in `config.py` maps tier names (`haiku`, `sonnet`, `opus`) to full model IDs. `AgentConfig` gets a `model` field (default `"sonnet"`). `BaseExpertAgent._call_api()` resolves the tier at call time. Agent YAML configs specify their tier.

**Tech Stack:** Python dataclasses, PyYAML, Anthropic SDK, pytest

---

### Task 1: Add MODEL_TIERS to config.py

**Files:**
- Modify: `config.py:11`

**Step 1: Add the tier mapping after DEFAULT_MODEL**

In `config.py`, after line 11 (`DEFAULT_MODEL = ...`), add:

```python
MODEL_TIERS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
}
DEFAULT_MODEL_TIER = "sonnet"
```

Keep `DEFAULT_MODEL` unchanged — existing non-agent code references it.

**Step 2: Verify import works**

Run: `python -c "from config import MODEL_TIERS, DEFAULT_MODEL_TIER; print(MODEL_TIERS)"`
Expected: `{'haiku': 'claude-haiku-4-5-20251001', 'sonnet': 'claude-sonnet-4-5-20250929', 'opus': 'claude-opus-4-6'}`

**Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add MODEL_TIERS and DEFAULT_MODEL_TIER to config"
```

---

### Task 2: Add model field to AgentConfig and update registry

**Files:**
- Modify: `agents/registry.py:16-25` (AgentConfig dataclass)
- Modify: `agents/registry.py:72-85` (save_agent data dict)
- Modify: `agents/registry.py:99-108` (_load_yaml AgentConfig constructor)
- Test: `tests/test_agent_registry.py`

**Step 1: Write the failing tests**

Add to `tests/test_agent_registry.py`:

```python
class TestModelField:
    def test_default_model_is_sonnet(self, registry, configs_dir):
        """AgentConfig without model field defaults to sonnet."""
        _write_agent_yaml(configs_dir, "no-model-agent", "Test", ["memory_read"])
        config = registry.get_agent("no-model-agent")
        assert config is not None
        assert config.model == "sonnet"

    def test_model_field_persisted(self, registry):
        """model field round-trips through save/load."""
        config = AgentConfig(
            name="haiku-agent",
            description="A fast agent",
            system_prompt="You are fast.",
            capabilities=["memory_read"],
            model="haiku",
        )
        registry.save_agent(config)
        loaded = registry.get_agent("haiku-agent")
        assert loaded is not None
        assert loaded.model == "haiku"

    def test_model_field_in_yaml(self, registry, configs_dir):
        """model field is written to YAML file."""
        config = AgentConfig(
            name="opus-agent",
            description="A deep thinker",
            system_prompt="You think deeply.",
            capabilities=["memory_read"],
            model="opus",
        )
        registry.save_agent(config)
        import yaml
        raw = yaml.safe_load((configs_dir / "opus-agent.yaml").read_text())
        assert raw["model"] == "opus"

    def test_default_model_not_written_to_yaml(self, registry, configs_dir):
        """When model is the default (sonnet), it is still persisted for explicitness."""
        config = AgentConfig(
            name="default-model-agent",
            description="Default",
            system_prompt="Default.",
            capabilities=["memory_read"],
        )
        registry.save_agent(config)
        import yaml
        raw = yaml.safe_load((configs_dir / "default-model-agent.yaml").read_text())
        assert raw["model"] == "sonnet"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_registry.py::TestModelField -v`
Expected: FAIL — `AgentConfig` has no `model` parameter

**Step 3: Add model field to AgentConfig**

In `agents/registry.py`, add `model` field to the `AgentConfig` dataclass (after `max_tokens`, before `created_by`):

```python
    model: str = "sonnet"
```

**Step 4: Update save_agent to persist model**

In `agents/registry.py`, `save_agent()`, add `"model"` to the data dict (after `"max_tokens"`):

```python
        data = {
            "name": config.name,
            "description": config.description,
            "system_prompt": config.system_prompt,
            "capabilities": normalized_capabilities,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "model": config.model,
        }
```

**Step 5: Update _load_yaml to read model**

In `agents/registry.py`, `_load_yaml()`, add `model` to the `AgentConfig` constructor:

```python
            return AgentConfig(
                name=data["name"],
                description=data.get("description", ""),
                system_prompt=data.get("system_prompt", ""),
                capabilities=capabilities,
                namespaces=data.get("namespaces", []),
                temperature=data.get("temperature", 0.3),
                max_tokens=data.get("max_tokens", 4096),
                model=data.get("model", "sonnet"),
                created_by=data.get("created_by"),
                created_at=data.get("created_at"),
            )
```

**Step 6: Run tests to verify they pass**

Run: `pytest tests/test_agent_registry.py -v`
Expected: ALL PASS (new tests + existing tests)

**Step 7: Commit**

```bash
git add agents/registry.py tests/test_agent_registry.py
git commit -m "feat: add model field to AgentConfig with save/load support"
```

---

### Task 3: Resolve model tier in BaseExpertAgent._call_api

**Files:**
- Modify: `agents/base.py:136-146` (_call_api method)
- Test: `tests/test_agent_base.py`

**Step 1: Write the failing tests**

Add to `tests/test_agent_base.py`:

```python
class TestModelTierResolution:
    @pytest.mark.asyncio
    async def test_default_model_uses_sonnet(self, agent):
        """Agent with default model='sonnet' resolves to sonnet model ID."""
        agent.client.messages.create = AsyncMock(
            return_value=_make_text_response("ok")
        )
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        call_kwargs = agent.client.messages.create.call_args.kwargs
        import config as app_config
        assert call_kwargs["model"] == app_config.MODEL_TIERS["sonnet"]

    @pytest.mark.asyncio
    async def test_haiku_agent_uses_haiku_model(self, memory_store, document_store):
        """Agent with model='haiku' resolves to haiku model ID."""
        config = AgentConfig(
            name="fast-agent",
            description="Fast",
            system_prompt="Fast.",
            capabilities=["memory_read"],
            model="haiku",
        )
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_make_text_response("ok"))
        agent = BaseExpertAgent(config, memory_store, document_store, client=client)
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        call_kwargs = client.messages.create.call_args.kwargs
        import config as app_config
        assert call_kwargs["model"] == app_config.MODEL_TIERS["haiku"]

    @pytest.mark.asyncio
    async def test_opus_agent_uses_opus_model(self, memory_store, document_store):
        """Agent with model='opus' resolves to opus model ID."""
        config = AgentConfig(
            name="deep-agent",
            description="Deep",
            system_prompt="Deep.",
            capabilities=["memory_read"],
            model="opus",
        )
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_make_text_response("ok"))
        agent = BaseExpertAgent(config, memory_store, document_store, client=client)
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        call_kwargs = client.messages.create.call_args.kwargs
        import config as app_config
        assert call_kwargs["model"] == app_config.MODEL_TIERS["opus"]

    @pytest.mark.asyncio
    async def test_unknown_tier_falls_back_to_default(self, memory_store, document_store):
        """Agent with unrecognized model tier falls back to DEFAULT_MODEL_TIER."""
        config = AgentConfig(
            name="bad-tier-agent",
            description="Bad tier",
            system_prompt="Bad.",
            capabilities=["memory_read"],
            model="nonexistent_tier",
        )
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=_make_text_response("ok"))
        agent = BaseExpertAgent(config, memory_store, document_store, client=client)
        await agent._call_api([{"role": "user", "content": "hi"}], [])
        call_kwargs = client.messages.create.call_args.kwargs
        import config as app_config
        assert call_kwargs["model"] == app_config.MODEL_TIERS[app_config.DEFAULT_MODEL_TIER]
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_base.py::TestModelTierResolution -v`
Expected: FAIL — `_call_api` still uses `app_config.DEFAULT_MODEL`

**Step 3: Update _call_api to resolve model tier**

In `agents/base.py`, replace the `_call_api` method body (lines 138-146):

```python
    @retry_api_call
    async def _call_api(self, messages: list, tools: list) -> Any:
        model_id = app_config.MODEL_TIERS.get(
            self.config.model,
            app_config.MODEL_TIERS[app_config.DEFAULT_MODEL_TIER],
        )
        kwargs = {
            "model": model_id,
            "max_tokens": self.config.max_tokens,
            "system": self.build_system_prompt(),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        return await self.client.messages.create(**kwargs)
```

Add the import at top if not already present: `from config import MAX_TOOL_ROUNDS` is already there, but `MODEL_TIERS` and `DEFAULT_MODEL_TIER` are accessed via `app_config` so no new import needed.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_base.py -v`
Expected: ALL PASS (new tests + all existing tests)

**Step 5: Commit**

```bash
git add agents/base.py tests/test_agent_base.py
git commit -m "feat: resolve model tier in BaseExpertAgent._call_api"
```

---

### Task 4: Update AgentFactory to use haiku

**Files:**
- Modify: `agents/factory.py:37-38`
- Test: `tests/test_agent_factory.py`

**Step 1: Write the failing test**

Add to `tests/test_agent_factory.py`:

```python
    def test_factory_uses_haiku_model(self, factory):
        """Factory should use haiku tier for generating agent configs."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(
            type="text",
            text="""{
                "name": "test_agent",
                "description": "Test",
                "system_prompt": "Test.",
                "capabilities": ["memory_read"],
                "temperature": 0.3
            }""",
        )]

        with patch("agents.factory.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            factory.create_agent("test agent")

            call_kwargs = mock_client.messages.create.call_args.kwargs
            import config as app_config
            assert call_kwargs["model"] == app_config.MODEL_TIERS["haiku"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_factory.py::TestAgentFactory::test_factory_uses_haiku_model -v`
Expected: FAIL — factory uses `app_config.DEFAULT_MODEL` (sonnet)

**Step 3: Update factory to use haiku tier**

In `agents/factory.py`, change line 38 from:

```python
            model=app_config.DEFAULT_MODEL,
```

to:

```python
            model=app_config.MODEL_TIERS["haiku"],
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_factory.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agents/factory.py tests/test_agent_factory.py
git commit -m "feat: use haiku tier for agent factory config generation"
```

---

### Task 5: Update 9 agent YAML configs to use haiku

**Files:**
- Modify: `agent_configs/inbox_triage.yaml`
- Modify: `agent_configs/communications.yaml`
- Modify: `agent_configs/scheduler.yaml`
- Modify: `agent_configs/project_review_architecture.yaml`
- Modify: `agent_configs/project_review_board.yaml`
- Modify: `agent_configs/project_review_delivery.yaml`
- Modify: `agent_configs/project_review_product.yaml`
- Modify: `agent_configs/project_review_reliability.yaml`
- Modify: `agent_configs/project_review_security.yaml`

**Step 1: Add `model: haiku` to each YAML file**

For each of the 9 files, add `model: haiku` as a top-level key (after `max_tokens` for consistency). Example for `inbox_triage.yaml`:

```yaml
capabilities:
- memory_read
- memory_write
- channel_read
description: Classifies incoming messages...
max_tokens: 512
model: haiku
name: inbox_triage
```

Apply the same pattern to all 9 files.

**Step 2: Verify YAML loads correctly**

Run: `python -c "from agents.registry import AgentRegistry; from config import AGENT_CONFIGS_DIR; r = AgentRegistry(AGENT_CONFIGS_DIR); print([(a.name, a.model) for a in r.list_agents() if a.model == 'haiku'])"`
Expected: List of 9 `(name, 'haiku')` tuples

**Step 3: Commit**

```bash
git add agent_configs/inbox_triage.yaml agent_configs/communications.yaml agent_configs/scheduler.yaml agent_configs/project_review_architecture.yaml agent_configs/project_review_board.yaml agent_configs/project_review_delivery.yaml agent_configs/project_review_product.yaml agent_configs/project_review_reliability.yaml agent_configs/project_review_security.yaml
git commit -m "feat: assign haiku model tier to 9 simple agent configs"
```

---

### Task 6: Run full test suite and verify no regressions

**Files:** None (verification only)

**Step 1: Run full test suite**

Run: `pytest`
Expected: All 1378+ tests pass, zero failures

**Step 2: Verify haiku agents load correctly**

Run: `python -c "from agents.registry import AgentRegistry; from config import AGENT_CONFIGS_DIR; r = AgentRegistry(AGENT_CONFIGS_DIR); haiku = [a.name for a in r.list_agents() if a.model == 'haiku']; sonnet = [a.name for a in r.list_agents() if a.model == 'sonnet']; print(f'haiku: {len(haiku)}, sonnet: {len(sonnet)}, total: {len(haiku)+len(sonnet)}')"`
Expected: `haiku: 9, sonnet: 35, total: 44`

**Step 3: Final commit (squash if desired)**

```bash
git add -A
git commit -m "feat: intelligent model routing — per-agent model tier selection

Add MODEL_TIERS dict to config.py mapping tier names (haiku/sonnet/opus) to
full model IDs. Add model field to AgentConfig with default 'sonnet'. Resolve
tier in BaseExpertAgent._call_api(). Update AgentFactory to use haiku for
config generation. Assign haiku tier to 9 simple agents (classifiers,
formatters, template-driven reviews). Estimated 75-80% cost reduction for
simple agent calls."
```
