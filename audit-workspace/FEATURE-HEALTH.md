# Feature Health Map

**Date**: 2026-03-30
**Based on**: Full codebase audit — 26 chunk agents + security agent + synthesis

| Feature | Health | Critical | Warnings | Top Issue |
|---------|--------|----------|----------|-----------|
| iMessage Integration | 🔴 | 3 | 2 | Daemon executes commands from any sender by default (SEC-CRIT-01); regex false positives block normal messages |
| Scheduled Tasks & Daemon | 🔴 | 3 | 2 | Arbitrary code execution via custom handler; infinite retry loop on bad config |
| Webhook & Event Processing | 🔴 | 2 | 3 | Payload injected verbatim into agent prompt (SEC-CRIT-02); no-match events re-dispatched forever |
| Document Search & Ingestion | 🔴 | 1 | 4 | chunk_text infinite loop hangs server process permanently |
| Session Persistence & Brain | 🔴 | 1 | 3 | Multi-word workstream status silently lost on every session restart |
| Security (cross-cutting) | 🔴 | 3 | 7 | iMessage prompt injection; webhook prompt injection; SharePoint SSRF (C-01/02/03 chain) |
| MCP Server Core | 🔴 | 1 | 4 | 5 unguarded int() env-var casts crash entire server at startup |
| Agent Dispatch & Orchestration | 🟡 | 1 | 4 | json.dumps() crash kills agent loop; empty context skips all conditional playbook workstreams |
| Calendar Management (Apple + M365) | 🟡 | 1 | 4 | Recurring event recurrence update always fails (empty startDate to Graph) |
| Memory & Fact Recall | 🟡 | 1 | 4 | Agent memory namespace silently dropped; unbounded table growth; hybrid search scores unnormalized |
| Email Read/Search/Send | 🟡 | 0 | 4 | BCC silently dropped on Graph send; reply_all/cc/bcc dropped on Graph reply; oldest not newest returned |
| Teams Messaging | 🟡 | 1 | 4 | 75s async event loop block on browser start; display name match delivers to wrong recipient |
| OKR Tracking & SharePoint | 🟡 | 1 | 3 | Schema field addition breaks all existing OKR snapshots silently |
| Decision/Delegation/Alert Tracking | 🟡 | 1 | 2 | update_decision/update_delegation bypass enum validation — corrupts status state machine |
| Availability & Scheduling | 🟡 | 1 | 2 | Infinite retry on bad cron; manual task run risks double execution |
| Proactive Suggestions | 🟡 | 1 | 3 | Hardcoded developer path causes 3 test failures; secondary skill patterns always below confidence threshold |
| Formatted Output & Delivery | 🟡 | 1 | 3 | ANSI ESC bytes left in email output; "0 pending" renders false section in briefs |
| Infrastructure & Utilities | 🟡 | 1 | 4 | SIGTERM-only cleanup creates zombie processes; async hooks silently do nothing |
| Identity & Person Enrichment | 🟢 | 0 | 3 | Store exceptions bypass logging; email enrichment uses Apple Mail only (no M365 path) |

## Health Key

- 🔴 Critical — has findings that cause real harm in production
- 🟡 Needs Work — functional with meaningful gaps
- 🟢 Clean — minor notes only or nothing to flag

## Total Finding Counts

- 🔴 Critical: 19
- 🟡 Warning: 43
- 🟢 Note / Improvement: 20+
- 💀 Dead weight: 9 items

## Recommended Focus Order

**Fix immediately (before enabling daemon)**: The three security Criticals form a chain — SEC-CRIT-01 (iMessage allowlist required), SEC-CRIT-02 (webhook payload delimiter), and SEC-CRIT-03 (SharePoint URL domain validation) must all be addressed before the autonomous daemon features are used in production. Any one of them alone creates a path for external command execution; together they are a complete attack chain.

**Fix next (daily-use stability)**: The five config.py int() crashes (C-06) are one-liners that could cause a total outage on any misconfiguration. The session brain regex (C-09) causes silent state loss on every restart. The agent loop json.dumps crash (C-07) will eventually surface as a mysterious agent failure. The chunk_text infinite loop (C-08) is a single bad API call away from permanently hanging the server.

**Fix before the next feature release**: The calendar recurring event update (C-17), the lifecycle enum bypass (C-13), the webhook infinite re-dispatch (C-11), and the orchestration falsy-context bug (W-26) affect core workflows. The email BCC/reply-all data loss (W-09) and the Teams display-name misdirection (W-15) affect users who rely on those communication paths.

**Address proactively**: The 41 silent exception swallows across all chunks, the three hardcoded developer paths, and the duplicate `_looks_work_calendar` implementations are the architectural hygiene issues most likely to cause new bugs as the system evolves.
