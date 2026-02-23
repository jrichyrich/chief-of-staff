# Dynamic Complexity Triage — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a lightweight Haiku pre-call that classifies task complexity before agent dispatch, downgrading sonnet agents to haiku for simple tasks.

**Architecture:** New `agents/triage.py` module with `classify_complexity` (Haiku API call) and `classify_and_resolve` (config override). Integrated into `EventDispatcher._dispatch_single` only — automated dispatches, not interactive MCP calls.

**Tech Stack:** Python, Anthropic SDK (sync client), dataclasses.replace, pytest

---

### Task 1: Create triage module with classify_complexity

**Files:**
- Create: `agents/triage.py`
- Create: `tests/test_triage.py`

**Step 1: Write the failing tests**

Create `tests/test_triage.py`:

```python
"""Tests for dynamic complexity triage."""

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from agents.registry import AgentConfig
from agents.triage import classify_complexity, classify_and_resolve

TRIAGE_PROMPT_PREFIX = "Given this task and agent description"


def _make_agent_config(model="sonnet", name="test-agent", description="A test agent"):
    return AgentConfig(
        name=name,
        description=description,
        system_prompt="You are a test agent.",
        capabilities=["memory_read"],
        model=model,
    )


def _mock_response(text):
    """Create a mock Anthropic response with the given text."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


class TestClassifyComplexity:
    def test_returns_simple(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config()
        result = classify_complexity("Check status", config, client=client)
        assert result == "simple"

    def test_returns_standard(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("standard")
        config = _make_agent_config()
        result = classify_complexity("Analyze the incident report", config, client=client)
        assert result == "standard"

    def test_returns_complex(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("complex")
        config = _make_agent_config()
        result = classify_complexity("Deep security audit", config, client=client)
        assert result == "complex"

    def test_strips_whitespace(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("  simple\n")
        config = _make_agent_config()
        result = classify_complexity("task", config, client=client)
        assert result == "simple"

    def test_api_error_returns_standard(self):
        client = MagicMock()
        client.messages.create.side_effect = Exception("API down")
        config = _make_agent_config()
        result = classify_complexity("task", config, client=client)
        assert result == "standard"

    def test_unexpected_response_returns_standard(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("I think this is medium difficulty")
        config = _make_agent_config()
        result = classify_complexity("task", config, client=client)
        assert result == "standard"

    def test_uses_haiku_model(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config()
        classify_complexity("task", config, client=client)
        call_kwargs = client.messages.create.call_args.kwargs
        import config as app_config
        assert call_kwargs["model"] == app_config.MODEL_TIERS["haiku"]

    def test_max_tokens_is_small(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config()
        classify_complexity("task", config, client=client)
        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] <= 10

    def test_task_text_truncated(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config()
        long_task = "x" * 5000
        classify_complexity(long_task, config, client=client)
        call_kwargs = client.messages.create.call_args.kwargs
        prompt_text = call_kwargs["messages"][0]["content"]
        # Task text in prompt should be truncated to 1000 chars
        assert len(prompt_text) < 1500

    def test_prompt_includes_agent_info(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config(name="incident-responder", description="Handles incidents")
        classify_complexity("Server is down", config, client=client)
        call_kwargs = client.messages.create.call_args.kwargs
        prompt_text = call_kwargs["messages"][0]["content"]
        assert "incident-responder" in prompt_text
        assert "Handles incidents" in prompt_text
        assert "Server is down" in prompt_text

    def test_creates_client_if_none(self):
        """When no client is passed, creates one internally."""
        config = _make_agent_config()
        with patch("agents.triage.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _mock_response("simple")
            mock_anthropic.Anthropic.return_value = mock_client
            result = classify_complexity("task", config)
            assert result == "simple"
            mock_anthropic.Anthropic.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_triage.py::TestClassifyComplexity -v`
Expected: FAIL — `agents.triage` module does not exist

**Step 3: Implement classify_complexity**

Create `agents/triage.py`:

```python
"""Dynamic complexity triage for expert agent dispatch.

Before dispatching an agent, a lightweight Haiku call classifies the task
as simple/standard/complex. Simple tasks get downgraded to haiku tier.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Optional

import anthropic

import config as app_config
from agents.registry import AgentConfig

logger = logging.getLogger("jarvis-triage")

_VALID_CLASSIFICATIONS = {"simple", "standard", "complex"}

_TRIAGE_PROMPT = (
    "Given this task and agent description, classify the reasoning depth required.\n"
    "Agent: {name} — {description}\n"
    "Task: {task}\n"
    "Reply with exactly one word: simple, standard, or complex."
)


def classify_complexity(
    task_text: str,
    agent_config: AgentConfig,
    client: Optional[anthropic.Anthropic] = None,
) -> str:
    """Classify task complexity using a Haiku pre-call.

    Returns 'simple', 'standard', or 'complex'.
    On any error, returns 'standard' (safe fallback).
    """
    if client is None:
        client = anthropic.Anthropic(api_key=app_config.ANTHROPIC_API_KEY)

    prompt = _TRIAGE_PROMPT.format(
        name=agent_config.name,
        description=agent_config.description,
        task=task_text[:1000],
    )

    try:
        response = client.messages.create(
            model=app_config.MODEL_TIERS["haiku"],
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip().lower()
        if text in _VALID_CLASSIFICATIONS:
            return text
        logger.warning("Triage returned unexpected value: %r, defaulting to standard", text)
        return "standard"
    except Exception as e:
        logger.warning("Triage classification failed: %s, defaulting to standard", e)
        return "standard"
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_triage.py::TestClassifyComplexity -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agents/triage.py tests/test_triage.py
git commit -m "feat: add classify_complexity for dynamic triage"
```

---

### Task 2: Add classify_and_resolve to triage module

**Files:**
- Modify: `agents/triage.py`
- Modify: `tests/test_triage.py`

**Step 1: Write the failing tests**

Add to `tests/test_triage.py`:

```python
class TestClassifyAndResolve:
    def test_simple_downgrades_sonnet_to_haiku(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config(model="sonnet")
        result = classify_and_resolve(config, "Check status", client=client)
        assert result.model == "haiku"
        # Original config unchanged
        assert config.model == "sonnet"

    def test_standard_keeps_sonnet(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("standard")
        config = _make_agent_config(model="sonnet")
        result = classify_and_resolve(config, "Analyze incident", client=client)
        assert result.model == "sonnet"

    def test_complex_keeps_sonnet(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("complex")
        config = _make_agent_config(model="sonnet")
        result = classify_and_resolve(config, "Deep audit", client=client)
        assert result.model == "sonnet"

    def test_haiku_agent_skips_triage(self):
        client = MagicMock()
        config = _make_agent_config(model="haiku")
        result = classify_and_resolve(config, "task", client=client)
        assert result.model == "haiku"
        # API should NOT have been called
        client.messages.create.assert_not_called()

    def test_opus_agent_never_downgraded(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config(model="opus")
        result = classify_and_resolve(config, "task", client=client)
        assert result.model == "opus"
        # Opus agents skip triage entirely
        client.messages.create.assert_not_called()

    def test_returns_copy_not_original(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = _make_agent_config(model="sonnet")
        result = classify_and_resolve(config, "task", client=client)
        assert result is not config
        assert result.model == "haiku"
        assert config.model == "sonnet"

    def test_preserves_all_other_fields(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("simple")
        config = AgentConfig(
            name="my-agent",
            description="Does stuff",
            system_prompt="You do stuff.",
            capabilities=["memory_read", "calendar_read"],
            namespaces=["team-a"],
            temperature=0.5,
            max_tokens=2048,
            model="sonnet",
        )
        result = classify_and_resolve(config, "task", client=client)
        assert result.model == "haiku"
        assert result.name == "my-agent"
        assert result.description == "Does stuff"
        assert result.system_prompt == "You do stuff."
        assert result.capabilities == ["memory_read", "calendar_read"]
        assert result.namespaces == ["team-a"]
        assert result.temperature == 0.5
        assert result.max_tokens == 2048

    def test_api_error_keeps_original_model(self):
        client = MagicMock()
        client.messages.create.side_effect = Exception("API down")
        config = _make_agent_config(model="sonnet")
        result = classify_and_resolve(config, "task", client=client)
        assert result.model == "sonnet"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_triage.py::TestClassifyAndResolve -v`
Expected: FAIL — `classify_and_resolve` is imported but not defined

**Step 3: Implement classify_and_resolve**

Add to `agents/triage.py` (after `classify_complexity`):

```python
# Tiers that should never be triaged (already cheapest, or reserved for high-stakes)
_SKIP_TRIAGE_TIERS = {"haiku", "opus"}


def classify_and_resolve(
    agent_config: AgentConfig,
    task_text: str,
    client: Optional[anthropic.Anthropic] = None,
) -> AgentConfig:
    """Classify task complexity and return a (possibly downgraded) config.

    Skips triage for haiku agents (already cheapest) and opus agents (reserved).
    Returns a copy with model overridden if downgraded; original config is never mutated.
    On error, returns the original config unchanged.
    """
    if agent_config.model in _SKIP_TRIAGE_TIERS:
        return agent_config

    classification = classify_complexity(task_text, agent_config, client=client)

    if classification == "simple":
        logger.info(
            "Triage: agent=%s classification=simple, downgrading from %s to haiku",
            agent_config.name,
            agent_config.model,
        )
        return replace(agent_config, model="haiku")

    return agent_config
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_triage.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agents/triage.py tests/test_triage.py
git commit -m "feat: add classify_and_resolve for config downgrade"
```

---

### Task 3: Integrate triage into EventDispatcher

**Files:**
- Modify: `webhook/dispatcher.py:79-121`
- Modify: `tests/test_event_dispatcher.py`

**Step 1: Write the failing tests**

Add to `tests/test_event_dispatcher.py`:

```python
class TestTriageIntegration:
    @pytest.mark.asyncio
    async def test_triage_called_before_agent_creation(self, dispatcher, memory_store):
        """Triage should be called and its result used for agent config."""
        _create_event_rule(memory_store)
        event = _create_webhook_event(memory_store)

        configs_used = []

        with patch("agents.base.BaseExpertAgent") as MockAgent, \
             patch("webhook.dispatcher.classify_and_resolve") as mock_triage:
            # Triage returns a config with model=haiku
            triaged_config = AgentConfig(
                name="incident-responder",
                description="Handles incident alerts",
                system_prompt="You are an incident responder.",
                capabilities=[],
                model="haiku",
            )
            mock_triage.return_value = triaged_config

            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            await dispatcher.dispatch(event)

            # Verify triage was called
            mock_triage.assert_called_once()
            # Verify the triaged config was passed to BaseExpertAgent
            call_kwargs = MockAgent.call_args.kwargs
            assert call_kwargs["config"].model == "haiku"

    @pytest.mark.asyncio
    async def test_triage_failure_does_not_block_dispatch(self, dispatcher, memory_store):
        """If triage fails, dispatch should still work with original config."""
        _create_event_rule(memory_store)
        event = _create_webhook_event(memory_store)

        with patch("agents.base.BaseExpertAgent") as MockAgent, \
             patch("webhook.dispatcher.classify_and_resolve") as mock_triage:
            mock_triage.side_effect = Exception("Triage crashed")

            mock_instance = AsyncMock()
            mock_instance.execute.return_value = "Done"
            MockAgent.return_value = mock_instance

            results = await dispatcher.dispatch(event)

            assert len(results) == 1
            assert results[0]["status"] == "success"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_event_dispatcher.py::TestTriageIntegration -v`
Expected: FAIL — `webhook.dispatcher.classify_and_resolve` doesn't exist (not imported yet)

**Step 3: Integrate triage into _dispatch_single**

In `webhook/dispatcher.py`, add the import at the top (after existing imports):

```python
from agents.triage import classify_and_resolve
```

In `_dispatch_single`, after the agent config is loaded and input is formatted (after line 112), but before creating BaseExpertAgent (line 116), add the triage call:

Replace lines 114-121 with:

```python
            # Triage: classify complexity and potentially downgrade model
            try:
                effective_config = classify_and_resolve(agent_config, agent_input)
            except Exception:
                effective_config = agent_config

            # Execute the agent
            from agents.base import BaseExpertAgent
            agent = BaseExpertAgent(
                config=effective_config,
                memory_store=self.memory_store,
                document_store=self.document_store,
            )
            result_text = await agent.execute(agent_input)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_event_dispatcher.py -v`
Expected: ALL PASS (new tests + existing tests)

**Step 5: Commit**

```bash
git add webhook/dispatcher.py tests/test_event_dispatcher.py
git commit -m "feat: integrate triage into EventDispatcher before agent creation"
```

---

### Task 4: Run full test suite and verify no regressions

**Files:** None (verification only)

**Step 1: Run full test suite**

Run: `pytest`
Expected: All 1414+ tests pass, zero failures

**Step 2: Verify triage module is importable**

Run: `python -c "from agents.triage import classify_complexity, classify_and_resolve; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add -A
git commit -m "feat: dynamic complexity triage before agent dispatch

Add agents/triage.py with Haiku pre-call that classifies task complexity
(simple/standard/complex) before agent dispatch. Simple tasks downgrade
sonnet agents to haiku. Integrated into EventDispatcher._dispatch_single.
Haiku and opus agents skip triage. Error-isolated: triage failure never
blocks dispatch. ~$0.001 per triage call, saves $0.01-0.05 per downgrade."
```
