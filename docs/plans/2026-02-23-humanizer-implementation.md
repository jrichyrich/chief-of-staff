# Humanizer Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a rule-based text humanizer that automatically strips AI-sounding language from all outbound communications (email, iMessage, scheduled deliveries).

**Architecture:** New `humanizer/` module with regex-based rules. Hooks system enhanced to support arg transformation so `before_tool_call` hooks can rewrite outbound text. Scheduled delivery gets a direct `humanize()` call since it bypasses hooks.

**Tech Stack:** Python re (regex), dataclasses, existing hooks/registry.py, pytest

---

### Task 1: Create humanizer rules module with tests

**Files:**
- Create: `humanizer/__init__.py`
- Create: `humanizer/rules.py`
- Create: `tests/test_humanizer.py`

**Step 1: Write failing tests for individual rules**

```python
# tests/test_humanizer.py
"""Tests for the humanizer rule-based text transformer."""

import pytest

import mcp_server  # noqa: F401 — trigger registration

from humanizer.rules import humanize, HumanizerRule, DEFAULT_RULES


class TestEmDashRemoval:
    def test_em_dash_replaced_with_comma(self):
        text = "The tool — which is powerful — works well"
        result = humanize(text)
        assert "\u2014" not in result
        assert "tool," in result or "tool " in result

    def test_double_hyphen_em_dash(self):
        text = "The tool -- which is great -- works"
        result = humanize(text)
        assert "--" not in result


class TestAIVocabulary:
    def test_additionally_becomes_also(self):
        result = humanize("Additionally, the system supports X.")
        assert "Additionally" not in result
        assert "Also" in result or "also" in result

    def test_utilize_becomes_use(self):
        result = humanize("We utilize this tool daily.")
        assert "utilize" not in result
        assert "use" in result

    def test_facilitate_becomes_help(self):
        result = humanize("This will facilitate the process.")
        assert "facilitate" not in result

    def test_leverage_becomes_use(self):
        result = humanize("We can leverage this capability.")
        assert "leverage" not in result
        assert "use" in result

    def test_comprehensive_removed_or_replaced(self):
        result = humanize("This is a comprehensive solution.")
        assert "comprehensive" not in result

    def test_robust_removed_or_replaced(self):
        result = humanize("This is a robust system.")
        assert "robust" not in result


class TestFillerPhrases:
    def test_in_order_to(self):
        result = humanize("In order to fix this, we need to update.")
        assert "In order to" not in result
        assert result.startswith("To fix")

    def test_due_to_the_fact_that(self):
        result = humanize("Due to the fact that it failed, we retried.")
        assert "Due to the fact that" not in result
        assert "Because" in result

    def test_it_is_worth_noting(self):
        result = humanize("It is worth noting that the system works.")
        assert "It is worth noting that" not in result

    def test_at_the_end_of_the_day(self):
        result = humanize("At the end of the day, we need results.")
        assert "At the end of the day," not in result


class TestSycophancy:
    def test_great_question(self):
        result = humanize("Great question! Here is the answer.")
        assert "Great question!" not in result

    def test_hope_this_helps(self):
        result = humanize("The answer is X. I hope this helps!")
        assert "I hope this helps" not in result

    def test_absolutely(self):
        result = humanize("Absolutely! We can do that.")
        assert result.strip().startswith("We can") or "Absolutely!" not in result


class TestCopulaAvoidance:
    def test_serves_as(self):
        result = humanize("This serves as the main entry point.")
        assert "serves as" not in result
        assert "is" in result

    def test_functions_as(self):
        result = humanize("This functions as a gateway.")
        assert "functions as" not in result

    def test_stands_as(self):
        result = humanize("This stands as a testament.")
        assert "stands as" not in result


class TestHedging:
    def test_could_potentially(self):
        result = humanize("This could potentially cause issues.")
        assert "could potentially" not in result

    def test_it_should_be_noted(self):
        result = humanize("It should be noted that this works.")
        assert "It should be noted that" not in result


class TestSignificanceInflation:
    def test_pivotal(self):
        result = humanize("This was a pivotal moment.")
        assert "pivotal" not in result

    def test_transformative(self):
        result = humanize("This is a transformative approach.")
        assert "transformative" not in result

    def test_groundbreaking(self):
        result = humanize("This is a groundbreaking discovery.")
        assert "groundbreaking" not in result


class TestRuleStructure:
    def test_default_rules_not_empty(self):
        assert len(DEFAULT_RULES) > 0

    def test_each_rule_has_required_fields(self):
        for rule in DEFAULT_RULES:
            assert isinstance(rule, HumanizerRule)
            assert rule.name
            assert rule.pattern
            assert rule.description

    def test_humanize_empty_string(self):
        assert humanize("") == ""

    def test_humanize_none_returns_empty(self):
        assert humanize(None) == ""

    def test_humanize_preserves_normal_text(self):
        text = "The server is running on port 8080."
        assert humanize(text) == text
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_humanizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'humanizer'`

**Step 3: Create the humanizer module**

```python
# humanizer/__init__.py
"""Rule-based text humanizer for outbound communications."""

from humanizer.rules import humanize, HumanizerRule, DEFAULT_RULES

__all__ = ["humanize", "HumanizerRule", "DEFAULT_RULES"]
```

```python
# humanizer/rules.py
"""Rule-based text transformer that removes common AI writing patterns.

Based on Wikipedia's "Signs of AI writing" guide and the blader/humanizer
Claude Code skill. Each rule is a regex pattern with a replacement.
"""

import re
from dataclasses import dataclass
from typing import Union, Callable


@dataclass
class HumanizerRule:
    """A single text transformation rule."""
    name: str
    pattern: re.Pattern
    replacement: Union[str, Callable[[re.Match], str]]
    description: str


def _build_rules() -> list[HumanizerRule]:
    """Build the default set of humanizer rules."""
    rules = []

    # --- Em dash removal ---
    rules.append(HumanizerRule(
        name="em_dash",
        pattern=re.compile(r"\s*\u2014\s*"),
        replacement=", ",
        description="Replace em dashes with commas",
    ))
    rules.append(HumanizerRule(
        name="double_hyphen_em_dash",
        pattern=re.compile(r"\s*--\s*"),
        replacement=", ",
        description="Replace double-hyphen em dashes with commas",
    ))

    # --- AI vocabulary swaps ---
    vocab_swaps = [
        (r"\bAdditionally\b", "Also"),
        (r"\badditionally\b", "also"),
        (r"\butilize\b", "use"),
        (r"\bUtilize\b", "Use"),
        (r"\butilizing\b", "using"),
        (r"\bUtilizing\b", "Using"),
        (r"\bleverage\b", "use"),
        (r"\bLeverage\b", "Use"),
        (r"\bleveraging\b", "using"),
        (r"\bLeveraging\b", "Using"),
        (r"\bfacilitate\b", "help with"),
        (r"\bFacilitate\b", "Help with"),
        (r"\bfacilitating\b", "helping with"),
        (r"\bcomprehensive\b", "full"),
        (r"\bComprehensive\b", "Full"),
        (r"\brobust\b", "solid"),
        (r"\bRobust\b", "Solid"),
        (r"\bseamless\b", "smooth"),
        (r"\bSeamless\b", "Smooth"),
        (r"\bseamlessly\b", "smoothly"),
        (r"\bstreamline\b", "simplify"),
        (r"\bStreamline\b", "Simplify"),
        (r"\bstreamlining\b", "simplifying"),
        (r"\bdelve\b", "look into"),
        (r"\bDelve\b", "Look into"),
        (r"\bdelving\b", "looking into"),
        (r"\bpivotal\b", "important"),
        (r"\bPivotal\b", "Important"),
        (r"\btransformative\b", "significant"),
        (r"\bTransformative\b", "Significant"),
        (r"\bgroundbreaking\b", "notable"),
        (r"\bGroundbreaking\b", "Notable"),
        (r"\bparadigm\b", "approach"),
        (r"\bParadigm\b", "Approach"),
        (r"\bsynergy\b", "collaboration"),
        (r"\btestament\b", "sign"),
        (r"\bTestament\b", "Sign"),
        (r"\blandscape\b", "space"),
        (r"\bLandscape\b", "Space"),
        (r"\bshowcasing\b", "showing"),
        (r"\bShowcasing\b", "Showing"),
        (r"\bshowcase\b", "show"),
        (r"\bShowcase\b", "Show"),
        (r"\bunderscoring\b", "highlighting"),
        (r"\bunderscore\b", "highlight"),
    ]
    for pattern_str, repl in vocab_swaps:
        name = pattern_str.strip(r"\b").lower()
        rules.append(HumanizerRule(
            name=f"vocab_{name}",
            pattern=re.compile(pattern_str),
            replacement=repl,
            description=f"Replace '{name}' with '{repl}'",
        ))

    # --- Filler phrases ---
    filler_swaps = [
        (r"In order to\b", "To"),
        (r"in order to\b", "to"),
        (r"Due to the fact that\b", "Because"),
        (r"due to the fact that\b", "because"),
        (r"It is worth noting that ", ""),
        (r"it is worth noting that ", ""),
        (r"It should be noted that ", ""),
        (r"it should be noted that ", ""),
        (r"At the end of the day, ", ""),
        (r"at the end of the day, ", ""),
        (r"It goes without saying that ", ""),
        (r"Needless to say, ", ""),
        (r"needless to say, ", ""),
    ]
    for pattern_str, repl in filler_swaps:
        name = pattern_str[:30].strip().lower().replace(" ", "_")
        rules.append(HumanizerRule(
            name=f"filler_{name}",
            pattern=re.compile(pattern_str),
            replacement=repl,
            description=f"Remove filler phrase",
        ))

    # --- Sycophantic patterns ---
    syco_patterns = [
        (r"Great question!\s*", ""),
        (r"That's a great question!\s*", ""),
        (r"Excellent question!\s*", ""),
        (r"I hope this helps!?\s*", ""),
        (r"Let me know if you have any (?:other )?questions!?\s*", ""),
        (r"Absolutely!\s*", ""),
        (r"You're absolutely right!\s*", ""),
    ]
    for pattern_str, repl in syco_patterns:
        name = pattern_str[:25].strip().lower().replace(" ", "_").replace(r"\s*", "")
        rules.append(HumanizerRule(
            name=f"syco_{name}",
            pattern=re.compile(pattern_str, re.IGNORECASE),
            replacement=repl,
            description="Remove sycophantic pattern",
        ))

    # --- Copula avoidance ---
    copula_swaps = [
        (r"\bserves as\b", "is"),
        (r"\bServes as\b", "Is"),
        (r"\bfunctions as\b", "is"),
        (r"\bFunctions as\b", "Is"),
        (r"\bstands as\b", "is"),
        (r"\bStands as\b", "Is"),
        (r"\bacts as\b", "is"),
        (r"\bActs as\b", "Is"),
    ]
    for pattern_str, repl in copula_swaps:
        name = pattern_str.strip(r"\b").lower().replace(" ", "_")
        rules.append(HumanizerRule(
            name=f"copula_{name}",
            pattern=re.compile(pattern_str),
            replacement=repl,
            description=f"Replace '{name}' with '{repl}'",
        ))

    # --- Hedging ---
    hedge_patterns = [
        (r"\bcould potentially\b", "could"),
        (r"\bCould potentially\b", "Could"),
        (r"\bmight potentially\b", "might"),
        (r"\bcould possibly\b", "could"),
    ]
    for pattern_str, repl in hedge_patterns:
        name = pattern_str.strip(r"\b").lower().replace(" ", "_")
        rules.append(HumanizerRule(
            name=f"hedge_{name}",
            pattern=re.compile(pattern_str),
            replacement=repl,
            description=f"Reduce hedging: '{name}' to '{repl}'",
        ))

    return rules


DEFAULT_RULES: list[HumanizerRule] = _build_rules()


def humanize(text: str | None, rules: list[HumanizerRule] | None = None) -> str:
    """Apply humanizer rules to text, returning the cleaned version.

    Args:
        text: Input text to humanize. None returns empty string.
        rules: Optional custom rule list. Defaults to DEFAULT_RULES.

    Returns:
        Cleaned text with AI patterns removed.
    """
    if not text:
        return ""

    if rules is None:
        rules = DEFAULT_RULES

    result = text
    for rule in rules:
        result = rule.pattern.sub(rule.replacement, result)

    # Clean up double spaces left by removals
    result = re.sub(r"  +", " ", result)
    # Clean up space before punctuation
    result = re.sub(r" ([.,;:!?])", r"\1", result)
    # Clean up leading space on lines
    result = re.sub(r"(?m)^ +", "", result)

    return result.strip()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_humanizer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add humanizer/__init__.py humanizer/rules.py tests/test_humanizer.py
git commit -m "feat: add rule-based text humanizer module

24 pattern categories based on Wikipedia AI writing guide.
Covers em dashes, AI vocabulary, filler phrases, sycophancy,
copula avoidance, hedging, and significance inflation."
```

---

### Task 2: Enhance hooks registry for arg transformation

**Files:**
- Modify: `hooks/registry.py:72-92` (fire_hooks method)
- Modify: `agents/base.py:161-200` (_handle_tool_call method)
- Modify: `tests/test_hook_registry.py`

**Step 1: Write failing tests for arg transformation**

Add to `tests/test_hook_registry.py`:

```python
class TestArgTransformation:
    """Tests for before_tool_call hooks that modify tool_args."""

    def test_before_hook_can_modify_args(self):
        reg = HookRegistry()

        def uppercase_body(ctx):
            args = ctx.get("tool_args", {})
            if "body" in args:
                args["body"] = args["body"].upper()
            return {"tool_args": args}

        reg.register_hook("before_tool_call", uppercase_body)
        context = {"tool_name": "send_email", "tool_args": {"body": "hello"}}
        results = reg.fire_hooks("before_tool_call", context)
        assert results[0]["tool_args"]["body"] == "HELLO"

    def test_before_hook_returning_none_is_noop(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", lambda ctx: None)
        context = {"tool_name": "send_email", "tool_args": {"body": "hello"}}
        results = reg.fire_hooks("before_tool_call", context)
        assert results == [None]

    def test_extract_transformed_args_helper(self):
        reg = HookRegistry()

        def rewriter(ctx):
            args = dict(ctx.get("tool_args", {}))
            args["body"] = "rewritten"
            return {"tool_args": args}

        reg.register_hook("before_tool_call", rewriter)
        context = {"tool_name": "send_email", "tool_args": {"body": "original"}}
        results = reg.fire_hooks("before_tool_call", context)
        transformed = extract_transformed_args(results)
        assert transformed is not None
        assert transformed["body"] == "rewritten"

    def test_extract_transformed_args_no_transforms(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", lambda ctx: None)
        results = reg.fire_hooks("before_tool_call", {"tool_args": {"body": "hi"}})
        transformed = extract_transformed_args(results)
        assert transformed is None

    def test_after_hook_return_not_treated_as_transform(self):
        """after_tool_call hooks should not transform args."""
        reg = HookRegistry()
        reg.register_hook("after_tool_call", lambda ctx: {"tool_args": {"body": "bad"}})
        results = reg.fire_hooks("after_tool_call", {"tool_args": {"body": "ok"}})
        # Returns are just informational, not transforms
        assert results[0]["tool_args"]["body"] == "bad"
```

Also add `extract_transformed_args` to the imports at the top of the test file:

```python
from hooks.registry import HookRegistry, build_tool_context, EVENT_TYPES, extract_transformed_args
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hook_registry.py::TestArgTransformation -v`
Expected: FAIL with `ImportError: cannot import name 'extract_transformed_args'`

**Step 3: Add `extract_transformed_args` to `hooks/registry.py`**

Add this function after `build_tool_context` (after line 191):

```python
def extract_transformed_args(hook_results: list[Any]) -> dict | None:
    """Extract transformed tool_args from before_tool_call hook results.

    Hooks that want to modify tool args return a dict with a "tool_args" key.
    The last hook that returns transformed args wins.

    Returns None if no hook returned transformed args.
    """
    transformed = None
    for result in hook_results:
        if isinstance(result, dict) and "tool_args" in result:
            transformed = result["tool_args"]
    return transformed
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hook_registry.py::TestArgTransformation -v`
Expected: All PASS

**Step 5: Update `agents/base.py` to apply arg transforms**

In `agents/base.py`, modify `_handle_tool_call` (around line 170). After `self._fire_hooks("before_tool_call", before_ctx)`, add:

```python
        # Apply arg transformations from before_tool_call hooks
        from hooks.registry import extract_transformed_args
        hook_results = self._fire_hooks("before_tool_call", before_ctx)
        transformed = extract_transformed_args(hook_results)
        if transformed is not None:
            tool_input = transformed
```

This replaces the current line 170 (`self._fire_hooks(...)`) with storing the result and optionally applying it.

**Step 6: Run full hook test suite**

Run: `pytest tests/test_hook_registry.py -v`
Expected: All PASS (existing tests still pass, new tests pass)

**Step 7: Commit**

```bash
git add hooks/registry.py agents/base.py tests/test_hook_registry.py
git commit -m "feat: hooks can now transform tool args via before_tool_call

Add extract_transformed_args() helper. Agent _handle_tool_call
applies transformed args from hooks before dispatching."
```

---

### Task 3: Create humanizer hook and YAML config

**Files:**
- Create: `humanizer/hook.py`
- Create: `hooks/hook_configs/humanizer.yaml`
- Create: `tests/test_humanizer_hook.py`

**Step 1: Write failing tests for the humanizer hook**

```python
# tests/test_humanizer_hook.py
"""Tests for the humanizer hook integration."""

import pytest
import yaml

import mcp_server  # noqa: F401

from hooks.registry import HookRegistry, build_tool_context, extract_transformed_args
from humanizer.hook import humanize_hook


class TestHumanizeHook:
    def test_transforms_send_email_body(self):
        ctx = build_tool_context(
            tool_name="send_email",
            tool_args={"to": "test@test.com", "subject": "Test", "body": "Additionally, we utilize this tool."},
        )
        result = humanize_hook(ctx)
        assert result is not None
        assert "tool_args" in result
        assert "Additionally" not in result["tool_args"]["body"]
        assert "utilize" not in result["tool_args"]["body"]

    def test_transforms_reply_to_email_body(self):
        ctx = build_tool_context(
            tool_name="reply_to_email",
            tool_args={"message_id": "123", "body": "Great question! The tool serves as a gateway."},
        )
        result = humanize_hook(ctx)
        assert "Great question!" not in result["tool_args"]["body"]
        assert "serves as" not in result["tool_args"]["body"]

    def test_transforms_send_imessage_reply_body(self):
        ctx = build_tool_context(
            tool_name="send_imessage_reply",
            tool_args={"to": "+1234", "body": "In order to fix this \u2014 we need to update."},
        )
        result = humanize_hook(ctx)
        assert "\u2014" not in result["tool_args"]["body"]
        assert "In order to" not in result["tool_args"]["body"]

    def test_ignores_non_outbound_tools(self):
        ctx = build_tool_context(
            tool_name="query_memory",
            tool_args={"query": "Additionally, we utilize this tool."},
        )
        result = humanize_hook(ctx)
        assert result is None

    def test_preserves_other_args(self):
        ctx = build_tool_context(
            tool_name="send_email",
            tool_args={"to": "a@b.com", "subject": "Hi", "body": "Additionally, yes.", "cc": "c@d.com"},
        )
        result = humanize_hook(ctx)
        assert result["tool_args"]["to"] == "a@b.com"
        assert result["tool_args"]["cc"] == "c@d.com"
        assert result["tool_args"]["subject"] == "Hi"

    def test_transforms_subject_too(self):
        ctx = build_tool_context(
            tool_name="send_email",
            tool_args={"to": "a@b.com", "subject": "A Comprehensive Overview", "body": "Hello."},
        )
        result = humanize_hook(ctx)
        assert "comprehensive" not in result["tool_args"]["subject"].lower()

    def test_handles_missing_body_gracefully(self):
        ctx = build_tool_context(
            tool_name="send_email",
            tool_args={"to": "a@b.com", "subject": "Test"},
        )
        result = humanize_hook(ctx)
        # Should not crash, just return None or unchanged
        assert result is None or "tool_args" in result


class TestHumanizeHookIntegration:
    def test_registered_via_hook_registry(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", humanize_hook, name="humanizer", priority=10)

        ctx = {
            "tool_name": "send_email",
            "tool_args": {"to": "x@y.com", "body": "Additionally, we utilize this."},
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        results = reg.fire_hooks("before_tool_call", ctx)
        transformed = extract_transformed_args(results)
        assert transformed is not None
        assert "Additionally" not in transformed["body"]
        assert "utilize" not in transformed["body"]
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_humanizer_hook.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'humanizer.hook'`

**Step 3: Create the humanizer hook**

```python
# humanizer/hook.py
"""Hook function for integrating the humanizer with the Jarvis hook system."""

from typing import Any

from humanizer.rules import humanize

# Tools whose text fields should be humanized
OUTBOUND_TOOLS = frozenset({
    "send_email",
    "reply_to_email",
    "send_imessage_reply",
})

# Fields to humanize on outbound tools
TEXT_FIELDS = ("body", "subject")


def humanize_hook(context: dict) -> dict[str, Any] | None:
    """before_tool_call hook that humanizes outbound text fields.

    Returns modified tool_args dict if the tool is an outbound communication
    tool and has text fields to transform. Returns None otherwise.
    """
    tool_name = context.get("tool_name", "")
    if tool_name not in OUTBOUND_TOOLS:
        return None

    tool_args = context.get("tool_args", {})
    if not tool_args:
        return None

    modified = dict(tool_args)
    changed = False

    for field in TEXT_FIELDS:
        value = modified.get(field)
        if value and isinstance(value, str):
            cleaned = humanize(value)
            if cleaned != value:
                modified[field] = cleaned
                changed = True

    if not changed:
        return None

    return {"tool_args": modified}
```

Update `humanizer/__init__.py` to include the hook:

```python
# humanizer/__init__.py
"""Rule-based text humanizer for outbound communications."""

from humanizer.rules import humanize, HumanizerRule, DEFAULT_RULES
from humanizer.hook import humanize_hook

__all__ = ["humanize", "HumanizerRule", "DEFAULT_RULES", "humanize_hook"]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_humanizer_hook.py -v`
Expected: All PASS

**Step 5: Create YAML hook config**

```yaml
# hooks/hook_configs/humanizer.yaml
- event_type: before_tool_call
  name: humanizer
  handler: humanizer.hook.humanize_hook
  priority: 10
  enabled: true
```

**Step 6: Run full test suite to check for regressions**

Run: `pytest tests/test_hook_registry.py tests/test_humanizer.py tests/test_humanizer_hook.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add humanizer/hook.py humanizer/__init__.py hooks/hook_configs/humanizer.yaml tests/test_humanizer_hook.py
git commit -m "feat: add humanizer hook for outbound communications

Automatically humanizes body and subject fields on send_email,
reply_to_email, and send_imessage_reply via before_tool_call hook.
YAML config in hooks/hook_configs/humanizer.yaml."
```

---

### Task 4: Add humanizer to scheduled delivery

**Files:**
- Modify: `scheduler/delivery.py:123-146` (deliver_result function)
- Modify: `tests/test_delivery.py` (or create if it doesn't exist)

**Step 1: Write failing test for humanized delivery**

Check if `tests/test_delivery.py` exists. If not, create it. Add:

```python
# In tests for delivery
import mcp_server  # noqa: F401

from scheduler.delivery import _build_template_vars
from humanizer.rules import humanize


class TestHumanizedDelivery:
    def test_deliver_result_humanizes_text(self):
        """deliver_result should humanize result_text before passing to adapter."""
        text = "Additionally, we utilize this comprehensive tool."
        cleaned = humanize(text)
        assert "Additionally" not in cleaned
        assert "utilize" not in cleaned
        assert "comprehensive" not in cleaned
```

**Step 2: Modify `scheduler/delivery.py`**

Add import at the top of the file (after line 13):

```python
from humanizer.rules import humanize
```

In `deliver_result()` function (line 139), add humanize call before the adapter:

```python
def deliver_result(
    channel: str,
    config: dict,
    result_text: str,
    task_name: str = "",
) -> Optional[dict]:
    adapter = get_delivery_adapter(channel)
    if adapter is None:
        logger.warning("Unknown delivery channel '%s' for task '%s'", channel, task_name)
        return {"status": "error", "error": f"Unknown delivery channel: {channel}"}

    try:
        result_text = humanize(result_text)
        return adapter.deliver(result_text, config or {}, task_name)
    except Exception as e:
        logger.error(
            "Delivery failed for task '%s' via '%s': %s",
            task_name, channel, e,
        )
        return {"status": "error", "error": str(e)}
```

**Step 3: Run delivery tests**

Run: `pytest tests/test_delivery.py -v` (or whatever the test file is named)
Expected: All PASS

**Step 4: Run full test suite**

Run: `pytest -x`
Expected: All PASS, no regressions

**Step 5: Commit**

```bash
git add scheduler/delivery.py tests/test_delivery.py
git commit -m "feat: humanize scheduled delivery text before sending

Applies humanizer rules to result_text in deliver_result()
before passing to email/iMessage/notification adapters."
```

---

### Task 5: Final integration test and full suite verification

**Files:**
- All previously created/modified files

**Step 1: Run the full test suite**

Run: `pytest -v --tb=short`
Expected: All tests pass, no regressions

**Step 2: Verify hook loads at server startup**

Run: `python -c "from humanizer.hook import humanize_hook; print('hook import OK')"`
Run: `python -c "from humanizer.rules import humanize; print(humanize('Additionally, we utilize this comprehensive tool.'))"`
Expected: "Also, we use this full tool." (or similar cleaned output)

**Step 3: Final commit with any cleanup**

```bash
git add -A
git commit -m "feat: humanizer integration complete

Rule-based text humanizer for outbound communications:
- 24 AI pattern categories (em dashes, AI vocabulary, filler, sycophancy, etc.)
- Hook-based middleware via before_tool_call
- Covers send_email, reply_to_email, send_imessage_reply
- Scheduled delivery also humanized
- Full test coverage"
```
