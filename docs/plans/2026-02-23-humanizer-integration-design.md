# Humanizer Integration Design

**Date:** 2026-02-23
**Status:** Approved

## Problem

Jarvis-generated outbound communications (emails, iMessages, scheduled deliveries) sound like AI wrote them. Common tells: em dashes, filler phrases ("In order to"), AI vocabulary ("utilize", "facilitate", "comprehensive"), sycophantic openers, excessive hedging, significance inflation.

## Scope

Outbound communications only:
- `send_email` / `reply_to_email` (Apple Mail)
- `send_imessage_reply` (Apple Messages)
- Scheduled delivery adapters (email, iMessage, notification)

NOT in scope: internal storage (decisions, delegations, agent memory), agent responses, documents.

## Design

### 1. New Module: `humanizer/rules.py`

Rule-based text transformer. Each rule is a dataclass with:
- `name`: identifier
- `pattern`: compiled regex
- `replacement`: string or callable
- `description`: what it catches

Main function: `humanize(text: str) -> str` runs all rules in sequence.

Key rules (based on blader/humanizer repo, 24 patterns):
- Em dash removal (replace with commas or periods)
- AI vocabulary swaps ("additionally" -> "also", "utilize" -> "use", "facilitate" -> "help")
- Filler phrase reduction ("In order to" -> "To", "Due to the fact that" -> "Because")
- Sycophantic opener stripping ("Great question!", "I hope this helps!")
- Excessive hedging collapse ("could potentially possibly" -> "may")
- Significance inflation flags ("pivotal", "transformative", "groundbreaking")
- Copula avoidance fixes ("serves as" -> "is", "functions as" -> "is")
- Bold/emoji removal from body text

Rules stored as a list, easy to add/remove over time.

### 2. Hooks Enhancement: `hooks/registry.py`

Current `before_tool_call` hooks are informational (fire-and-forget). Enhancement:
- `before_tool_call` hooks can return a modified `tool_args` dict
- If hook returns `None`, args pass through unchanged (backward compatible)
- Multiple hooks chain: each receives the args from the previous hook

Hook function signature change:
```python
# Before (informational)
def fire_hooks(event, context) -> None

# After (transformational for before_tool_call)
def fire_hooks(event, context) -> Optional[dict]
```

### 3. Humanizer Hook Config: `hooks/humanizer.yaml`

```yaml
name: humanizer
event: before_tool_call
handler: humanizer.rules.humanize_hook
priority: 10
enabled: true
tools:
  - send_email
  - reply_to_email
  - send_imessage_reply
fields:
  - body
  - subject
```

The `humanize_hook` function:
1. Checks if `tool_name` is in configured tools list
2. For each field in the fields list, runs `humanize()` on `tool_args[field]`
3. Returns modified `tool_args`

### 4. Scheduled Delivery Coverage: `scheduler/delivery.py`

Delivery adapters bypass MCP tools, so hooks don't fire. Add a direct call:

```python
from humanizer.rules import humanize

# In deliver_result(), before passing to adapter:
result_text = humanize(result_text)
```

One line covers all three delivery channels (email, iMessage, notification).

### 5. User Experience

The `confirm_send` flow is unchanged:
1. User asks Jarvis to send email
2. Jarvis drafts text (may contain AI-isms)
3. Humanizer hook transforms text before `send_email` executes
4. `confirm_send=False` returns preview with humanized text
5. User reviews, confirms with `confirm_send=True`
6. Humanized text goes out

### 6. Testing

- `tests/test_humanizer.py`: Unit tests for each rule
- `tests/test_humanizer_hook.py`: Integration test that `before_tool_call` hook modifies args on `send_email`
- Test that scheduled delivery applies humanizer
- Test that `confirm_send=False` preview shows humanized text

## Files to Create/Modify

| Action | File |
|--------|------|
| Create | `humanizer/__init__.py` |
| Create | `humanizer/rules.py` |
| Modify | `hooks/registry.py` (support arg transformation) |
| Create | `hooks/configs/humanizer.yaml` |
| Modify | `scheduler/delivery.py` (add humanize call) |
| Create | `tests/test_humanizer.py` |
| Create | `tests/test_humanizer_hook.py` |
