# Security Audit Report — Chief of Staff (Jarvis)

**Auditor**: Security Agent (Claude Sonnet 4.6)
**Date**: 2026-03-30
**Scope**: Full codebase security audit — all layers

**Stack**: Python 3.13, FastMCP (stdio), SQLite (memory.db, chat.db, profile.db), ChromaDB,
  Anthropic API (Claude), PyObjC EventKit, osascript/AppleScript, Playwright/Chromium,
  MSAL (M365 Graph API), macOS Keychain

**External services**: Anthropic API, Microsoft 365 Graph API (calendar/email/Teams),
  SharePoint Online, iMessage (chat.db), Apple Calendar/Reminders/Mail, macOS Keychain

**Auth mechanism**: API keys (Anthropic, M365 MSAL OAuth2 with Keychain-backed token cache),
  no HTTP server auth (stdio-only MCP — no inbound network surface)

---

## Critical Findings 🔴

### SEC-CRIT-01: iMessage Daemon Prompt Injection — Unauthenticated Command Execution

- **Type**: Prompt Injection / Authentication Bypass
- **Location**: `chief/imessage_executor.py:44`, `chief/imessage_daemon.py:385`
- **What it is**: The iMessage daemon reads raw iMessage text from `chat.db`, applies only
  optional sender allowlist filtering, and passes the message text verbatim as the `instruction`
  to a Claude API call. There is zero sanitization between the received iMessage content and
  the LLM prompt. Any iMessage that matches the prefix filter (default: `"jarvis"`) is executed
  as an autonomous Claude agent call with access to all tools wired into the executor
  (memory writes, calendar reads, email drafts, etc.).

  Critically, when `IMESSAGE_DAEMON_ALLOWED_SENDERS` is empty (the **default**), _all senders_
  are processed. There is no require-allowlist-before-running guard. The only default protection
  is the command prefix `"jarvis"`, which is a publicly known string for this project.

- **Exploitability**: Any iMessage sent to the target phone number starting with "jarvis" is
  autonomously executed. The sender does not need to be in any allowlist by default. A malicious
  iMessage could instruct the agent to read facts/memory, send emails or iMessages on behalf of
  the user, or store false data in the memory store.
- **Impact**: Unauthorized command execution, data exfiltration via iMessage replies, social
  engineering via outbound email/Teams posts, memory store poisoning.
- **Fix**:
  1. Require `IMESSAGE_DAEMON_ALLOWED_SENDERS` to be non-empty as a hard prerequisite for the
     daemon to start. Refuse to run without an explicit allowlist.
  2. Add a max-tools-per-sender daily rate limit.
  3. Consider requiring a second-factor prefix known only to the owner (e.g., a configurable
     secret phrase per sender, not just "jarvis").
  4. The `is_from_me` bypass in the allowlist check (line 355) means self-originated messages
     always bypass the allowlist — this is intentional but creates an interesting edge if the
     user's account is compromised.

---

### SEC-CRIT-02: Webhook Payload Injected Verbatim into Agent Prompt

- **Type**: Prompt Injection
- **Location**: `webhook/dispatcher.py:157`, `webhook/dispatcher.py:273`
- **What it is**: The `_format_input` method interpolates the raw `payload` string from an
  ingested webhook JSON file directly into the agent's instruction via `string.Template`. The
  `payload` field is attacker-controlled — any external system that can write a `.json` file
  to the inbox directory controls what text the agent receives as its prompt.
  There is no sanitization of prompt-injection characters or instructions.
- **Exploitability**: If an attacker can write to the webhook inbox directory (e.g., via a
  misconfigured automation, CI/CD pipeline, or local file write), they can cause the dispatched
  agent to execute arbitrary tool calls. The agent can send emails, write iMessages, modify
  memory/facts, or perform calendar actions.
- **Impact**: Full autonomous agent takeover limited only by the dispatched agent's capabilities.
- **Fix**:
  1. Wrap `payload` content in a clear delimiter: `--- BEGIN EXTERNAL DATA ---\n{payload}\n--- END EXTERNAL DATA ---`
     and instruct the agent in its system prompt not to follow instructions inside that block.
  2. Validate and size-limit payload content (e.g., reject payloads > 50KB).
  3. Consider a `source` allowlist: only process events from known, trusted sources.

---

### SEC-CRIT-03: SharePoint Download Tool Accepts Arbitrary URLs — SSRF Vector

- **Type**: SSRF (Server-Side Request Forgery)
- **Location**: `mcp_tools/sharepoint_tools.py:52-141`
- **What it is**: The `download_from_sharepoint` MCP tool accepts a `sharepoint_url` parameter
  with no domain validation. There is no check that the URL belongs to a SharePoint tenant
  (`*.sharepoint.com`) or the organization's known domain. The URL is passed directly to a
  Playwright browser that is already Okta-authenticated with corporate credentials.

  An agent (or an adversarial LLM call) could pass `http://attacker.com/payload.xlsx` as the
  URL, causing the authenticated corporate browser to fetch arbitrary URLs using the user's
  corporate session.
- **Exploitability**: Requires an LLM agent call with a malicious URL. An adversarial webhook
  or iMessage payload (see SEC-CRIT-01/02) could chain this to exfiltrate the OAuth session
  token to an attacker-controlled server.
- **Impact**: Corporate credential exfiltration, SSRF using authenticated session, potential
  internal network scanning.
- **Fix**:
  ```python
  from urllib.parse import urlparse
  parsed = urlparse(sharepoint_url)
  if not parsed.hostname or not (
      parsed.hostname.endswith(".sharepoint.com") or
      parsed.hostname.endswith(".chghealthcare.com")
  ):
      return json.dumps({"status": "error", "error": "URL must be a SharePoint domain"})
  ```

---

## Warning Findings 🟡

### SEC-WARN-01: Module-Level Secret Constants (Config)

- **Type**: Secret Leakage
- **Location**: `config.py:165` (`M365_CLIENT_SECRET`), `config.py:18` (`ANTHROPIC_API_KEY`)
- **Issue**: Both secrets are resolved at import time and stored as plain string module
  attributes for the lifetime of the process. Any code path that can read `config.*` (debug
  endpoints, crash dumps, `repr()`) exposes the raw secret. Previously documented as
  FINDING-01/11 in the Graph API audit.
- **Fix**: Replace with lazy accessor functions: `def get_m365_client_secret() -> str: ...`
  Route `ANTHROPIC_API_KEY` through `get_secret()` for consistency.

---

### SEC-WARN-02: Token Cache File World-Readable (Default Permissions)

- **Type**: Token Security
- **Location**: `connectors/graph_client.py:209-215`
- **Issue**: File-based MSAL token cache is written with default umask permissions.
  `token_cache.lock` observed as `-rw-r--r--`. On a shared system this exposes OAuth tokens.
  Previously documented as FINDING-02.
- **Fix**: `cache_dir.mkdir(mode=0o700, ...)` and `cache_path.chmod(0o600)` after creation.

---

### SEC-WARN-03: Dynamic SQL WHERE Clause Construction in `fact_store.py`

- **Type**: SQL Injection (Low Exploitability — Internal)
- **Location**: `memory/fact_store.py:169`, `memory/fact_store.py:322`, `memory/fact_store.py:342`
- **Issue**: Three queries construct f-string SQL `WHERE` clauses. The clauses use
  `OR`-joined `(category=? AND key=?)` pairs or `WHERE ...key LIKE ?` clauses, with all
  values passed as parameterized `?` placeholders. The f-string only interpolates
  structural parts (e.g., `{placeholders}` built from `"(category=? AND key=?)"` repeated N
  times, and `{where}` built from static clause strings). User-controlled values are
  never interpolated into the f-string.

  **Reviewed — not directly injectable via parameters.** However, the pattern is fragile:
  if future changes interpolate dynamic filter values rather than `?` placeholders, this
  will become a real SQL injection.
- **Fix**: Refactor to use parameterized query helpers rather than f-strings for all SQL
  construction, eliminating the pattern entirely. Document this as a code hygiene rule.

---

### SEC-WARN-04: Graph API URL Path Parameters Not Validated

- **Type**: Input Validation / URL Injection
- **Location**: `connectors/graph_client.py:472, 479, 575`
- **Issue**: `chat_id` and `message_id` are interpolated directly into URL path strings.
  No allowlist character validation. Previously documented as FINDING-03.
- **Fix**: Validate against `re.match(r'^[a-zA-Z0-9:_@.\-=]+$', chat_id)` and
  `urllib.parse.quote(chat_id, safe='')`.

---

### SEC-WARN-05: Subprocess Key Argument Not Validated (Keychain)

- **Type**: Subprocess Injection (Theoretical)
- **Location**: `vault/keychain.py:46-56, 86-97`
- **Issue**: `key` parameter passed to `security` CLI subprocess without character validation.
  `shell=False` prevents classic shell injection, but the `security` tool may handle unusual
  key values unexpectedly. Previously documented as FINDING-04.
- **Fix**: Add `_validate_key()` with allowlist pattern `r'^[a-zA-Z0-9_\-]+'`.

---

### SEC-WARN-06: OAuth Auth Code Flow Vulnerable to Port Race (TOCTOU)

- **Type**: Auth Flow / TOCTOU
- **Location**: `connectors/graph_client.py:292-374`
- **Issue**: Binds to fixed port 8400 without checking if already bound. A local attacker
  could pre-bind port 8400 to intercept the OAuth callback. Previously documented as FINDING-05.
- **Fix**: Bind to port 0 (OS-assigned) and construct `redirect_uri` dynamically.

---

### SEC-WARN-07: In-Memory Secret Cache Never Cleared

- **Type**: Secret Leakage (Residual)
- **Location**: `vault/keychain.py:18-24`
- **Issue**: `clear_secret_cache()` exists but is never called. Secrets persist in
  `_cache: dict[str, str]` for the full process lifetime. Previously documented as FINDING-07.
- **Fix**: Call `clear_secret_cache()` in server shutdown/session cleanup hooks.

---

### SEC-WARN-08: Teams Graph Backend Sends Without Confirm Gate

- **Type**: Insufficient Authorization (LLM Agent Misuse)
- **Location**: `mcp_tools/teams_browser_tools.py:309-317`
- **Issue**: When `TEAMS_SEND_BACKEND=graph`, `post_teams_message` sends immediately without
  a `confirm_send` gate. Inconsistent with email tools. Previously documented as FINDING-08.
- **Fix**: Add `confirm_send` parameter and gate matching the email tool pattern.

---

### SEC-WARN-09: iMessage `allowed_senders` Empty by Default — No Warning at Startup

- **Type**: Insufficient Authorization (Configuration Risk)
- **Location**: `config.py:201-203`, `chief/imessage_daemon.py:87`
- **Issue**: `IMESSAGE_DAEMON_ALLOWED_SENDERS` defaults to an empty tuple. When empty, the
  daemon comment says "if non-empty, only process from these senders" — meaning empty =
  **no restrictions**. There is no warning log, startup failure, or documentation that
  deploying without this setting is a security risk. This amplifies SEC-CRIT-01.
- **Fix**: Log a `WARNING: IMESSAGE_DAEMON_ALLOWED_SENDERS is unset — processing iMessages
  from all senders. Set this env var to restrict access.` at daemon startup. Consider making
  this a hard error in production mode.

---

### SEC-WARN-10: Device Code Flow Logged at INFO Level

- **Type**: Auth Flow / Phishing Surface
- **Location**: `connectors/graph_client.py:277-286`
- **Issue**: Device code printed to stderr and logged at INFO. Log access exposes an active
  auth code with 15-minute validity window. Previously documented as FINDING-06.
- **Fix**: Log at WARNING level with a note not to share. Confirm authenticated identity
  matches expected user after device code flow completes.

---

## Informational 🟢

### SEC-INFO-01: SQL Migration Uses f-string Column Names (Hardcoded — Not User Input)

- **Location**: `memory/store.py:468`
- **Code**: `self.conn.execute(f"ALTER TABLE scheduled_tasks ADD COLUMN {col} {col_type}")`
- The `col` and `col_type` values are hardcoded tuples in `_migrate_scheduled_tasks_delivery()`:
  `[("delivery_channel", "TEXT"), ("delivery_config", "TEXT")]`. These are never user-controlled.
  **Not exploitable.** Noted to prevent future regressions.

### SEC-INFO-02: communicate.sh Passes Body Text to AppleScript

- **Location**: `scripts/communicate.sh:100-110, 124-133`
- The shell script's `escape_applescript()` function escapes `\`, `"`, `\n`, `\r`, `\t` before
  embedding in AppleScript. This mirrors `utils/osascript.py:escape_osascript()`.

  **Risk**: AppleScript injection requires breaking out of the quoted string context. The
  escaping handles the primary injection chars but does not handle Unicode/emoji edge cases or
  null bytes. The body arrives from Python subprocess argument list (not shell expansion), so
  this is low risk. Mark for review if the escape function is changed.

### SEC-INFO-03: Fact Store FTS5 Query Uses Quoted Token Wrapping

- **Location**: `memory/fact_store.py:120`
- FTS5 input is sanitized by removing special chars via `_FTS5_SPECIAL.sub(" ", query)` before
  quoting each token with `f'"{t}"'`. This prevents most FTS injection. Acceptable.

### SEC-INFO-04: Document Ingest Path Traversal Mitigation Exists

- **Location**: `mcp_tools/document_tools.py:48-61`
- `ingest_documents` uses `Path(path).resolve()` and validates against `allowed_ingest_roots`.
  The protection is only active when `state.allowed_ingest_roots` is set (defaults to
  `~/Documents`, `~/Desktop`, `~/Downloads`). The default set is reasonable but notably
  excludes `/tmp` and `/var` — no bypass found.

### SEC-INFO-05: Keychain Service Name Too Generic

- **Location**: `vault/keychain.py:14`
- `KEYCHAIN_SERVICE = "jarvis"` — generic name. Low collision risk but should be
  `com.jarvis.chief-of-staff`. Previously documented as FINDING-09.

### SEC-INFO-06: Graph Error Responses Leak Tenant Metadata

- **Location**: `connectors/graph_client.py:447-456`
- Error body truncated to 500 chars included in exception messages. May leak tenant IDs,
  request IDs. Low risk but should parse `error.code`/`error.message` fields only.
  Previously documented as FINDING-10.

---

## Dependency Vulnerabilities

pip-audit was not installed in the active environment. Dependency scan could not be completed.

**Manually noted**: No obviously outdated packages identified from `pyproject.toml` review.
`anthropic`, `msal`, `playwright`, `chromadb`, `fastmcp` are all actively maintained.
A full `pip-audit` run is strongly recommended as part of CI.

---

## Auth and Authorization Assessment

**Session management**: No HTTP session layer (stdio MCP, no inbound network). Not applicable.

**Token validation**: MSAL handles M365 token lifecycle correctly. Keychain-first storage with
file-based fallback. Token expiry respected (MSAL handles refresh). Algorithm not configurable
(MSAL handles internally). No JWT algorithm confusion risk identified.

**Authorization checks**: The MCP server has no authorization model — any process that can
connect to the stdio MCP server (i.e., Claude Desktop/Code running as the same user) can call
any tool. This is the intended design for a single-user desktop tool. The only "authorization"
controls are operational gates (`confirm_send` for email/iMessage, safety tier for routing).

**Password handling**: No passwords stored or processed by this application.

**Privilege escalation risk**: The iMessage daemon (SEC-CRIT-01) and webhook dispatcher
(SEC-CRIT-02) represent the closest analog to privilege escalation — an unprivileged external
sender gaining the agent's full capability set. These are flagged as Critical above.

---

## Positive Findings (Good Practices)

1. **SSL never disabled**: No `verify=False` found anywhere in the codebase.
2. **No `shell=True` in project code**: All subprocess calls use list-form arguments.
3. **`confirm_send` gate on email**: Both `send_email` and `reply_to_email` require explicit
   confirmation.
4. **Document ingest path traversal guard**: Allowlist-based root checking in `document_tools.py`.
5. **SharePoint download extension allowlist**: Only whitelisted file extensions accepted.
6. **SharePoint download directory restriction**: Output constrained to allowed paths.
7. **Secret masking in bootstrap output**: `scripts/bootstrap_secrets.py` masks credentials.
8. **No `yaml.load()` unsafe calls**: All YAML loading uses `yaml.safe_load()`.
9. **FTS5 query sanitization**: Special chars stripped before FTS5 query construction.
10. **Headless mode disables interactive auth**: Device code and auth code flows blocked when
    `interactive=False`.
11. **Column name allowlist in lifecycle store**: `update_decision`/`update_delegation` validate
    column names against `_DECISION_COLUMNS`/`_DELEGATION_COLUMNS` frozensets before building
    dynamic `SET` clauses.
12. **Webhook ingest uses exclusive file lock**: `fcntl.LOCK_EX` prevents concurrent ingest race.
13. **iMessage sends require `confirm_send=True`**: `MessageStore.send_message` has explicit gate.
14. **AppleScript escaping implemented**: Both Python (`utils/osascript.py`) and shell
    (`communicate.sh`) escape special chars before embedding in AppleScript strings.

---

## Areas NOT Covered

- **Runtime SSRF verification**: Cannot confirm whether the Playwright browser would actually
  follow the attacker-controlled URL without a live test environment.
- **Anthropic API prompt injection via tool results**: Tool results flow back into Claude messages.
  A malicious external data source (e.g., a fact retrieved from memory, an email body) could
  embed prompt injection. Not systematically analyzed.
- **ChromaDB vector store security**: Embedding model (`all-MiniLM-L6-v2`) and ChromaDB
  persistence security not evaluated.
- **Playwright Chromium browser session isolation**: Whether the same browser profile is used
  across SharePoint downloads and Teams sessions (credential sharing risk) not confirmed.
- **Dependency CVE scan**: pip-audit not available in environment. Full scan required.
- **launchd plist configurations**: Not reviewed for TOCTOU or privilege escalation vectors.
- **Git history secret scan**: Not performed beyond the 20 most recent commits.

---

## Overall Security Verdict

This codebase is a capable single-user desktop automation tool with several meaningful security
controls (AppleScript escaping, confirm-send gates, extension allowlists, Keychain-backed
secrets). However, it has **three Critical findings that could enable an external attacker to
achieve autonomous command execution** in the user's Jarvis environment:

1. **The iMessage daemon processes messages from any sender by default** (SEC-CRIT-01). Anyone
   who can send an iMessage to this phone number and prefix it with "jarvis" can execute
   arbitrary agent commands. This is the highest-risk finding.

2. **Webhook payloads are injected verbatim into agent prompts** (SEC-CRIT-02). Any system
   that can write to the webhook inbox directory controls what the dispatched agent does.

3. **The SharePoint download tool accepts arbitrary URLs** (SEC-CRIT-03), enabling SSRF using
   an already-authenticated corporate browser session.

These three findings chain: a malicious iMessage (SEC-CRIT-01) could instruct the agent to
call `download_from_sharepoint` with an attacker URL (SEC-CRIT-03), exfiltrating the
corporate session token. Before enabling the iMessage daemon in production, SEC-CRIT-01 must
be addressed with a mandatory sender allowlist requirement.
