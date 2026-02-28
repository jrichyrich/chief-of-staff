# memory/store.py
"""MemoryStore facade — delegates to domain-scoped stores.

All public methods are preserved for backward compatibility.
Table creation, migrations, and connection management remain centralized here.
"""
import logging
import sqlite3
import threading
from pathlib import Path

from memory.agent_memory_store import AgentMemoryStore
from memory.fact_store import FactStore
from memory.identity_store import IdentityStore
from memory.lifecycle_store import LifecycleStore
from memory.scheduler_store import SchedulerStore
from memory.skill_store import SkillStore
from memory.webhook_store import WebhookStore

logger = logging.getLogger(__name__)


class MemoryStore:
    def __init__(self, db_path: Path, chroma_client=None):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row
        self._chroma_client = chroma_client
        self._facts_collection = None
        if chroma_client is not None:
            self._facts_collection = chroma_client.get_or_create_collection(
                "facts_vectors",
                metadata={"hnsw:space": "cosine"},
            )
        self._create_tables()
        self._migrate_facts_pinned()
        self._migrate_agent_memory_namespace()
        self._migrate_scheduled_tasks_delivery()

        # --- Thread safety: shared lock for all write operations ---
        self._lock = threading.RLock()

        # --- Domain stores (shared connection + lock) ---
        self._fact_store = FactStore(self.conn, self._facts_collection, lock=self._lock)
        self._lifecycle_store = LifecycleStore(self.conn, lock=self._lock)
        self._webhook_store = WebhookStore(self.conn, lock=self._lock)
        self._scheduler_store = SchedulerStore(self.conn, lock=self._lock)
        self._skill_store = SkillStore(self.conn, lock=self._lock)
        self._agent_memory_store = AgentMemoryStore(self.conn, lock=self._lock)
        self._identity_store = IdentityStore(self.conn, lock=self._lock)

        # --- Delegate all public methods ---

        # FactStore: facts, locations, context
        self.store_fact = self._fact_store.store_fact
        self.get_fact = self._fact_store.get_fact
        self.get_facts_by_category = self._fact_store.get_facts_by_category
        self.search_facts = self._fact_store.search_facts
        self.rank_facts = self._fact_store.rank_facts
        self.search_facts_ranked = self._fact_store.search_facts_ranked
        self.search_facts_fts = self._fact_store.search_facts_fts
        self.search_facts_vector = self._fact_store.search_facts_vector
        self.search_facts_hybrid = self._fact_store.search_facts_hybrid
        self.delete_fact = self._fact_store.delete_fact
        self.repair_vector_index = self._fact_store.repair_vector_index
        self.store_location = self._fact_store.store_location
        self.get_location = self._fact_store.get_location
        self.list_locations = self._fact_store.list_locations
        self.store_context = self._fact_store.store_context
        self.list_context = self._fact_store.list_context
        self.search_context = self._fact_store.search_context

        # LifecycleStore: decisions, delegations, alert rules
        self.store_decision = self._lifecycle_store.store_decision
        self.get_decision = self._lifecycle_store.get_decision
        self.search_decisions = self._lifecycle_store.search_decisions
        self.list_decisions_by_status = self._lifecycle_store.list_decisions_by_status
        self.update_decision = self._lifecycle_store.update_decision
        self.delete_decision = self._lifecycle_store.delete_decision
        self.store_delegation = self._lifecycle_store.store_delegation
        self.get_delegation = self._lifecycle_store.get_delegation
        self.list_delegations = self._lifecycle_store.list_delegations
        self.list_overdue_delegations = self._lifecycle_store.list_overdue_delegations
        self.update_delegation = self._lifecycle_store.update_delegation
        self.delete_delegation = self._lifecycle_store.delete_delegation
        self.store_alert_rule = self._lifecycle_store.store_alert_rule
        self.get_alert_rule = self._lifecycle_store.get_alert_rule
        self.list_alert_rules = self._lifecycle_store.list_alert_rules
        self.update_alert_rule = self._lifecycle_store.update_alert_rule
        self.delete_alert_rule = self._lifecycle_store.delete_alert_rule

        # WebhookStore: webhook events, event rules
        self.store_webhook_event = self._webhook_store.store_webhook_event
        self.get_webhook_event = self._webhook_store.get_webhook_event
        self.list_webhook_events = self._webhook_store.list_webhook_events
        self.update_webhook_event_status = self._webhook_store.update_webhook_event_status
        self.create_event_rule = self._webhook_store.create_event_rule
        self.get_event_rule = self._webhook_store.get_event_rule
        self.list_event_rules = self._webhook_store.list_event_rules
        self.update_event_rule = self._webhook_store.update_event_rule
        self.delete_event_rule = self._webhook_store.delete_event_rule
        self.match_event_rules = self._webhook_store.match_event_rules

        # SchedulerStore: scheduled tasks
        self.store_scheduled_task = self._scheduler_store.store_scheduled_task
        self.get_scheduled_task = self._scheduler_store.get_scheduled_task
        self.get_scheduled_task_by_name = self._scheduler_store.get_scheduled_task_by_name
        self.list_scheduled_tasks = self._scheduler_store.list_scheduled_tasks
        self.get_due_tasks = self._scheduler_store.get_due_tasks
        self.update_scheduled_task = self._scheduler_store.update_scheduled_task
        self.delete_scheduled_task = self._scheduler_store.delete_scheduled_task

        # SkillStore: skill usage, tool usage log, skill suggestions
        self.record_skill_usage = self._skill_store.record_skill_usage
        self.get_skill_usage_patterns = self._skill_store.get_skill_usage_patterns
        self.log_tool_invocation = self._skill_store.log_tool_invocation
        self.get_tool_usage_log = self._skill_store.get_tool_usage_log
        self.get_tool_stats_summary = self._skill_store.get_tool_stats_summary
        self.get_top_patterns_by_tool = self._skill_store.get_top_patterns_by_tool
        self.store_skill_suggestion = self._skill_store.store_skill_suggestion
        self.get_skill_suggestion = self._skill_store.get_skill_suggestion
        self.list_skill_suggestions = self._skill_store.list_skill_suggestions
        self.update_skill_suggestion_status = self._skill_store.update_skill_suggestion_status

        # AgentMemoryStore: agent memory, shared memory
        self.store_agent_memory = self._agent_memory_store.store_agent_memory
        self.get_agent_memories = self._agent_memory_store.get_agent_memories
        self.search_agent_memories = self._agent_memory_store.search_agent_memories
        self.delete_agent_memory = self._agent_memory_store.delete_agent_memory
        self.clear_agent_memories = self._agent_memory_store.clear_agent_memories
        self.store_shared_memory = self._agent_memory_store.store_shared_memory
        self.get_shared_memories = self._agent_memory_store.get_shared_memories
        self.search_shared_memories = self._agent_memory_store.search_shared_memories

        # IdentityStore: identities
        self.link_identity = self._identity_store.link_identity
        self.unlink_identity = self._identity_store.unlink_identity
        self.get_identity = self._identity_store.get_identity
        self.search_identity = self._identity_store.search_identity
        self.resolve_sender = self._identity_store.resolve_sender
        self.resolve_handle_to_name = self._identity_store.resolve_handle_to_name

    # Preserve backward compat for _mmr_rerank (was a @staticmethod on MemoryStore)
    _mmr_rerank = staticmethod(FactStore._mmr_rerank)

    # --- Domain store properties ---

    @property
    def fact_store(self) -> FactStore:
        return self._fact_store

    @property
    def lifecycle_store(self) -> LifecycleStore:
        return self._lifecycle_store

    @property
    def webhook_store(self) -> WebhookStore:
        return self._webhook_store

    @property
    def scheduler_store(self) -> SchedulerStore:
        return self._scheduler_store

    @property
    def skill_store(self) -> SkillStore:
        return self._skill_store

    @property
    def agent_memory_store(self) -> AgentMemoryStore:
        return self._agent_memory_store

    @property
    def identity_store(self) -> IdentityStore:
        return self._identity_store

    # --- Table creation (centralized) ---

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, key)
            );

            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                address TEXT,
                latitude REAL,
                longitude REAL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS context (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                context TEXT DEFAULT '',
                alternatives_considered TEXT DEFAULT '',
                decided_by TEXT DEFAULT '',
                owner TEXT DEFAULT '',
                status TEXT DEFAULT 'pending_execution',
                follow_up_date TEXT,
                tags TEXT DEFAULT '',
                source TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS delegations (
                id INTEGER PRIMARY KEY,
                task TEXT NOT NULL,
                description TEXT DEFAULT '',
                delegated_to TEXT NOT NULL,
                delegated_by TEXT DEFAULT '',
                due_date TEXT,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'active',
                source TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                alert_type TEXT NOT NULL,
                condition TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                last_triggered_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                schedule_type TEXT NOT NULL,
                schedule_config TEXT DEFAULT '',
                handler_type TEXT DEFAULT '',
                handler_config TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                last_run_at TIMESTAMP,
                next_run_at TIMESTAMP,
                last_result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS skill_usage (
                id INTEGER PRIMARY KEY,
                tool_name TEXT NOT NULL,
                query_pattern TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tool_name, query_pattern)
            );

            CREATE TABLE IF NOT EXISTS tool_usage_log (
                id INTEGER PRIMARY KEY,
                tool_name TEXT NOT NULL,
                query_pattern TEXT NOT NULL DEFAULT 'auto',
                success INTEGER NOT NULL DEFAULT 1,
                duration_ms INTEGER,
                session_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_tool_usage_log_tool ON tool_usage_log(tool_name);
            CREATE INDEX IF NOT EXISTS idx_tool_usage_log_created ON tool_usage_log(created_at);

            CREATE TABLE IF NOT EXISTS skill_suggestions (
                id INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                suggested_name TEXT DEFAULT '',
                suggested_capabilities TEXT DEFAULT '',
                confidence REAL DEFAULT 0.0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS event_rules (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                event_source TEXT NOT NULL,
                event_type_pattern TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                agent_input_template TEXT DEFAULT '',
                delivery_channel TEXT,
                delivery_config TEXT,
                enabled INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 100,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_memory (
                id INTEGER PRIMARY KEY,
                agent_name TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agent_name, memory_type, key)
            );

            CREATE TABLE IF NOT EXISTS identities (
                id INTEGER PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                email TEXT DEFAULT '',
                metadata TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, provider_id)
            );

            CREATE INDEX IF NOT EXISTS idx_identities_canonical_name ON identities(canonical_name);

            CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                key, value, category,
                content='facts', content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
                INSERT INTO facts_fts(rowid, key, value, category) VALUES (new.id, new.key, new.value, new.category);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
                INSERT INTO facts_fts(facts_fts, rowid, key, value, category) VALUES('delete', old.id, old.key, old.value, old.category);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
                INSERT INTO facts_fts(facts_fts, rowid, key, value, category) VALUES('delete', old.id, old.key, old.value, old.category);
                INSERT INTO facts_fts(rowid, key, value, category) VALUES (new.id, new.key, new.value, new.category);
            END;
        """)
        self.conn.commit()
        # Rebuild FTS index to pick up any pre-existing data
        self.conn.execute("INSERT INTO facts_fts(facts_fts) VALUES('rebuild')")
        self.conn.commit()

    # --- Migrations (centralized) ---

    def _migrate_facts_pinned(self):
        """Add pinned column to facts if it doesn't exist."""
        try:
            self.conn.execute("ALTER TABLE facts ADD COLUMN pinned INTEGER DEFAULT 0")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

    def _migrate_agent_memory_namespace(self):
        """Add namespace column to agent_memory if it doesn't exist."""
        try:
            self.conn.execute("ALTER TABLE agent_memory ADD COLUMN namespace TEXT")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

    def _migrate_scheduled_tasks_delivery(self):
        """Add delivery_channel and delivery_config columns to scheduled_tasks if they don't exist."""
        for col, col_type in [("delivery_channel", "TEXT"), ("delivery_config", "TEXT")]:
            try:
                self.conn.execute(f"ALTER TABLE scheduled_tasks ADD COLUMN {col} {col_type}")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

    # --- Connection management ---

    def close(self):
        self.conn.close()
