# Chunk Audit: Documents & Search

**User-facing feature**: Semantic document search, file ingestion
**Risk Level**: Medium
**Files Audited**:
- `documents/__init__.py`
- `documents/store.py`
- `documents/ingestion.py`
- `mcp_tools/document_tools.py`

**Status**: Complete

## Purpose (as understood from reading the code)

This chunk ingests files from disk (txt, md, py, json, yaml, pdf, docx) into a ChromaDB vector collection using word-based chunking (500 words, 50 overlap), and exposes semantic search via ChromaDB cosine similarity queries. The MCP tool layer adds path-traversal security, symlink rejection, and file-size limits before calling the ingestion logic.

No divergence from stated purpose. `documents/__init__.py` is an empty package marker (1 line).

## Runtime Probe Results

- **Tests found**: Yes — `tests/test_document_store.py` (19 tests)
- **Tests run**: 19 passed, 0 failed
- **Import/load check**: OK (all three substantive modules import cleanly)
- **Type check**: Not applicable (mypy not installed in active venv)
- **Edge case probes**:
  - `chunk_text(None)` → `AttributeError: 'NoneType' object has no attribute 'split'` (no null guard)
  - `chunk_text("")` → `['']` (returns list with one empty string — harmless but semantically odd)
  - `content_hash(None)` → `AttributeError` (no null guard)
  - `chunk_text(text, chunk_size=10, overlap=10)` → **CONFIRMED INFINITE LOOP** (see Critical finding below)
  - `chunk_text(text, chunk_size=10, overlap=15)` → **CONFIRMED INFINITE LOOP**
  - `search(query, top_k=10)` with 1-doc collection → ChromaDB clamps gracefully, returns 1 result
  - Same-filename deduplication: both copies merge under `report.txt`, `delete_by_source("report.txt")` deletes ALL of them (data loss)
  - Re-ingest same file (unchanged): upsert deduplication works correctly (count stays at 1)
  - Re-ingest updated file (changed content): **stale chunks accumulate** — old version chunks persist alongside new ones
- **Key observation**: Two confirmed hanging bugs (infinite loop in `chunk_text` when `overlap >= chunk_size`; stale chunks on file update). The production defaults (500/50) are safe, but the code has no guard against misconfiguration.

## Dimension Assessments

### Implemented

All four MCP tools (`search_documents`, `ingest_documents`, `list_documents`, `delete_document`, `archive_document`) are fully implemented with real logic. All `DocumentStore` methods are real. `chunk_text`, `load_text_file`, `content_hash`, `ingest_path` all exist with substantive bodies. No stubs, no TODOs, no `pass`-only bodies.

### Correct

**Happy path** (ingest → search) works correctly. Deduplication via `upsert` on `{hash}_{chunk_index}` IDs works as designed. PDF/DOCX loading is properly guarded with `try/except ImportError`.

**Known logical flaws**:

1. **Stale document accumulation on update** (`ingestion.py:150-176`): When a file changes content, `ingest_path` computes a new hash, producing new IDs. The old chunks (with old IDs) remain in ChromaDB. There is no "delete old chunks for this filename before re-inserting" step. Over time the collection accumulates stale data from previous file versions, and search returns outdated content alongside current content.

2. **Filename-only source key causes cross-path collisions** (`ingestion.py:167`): `metadata["source"]` is set to `str(file.name)` — the basename only. Two files named `report.txt` in different directories share the same source key. `delete_by_source("report.txt")` deletes ALL chunks from both files. This is a silent data loss risk when ingesting across multiple directories.

3. **`archive_document` silently archives the first match only** (`document_tools.py:146`): `rglob(source)` may return multiple files with the same name in different subdirectories. Only `matches[0]` is acted on, with no warning that additional files exist.

### Efficient

**`list_sources` fetches the entire collection** (`store.py:52`): `self.collection.get()` with no `where` filter retrieves all chunk metadata into Python memory to count by source. This is an O(n) memory operation proportional to total chunk count. At small scale this is fine; at tens of thousands of chunks it is a noticeable overhead. ChromaDB does not expose a native aggregation API, so this is an inherent limitation — but worth noting.

All other paths are efficient. File reading is streaming (no full-content-in-RAM except for chunking, which is necessary). The chunking algorithm is O(n) in word count.

### Robust

1. **`chunk_text` infinite loop** (`ingestion.py:35-41`): When `overlap >= chunk_size`, `start = end - overlap` results in `start` either staying at the same position or moving backward. The while loop never terminates. Confirmed via runtime probe. The production defaults (500/50) are safe, but there is no guard: passing `overlap=500` or `overlap=chunk_size` hangs the server process.

2. **`chunk_text` called with `None`** (`ingestion.py:30`): Raises `AttributeError`, not a descriptive `ValueError`. No null guard. In practice `text` is always the output of `load_text_file`, so `None` would only arise from a bug upstream — but the error message would be confusing.

3. **Single-file symlink protection is correct but indirect**: `ingest_path` for a single file calls `load_text_file`, which checks `path.is_symlink()`. This works. However, the symlink check is inside the `(ValueError, ImportError)` catch block in `ingest_path:140-144` — a symlink raises `ValueError`, which is caught and logged as a skip. This is correct behavior but subtle.

4. **`archive_document` at `document_tools.py:160`** uses `shutil.move` before deleting chunks from ChromaDB. If the ChromaDB delete fails, the file is already moved and the ChromaDB record now points to a non-existent path. The two operations are not atomic. A failure leaves ChromaDB with a dangling source reference and the file physically archived.

5. **`search_documents` and `ingest_documents` wrap ChromaDB errors under `_retry_on_transient`**, which retries on `sqlite3.OperationalError` and `OSError`. ChromaDB-native exceptions (e.g., `chromadb.errors.InvalidDimensionException`) would fall through to the `@tool_errors` decorator and surface as error strings — acceptable.

### Architecture

**Two hardcoded user-specific absolute paths** in `document_tools.py`:
- Line 107: `Path("/Users/jasricha/Library/CloudStorage/OneDrive-CHGHealthcare/Jarvis/_index.md")`
- Line 136: `Path("/Users/jasricha/Library/CloudStorage/OneDrive-CHGHealthcare/Jarvis")`

These paths are embedded directly in production tool code. They would break on any deployment other than the author's machine and are untestable without mocking at the filesystem level.

**`state.allowed_ingest_roots` defaults to `None`** and is never set to a non-`None` value in `mcp_server.py` (confirmed at line 278). The fallback in `document_tools.py:53-57` builds the allowed roots inline. This pattern obscures the actual security boundary and means the allowed roots are not visible in configuration; they only materialize at runtime inside the tool function.

**No test coverage for `delete_document` or `archive_document` MCP tools**: `test_mcp_server.py` tests `ingest_documents`, `search_documents`, and security path-traversal on ingest. The delete and archive tools have no test coverage in the MCP layer.

**Separation of concerns is sound overall**: `DocumentStore` is a clean ChromaDB wrapper; `ingestion.py` handles I/O and chunking; `document_tools.py` handles security and MCP wiring. The layers are well-separated.

## Findings

### Critical

- **`documents/ingestion.py:35-41`** — `chunk_text` infinite loop when `overlap >= chunk_size`. The `while start < len(words)` loop sets `start = end - overlap`; if `overlap >= chunk_size`, `start` never advances past `end`. Confirmed via runtime probe: passing `chunk_size=10, overlap=10` or `chunk_size=10, overlap=15` hangs indefinitely. Default values (500/50) are safe, but there is no guard against misconfiguration. A single bad MCP call or future change to defaults could hang the server process with no timeout or escape path. Fix: add `assert overlap < chunk_size` or `start = max(start + 1, end - overlap)` as a floor guard.

### Warning

- **`documents/ingestion.py:167`** — Source metadata stores basename only (`file.name`), not the full path. Two files with the same name in different directories share one source key. `delete_by_source` will silently delete chunks from both files when the user intended to delete only one. This is a data-loss path when ingesting across multiple directories.

- **`documents/ingestion.py:149-176`** — Re-ingesting a changed file does not purge the old chunks. New hash → new IDs → upsert adds new chunks without removing old ones. Over time, outdated versions accumulate in ChromaDB. Search results may return stale content from previous file versions. Fix: call `delete_by_source(file.name)` before inserting the new chunks.

- **`mcp_tools/document_tools.py:107` and `136`** — Hardcoded absolute paths to the author's personal OneDrive directory. These paths are not configurable and will silently fail (log a warning, continue) on any other machine. The `archive_document` tool's entire file-location logic (`jarvis_root = ...`) depends on this path. Should be moved to `config.py` or `ServerState`.

- **`mcp_tools/document_tools.py:148-165`** — `archive_document` moves the file on disk (line 160) before deleting its ChromaDB chunks (line 164). If the delete fails, ChromaDB retains a dangling source reference with no corresponding file. The two operations should be ordered: delete ChromaDB chunks first, then move the file — or the error handling should be improved to alert on partial failure.

- **`mcp_tools/document_tools.py:139-146`** — `archive_document` archives only `matches[0]` when `rglob` returns multiple files with the same name. No warning is issued. A user who has `report.txt` in two subdirectories will see one silently ignored.

- **`documents/store.py:52`** — `list_sources` fetches all chunk metadata into Python memory via `collection.get()` (no filter). At scale (tens of thousands of chunks), this is a full-collection in-memory load for what is effectively a `GROUP BY source COUNT(*)` query. Low-risk at current scale; notable for growth path.

### Note

- `documents/__init__.py` is a single blank line (empty package marker). This is correct and intentional.
- `chunk_text("")` returns `['']` — an empty string as a single chunk. ChromaDB will embed and store it without error. This is harmless but means empty files produce a stored chunk with no useful content. A simple `if not text.strip(): return []` guard in `ingest_path` or `chunk_text` would prevent this.
- The `_migrate_collection_name` method in `DocumentStore` is a one-time migration for old deployments. There is no mechanism to remove this dead code path after migration completes, but the overhead is a single `list_collections` call at startup — negligible.
- No test coverage for `delete_document` or `archive_document` MCP tool wrappers (the underlying `DocumentStore` methods are tested, but the MCP-layer logic — including `_index.md` update, path validation — is untested).

## Verdict

The core document pipeline (ingest → chunk → embed → search) is implemented correctly and all 19 tests pass. However, there is one confirmed critical bug: `chunk_text` hangs forever when `overlap >= chunk_size`, which can lock the server process. There is also a meaningful data integrity issue: re-ingesting an updated file accumulates stale chunks rather than replacing them, so search results may return outdated content. Two hardcoded personal paths in `archive_document` and `delete_document` make those tools non-portable. The chunk should be considered conditionally working: safe under normal usage with default parameters, but fragile at the edges.
