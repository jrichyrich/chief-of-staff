# Chunk Audit: iMessage & Channels

**User-facing feature**: iMessage history read/send, unified channel event aggregation, outbound routing safety
**Risk Level**: High
**Files Audited**:
- `apple_messages/__init__.py`
- `apple_messages/messages.py`
- `channels/__init__.py`
- `channels/adapter.py`
- `channels/consumers.py`
- `channels/models.py`
- `channels/router.py`
- `channels/routing.py`
- `chief/__init__.py`
- `chief/imessage_daemon.py`
- `chief/imessage_executor.py`
- `chief/imessage_tools.py`
- `mcp_tools/imessage_tools.py`
- `mcp_tools/channel_tools.py`
- `mcp_tools/routing_tools.py`

**Status**: Complete

## Purpose (as understood from reading the code)

This chunk provides end-to-end iMessage capability: `apple_messages/messages.py` reads Apple's `chat.db` (SQLite) and sends via `communicate.sh`; `mcp_tools/imessage_tools.py` wraps these as MCP tools; `chief/imessage_daemon.py` runs an autonomous polling loop that ingests new messages, invokes Claude via `IMessageExecutor`, and replies; `channels/` provides a unified normalization layer (`InboundEvent`) and outbound safety routing. The chunk matches its described purpose with no significant divergence.

## Runtime Probe Results

- **Tests found**: Yes — 10 test files: `test_apple_messages.py`, `test_channel_adapter.py`, `test_channel_router.py`, `test_channel_routing.py`, `test_imessage_daemon.py`, `test_imessage_executor.py`, `test_imessage_integration.py`, `test_imessage_tools.py`, `test_mcp_imessages.py`, `test_routing_tools.py`
- **Tests run**: 151 passed, 0 failed (includes 5 integration tests)
- **Import/load check**: All 15 files pass `python -m py_compile` with no syntax errors
- **Type check**: mypy not installed; not applicable
- **Edge case probes**:
  - `is_sensitive_topic(None)` → returns `False` (handles None gracefully; content check guards it)
  - `is_sensitive_topic("riff raff")` → **True** (false positive — `rif` keyword matches `riff`)
  - `is_sensitive_topic("pipeline")` → **True** (false positive — `pip` keyword matches `pipel...`)
  - `determine_safety_tier("self", first_contact=True)` → `AUTO_SEND` (first_contact does not affect self tier — correct by design)
  - `select_channel("internal", "unknown_urgency", work_hours=True)` → `email` (safe fallback)
  - `decode_attributed_body(None)` → `None` (safe)
  - `compute_lookback_minutes(0, 9999999, 30, 1440)` → `30` (bootstrap shortcut correct)
  - `parse_local_date_to_epoch("not-a-date")` raises `ValueError` (propagates without catch — daemon handles at call site)
- **Key observation**: Two confirmed false positives in sensitive keyword detection (`rif` matches `riff`/`rift`/`riffing`, `pip` matches `pipeline`); these cause over-restriction for normal messages routed through `route_message`.

## Dimension Assessments

### Implemented

All functions listed in the CLAUDE.md module map are fully implemented with real logic. No stubs or empty bodies. The `channels/__init__.py` is intentionally empty (no `__all__` export); `chief/__init__.py` is empty. `get_imessage_threads` at `mcp_tools/imessage_tools.py:104` is kept as a non-MCP backward-compat alias (explicitly documented). The single `pass` at `chief/imessage_executor.py:71` is in an exception handler (`except Exception: pass`) that swallows the API logging failure — this is a deliberate silent-fail for a non-critical observability side effect, not a stub.

### Correct

**Happy path is correct.** Verified: message polling → dedup by GUID → job queue → executor → reply. The date math for Apple's CoreData epoch offset (978307200 = Jan 1 2001) is correct throughout. `decode_attributed_body` correctly handles indicator bytes 0x81/0x82/0x83 and unknown indicators.

**Two logic issues found:**

1. **`channels/routing.py:68-95` — `rif` and `pip` keyword patterns match unintended words.** The pattern is `\b(?:rif)` with `re.IGNORECASE` — this uses `\b` only at the start of the match, not at the end. `riff`, `riffing`, `rift`, `terrific` are not matched (trailing `\b` applies to the last word only via alternation), but `rif` DOES match `riff` and `riffing` because `\b` before `rif` matches any word boundary followed by `r-i-f`. Confirmed via runtime probe: `is_sensitive_topic("riff raff")` → `True`, `is_sensitive_topic("riffing")` → `True`, `is_sensitive_topic("pipeline")` → `True`. The pattern should use `\b...\b` or `\b(?:rif|pip)\b`.

2. **`chief/imessage_daemon.py:405-408` — Reply always goes to the configured `IMESSAGE_DAEMON_REPLY_HANDLE`, not back to the actual message sender.** `list_queued_jobs()` does not return `raw_json`, `sender`, or `chat_identifier` — only `text`, `date_local`, `timestamp_epoch`. The dispatch cycle therefore cannot route the reply to the originating sender. This works correctly for single-user self-chat setups but will misroute in any multi-sender configuration. The `raw_json` is stored but never read back during dispatch.

### Efficient

**One genuine inefficiency:** `apple_messages/messages.py:184-194` — `_record_observations()` is called after every query result set (up to 200 messages). It calls `_upsert_thread_observation()` for each unique `(chat_id, sender, date)` tuple. Each call opens a new `sqlite3.connect()`, executes two SQL statements, and commits. For 200 messages with unique senders, this means up to 200 connection open/close cycles per query. The fix is to batch all upserts into a single connection and transaction inside `_record_observations`. At the default `limit=25` this is acceptable; at `limit=200` it adds measurable latency.

**`search_messages` attributedBody over-fetch:** `apple_messages/messages.py:328-329` — The WHERE clause includes `OR (m.text IS NULL AND m.attributedBody IS NOT NULL)` unconditionally. This fetches ALL messages with no text but with an attributedBody blob regardless of the search query, then filters in Python. This is a correctness/recall trade-off (intentional), but on large chat databases it loads unnecessary data into memory.

### Robust

**Strong overall.** Key robustness features:
- `_query_with_retry()` handles `locked` SQLite errors with exponential backoff (3 attempts)
- `_IS_MACOS` guard returns a clean error dict on non-macOS rather than raising
- `_normalize_limit()` and `_normalize_minutes()` clamp all user inputs to safe ranges
- `StateStore.recover_stale_running_jobs()` resets stuck jobs on every `run_once()` call
- Job execution errors are caught per-job; one failed job does not abort the batch
- Reply failure is caught and logged but does not retroactively fail the execution job record

**Three gaps:**

1. **`apple_messages/messages.py:79` — SQLite URI for chat.db does not escape `self.db_path`.** `f"file:{self.db_path}?mode=ro"` — if `db_path` contains spaces or special characters, the URI will be malformed. In practice db_path comes from config defaults (e.g., `~/Library/Messages/chat.db`) so this is low probability but the path should be URL-encoded for correctness.

2. **`chief/imessage_daemon.py:360` — `parse_local_date_to_epoch()` raises `ValueError` on malformed `date_local` strings.** The exception propagates out of `_ingest_cycle()` uncaught, which would crash the daemon's current tick for a single bad message. A try/except around the call at line 360 would isolate bad messages. The caller at line 360 does not wrap this.

3. **`chief/imessage_executor.py:71` — API logging failure is silently swallowed with bare `pass`.** Any exception from `memory_store.log_api_call()` is discarded without even a debug log line. While intentional (observability should not break execution), a `logger.debug(...)` would preserve diagnosability.

### Architecture

**Well-structured overall.** Clean separation: `apple_messages` is platform I/O, `channels` is normalization + routing policy, `chief` is daemon orchestration, `mcp_tools` is the MCP surface. No circular imports. The `channels/__init__.py` is empty — this is technically fine but the package exposes no convenience imports; users must import submodules directly.

**One architectural gap worth noting:** The `IMessageDaemon._dispatch_cycle()` processes jobs sequentially in a for-loop with `await asyncio.wait_for(executor.execute(...))`. With `dispatch_batch_size=25` and `DISPATCH_TIMEOUT_SECONDS=120`, a full batch could take up to 50 minutes before the loop exits. In practice the JarvisDaemon tick runs `run_once()` every 60 seconds and awaits it — meaning the tick is blocked for the full dispatch duration. This is by design (single-user self-chat) but creates a latency cliff if queue depth grows.

**`channels/__init__.py` and `chief/__init__.py` are both empty.** These packages expose no public API. Not wrong, but callers must know to import from submodules. The `apple_messages/__init__.py` correctly exports `MessageStore`.

## Findings

### 🔴 Critical

- **`channels/routing.py:68-95`** — `rif` keyword pattern matches `riff`, `riffing`, `rift` due to missing trailing `\b` word boundary anchor. `is_sensitive_topic("riff raff")` returns `True`. Any message containing "terrific", "riffing", "pipeline", "pipping" will be escalated to a higher safety tier, potentially preventing auto-send of routine messages. Fix: change `rif` to `rif\b` and `pip` to `pip\b` in `_SENSITIVE_KEYWORDS` or ensure the compiled pattern uses `\b...\b` anchors around each keyword.

### 🟡 Warning

- **`chief/imessage_daemon.py:360`** — `parse_local_date_to_epoch(date_local)` is called without a try/except. A single message with a malformed `date_local` (e.g., empty string from a system message or emoji-only message) raises `ValueError` and aborts the entire `_ingest_cycle()` tick. The daemon recovers on the next tick, but the bad message is never ingested or skipped — it re-fetches on the next poll and fails again indefinitely. Wrap the call in a try/except and `continue` on parse failure.

- **`chief/imessage_daemon.py:376-407`** — Replies are always sent to `IMESSAGE_DAEMON_REPLY_HANDLE` (a single configured phone number/email), not to the originating sender. `list_queued_jobs()` does not return `raw_json`, `sender`, or `chat_identifier`. For the documented single-user self-chat design this is acceptable, but the architecture silently drops sender context that was captured at ingestion time. If the daemon is ever used with `allowed_senders` containing multiple handles, all replies go to one handle.

- **`apple_messages/messages.py:184-194`** — `_record_observations()` opens one SQLite connection per unique `(chat_id, sender, date)` tuple. For a `get_messages(limit=200)` call this can mean 200 connection open/commit/close cycles. At low default limits this is fine; at high limits it adds measurable latency. Batch into a single connection.

### 🟢 Note

- `channels/__init__.py` is empty — the package exposes no top-level imports. Callers must use `from channels.adapter import adapt_event`. Minor discoverability issue.

- `chief/imessage_executor.py:71` — bare `pass` on `log_api_call` exception. Should be at minimum `logger.debug("API usage logging failed", exc_info=True)` to preserve diagnosability without breaking execution.

- `channels/routing.py:119-141` — work hours hardcoded to `9-18` Monday-Friday. No configuration path. Reasonable for a personal assistant, but noted.

- `apple_messages/messages.py:328-329` — `search_messages` fetches all `attributedBody` messages regardless of query match, then filters in Python. Intentional correctness trade-off but adds memory pressure on large chat databases.

- `apple_messages/messages.py:79` — chat.db path is not URL-encoded in the SQLite URI. Paths with spaces (unusual but possible via custom `db_path`) would produce a malformed URI and raise an unhelpful `OperationalError`. Low probability given default path.

### ✅ Nothing to flag

- SQL injection: All user-supplied values are passed as parameterized query bindings, never interpolated into SQL strings. f-strings are used only for structural WHERE clause assembly (e.g., `IN (?,?,?)` placeholder generation).
- Confirmation gate: `send_message()` requires `confirm_send=True` to actually send; without it returns a preview dict. MCP tool `send_imessage_reply` correctly propagates this.
- Recipient verification: Three-source verification (identity store → thread profiles → resolve_sender) with mismatch warnings before send is robust and well-tested.
- Thread-safety of `EventRouter`: Uses `threading.Lock` for handler registration and routing — correct.
- Retry on chat.db lock: `_query_with_retry` correctly handles `locked` errors with exponential backoff.

## Verdict

This chunk is largely working and well-tested (151 tests, all green). The iMessage read pipeline, thread profile tracking, recipient verification, and daemon job queue are solid. Two issues need attention: (1) the `is_sensitive_topic()` regex has missing word-boundary anchors causing false positives on common words like "riff" and "pipeline" — this is a confirmed correctness bug affecting outbound routing safety decisions; (2) `parse_local_date_to_epoch()` is called unguarded in the ingest loop, meaning a single malformed `date_local` string from chat.db will abort the daemon's ingest tick repeatedly for the same message. The reply-to-sender architectural gap is a known design constraint (single-user) but worth documenting if multi-user support is ever added.
