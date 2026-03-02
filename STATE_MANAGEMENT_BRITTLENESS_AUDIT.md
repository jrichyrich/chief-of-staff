# State Management, Concurrency & Data Integrity Audit

**Date:** February 27, 2026
**Scope:** SQLite transactions, file-based state, concurrent MCP calls, initialization failures, scheduler race conditions
**Status:** Critical issues identified in multiple areas

---

## Executive Summary

The chief-of-staff system has **significant brittleness** in state management and concurrency. Multiple single points of failure exist where partial initialization, concurrent SQLite access, and file-based state races can corrupt data or leave the system in an inconsistent state.

### Critical Issues
- **SQLite WAL mode enabled but no PRAGMA busy_timeout** — concurrent MCP calls can timeout
- **Module-level `_state` populated sequentially during lifespan** — if any store init fails, partial state remains
- **No transaction boundaries in multi-step operations** — facts + ChromaDB can desync
- **OKRStore uses naive JSON file write/read** — file truncation races during concurrent access
- **SessionBrain uses unguarded file I/O** — multiple simultaneous saves can corrupt markdown
- **Scheduler.daemon reads/writes tasks without locking** — overlapping executions possible
- **UnifiedCalendarService creates new DB connections per operation** — ownership table can have stale reads
- **Webhook ingestion has file move races** — duplicate events or lost files in high-concurrency scenarios

---

## 1. SQLite Concurrency & Transaction Management

### Issue 1.1: WAL Mode Enabled But No Busy Timeout

**File:** `memory/store.py:15-29`

```python
def __init__(self, db_path: Path, chroma_client=None):
    self.db_path = db_path
    self.conn = sqlite3.connect(str(db_path))
    self.conn.execute("PRAGMA journal_mode=WAL")  # ✓ Enabled
    self.conn.execute("PRAGMA foreign_keys=ON")
    self.conn.row_factory = sqlite3.Row
    # ✗ NO: self.conn.execute("PRAGMA busy_timeout=30000")
```

**Risk:**
- WAL mode prevents readers from blocking writers (good for throughput)
- But without `busy_timeout`, **concurrent MCP tool calls will timeout immediately** instead of waiting
- Each tool invocation opens a separate connection — no shared timeout
- Result: **Intermittent failures during parallel tool calls** (e.g., multiple users in Claude Code)

**Example:**
```
Thread A: Tool 1 starts writing facts
Thread B: Tool 2 tries to read delegations
Thread B's connection: "database is locked" (no retry)
```

### Issue 1.2: Missing Explicit Transaction Boundaries

**File:** `memory/store.py` — **All write methods**

Every write operation **commits immediately after a single SQL statement**:
- `store_fact()` at 261-275: INSERT → commit
- `store_delegation()` at 710-721: INSERT → commit
- `update_delegation()` at 756-769: UPDATE → commit
- `store_webhook_event()` at 874-882: INSERT → commit
- `create_event_rule()` at 930-958: INSERT → commit → SELECT

**Critical Race:** Facts + ChromaDB desync

```python
def store_fact(self, fact: Fact) -> Fact:
    # Step 1: Insert into SQLite (COMMITTED)
    self.conn.execute("INSERT INTO facts ...")
    self.conn.commit()  # ← Now visible to all readers!

    # Step 2: Try to insert into ChromaDB (ASYNC, NO TRANSACTION)
    if self._facts_collection is not None:
        try:
            self._facts_collection.upsert(...)  # ← Can fail silently
        except Exception:
            pass  # ← Catches and ignores all errors!
    return self.get_fact(...)  # ← Reads back from SQLite (inconsistent with Chroma)
```

**Consequence:**
- If ChromaDB upsert fails, the fact exists in SQLite but NOT in ChromaDB
- Vector search queries will miss the fact
- No warning, no alert, no recovery

### Issue 1.3: Unsafe ON CONFLICT Upserts

**File:** `memory/store.py:261-275`, `memory/store.py:796-814`

```python
def store_fact(self, fact: Fact) -> Fact:
    self.conn.execute(
        """INSERT INTO facts (category, key, value, confidence, source, pinned, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(category, key) DO UPDATE SET ...
        """,
        (fact.category, fact.key, fact.value, fact.confidence, fact.source, ...)
    )
    self.conn.commit()
    # ...
    row = self.conn.execute("SELECT * FROM facts WHERE category=? AND key=?", ...).fetchone()
    return self._row_to_fact(row)
```

**Race Condition:**
1. Thread A: `INSERT ... ON CONFLICT ... DO UPDATE`
2. Commit A: Fact updated
3. Thread B: `SELECT * FROM facts ...` (may see old version if isolation level is IMMEDIATE)
4. Return: May return stale data to caller

**PostgreSQL** has `RETURNING` to solve this. **SQLite** requires a second round-trip query.

---

## 2. Module-Level State & Initialization Brittleness

### Issue 2.1: Sequential Store Initialization With No Rollback

**File:** `mcp_server.py:45-127`

```python
@asynccontextmanager
async def app_lifespan(server: FastMCP):
    # Sequential initialization — if ANY fails, partial state remains
    memory_store = MemoryStore(...)              # [1] Can fail at table creation
    document_store = DocumentStore(...)          # [2] Can fail at ChromaDB init
    agent_registry = AgentRegistry(...)          # [3] Can fail at config load
    # ... 9 more stores ...

    # ALL stores assigned to module-level _state
    _state.memory_store = memory_store
    _state.document_store = document_store       # ← If [3] fails, these remain set!
    # ...

    try:
        yield  # ← MCP server running with PARTIAL state
    finally:
        # Cleanup attempts but doesn't verify all were initialized
        _state.memory_store.close()
        _state.document_store = None
```

**Scenario: Initialization Failure**
```
1. MemoryStore init: OK
2. DocumentStore init: ChromaDB server down → Exception
3. _state.memory_store is set but _state.document_store is NONE
4. MCP server starts and accepts requests
5. Any tool using document_store crashes with AttributeError
6. Session is already open → recovery is manual
```

**No Validation:**
- No `if memory_store is None` check in tool handlers
- No server-level validation that all stores are initialized
- Tool handlers assume non-None stores

### Issue 2.2: Module-Level _state Can Be Partially Populated

**File:** `mcp_server.py:42, 108-118, 175-195`

```python
_state = ServerState()  # Empty at module load

# Later, in lifespan():
_state.memory_store = memory_store       # Set one by one
_state.document_store = document_store
_state.agent_registry = agent_registry
# ...

# In finally block:
_state.hook_registry = None  # Reset one by one
_state.memory_store = None
_state.document_store = None
```

**Race Window:**
- Between assignment of different stores, `_state` is in an inconsistent state
- A tool handler could be called while `_state.memory_store` is set but `_state.session_manager` is not
- No locks protect this

---

## 3. File-Based State: OKRStore & SessionBrain

### Issue 3.1: OKRStore JSON Write Race

**File:** `okr/store.py:18-22`

```python
def save(self, snapshot: OKRSnapshot) -> Path:
    """Serialize snapshot to JSON and write to disk."""
    data = asdict(snapshot)
    self._snapshot_path.write_text(json.dumps(data, indent=2, default=str))
    return self._snapshot_path
```

**No Atomic Writes:**
- `write_text()` does **not** use atomic rename
- Two concurrent `save()` calls can **truncate or corrupt the file**
- `read_text()` can get partial JSON

**Attack Pattern:**
```
Thread A: write_text(big_file)  # 50KB
Thread B: write_text(small_file) # 2KB
Result: File is 2KB, corrupted mid-JSON, parse fails
```

**No temp-file-then-rename pattern:**
```python
# Should be:
import tempfile
with tempfile.NamedTemporaryFile(mode='w', delete=False, dir=self._data_dir) as f:
    json.dump(data, f, indent=2, default=str)
    temp_path = f.name
os.replace(temp_path, self._snapshot_path)  # ← Atomic on all platforms
```

### Issue 3.2: SessionBrain Markdown Write Race

**File:** `session/brain.py:49-52`

```python
def save(self) -> None:
    """Render and write the brain to the markdown file."""
    self.path.parent.mkdir(parents=True, exist_ok=True)
    self.path.write_text(self.render(), encoding="utf-8")  # ← NOT ATOMIC
```

**Same risk as OKRStore:**
- Two simultaneous `save()` calls corrupt the file
- Multiple workstreams + session manager flushing in parallel = corruption
- Recovery: manual file restoration from backup (if exists)

---

## 4. Calendar Routing Database Brittleness

### Issue 4.1: Ownership DB Creates New Connection Per Operation

**File:** `connectors/calendar_unified.py:26-29, 52-72, 74-79, 81-92`

```python
def _open_ownership_db(self) -> sqlite3.Connection:
    conn = sqlite3.connect(self.ownership_db_path)
    conn.row_factory = sqlite3.Row
    return conn  # ← Returned to caller, NOT managed

def _upsert_ownership(self, event: dict) -> None:
    # ...
    with self._open_ownership_db() as conn:  # ← New connection EVERY time
        conn.execute("INSERT INTO event_ownership ...")
        conn.commit()

def _lookup_ownership(self, event_uid: str) -> tuple[str, str] | None:
    # ...
    with self._open_ownership_db() as conn:  # ← Different connection, different cache
        row = conn.execute("SELECT provider, native_id FROM event_ownership ...")
```

**Concurrency Issues:**
1. **No WAL mode or busy_timeout** on calendar routing DB
2. **Two separate connections = two separate caches** — possible stale reads
3. **Upsert then lookup may see old data** if second connection has cached an older page

**Scenario:**
```
T0: Conn A reads event_ownership (gets cached version X)
T1: Conn B writes to event_ownership (changes to version Y)
T2: Conn A reads again from cache → still sees version X!
```

---

## 5. Scheduler & Daemon Concurrency

### Issue 5.1: Task Execution Without Locking

**File:** `scheduler/engine.py:391-403, 405-457`

```python
def evaluate_due_tasks(self, now: Optional[datetime] = None) -> list[dict]:
    due_tasks = self.memory_store.get_due_tasks(now=now.isoformat())  # ← Read

    for task in due_tasks:
        result = self._execute_task(task, now)  # ← Can be slow (30+ seconds)

    return results

def _execute_task(self, task, now: datetime) -> dict:
    # ... execute handler ...

    # Update task state AFTER execution
    self.memory_store.update_scheduled_task(
        task.id,
        last_run_at=now.isoformat(),
        next_run_at=next_run,
        last_result=handler_result,
    )
```

**Race: Overlapping Executions**

```
Daemon tick 1 (t=0):
  get_due_tasks() → [Task #1 (next_run=t0)]
  _execute_task(Task #1) → executes for 30 seconds
  update_scheduled_task(#1, next_run=t+5min) → COMMIT at t=30

Daemon tick 2 (t=5):
  get_due_tasks() → [Task #1 (next_run=t0)] ← STILL DUE!
  _execute_task(Task #1) → RUNS AGAIN while first is still executing
```

**No mutex or row-level lock prevents concurrent execution of the same task.**

### Issue 5.2: Daemon Graceful Shutdown Not Atomic

**File:** `scheduler/daemon.py:42-46`

```python
def shutdown(self):
    """Request graceful shutdown after the current tick completes."""
    self._shutdown = True  # ← Just a flag
    if self._sleep_task and not self._sleep_task.done():
        self._sleep_task.cancel()
```

**Race:**
```
Main: signal SIGTERM → daemon.shutdown()
Daemon: in the middle of _tick() executing a task
Result: Task may be half-executed, database may have uncommitted writes
```

No wait for task completion, no timeout, no forced rollback.

---

## 6. Webhook Event Ingestion: File Race Conditions

### Issue 6.1: File Move Race in Webhook Ingest

**File:** `webhook/ingest.py:68-147`

```python
def ingest_events(memory_store, inbox_dir: Path) -> dict:
    json_files = sorted(inbox_dir.glob("*.json"))  # ← Snapshot at time T

    for filepath in json_files:
        try:
            raw = filepath.read_text(encoding="utf-8")  # ← Can fail if file deleted
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Malformed file %s: %s", filepath.name, exc)
            _move_file(filepath, failed_dir)  # ← May already be moved by another process
            continue

        # ... store event ...
        _move_file(filepath, processed_dir)  # ← Race: file already moved?
```

**Concurrent Ingestion Scenario:**
```
Webhook poll handler A: glob() → [event1.json, event2.json]
Webhook poll handler B: glob() → [event1.json, event2.json]  ← Same files!

A: read_text(event1.json) ✓
A: store_webhook_event() ✓
A: _move_file(event1.json → processed/) ✓

B: read_text(event1.json) ✗ (file not found, moved by A)
B: _move_file(event1.json → failed/) ✗ (file not found)
B: Event is lost!
```

---

## 7. ChromaDB Collection Access Brittleness

### Issue 7.1: Concurrent Upsert Without Batch Deduplication

**File:** `documents/store.py:32-38, memory/store.py:276-284`

```python
def store_fact(self, fact: Fact) -> Fact:
    # ... SQLite upsert ...
    if self._facts_collection is not None:
        try:
            self._facts_collection.upsert(
                ids=[f"{fact.category}:{fact.key}"],
                documents=[f"{fact.key}: {fact.value}"],
                metadatas=[{"category": fact.category, "key": fact.key}],
            )
        except Exception:
            pass  # ← Silently ignore ChromaDB failures!
```

**Issue:**
- If ChromaDB fails, the exception is silently caught
- No retry, no logging, no flag set
- Caller doesn't know the fact wasn't indexed
- Later vector searches miss this fact permanently

**Example:**
```python
store_fact("work", "ruby_version", "3.2.0")
# ChromaDB is down → upsert fails silently
query_memory("ruby")  # ← Returns nothing, user doesn't know it exists
```

---

## 8. Session Management & Flushing

### Issue 8.1: Multi-Step Flush Without Atomicity

**File:** `session/manager.py:100+` (hypothetical, based on usage pattern)

When `flush_session_memory()` is called during active tool use:
```
Main thread: Executing tool A
Session manager: Starting to flush
  1. Extract structured data ✓
  2. Store facts to SQLite ✓
  3. Create decision entries ✓
  4. Save to session brain (file I/O) ← Can fail
  5. Checkpoint to DB ← May not execute
Result: Partial flush, inconsistent state
```

No transaction wraps these steps.

---

## 9. Lifespan Manager Cleanup Brittleness

### Issue 9.1: Exception in Finally Block Suppresses Original Error

**File:** `mcp_server.py:175-197`

```python
try:
    yield
finally:
    hook_registry.fire_hooks("session_end", {...})  # ← Can raise!

    # Reset state attributes
    _state.hook_registry = None
    _state.memory_store = None
    # ...

    memory_store.close()  # ← Can raise!
    logger.info("Jarvis MCP server shut down")
```

**If any hook or close() raises:**
- Original exception from server is **suppressed**
- Only cleanup exception is logged
- Tools left in undefined state

---

## Summary Table: Issues & Severity

| Issue | File | Line | Severity | Impact |
|-------|------|------|----------|--------|
| No SQLite busy_timeout | memory/store.py | 18-20 | **CRITICAL** | Concurrent tool call timeouts |
| Facts + ChromaDB desync | memory/store.py | 276-284 | **CRITICAL** | Silent data loss, vector search gaps |
| Partial initialization rollback | mcp_server.py | 45-127 | **HIGH** | Undefined state if store init fails |
| Module-level _state race | mcp_server.py | 42-118 | **HIGH** | Attribute errors during startup |
| OKRStore file corruption | okr/store.py | 18-22 | **CRITICAL** | Concurrent saves corrupt JSON |
| SessionBrain file corruption | session/brain.py | 49-52 | **CRITICAL** | Markdown file corruption |
| Calendar ownership DB locking | connectors/calendar_unified.py | 26-72 | **HIGH** | Stale reads, consistency issues |
| Task execution overlap | scheduler/engine.py | 391-403 | **CRITICAL** | Duplicate task executions |
| Webhook file move races | webhook/ingest.py | 68-147 | **HIGH** | Lost events, duplicate processing |
| ChromaDB failures silent | memory/store.py | 276-284 | **HIGH** | Vector search gaps without notice |
| Finally block exception suppression | mcp_server.py | 175-197 | **MEDIUM** | Masked shutdown errors |

---

## Recommendations

### Immediate (Critical)

1. **Add SQLite busy_timeout to MemoryStore init**
   ```python
   self.conn.execute("PRAGMA busy_timeout=30000")  # 30 seconds
   ```

2. **Wrap multi-step operations in transactions**
   ```python
   def store_fact(self, fact: Fact):
       try:
           self.conn.execute("BEGIN IMMEDIATE")
           self.conn.execute("INSERT INTO facts ...")
           self._facts_collection.upsert(...)  # Can fail
           self.conn.commit()
       except Exception:
           self.conn.rollback()
           raise
   ```

3. **Use atomic file writes**
   ```python
   import tempfile, os
   with tempfile.NamedTemporaryFile(mode='w', delete=False, dir=dir) as f:
       json.dump(data, f)
       temp = f.name
   os.replace(temp, target_path)  # Atomic
   ```

4. **Add task execution lock to scheduler**
   ```python
   def _execute_task(self, task):
       # Don't fetch again; mark as locked first
       if not self.memory_store.acquire_task_lock(task.id, timeout=5):
           return  # Locked by another executor
       try:
           # Execute task
       finally:
           self.memory_store.release_task_lock(task.id)
   ```

### Short-term (High)

5. **Validate all stores initialized before yielding**
   ```python
   async def app_lifespan(server):
       # ... init stores ...
       _state.validate_all_initialized()  # Raises if None
       yield
   ```

6. **Catch and log ChromaDB failures properly**
   ```python
   except Exception as e:
       logger.error(f"ChromaDB upsert failed for {fact.category}:{fact.key}: {e}")
       # Consider a retry queue or fallback
   ```

7. **Add proper exception handling to daemon shutdown**
   ```python
   async def run(self):
       try:
           # Main loop
       finally:
           await self._graceful_shutdown(timeout=10)
   ```

### Medium-term

8. **Implement connection pooling** for calendar_unified and memory stores
9. **Add deadlock detection and recovery** for long-running scheduler handlers
10. **Implement saga pattern** for distributed state updates (facts + ChromaDB)

---

## Testing Recommendations

1. **Concurrent tool call stress test**: 10+ parallel fact writes, verify no timeouts
2. **Initialization failure scenario**: Simulate ChromaDB down during lifespan, verify error handling
3. **File corruption test**: Concurrent OKRStore.save() calls, verify atomic writes
4. **Scheduler overlap test**: Modify daemon to slow down handler, verify no duplicate executions
5. **Webhook race test**: Concurrent ingest calls with same files, verify no lost events

