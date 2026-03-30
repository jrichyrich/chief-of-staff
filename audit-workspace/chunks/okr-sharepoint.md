# Chunk Audit: OKR & SharePoint

**User-facing feature**: OKR status queries, OKR refresh from SharePoint
**Risk Level**: Medium
**Files Audited**:
- `okr/__init__.py` (0 lines — empty package marker)
- `okr/models.py` (77 lines)
- `okr/parser.py` (299 lines)
- `okr/store.py` (186 lines)
- `mcp_tools/okr_tools.py` (192 lines)
- `mcp_tools/sharepoint_tools.py` (162 lines)

**Status**: Complete

## Purpose (as understood from reading the code)

This chunk parses an Excel-based OKR tracker (3 tabs: Objectives, Key Results, Initiatives) using header-based column mapping, persists a JSON snapshot atomically, and exposes three MCP tools: `refresh_okr_data`, `query_okr_status`, and `refresh_okr_from_sharepoint`. The `download_from_sharepoint` tool provides a generic SharePoint file download via a persistent Playwright browser. This matches the stated purpose accurately.

## Runtime Probe Results

- **Tests found**: Yes — 7 test files (test_okr_store.py, test_okr_models.py, test_okr_parser.py, test_mcp_okr.py, test_okr_sharepoint_tool.py, test_sharepoint_tools.py, test_sharepoint_download.py)
- **Tests run**: 69 passed, 1 skipped (the skipped test is annotated with an explanatory reason — not a failure)
- **Import/load check**: OK — `from okr import models, parser, store` succeeds cleanly
- **Type check**: mypy not installed in venv; not applicable
- **Edge case probes**:
  - `_cell_pct(None)` → `0.0` (safe)
  - `_cell_pct(-0.1)` → `-10.0` (negative percentages silently pass through — see findings)
  - `_cell_pct('100%')` → `0.0` (percent-formatted strings silently become 0.0 — see findings)
  - `_cell_pct(1.5)` → `150.0` (over-100 values pass silently)
  - `_infer_filename('')` → `'sharepoint_download'` (safe fallback)
  - openpyxl in read_only mode pads short rows with `None` cells — no IndexError risk
  - `_compute_blended([], [], 'OKR1')` → `{blended_pct: 0.0}` (safe)
- **Key observation**: `_format_okr_results` in `okr_tools.py` is dead code — it looks for key `"results"` in a dict that always has keys `"objectives"`, `"key_results"`, `"initiatives"`. The `"formatted"` field added to every `query_okr_status` response is always an empty string.

## Dimension Assessments

### Implemented

All declared functions exist with real logic. No stubs, no TODOs, no `pass` bodies, no `NotImplementedError`. The three MCP tools (`refresh_okr_data`, `query_okr_status`, `refresh_okr_from_sharepoint`) and the generic `download_from_sharepoint` tool are all fully implemented. Column mapping handles both required and optional fields via alias lists. The blended percentage formula is correctly implemented and well-tested.

### Correct

Main happy path is sound: workbook opens → tabs validated → header mapping built → rows parsed → snapshot serialized → stored atomically. The blended formula `(KR_avg * 0.6) + (Initiative_avg * 0.4)` correctly uses the **full unfiltered** KR/initiative lists when enriching objectives in `query()` (explicitly noted in a comment at store.py:122-127). This is the correct behavior.

One incorrect behavior confirmed by probe: `_cell_pct` silently returns `0.0` for Excel percent-format strings like `"85%"` — the `float("85%")` conversion fails and falls back to `0.0`. In practice this is unlikely (Excel cells formatted as percentages deliver a float via openpyxl), but it's a silent data loss risk on malformed input.

### Efficient

The `query()` method calls `load_latest()` which reads and deserializes the full JSON snapshot from disk on every call. With a large OKR file (thousands of initiatives), this is a repeated full-load per query with no in-memory caching. For current scale (tens of objectives, hundreds of initiatives), this is acceptable. If data volume grows, an in-memory LRU cache would be appropriate.

`executive_summary()` also calls `load_latest()` independently — two full loads if both are called in the same request.

### Robust

**Strongest issue**: `OKRStore.load_latest()` reconstructs models with `Objective(**o)`, `KeyResult(**kr)`, `Initiative(**i)` using `**kwargs` unpacking from the JSON. If the snapshot JSON was written by an older version of the model (missing a field now required), or a newer version (extra field not in current dataclass), this raises `TypeError` with no error handling. A schema migration scenario — e.g., adding a new field to `KeyResult` — silently breaks all existing snapshots until they are refreshed.

`refresh_okr_from_sharepoint` has no timeout on the SharePoint download step — if the browser hangs or the file is very large, the operation blocks indefinitely. The browser manager's `is_alive()` check only confirms the process is running, not that it's responsive.

`_cell_pct` converting `"85%"` → `0.0` is a silent data corruption path on malformed input (no warning logged).

The OKR spreadsheet path in `refresh_okr_data` is validated against allowed directories, but the check uses `Path.is_relative_to()` which requires Python 3.9+. Since the project uses 3.11+, this is fine.

### Architecture

The `_format_okr_results` function (okr_tools.py:14-34) is dead code. It reads `results.get("results", [])` but `OKRStore.query()` returns `{"objectives": ..., "key_results": ..., "initiatives": ...}` — the key `"results"` is never present. Every call to `query_okr_status` returns a JSON object with an extraneous `"formatted": ""` field.

`blocked_only` semantics in `query()` are inconsistent: it filters `initiatives` to those with a non-empty `blocker` field but leaves `objectives` and `key_results` unfiltered. The comment at store.py:103 says "only return initiatives (objectives/KRs not filtered)" but all three lists are still in the response — callers querying for "blocked work" get a mixed signal. The UI doc says `blocked_only: If true, only return initiatives with blockers` which is accurate but the full objectives/KRs appearing alongside may confuse callers.

Security posture is good: both `refresh_okr_data` and `download_from_sharepoint` apply path restrictions to allowed directories, symlink rejection, and extension allow-listing. The only minor gap is that `_infer_filename` can return an extensionless filename (e.g., `"sharepoint_download"`) which bypasses the extension check due to the `if ext and ext not in _ALLOWED_EXTENSIONS` guard — an extensionless file passes through. This is low risk since the content would be whatever the browser downloaded, but it is a small inconsistency.

## Findings

### 🔴 Critical

- **`okr/store.py:54-59`** — `load_latest()` uses `Objective(**o)`, `KeyResult(**kr)`, `Initiative(**i)` with no error handling. If the persisted JSON snapshot was written with an older or newer model schema, every subsequent call to `query_okr_status` or `refresh_okr_data` will raise `TypeError` and the OKR system becomes completely unusable until the snapshot is deleted and re-refreshed. This is a silent forward-compat break on any field addition to the dataclasses.

### 🟡 Warning

- **`mcp_tools/okr_tools.py:14-34`** — `_format_okr_results` is dead code. It reads `results.get("results", [])` but the dict returned by `OKRStore.query()` never has a `"results"` key — it has `"objectives"`, `"key_results"`, and `"initiatives"`. Every `query_okr_status` response includes `"formatted": ""` as a useless field. Either wire the function to the actual structure or remove it.

- **`okr/parser.py:101-108`** — `_cell_pct` silently converts unrecognizable strings (e.g., `"85%"`, `"N/A"`, `"TBD"`) to `0.0` with no log warning. If an Excel cell contains a percent-formatted string rather than a numeric value (possible if the user typed it manually), the percentage is silently zeroed. This produces incorrect OKR status without any alert.

- **`okr/store.py:48-60`** — No staleness signal in `load_latest()`. The snapshot's `timestamp` field is available but not checked. If `refresh_okr_from_sharepoint` is called and the download fails silently, `query_okr_status` continues serving stale data with no age warning. The `query_okr_status` tool also has no staleness check — callers relying on `query_okr_status` without first calling `refresh_okr_from_sharepoint` get old data silently.

- **`mcp_tools/sharepoint_tools.py:113-118`** — Extension validation is bypassed when the inferred filename has no extension (e.g., the fallback `"sharepoint_download"`). The guard is `if ext and ext not in _ALLOWED_EXTENSIONS` — an empty `ext` is falsy so the check is skipped entirely. A file without an extension can be downloaded regardless of content type.

### 🟢 Note

- `okr/store.py:101-103`: The `blocked_only` parameter comment ("For blocked_only, only return initiatives") is misleading — objectives and key_results are still returned; only the initiative list is filtered. Consider either filtering all lists or clarifying the docstring.

- `okr/store.py:76-82`: `query()` calls `load_latest()` which does a full disk read + JSON parse + dataclass construction on every call. For current data scale this is fine, but an in-memory snapshot cache (invalidated on `save()`) would improve responsiveness under repeated queries.

- `okr/parser.py:172`: `openpyxl.load_workbook(..., read_only=True)` correctly pads short rows with `None` cells (confirmed by probe), so there is no IndexError risk from sparse rows.

- Security posture is solid overall: path traversal is blocked, symlinks are rejected, file extensions are allow-listed, and directory restrictions are enforced in both `refresh_okr_data` and `download_from_sharepoint`.

- 69/69 executable tests pass with strong coverage across parser, store, models, and both tool entrypoints.

## Verdict

This chunk is functionally working and well-tested (69 tests, all passing). The most important risk is in `OKRStore.load_latest()`: schema-unguarded `**kwargs` reconstruction means any dataclass field addition will corrupt all existing snapshots and break OKR queries silently until a manual refresh. The secondary issue is `_format_okr_results` being dead code that adds a useless `"formatted"` key to every query response — it should be wired to the correct dict keys or removed. Everything else (parsing logic, blended percentages, security guards, atomicity) is correct and clean.
