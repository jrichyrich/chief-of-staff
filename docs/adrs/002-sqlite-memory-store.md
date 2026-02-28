# ADR-002: SQLite as the Primary Data Store

## Status

Accepted (2026-02-12)

## Context

Jarvis needs persistent storage for facts, decisions, delegations, scheduled tasks, webhook events, identity links, and more. Requirements:

- Single-user macOS application (no multi-tenant scaling needed)
- Zero external infrastructure (no database servers to manage)
- Full-text search for fact retrieval
- Transactional consistency for related writes
- Portable data (single file backup)

Options considered:
1. **PostgreSQL** -- Full-featured RDBMS, but requires a running server
2. **SQLite** -- Embedded, zero-config, file-based
3. **JSON files** -- Simple, but no indexing, transactions, or full-text search

## Decision

SQLite is the primary data store, with ChromaDB as a secondary store for vector search.

### Configuration

- **WAL mode** for concurrent read/write access
- **busy_timeout=30000** (30 seconds) to handle lock contention
- **foreign_keys=ON** for referential integrity
- **threading.RLock** for thread-safe writes across domain stores
- **FTS5 virtual table** with triggers for real-time full-text search on facts

### Schema

14 tables across 7 domain stores, all sharing a single connection. The `MemoryStore` facade delegates to domain stores while centralizing table creation and migrations.

## Consequences

**Benefits:**
- Zero infrastructure -- just a file at `data/memory.db`
- Portable backup -- copy one file
- FTS5 provides fast full-text search with BM25 ranking
- WAL mode enables concurrent reads during writes
- SQLite is the most deployed database engine in the world

**Tradeoffs:**
- Single-writer limitation (mitigated by RLock and WAL mode)
- No built-in vector search (solved by ChromaDB sidecar for embeddings)
- Schema migrations are manual (ALTER TABLE with try/except for idempotency)
- No native JSON column type (JSON stored as TEXT, parsed at application level)

## Related

- `memory/store.py` -- MemoryStore facade
- `memory/fact_store.py` -- FTS5 + vector search implementation
- `documents/store.py` -- ChromaDB vector store
- `connectors/calendar_unified.py` -- Separate SQLite DB for calendar ownership
