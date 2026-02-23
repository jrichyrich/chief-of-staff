# Proactive Session Context Loading — Design

**Date**: 2026-02-22
**Status**: Approved
**Backlog**: jarvis_backlog_015_proactive_session_context_loading

## Problem

When a Claude session starts, Jarvis provides no automatic context. The user must manually call tools to understand what's pending — overdue delegations, upcoming meetings, stale decisions, etc. The proactive suggestion engine exists but is never invoked automatically.

## Design

### MCP Resource: `session://context`

A new MCP resource in `mcp_tools/resources.py` that computes a rich context bundle on read. Claude Code/Desktop reads this automatically on connect — zero tool calls required.

### Response Schema

```json
{
  "today": "2026-02-22",
  "calendar_today": [{"title": "...", "start": "...", "end": "..."}],
  "pending_delegations": [{"task": "...", "due_date": "...", "delegated_to": "..."}],
  "overdue_delegations": [{"task": "...", "due_date": "...", "days_overdue": 3}],
  "pending_decisions": [{"title": "...", "status": "...", "created_at": "..."}],
  "due_reminders": [{"title": "...", "due_date": "..."}],
  "unprocessed_webhooks": 2,
  "proactive_suggestions": [{"priority": "high", "title": "...", "action": "..."}]
}
```

Empty sections are omitted.

### Data Sources

| Section | Store | Method | Cap |
|---------|-------|--------|-----|
| `calendar_today` | CalendarStore | `get_events(today, tomorrow)` | 15 events |
| `pending_delegations` | MemoryStore | `list_delegations(status="active")` | 10 |
| `overdue_delegations` | MemoryStore | `list_overdue_delegations()` | 10 |
| `pending_decisions` | MemoryStore | `list_decisions_by_status("pending_execution")` | 10 |
| `due_reminders` | ReminderStore | `list_reminders(completed=False)` | 10 |
| `unprocessed_webhooks` | MemoryStore | `list_webhook_events(status="pending")` | count only |
| `proactive_suggestions` | ProactiveSuggestionEngine | `generate()` | 5 |

### Error Isolation

Each section is wrapped in try/except. If a data source fails (e.g., calendar unavailable on non-macOS), that section is omitted. The resource never fails entirely.

### Files Modified

| File | Change |
|------|--------|
| `mcp_tools/resources.py` | Add `session://context` resource function |
| `tests/test_resources.py` | Tests for the new resource |

### Exclusions

- No caching layer (SQLite + EventKit fast enough)
- No session-start hook changes
- No changes to existing tools
- No mail/iMessage summary (slow, fetch on demand)
