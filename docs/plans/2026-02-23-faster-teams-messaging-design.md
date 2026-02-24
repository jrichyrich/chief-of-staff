# Faster Teams Messaging — Design

**Goal:** Reduce latency and manual intervention when sending Teams messages via Jarvis.

**Problem:** Three issues cause slowness:
1. Page state corruption after failed searches requires manual reload
2. Full names with particles (e.g. "de Oliveira") fail Teams search
3. Two-phase confirm flow is unnecessary for programmatic "Jarvis, send X" use

## Changes

### 1. Auto-Recover Page State

**File:** `browser/navigator.py` — `search_and_navigate()`

When the search bar is not found, reload the page and retry once before returning an error. This handles the common case where the Teams SPA is in a chat view or stuck state after a previous interaction.

Flow: search bar not found → `page.reload(wait_until="domcontentloaded")` → wait 3s → retry search bar lookup → error only if still not found.

### 2. Fuzzy Name Fallback

**File:** `browser/navigator.py` — `search_and_navigate()`

When the full search query returns no TOPHITS results, try progressively shorter queries:
- Original: `"Jonas de Oliveira"` → no results
- Fallback 1: Drop middle words → `"Jonas Oliveira"` (first + last only)
- Fallback 2: First word only → `"Jonas"`

After each retry, check TOPHITS results and match text against the **original** full target name.

### 3. One-Shot Send Mode

**Files:** `browser/teams_poster.py`, `mcp_tools/teams_browser_tools.py`

Add `send_message(target, message)` method to `PlaywrightTeamsPoster` that combines prepare + send without confirmation.

Add `auto_send: bool = False` parameter to `post_teams_message` MCP tool. When `True`, sends immediately and returns `{"status": "sent", ...}` instead of `{"status": "confirm_required", ...}`.

## Files Modified

| File | Change |
|------|--------|
| `browser/navigator.py` | Auto-recover + fuzzy name fallback |
| `browser/teams_poster.py` | `send_message()` one-shot method |
| `mcp_tools/teams_browser_tools.py` | `auto_send` parameter |
| `tests/test_teams_navigator.py` | Tests for recovery + fuzzy fallback |
| `tests/test_teams_poster.py` | Tests for `send_message()` |
| `tests/test_teams_browser_tools.py` | Tests for `auto_send` param |

## Not Changed

- `browser/manager.py` — no changes needed
- `browser/constants.py` — no new constants
- `capabilities/registry.py` — `auto_send` is optional, schema doesn't need updating
