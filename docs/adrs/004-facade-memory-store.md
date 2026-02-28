# ADR-004: Facade Pattern for MemoryStore Decomposition

## Status

Accepted (2026-02-27)

## Context

The original `MemoryStore` was a single class with all 14 tables' CRUD methods in one file. As the system grew to cover facts, locations, context, decisions, delegations, alerts, webhooks, scheduled tasks, skills, agent memory, and identities, the file became difficult to navigate and test.

We needed to decompose the store while preserving:
- Backward compatibility (all existing callers use `memory_store.method_name()`)
- A single SQLite connection (for transactional consistency)
- A single thread lock (for write safety)
- Centralized table creation and migrations

## Decision

Apply the **Facade pattern**: `MemoryStore` remains the public API but delegates all operations to 7 domain stores:

| Domain Store | Tables | Responsibility |
|-------------|--------|---------------|
| `FactStore` | facts, facts_fts, locations, context | Fact CRUD with FTS5, vector search, temporal decay |
| `LifecycleStore` | decisions, delegations, alert_rules | Decision/delegation/alert CRUD |
| `WebhookStore` | webhook_events, event_rules | Webhook and event rule management |
| `SchedulerStore` | scheduled_tasks | Scheduled task management |
| `SkillStore` | skill_usage, tool_usage_log, skill_suggestions | Tool usage tracking and pattern analysis |
| `AgentMemoryStore` | agent_memory | Per-agent and shared namespace memory |
| `IdentityStore` | identities | Cross-channel identity linking |

### Key Implementation Details

- The facade assigns domain store methods directly as its own attributes (e.g. `self.store_fact = self._fact_store.store_fact`)
- All domain stores receive the same `sqlite3.Connection` and `threading.RLock` instances
- Table creation and schema migrations remain in `MemoryStore._create_tables()` and `_migrate_*()` methods
- Domain store properties are exposed for direct access when needed (`memory_store.fact_store`, etc.)

## Consequences

**Benefits:**
- Each domain store is independently testable and navigable
- The facade preserves full backward compatibility -- no caller changes needed
- Shared connection ensures transactional consistency across domains
- Clear separation of concerns by data domain

**Tradeoffs:**
- The facade's attribute assignment pattern (`self.store_fact = self._fact_store.store_fact`) makes it harder to see at a glance which methods exist
- Table creation is still centralized rather than in each domain store, creating a coupling
- Adding a new domain requires updating both the domain store and the facade

## Related

- `memory/store.py` -- MemoryStore facade
- `memory/fact_store.py`, `memory/lifecycle_store.py`, `memory/webhook_store.py`, `memory/scheduler_store.py`, `memory/skill_store.py`, `memory/agent_memory_store.py`, `memory/identity_store.py` -- Domain stores
