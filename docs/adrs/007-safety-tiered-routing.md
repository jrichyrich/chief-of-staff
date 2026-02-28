# ADR-007: Safety-Tiered Outbound Message Routing

## Status

Accepted (2026-02-23)

## Context

The system can send outbound messages through multiple channels: email, iMessage, Microsoft Teams, and macOS notifications. Without guardrails, an agent or scheduled task could automatically send sensitive content to external recipients, or fire off messages to someone the user has never contacted before.

Risks without safety tiers:
- An agent auto-sends a message containing salary or legal information to an external contact
- A scheduled task delivers a draft email to the wrong recipient without review
- First-contact messages are sent without the user seeing the content first
- Off-hours messages interrupt colleagues via Teams when email would suffice

We needed a system that:
- Classifies outbound messages into safety levels before delivery
- Routes messages to the appropriate channel based on recipient, urgency, and time of day
- Detects sensitive content and escalates the safety tier automatically
- Allows explicit overrides when the user knows what they want
- Integrates with the existing delivery adapters without coupling to specific channels

## Decision

Introduce a **two-phase routing system**: first determine a **SafetyTier** (whether to send, confirm, or draft), then **select the delivery channel** (which transport to use).

### Safety Tiers

Three tiers, modeled as an `IntEnum` (higher value = more restrictive):

| Tier | Value | Behavior |
|------|-------|----------|
| `AUTO_SEND` | 1 | Send immediately without confirmation |
| `CONFIRM` | 2 | Show draft and require explicit user confirmation |
| `DRAFT_ONLY` | 3 | Create draft only; user must manually review and send |

### Tier Determination

Resolution order:

1. **Explicit override** -- If the user specifies `override="auto"`, `"confirm"`, or `"draft_only"`, return that tier immediately (no further logic).
2. **Recipient baseline** -- Start with the tier associated with the recipient type:
   - `self` -> `AUTO_SEND` (notes to yourself are always safe)
   - `internal` -> `CONFIRM` (work colleagues need a review step)
   - `external` -> `DRAFT_ONLY` (external contacts require full review)
3. **Sensitivity bump** -- If `sensitive=True` (or detected via keyword scan), bump up one tier (capped at `DRAFT_ONLY`). For example, `internal` + sensitive moves from `CONFIRM` to `DRAFT_ONLY`.
4. **First-contact bump** -- If `first_contact=True` and recipient is not `self`, set tier to `DRAFT_ONLY`. First messages to any person always require manual review.

### Sensitive Topic Detection

A compiled regex scans message content for ~20 keywords indicating HR, legal, financial, or security topics:

- HR: `salary`, `compensation`, `termination`, `performance review`, `pip`, `disciplin*`, `severance`, `layoff`, `reduction in force`, `rif`, `harassment`
- Legal: `legal`, `nda`, `lawsuit`, `whistleblow*`
- Financial: `insider`, `merger`, `acquisition`
- Security: `confidential`, `pii`

Matching is case-insensitive with word-boundary awareness. A single keyword hit sets `sensitive=True`.

### Channel Selection

After tier determination, the system selects the delivery channel based on a matrix:

**Self:**
| Urgency | Channel |
|---------|---------|
| urgent | iMessage |
| ephemeral | notification |
| (other) | email |

**Internal (work hours: Mon-Fri 09:00-17:59):**
| Urgency | Channel |
|---------|---------|
| informal, urgent | Teams |
| (other) | email |

**Internal (off hours):**
| Urgency | Channel |
|---------|---------|
| urgent | iMessage |
| (other) | queued (deferred) |

**External:**
| Urgency | Channel |
|---------|---------|
| (any) | email |

### MCP Integration

The `route_message` tool exposes both phases as a single call, returning `{safety_tier, channel, recipient_type, urgency, work_hours}`. Callers (agents, scheduled tasks, or the host Claude) use this response to decide whether to proceed, confirm, or create a draft.

## Consequences

**Benefits:**
- Messages to external recipients always require manual review, preventing accidental sends
- Sensitive content is automatically detected and escalated, even if the caller forgets to flag it
- First-contact messages get the highest safety tier, protecting the user's reputation
- Channel selection adapts to work hours, avoiding off-hours Teams messages
- The override mechanism lets power users bypass tiers when they know the context
- Safety logic is centralized in one module, not scattered across delivery adapters

**Tradeoffs:**
- Keyword-based sensitivity detection is brittle -- it can false-positive on benign uses of "legal" or "pip" and false-negative on novel sensitive topics
- Work hours are hardcoded (Mon-Fri 09:00-17:59 local time) with no timezone or per-user customization
- The `queued` channel (deferred delivery) is a return value only -- the actual deferral mechanism must be implemented by the caller
- The tier system has only three levels; there is no distinction between "send with a 5-second undo window" and "send immediately"
- No learning from user behavior -- the system does not adjust tiers based on historical send patterns

## Related

- `channels/routing.py` -- SafetyTier, determine_safety_tier, select_channel, is_sensitive_topic, is_work_hours
- `mcp_tools/routing_tools.py` -- route_message MCP tool
- `delivery/service.py` -- Delivery adapters that act on routing decisions
- `scheduler/delivery.py` -- Scheduled task delivery (consumes routing decisions)
