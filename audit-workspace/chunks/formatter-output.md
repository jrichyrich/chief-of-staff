# Chunk Audit: Formatter & Output

**User-facing feature**: Brief rendering, card formatting, tables, dashboards — all intended for delivery channels (email, iMessage, macOS notifications)
**Risk Level**: Low
**Files Audited**:
- `formatter/__init__.py`
- `formatter/brief.py`
- `formatter/cards.py`
- `formatter/console.py`
- `formatter/dashboard.py`
- `formatter/data_helpers.py`
- `formatter/styles.py`
- `formatter/tables.py`
- `formatter/text.py`
- `formatter/types.py`
- `mcp_tools/formatter_tools.py`

**Status**: Complete

## Purpose (as understood from reading the code)

This chunk provides Rich-powered ANSI terminal and plain-text rendering for structured data (calendar events, action items, delegations, decisions, OKRs, email highlights) into formatted output strings suitable for delivery channels. The dual-mode design (`terminal` vs `plain`) is sound and consistently applied. This matches the stated purpose with no divergence.

## Runtime Probe Results

- **Tests found**: Yes — 7 test files
- **Tests run**: 75 passed, 0 failed (1.34s)
- **Import/load check**: OK (Python 3.11 with project deps; `rich` module confirmed available via pytest env)
- **Type check**: Not applicable (mypy not installed in project env)
- **Edge case probes**: Run on `strip_ansi`, `priority_icon`, `_format_time`, `calendar_events_to_entries`, `decisions_to_summary`, `delegations_to_summary`, `render_daily`, `format_brief`
- **Key observation**: Two confirmed bugs — `strip_ansi(None)` raises `TypeError`, and the ANSI regex leaves the `\x1b` escape byte behind (strips only `[...m`, not the preceding ESC). Additionally, `decisions_to_summary` returns `"0 pending"` (truthy) when all decisions are non-pending, causing a visible "DECISIONS — 0 pending" panel in the brief output.

## Dimension Assessments

### Implemented

All stated functionality is fully implemented with real logic. No stubs, no TODOs, no `NotImplementedError`. Every function called in the MCP tools layer exists and has a body:
- `formatter.brief.render_daily` — complete with 9 optional section params and coercion logic
- `formatter.tables.render` — complete with padding
- `formatter.cards.render` and `render_kv` — complete
- `formatter.dashboard.render` — complete
- `formatter.data_helpers` — 6 helper functions, all implemented
- `formatter.text` — 3 utility functions, all implemented
- `mcp_tools/formatter_tools.py` — 4 MCP tools (`format_table`, `format_brief`, `format_dashboard`, `format_card`), all implemented

The `columns` parameter in `dashboard.render` is accepted and documented as "reserved for future use" — this is a known placeholder, not a gap.

### Correct

**Happy path**: All 75 tests pass and manual probes confirm core rendering works correctly. Rich tables render, ANSI/plain modes are properly controlled, coercion of plain strings to dicts works.

**Confirmed bugs:**

1. **`formatter/text.py:10` — `strip_ansi(None)` raises `TypeError`**. The regex `_ANSI_ESCAPE.sub("", text)` receives `None` and raises `TypeError: expected string or bytes-like object, got 'NoneType'`. Callers (e.g. scheduled delivery path) that pass unchecked output could hit this.

2. **`formatter/text.py:7` — ANSI regex is incomplete**. Pattern is `r"\[[0-9;]*m"` — it strips `[32m` but leaves the preceding `\x1b` (ESC, 0x1b) byte. Confirmed via probe: `strip_ansi("\x1b[32mGreen\x1b[0m")` returns `"\x1bGreen\x1b"` with ESC bytes intact. For plain-text email/iMessage delivery this is a real defect — the ESC char is invisible in terminal but appears as a garbage character in email clients.

3. **`formatter/data_helpers.py:119` — `decisions_to_summary` returns `"0 pending"` when all decisions are non-pending**. `"0 pending"` is a truthy string. When passed to `render_daily(decisions="0 pending")` it renders a visible DECISIONS section with "0 pending" content. The section should not appear when there is nothing actionable. The fix is to return `""` when `pending` count is 0.

4. **`formatter/data_helpers.py:16` — `_format_time(None)` returns `None`**. The `except (ValueError, TypeError)` block catches `TypeError` and falls through to `return iso_str` — which is `None`. Downstream, `CalendarEntry.time = None`, and `_build_calendar_table` calls `entry.get("time", "")` which returns `None` (dict `.get()` returns the stored value, not the default, if the key exists with a `None` value). Rich's `table.add_row` receives `None` but silently renders it as empty string, so this does not crash in practice. However, the return type is wrong (`None` instead of `str`).

5. **`mcp_tools/formatter_tools.py:83` — `format_brief` is vulnerable to unexpected JSON keys**. `render_daily(**parsed, mode=mode)` with unknown keys (e.g. `{"date": "...", "extra_key": "value"}`) raises `TypeError: render_daily() got an unexpected keyword argument 'extra_key'` and returns a JSON error. Confirmed via probe. Since this is an LLM-facing tool, the model may occasionally pass extra metadata keys and get an opaque error back.

### Efficient

This chunk is pure in-memory string formatting — no DB, no network, no loops over large collections. No efficiency issues. The `render_to_string` uses `StringIO` with a `seek(0)` approach which is clean and re-readable. The `get_console` factory creates a fresh Console per call which is correct (StringIO state is per-render).

### Robust

**Not robust (but contained):**
- `strip_ansi(None)` raises — no guard against `None` input.
- `priority_icon(None)` raises `AttributeError: 'NoneType' has no attribute 'lower'` — no `None` guard.
- `calendar_events_to_entries(None)` raises `TypeError: 'NoneType' object is not iterable` — callers must not pass `None`.

The formatter_tools exception handling is structured well — all four MCP tools have explicit `try/except` blocks that catch `json.JSONDecodeError` and a general `Exception`, log the stack trace, and return a JSON error dict. This prevents MCP crashes. However, the `@tool_errors` decorator is applied above the inner `try/except`, making it redundant for the expected errors but harmless.

The `delivery/service.py` caller wraps `render_daily(**data, mode="plain")` in a bare `except Exception` with a `logger.debug` fallback — so the ANSI-in-email bug only manifests if the data went through a path that bypasses `render_daily` and produced raw ANSI strings before `strip_ansi` was called.

### Architecture

**Clean overall.** The design is well-structured:
- `console.py` is a pure factory with no side effects — correctly isolated.
- `styles.py` is a pure constants module — shared cleanly.
- `types.py` provides TypedDicts — appropriate level of type documentation.
- `data_helpers.py` correctly separates data transformation from rendering.

**Minor duplication:** `formatter/brief.py` contains private builders `_build_delegation_table` (line 129) and `_build_decision_table` (line 146) that duplicate the schema knowledge in `formatter/data_helpers.py:delegations_to_table_data` and `decisions_to_table_data`. The `brief.py` builders are specialized (they drop the "Due" column for delegations, drop the "Follow-up" column for decisions) which justifies having them separate — but it means schema changes require updates in two places.

**Unregistered module exports:** `formatter/__init__.py` has only a docstring — it doesn't export anything. This is fine for a namespace package, but callers import submodules directly (`from formatter.brief import render_daily`). Acceptable given the current usage pattern.

**`dashboard.py` `columns` param** is accepted, documented, and silently ignored — this is correctly documented in the docstring as "reserved for future use." Not a bug, but if multi-column layout is never implemented, the parameter becomes permanent dead weight.

## Findings

### 🔴 Critical

- **`formatter/text.py:7`** — ANSI regex `r"\[[0-9;]*m"` does not strip the leading ESC byte (`\x1b`). `strip_ansi("\x1b[32mGreen\x1b[0m")` returns `"\x1bGreen\x1b"`. When used in email or iMessage delivery, the ESC byte appears as a garbage character (e.g. `←`) in some clients. The correct pattern is `r"\x1b\[[0-9;]*m"` (or `r"\033\[[0-9;]*m"`). This is a delivery-correctness bug affecting every terminal-mode output that goes through `strip_ansi`.

### 🟡 Warning

- **`formatter/data_helpers.py:119`** — `decisions_to_summary` returns `"0 pending"` (truthy) when no decisions are pending. This causes `render_daily` to render a visible "DECISIONS — 0 pending" section in briefs. The fix is `return "" if not pending else ...` or changing `parts = [f"{len(pending)} pending"]` to an early return when `len(pending) == 0`.

- **`formatter/text.py:10`** — `strip_ansi(None)` raises `TypeError`. No documented contract that callers must pass a string. In delivery paths where formatter output might be `None`, this would surface as an unhandled exception. Fix: add `if not isinstance(text, str): return ""` guard.

- **`mcp_tools/formatter_tools.py:83`** — `format_brief` passes `**parsed` directly to `render_daily` with no key filtering. Unknown JSON keys (e.g. metadata or extra fields an LLM might add) raise `TypeError` and return an opaque error. Fix: whitelist accepted keys, or use `**{k: v for k, v in parsed.items() if k in KNOWN_KEYS}`.

- **`formatter/data_helpers.py:16`** — `_format_time(None)` returns `None` instead of `""`. The function signature says it returns `str` but can return `None` when `iso_str` is `None` and the `except` block falls through. In practice Rich silently handles it, but it's a latent type error.

### 🟢 Note

- The `columns` parameter in `dashboard.render` is a permanently accepted-but-ignored parameter. If multi-column layout is never planned, removing it would reduce API surface confusion.
- `formatter/__init__.py` is a docstring-only module. Adding explicit `__all__` or re-exports would make the public API clearer, but is not required.
- `_build_delegation_table` in `brief.py` and `delegations_to_table_data` in `data_helpers.py` encode overlapping schema knowledge. Consider a single source of truth if the delegation schema evolves.
- `priority_icon(None)` raises `AttributeError` — same null-guard issue as `strip_ansi`.

## Verdict

The formatter chunk is well-implemented and fully tested (75/75 passing). The core rendering path is correct and the dual-mode (terminal/plain) design is sound. Two delivery-impacting bugs exist: the ANSI regex leaves ESC bytes in the output (affecting plain-text email/iMessage consumers of `strip_ansi`), and `decisions_to_summary` produces a misleading "0 pending" section in briefs. Both are straightforward one-line fixes. The `format_brief` MCP tool's `**kwargs` pass-through to `render_daily` is a usability hazard for LLM callers but not a crash path. Everything else is clean.
