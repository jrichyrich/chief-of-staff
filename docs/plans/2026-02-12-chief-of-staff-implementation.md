# Chief of Staff Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python CLI application where a Chief of Staff agent orchestrates expert agents in parallel, with shared memory (SQLite) and document retrieval (ChromaDB).

**Architecture:** Hybrid tool-based decision making + async parallel dispatch. The Chief of Staff uses Claude API with tool-use to decide what to do, then dispatches expert agents (defined as YAML configs) concurrently via asyncio. All agents share a SQLite memory store and ChromaDB document store.

**Tech Stack:** Python 3.11+, Anthropic Claude API, ChromaDB, SQLite, sentence-transformers, PyYAML, asyncio

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `config.py`
- Create: `chief/__init__.py`
- Create: `agents/__init__.py`
- Create: `memory/__init__.py`
- Create: `documents/__init__.py`
- Create: `tools/__init__.py`
- Create: `agent_configs/.gitkeep`
- Create: `data/.gitkeep`
- Create: `tests/__init__.py`
- Create: `.gitignore`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "chief-of-staff"
version = "0.1.0"
description = "AI orchestration system with a Chief of Staff managing expert agents"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.42.0",
    "chromadb>=0.5.0",
    "sentence-transformers>=3.0.0",
    "pyyaml>=6.0",
    "rich>=13.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
    "pytest-mock>=3.14.0",
]

[project.scripts]
chief = "main:cli_entry"
```

**Step 2: Create requirements.txt**

```
anthropic>=0.42.0
chromadb>=0.5.0
sentence-transformers>=3.0.0
pyyaml>=6.0
rich>=13.0.0
pytest>=8.0
pytest-asyncio>=0.24.0
pytest-mock>=3.14.0
```

**Step 3: Create config.py**

```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
AGENT_CONFIGS_DIR = BASE_DIR / "agent_configs"
DATA_DIR = BASE_DIR / "data"
MEMORY_DB_PATH = DATA_DIR / "memory.db"
CHROMA_PERSIST_DIR = DATA_DIR / "chroma"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
CHIEF_MODEL = "claude-sonnet-4-5-20250929"

AGENT_TIMEOUT_SECONDS = 60
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
```

**Step 4: Create all __init__.py files and directories**

Create empty `__init__.py` in: `chief/`, `agents/`, `memory/`, `documents/`, `tools/`, `tests/`.
Create empty `.gitkeep` in: `agent_configs/`, `data/`.

**Step 5: Create .gitignore**

```
__pycache__/
*.pyc
.env
data/memory.db
data/chroma/
*.egg-info/
dist/
.pytest_cache/
.venv/
```

**Step 6: Install dependencies**

Run: `pip install -e ".[dev]"`

**Step 7: Verify setup**

Run: `python -c "import anthropic; import chromadb; import yaml; print('All imports OK')"`
Expected: `All imports OK`

**Step 8: Commit**

```bash
git add -A
git commit -m "feat: project scaffolding with dependencies and config"
```

---

### Task 2: Memory Data Models

**Files:**
- Create: `memory/models.py`
- Create: `tests/test_memory_models.py`

**Step 1: Write the failing test**

```python
# tests/test_memory_models.py
from memory.models import Fact, Location, ContextEntry
from datetime import datetime


def test_fact_creation():
    fact = Fact(
        category="personal",
        key="name",
        value="Jason",
        confidence=1.0,
        source="chief_of_staff",
    )
    assert fact.category == "personal"
    assert fact.key == "name"
    assert fact.value == "Jason"
    assert fact.confidence == 1.0
    assert fact.source == "chief_of_staff"


def test_fact_defaults():
    fact = Fact(category="preference", key="color", value="blue")
    assert fact.confidence == 1.0
    assert fact.source is None
    assert fact.id is None


def test_location_creation():
    loc = Location(
        name="office",
        address="123 Main St",
        latitude=37.7749,
        longitude=-122.4194,
        notes='{"floor": 3}',
    )
    assert loc.name == "office"
    assert loc.address == "123 Main St"
    assert loc.latitude == 37.7749


def test_context_entry_creation():
    entry = ContextEntry(
        session_id="sess_001",
        topic="project planning",
        summary="Discussed Q2 roadmap priorities",
        agent="research_analyst",
    )
    assert entry.topic == "project planning"
    assert entry.agent == "research_analyst"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memory.models'`

**Step 3: Write minimal implementation**

```python
# memory/models.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Fact:
    category: str
    key: str
    value: str
    confidence: float = 1.0
    source: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Location:
    name: str
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notes: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class ContextEntry:
    topic: str
    summary: str
    session_id: Optional[str] = None
    agent: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory_models.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add memory/models.py tests/test_memory_models.py
git commit -m "feat: add memory data models (Fact, Location, ContextEntry)"
```

---

### Task 3: Memory Store (SQLite)

**Files:**
- Create: `memory/store.py`
- Create: `tests/test_memory_store.py`

**Step 1: Write the failing tests**

```python
# tests/test_memory_store.py
import pytest
import os
from pathlib import Path
from memory.store import MemoryStore
from memory.models import Fact, Location, ContextEntry


@pytest.fixture
def memory_store(tmp_path):
    db_path = tmp_path / "test_memory.db"
    store = MemoryStore(db_path)
    yield store
    store.close()


class TestFacts:
    def test_store_and_retrieve_fact(self, memory_store):
        fact = Fact(category="personal", key="name", value="Jason", source="test")
        memory_store.store_fact(fact)
        result = memory_store.get_fact("personal", "name")
        assert result is not None
        assert result.value == "Jason"
        assert result.source == "test"
        assert result.id is not None

    def test_get_nonexistent_fact(self, memory_store):
        result = memory_store.get_fact("personal", "nonexistent")
        assert result is None

    def test_update_fact_overwrites(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        memory_store.store_fact(Fact(category="personal", key="name", value="Jay"))
        result = memory_store.get_fact("personal", "name")
        assert result.value == "Jay"

    def test_get_facts_by_category(self, memory_store):
        memory_store.store_fact(Fact(category="preference", key="color", value="blue"))
        memory_store.store_fact(Fact(category="preference", key="food", value="sushi"))
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        results = memory_store.get_facts_by_category("preference")
        assert len(results) == 2

    def test_search_facts(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        memory_store.store_fact(Fact(category="work", key="title", value="Engineer"))
        results = memory_store.search_facts("Jason")
        assert len(results) == 1
        assert results[0].key == "name"


class TestLocations:
    def test_store_and_retrieve_location(self, memory_store):
        loc = Location(name="office", address="123 Main St", latitude=37.77, longitude=-122.41)
        memory_store.store_location(loc)
        result = memory_store.get_location("office")
        assert result is not None
        assert result.address == "123 Main St"

    def test_get_nonexistent_location(self, memory_store):
        result = memory_store.get_location("nowhere")
        assert result is None

    def test_list_locations(self, memory_store):
        memory_store.store_location(Location(name="home", address="456 Oak Ave"))
        memory_store.store_location(Location(name="office", address="123 Main St"))
        results = memory_store.list_locations()
        assert len(results) == 2


class TestContext:
    def test_store_and_retrieve_context(self, memory_store):
        entry = ContextEntry(
            session_id="sess_001",
            topic="planning",
            summary="Discussed roadmap",
            agent="chief",
        )
        memory_store.store_context(entry)
        results = memory_store.get_context_by_session("sess_001")
        assert len(results) == 1
        assert results[0].topic == "planning"

    def test_get_recent_context(self, memory_store):
        for i in range(5):
            memory_store.store_context(
                ContextEntry(topic=f"topic_{i}", summary=f"summary_{i}")
            )
        results = memory_store.get_recent_context(limit=3)
        assert len(results) == 3
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memory.store'`

**Step 3: Write minimal implementation**

```python
# memory/store.py
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from memory.models import ContextEntry, Fact, Location


class MemoryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

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
        """)
        self.conn.commit()

    # --- Facts ---

    def store_fact(self, fact: Fact) -> Fact:
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO facts (category, key, value, confidence, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(category, key) DO UPDATE SET
                   value=excluded.value,
                   confidence=excluded.confidence,
                   source=excluded.source,
                   updated_at=excluded.updated_at""",
            (fact.category, fact.key, fact.value, fact.confidence, fact.source, now, now),
        )
        self.conn.commit()
        return self.get_fact(fact.category, fact.key)

    def get_fact(self, category: str, key: str) -> Optional[Fact]:
        row = self.conn.execute(
            "SELECT * FROM facts WHERE category=? AND key=?", (category, key)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_fact(row)

    def get_facts_by_category(self, category: str) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE category=?", (category,)
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def search_facts(self, query: str) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE value LIKE ? OR key LIKE ?",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def _row_to_fact(self, row: sqlite3.Row) -> Fact:
        return Fact(
            id=row["id"],
            category=row["category"],
            key=row["key"],
            value=row["value"],
            confidence=row["confidence"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Locations ---

    def store_location(self, location: Location) -> Location:
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO locations (name, address, latitude, longitude, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   address=excluded.address,
                   latitude=excluded.latitude,
                   longitude=excluded.longitude,
                   notes=excluded.notes""",
            (location.name, location.address, location.latitude, location.longitude, location.notes, now),
        )
        self.conn.commit()
        return self.get_location(location.name)

    def get_location(self, name: str) -> Optional[Location]:
        row = self.conn.execute(
            "SELECT * FROM locations WHERE name=?", (name,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_location(row)

    def list_locations(self) -> list[Location]:
        rows = self.conn.execute("SELECT * FROM locations").fetchall()
        return [self._row_to_location(r) for r in rows]

    def _row_to_location(self, row: sqlite3.Row) -> Location:
        return Location(
            id=row["id"],
            name=row["name"],
            address=row["address"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            notes=row["notes"],
            created_at=row["created_at"],
        )

    # --- Context ---

    def store_context(self, entry: ContextEntry) -> None:
        self.conn.execute(
            """INSERT INTO context (session_id, topic, summary, agent)
               VALUES (?, ?, ?, ?)""",
            (entry.session_id, entry.topic, entry.summary, entry.agent),
        )
        self.conn.commit()

    def get_context_by_session(self, session_id: str) -> list[ContextEntry]:
        rows = self.conn.execute(
            "SELECT * FROM context WHERE session_id=? ORDER BY created_at", (session_id,)
        ).fetchall()
        return [self._row_to_context(r) for r in rows]

    def get_recent_context(self, limit: int = 10) -> list[ContextEntry]:
        rows = self.conn.execute(
            "SELECT * FROM context ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_context(r) for r in rows]

    def _row_to_context(self, row: sqlite3.Row) -> ContextEntry:
        return ContextEntry(
            id=row["id"],
            session_id=row["session_id"],
            topic=row["topic"],
            summary=row["summary"],
            agent=row["agent"],
            created_at=row["created_at"],
        )

    def close(self):
        self.conn.close()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory_store.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add memory/store.py tests/test_memory_store.py
git commit -m "feat: add SQLite-backed memory store with facts, locations, and context"
```

---

### Task 4: Document Store (ChromaDB)

**Files:**
- Create: `documents/store.py`
- Create: `documents/ingestion.py`
- Create: `tests/test_document_store.py`

**Step 1: Write the failing tests**

```python
# tests/test_document_store.py
import pytest
from pathlib import Path
from documents.store import DocumentStore
from documents.ingestion import chunk_text, load_text_file


@pytest.fixture
def doc_store(tmp_path):
    store = DocumentStore(persist_dir=tmp_path / "chroma")
    yield store


class TestDocumentStore:
    def test_add_and_search(self, doc_store):
        doc_store.add_documents(
            texts=["Python is a programming language", "The weather is sunny today"],
            metadatas=[{"source": "doc1.txt"}, {"source": "doc2.txt"}],
            ids=["chunk_1", "chunk_2"],
        )
        results = doc_store.search("programming", top_k=1)
        assert len(results) == 1
        assert "Python" in results[0]["text"]

    def test_search_returns_metadata(self, doc_store):
        doc_store.add_documents(
            texts=["Claude is an AI assistant"],
            metadatas=[{"source": "ai.txt", "page": 1}],
            ids=["chunk_1"],
        )
        results = doc_store.search("AI assistant", top_k=1)
        assert results[0]["metadata"]["source"] == "ai.txt"

    def test_search_empty_store(self, doc_store):
        results = doc_store.search("anything", top_k=5)
        assert results == []

    def test_search_top_k(self, doc_store):
        texts = [f"Document number {i}" for i in range(10)]
        metadatas = [{"source": f"doc_{i}.txt"} for i in range(10)]
        ids = [f"chunk_{i}" for i in range(10)]
        doc_store.add_documents(texts=texts, metadatas=metadatas, ids=ids)
        results = doc_store.search("Document", top_k=3)
        assert len(results) == 3


class TestChunking:
    def test_chunk_short_text(self):
        chunks = chunk_text("Hello world", chunk_size=100, overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_chunk_long_text(self):
        words = ["word"] * 200
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.split()) <= 50

    def test_chunk_overlap(self):
        words = [f"word{i}" for i in range(100)]
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=30, overlap=5)
        assert len(chunks) >= 2
        # Overlap means end of chunk N shares words with start of chunk N+1
        first_end_words = chunks[0].split()[-5:]
        second_start_words = chunks[1].split()[:5]
        assert first_end_words == second_start_words


class TestIngestion:
    def test_load_text_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, this is a test document.")
        text = load_text_file(test_file)
        assert text == "Hello, this is a test document."

    def test_load_markdown_file(self, tmp_path):
        test_file = tmp_path / "test.md"
        test_file.write_text("# Title\n\nSome content here.")
        text = load_text_file(test_file)
        assert "Title" in text
        assert "Some content here." in text
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_document_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write ingestion module**

```python
# documents/ingestion.py
import hashlib
from pathlib import Path


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start = end - overlap

    return chunks


def load_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]
```

**Step 4: Write document store**

```python
# documents/store.py
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings


class DocumentStore:
    def __init__(self, persist_dir: Path):
        self.client = chromadb.Client(Settings(
            persist_directory=str(persist_dir),
            is_persistent=True,
            anonymized_telemetry=False,
        ))
        self.collection = self.client.get_or_create_collection(
            name="chief_of_staff_docs",
            metadata={"hnsw:space": "cosine"},
        )

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict],
        ids: list[str],
    ) -> None:
        self.collection.add(documents=texts, metadatas=metadatas, ids=ids)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if self.collection.count() == 0:
            return []
        results = self.collection.query(query_texts=[query], n_results=top_k)
        output = []
        for i in range(len(results["documents"][0])):
            output.append({
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else None,
            })
        return output
```

**Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_document_store.py -v`
Expected: All 8 tests PASS

**Step 6: Commit**

```bash
git add documents/store.py documents/ingestion.py tests/test_document_store.py
git commit -m "feat: add ChromaDB document store with chunking and ingestion"
```

---

### Task 5: Agent Registry

**Files:**
- Create: `agents/registry.py`
- Create: `tests/test_agent_registry.py`
- Create: `agent_configs/example_agent.yaml`

**Step 1: Write the failing tests**

```python
# tests/test_agent_registry.py
import pytest
import yaml
from pathlib import Path
from agents.registry import AgentRegistry, AgentConfig


@pytest.fixture
def configs_dir(tmp_path):
    return tmp_path / "agent_configs"


@pytest.fixture
def registry(configs_dir):
    configs_dir.mkdir()
    return AgentRegistry(configs_dir)


def _write_agent_yaml(configs_dir: Path, name: str, description: str, capabilities: list[str]):
    config = {
        "name": name,
        "description": description,
        "system_prompt": f"You are a {name}.",
        "capabilities": capabilities,
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    path = configs_dir / f"{name}.yaml"
    path.write_text(yaml.dump(config))
    return path


class TestAgentRegistry:
    def test_list_agents_empty(self, registry):
        agents = registry.list_agents()
        assert agents == []

    def test_load_agent(self, registry, configs_dir):
        _write_agent_yaml(configs_dir, "researcher", "Research expert", ["web_search"])
        config = registry.get_agent("researcher")
        assert config is not None
        assert config.name == "researcher"
        assert config.description == "Research expert"
        assert "web_search" in config.capabilities

    def test_list_agents(self, registry, configs_dir):
        _write_agent_yaml(configs_dir, "researcher", "Research expert", ["web_search"])
        _write_agent_yaml(configs_dir, "planner", "Event planner", ["memory_read"])
        agents = registry.list_agents()
        assert len(agents) == 2
        names = [a.name for a in agents]
        assert "researcher" in names
        assert "planner" in names

    def test_get_nonexistent_agent(self, registry):
        result = registry.get_agent("nonexistent")
        assert result is None

    def test_save_agent(self, registry, configs_dir):
        config = AgentConfig(
            name="new_agent",
            description="A new agent",
            system_prompt="You are a new agent.",
            capabilities=["memory_read", "memory_write"],
            temperature=0.5,
            max_tokens=2048,
        )
        registry.save_agent(config)
        assert (configs_dir / "new_agent.yaml").exists()

        loaded = registry.get_agent("new_agent")
        assert loaded is not None
        assert loaded.description == "A new agent"
        assert loaded.temperature == 0.5

    def test_agent_exists(self, registry, configs_dir):
        assert not registry.agent_exists("researcher")
        _write_agent_yaml(configs_dir, "researcher", "Research expert", ["web_search"])
        assert registry.agent_exists("researcher")
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_registry.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# agents/registry.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class AgentConfig:
    name: str
    description: str
    system_prompt: str
    capabilities: list[str] = field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 4096
    created_by: Optional[str] = None
    created_at: Optional[str] = None


class AgentRegistry:
    def __init__(self, configs_dir: Path):
        self.configs_dir = configs_dir
        self.configs_dir.mkdir(parents=True, exist_ok=True)

    def list_agents(self) -> list[AgentConfig]:
        agents = []
        for path in sorted(self.configs_dir.glob("*.yaml")):
            config = self._load_yaml(path)
            if config:
                agents.append(config)
        return agents

    def get_agent(self, name: str) -> Optional[AgentConfig]:
        path = self.configs_dir / f"{name}.yaml"
        if not path.exists():
            return None
        return self._load_yaml(path)

    def save_agent(self, config: AgentConfig) -> Path:
        path = self.configs_dir / f"{config.name}.yaml"
        data = {
            "name": config.name,
            "description": config.description,
            "system_prompt": config.system_prompt,
            "capabilities": config.capabilities,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }
        if config.created_by:
            data["created_by"] = config.created_by
        if config.created_at:
            data["created_at"] = config.created_at
        path.write_text(yaml.dump(data, default_flow_style=False))
        return path

    def agent_exists(self, name: str) -> bool:
        return (self.configs_dir / f"{name}.yaml").exists()

    def _load_yaml(self, path: Path) -> Optional[AgentConfig]:
        try:
            data = yaml.safe_load(path.read_text())
            return AgentConfig(
                name=data["name"],
                description=data.get("description", ""),
                system_prompt=data.get("system_prompt", ""),
                capabilities=data.get("capabilities", []),
                temperature=data.get("temperature", 0.3),
                max_tokens=data.get("max_tokens", 4096),
                created_by=data.get("created_by"),
                created_at=data.get("created_at"),
            )
        except (yaml.YAMLError, KeyError):
            return None
```

**Step 4: Create the example agent config**

```yaml
# agent_configs/example_agent.yaml
name: general_assistant
description: "A general-purpose assistant for common tasks"
system_prompt: |
  You are a general-purpose assistant. You help with a wide range of tasks
  including answering questions, writing text, and providing recommendations.
  Be concise and helpful.
capabilities:
  - memory_read
  - memory_write
  - document_search
temperature: 0.5
max_tokens: 4096
created_by: system
created_at: "2026-02-12"
```

**Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_registry.py -v`
Expected: All 6 tests PASS

**Step 6: Commit**

```bash
git add agents/registry.py tests/test_agent_registry.py agent_configs/example_agent.yaml
git commit -m "feat: add agent registry with YAML config loading and saving"
```

---

### Task 6: Base Expert Agent

**Files:**
- Create: `agents/base.py`
- Create: `tests/test_base_agent.py`

**Step 1: Write the failing tests**

```python
# tests/test_base_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.base import BaseExpertAgent
from agents.registry import AgentConfig
from memory.store import MemoryStore
from documents.store import DocumentStore


@pytest.fixture
def agent_config():
    return AgentConfig(
        name="test_agent",
        description="A test agent",
        system_prompt="You are a test agent. Be helpful.",
        capabilities=["memory_read", "document_search"],
        temperature=0.3,
        max_tokens=4096,
    )


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def doc_store(tmp_path):
    return DocumentStore(persist_dir=tmp_path / "chroma")


class TestBaseExpertAgent:
    def test_agent_creation(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        assert agent.name == "test_agent"
        assert agent.config.temperature == 0.3

    def test_agent_builds_system_prompt(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        system = agent.build_system_prompt()
        assert "You are a test agent" in system

    def test_agent_gets_tools_from_capabilities(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        tools = agent.get_tools()
        tool_names = [t["name"] for t in tools]
        assert "query_memory" in tool_names
        assert "search_documents" in tool_names
        # memory_write not in capabilities, so store_memory should not be present
        assert "store_memory" not in tool_names

    @pytest.mark.asyncio
    async def test_agent_execute_calls_api(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Test response")]
        mock_response.stop_reason = "end_turn"

        with patch.object(agent, "_call_api", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.execute("Hello, test agent")
            assert result == "Test response"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_base_agent.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# agents/base.py
import json
from typing import Any, Optional

import anthropic

import config as app_config
from agents.registry import AgentConfig
from documents.store import DocumentStore
from memory.models import Fact
from memory.store import MemoryStore

CAPABILITY_TOOLS = {
    "memory_read": {
        "name": "query_memory",
        "description": "Look up facts, locations, or personal details from shared memory",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term to look up in memory"},
                "category": {"type": "string", "description": "Optional category filter (personal, preference, work, relationship)"},
            },
            "required": ["query"],
        },
    },
    "memory_write": {
        "name": "store_memory",
        "description": "Save a new fact to shared memory",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Fact category (personal, preference, work, relationship)"},
                "key": {"type": "string", "description": "Fact key (e.g., 'name', 'favorite_food')"},
                "value": {"type": "string", "description": "Fact value"},
            },
            "required": ["category", "key", "value"],
        },
    },
    "document_search": {
        "name": "search_documents",
        "description": "Semantic search over ingested documents",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "description": "Number of results to return", "default": 5},
            },
            "required": ["query"],
        },
    },
}


class BaseExpertAgent:
    def __init__(
        self,
        config: AgentConfig,
        memory_store: MemoryStore,
        document_store: DocumentStore,
    ):
        self.config = config
        self.name = config.name
        self.memory_store = memory_store
        self.document_store = document_store
        self.client = anthropic.Anthropic(api_key=app_config.ANTHROPIC_API_KEY)

    def build_system_prompt(self) -> str:
        return self.config.system_prompt

    def get_tools(self) -> list[dict]:
        tools = []
        for capability in self.config.capabilities:
            if capability in CAPABILITY_TOOLS:
                tools.append(CAPABILITY_TOOLS[capability])
        return tools

    async def execute(self, task: str) -> str:
        messages = [{"role": "user", "content": task}]
        tools = self.get_tools()

        while True:
            response = await self._call_api(messages, tools)

            # Check if the model wants to use a tool
            if response.stop_reason == "tool_use":
                # Process tool calls
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        result = self._handle_tool_call(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            # Extract text response
            for block in response.content:
                if block.type == "text":
                    return block.text

            return ""

    async def _call_api(self, messages: list, tools: list) -> Any:
        kwargs = {
            "model": app_config.DEFAULT_MODEL,
            "max_tokens": self.config.max_tokens,
            "system": self.build_system_prompt(),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        return self.client.messages.create(**kwargs)

    def _handle_tool_call(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name == "query_memory":
            query = tool_input["query"]
            category = tool_input.get("category")
            if category:
                facts = self.memory_store.get_facts_by_category(category)
                facts = [f for f in facts if query.lower() in f.value.lower() or query.lower() in f.key.lower()]
            else:
                facts = self.memory_store.search_facts(query)
            return [{"category": f.category, "key": f.key, "value": f.value} for f in facts]

        elif tool_name == "store_memory":
            fact = Fact(
                category=tool_input["category"],
                key=tool_input["key"],
                value=tool_input["value"],
                source=self.name,
            )
            self.memory_store.store_fact(fact)
            return {"status": "stored", "key": tool_input["key"]}

        elif tool_name == "search_documents":
            query = tool_input["query"]
            top_k = tool_input.get("top_k", 5)
            results = self.document_store.search(query, top_k=top_k)
            return [{"text": r["text"], "source": r["metadata"].get("source", "unknown")} for r in results]

        return {"error": f"Unknown tool: {tool_name}"}
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_base_agent.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add agents/base.py tests/test_base_agent.py
git commit -m "feat: add BaseExpertAgent with capability-based tool mapping"
```

---

### Task 7: Agent Factory (Dynamic Creation)

**Files:**
- Create: `agents/factory.py`
- Create: `tests/test_agent_factory.py`

**Step 1: Write the failing tests**

```python
# tests/test_agent_factory.py
import pytest
from unittest.mock import MagicMock, patch
from agents.factory import AgentFactory
from agents.registry import AgentRegistry, AgentConfig


@pytest.fixture
def registry(tmp_path):
    return AgentRegistry(tmp_path / "agent_configs")


@pytest.fixture
def factory(registry):
    return AgentFactory(registry)


class TestAgentFactory:
    def test_create_agent_from_description(self, factory, registry):
        """Factory should generate an AgentConfig from a natural language description."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(
            type="text",
            text="""{
                "name": "event_planner",
                "description": "Expert at planning events, venues, catering, and logistics",
                "system_prompt": "You are an event planning expert. You help organize events by finding venues, coordinating logistics, and managing timelines.",
                "capabilities": ["memory_read", "memory_write", "web_search"],
                "temperature": 0.4
            }""",
        )]

        with patch("agents.factory.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            config = factory.create_agent("I need help planning a company offsite event")

        assert config.name == "event_planner"
        assert "event" in config.description.lower()
        assert len(config.capabilities) > 0
        # Should be saved to registry
        assert registry.agent_exists("event_planner")

    def test_create_agent_saves_to_registry(self, factory, registry):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(
            type="text",
            text="""{
                "name": "budget_analyst",
                "description": "Expert at financial analysis and budgeting",
                "system_prompt": "You are a budget analyst.",
                "capabilities": ["memory_read"],
                "temperature": 0.2
            }""",
        )]

        with patch("agents.factory.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            factory.create_agent("Help me analyze my budget")

        loaded = registry.get_agent("budget_analyst")
        assert loaded is not None
        assert loaded.name == "budget_analyst"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_factory.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# agents/factory.py
import json
from datetime import datetime

import anthropic

import config as app_config
from agents.registry import AgentConfig, AgentRegistry

AGENT_CREATION_PROMPT = """You are an expert at creating AI agent configurations. Given a user's need, generate a JSON agent config.

Available capabilities (choose only what's relevant):
- memory_read: Read from shared memory (facts, locations, personal details)
- memory_write: Write to shared memory
- document_search: Search over ingested documents
- web_search: Search the web
- file_operations: Read/write local files
- code_execution: Run Python code

Respond with ONLY valid JSON (no markdown, no explanation):
{
    "name": "snake_case_name",
    "description": "One-line description of expertise",
    "system_prompt": "Detailed system prompt for the agent",
    "capabilities": ["list", "of", "capabilities"],
    "temperature": 0.3
}"""


class AgentFactory:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry
        self.client = anthropic.Anthropic(api_key=app_config.ANTHROPIC_API_KEY)

    def create_agent(self, description: str) -> AgentConfig:
        response = self.client.messages.create(
            model=app_config.CHIEF_MODEL,
            max_tokens=1024,
            system=AGENT_CREATION_PROMPT,
            messages=[{"role": "user", "content": f"I need an agent for: {description}"}],
        )

        raw = response.content[0].text
        data = json.loads(raw)

        config = AgentConfig(
            name=data["name"],
            description=data["description"],
            system_prompt=data["system_prompt"],
            capabilities=data.get("capabilities", ["memory_read"]),
            temperature=data.get("temperature", 0.3),
            max_tokens=data.get("max_tokens", 4096),
            created_by="chief_of_staff",
            created_at=datetime.now().isoformat(),
        )

        self.registry.save_agent(config)
        return config
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_factory.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add agents/factory.py tests/test_agent_factory.py
git commit -m "feat: add agent factory for dynamic agent creation via Claude"
```

---

### Task 8: Async Agent Dispatcher

**Files:**
- Create: `chief/dispatcher.py`
- Create: `tests/test_dispatcher.py`

**Step 1: Write the failing tests**

```python
# tests/test_dispatcher.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from chief.dispatcher import AgentDispatcher, DispatchResult


@pytest.fixture
def dispatcher():
    return AgentDispatcher(timeout_seconds=5)


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_single_agent(self, dispatcher):
        agent = MagicMock()
        agent.name = "test_agent"
        agent.execute = AsyncMock(return_value="Agent result")

        results = await dispatcher.dispatch([("test_agent", agent, "Do something")])
        assert len(results) == 1
        assert results[0].agent_name == "test_agent"
        assert results[0].result == "Agent result"
        assert results[0].error is None

    @pytest.mark.asyncio
    async def test_dispatch_multiple_agents_parallel(self, dispatcher):
        agents = []
        for i in range(3):
            agent = MagicMock()
            agent.name = f"agent_{i}"
            agent.execute = AsyncMock(return_value=f"Result {i}")
            agents.append((f"agent_{i}", agent, f"Task {i}"))

        results = await dispatcher.dispatch(agents)
        assert len(results) == 3
        result_texts = [r.result for r in results]
        assert "Result 0" in result_texts
        assert "Result 1" in result_texts
        assert "Result 2" in result_texts

    @pytest.mark.asyncio
    async def test_dispatch_handles_agent_error(self, dispatcher):
        agent = MagicMock()
        agent.name = "failing_agent"
        agent.execute = AsyncMock(side_effect=Exception("Agent crashed"))

        results = await dispatcher.dispatch([("failing_agent", agent, "Do something")])
        assert len(results) == 1
        assert results[0].error is not None
        assert "Agent crashed" in results[0].error

    @pytest.mark.asyncio
    async def test_dispatch_handles_timeout(self):
        dispatcher = AgentDispatcher(timeout_seconds=1)
        agent = MagicMock()
        agent.name = "slow_agent"

        async def slow_task(task):
            await asyncio.sleep(10)
            return "Never returns"

        agent.execute = slow_task

        results = await dispatcher.dispatch([("slow_agent", agent, "Do something")])
        assert len(results) == 1
        assert results[0].error is not None
        assert "timed out" in results[0].error.lower()

    @pytest.mark.asyncio
    async def test_dispatch_partial_failure(self, dispatcher):
        good_agent = MagicMock()
        good_agent.name = "good_agent"
        good_agent.execute = AsyncMock(return_value="Success")

        bad_agent = MagicMock()
        bad_agent.name = "bad_agent"
        bad_agent.execute = AsyncMock(side_effect=RuntimeError("Failed"))

        results = await dispatcher.dispatch([
            ("good_agent", good_agent, "Task 1"),
            ("bad_agent", bad_agent, "Task 2"),
        ])
        assert len(results) == 2
        success = [r for r in results if r.error is None]
        failures = [r for r in results if r.error is not None]
        assert len(success) == 1
        assert len(failures) == 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dispatcher.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# chief/dispatcher.py
import asyncio
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class DispatchResult:
    agent_name: str
    result: Optional[str] = None
    error: Optional[str] = None


class AgentDispatcher:
    def __init__(self, timeout_seconds: int = 60):
        self.timeout_seconds = timeout_seconds

    async def dispatch(
        self, tasks: list[tuple[str, Any, str]]
    ) -> list[DispatchResult]:
        """Dispatch tasks to agents in parallel.

        Args:
            tasks: List of (agent_name, agent_instance, task_description) tuples

        Returns:
            List of DispatchResult with results or errors
        """
        coroutines = [
            self._run_agent(name, agent, task)
            for name, agent, task in tasks
        ]
        return await asyncio.gather(*coroutines)

    async def _run_agent(
        self, name: str, agent: Any, task: str
    ) -> DispatchResult:
        try:
            result = await asyncio.wait_for(
                agent.execute(task), timeout=self.timeout_seconds
            )
            return DispatchResult(agent_name=name, result=result)
        except asyncio.TimeoutError:
            return DispatchResult(
                agent_name=name, error=f"Agent '{name}' timed out after {self.timeout_seconds}s"
            )
        except Exception as e:
            return DispatchResult(agent_name=name, error=str(e))
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dispatcher.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add chief/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: add async agent dispatcher with parallel execution and timeout"
```

---

### Task 9: Tool Definitions for Chief of Staff

**Files:**
- Create: `tools/definitions.py`
- Create: `tests/test_tool_definitions.py`

**Step 1: Write the failing tests**

```python
# tests/test_tool_definitions.py
from tools.definitions import get_chief_tools, CHIEF_TOOLS


class TestToolDefinitions:
    def test_all_tools_have_required_fields(self):
        tools = get_chief_tools()
        for tool in tools:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool {tool['name']} missing 'description'"
            assert "input_schema" in tool, f"Tool {tool['name']} missing 'input_schema'"
            assert tool["input_schema"]["type"] == "object"

    def test_expected_tools_exist(self):
        tools = get_chief_tools()
        names = [t["name"] for t in tools]
        assert "query_memory" in names
        assert "store_memory" in names
        assert "search_documents" in names
        assert "list_agents" in names
        assert "dispatch_agent" in names
        assert "create_agent" in names
        assert "dispatch_parallel" in names

    def test_tool_count(self):
        tools = get_chief_tools()
        assert len(tools) == 7
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tool_definitions.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# tools/definitions.py

CHIEF_TOOLS = [
    {
        "name": "query_memory",
        "description": "Look up facts, locations, or personal details from shared memory. Use this to recall things about the user or context from previous conversations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term to look up"},
                "category": {
                    "type": "string",
                    "description": "Optional category filter",
                    "enum": ["personal", "preference", "work", "relationship", "location"],
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "store_memory",
        "description": "Save a new fact or detail to shared memory so it can be recalled later.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Fact category",
                    "enum": ["personal", "preference", "work", "relationship"],
                },
                "key": {"type": "string", "description": "Fact key (e.g., 'name', 'favorite_food')"},
                "value": {"type": "string", "description": "Fact value"},
            },
            "required": ["category", "key", "value"],
        },
    },
    {
        "name": "search_documents",
        "description": "Search over ingested documents using semantic similarity. Returns relevant passages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "top_k": {"type": "integer", "description": "Number of results", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_agents",
        "description": "List all available expert agents and their descriptions.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "dispatch_agent",
        "description": "Send a task to a specific expert agent and get their response.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Name of the expert agent to dispatch"},
                "task": {"type": "string", "description": "The task description for the agent"},
            },
            "required": ["agent_name", "task"],
        },
    },
    {
        "name": "create_agent",
        "description": "Create a new expert agent when no existing agent has the right expertise. Describe what kind of expert is needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Description of the expertise needed (e.g., 'an expert in event planning and logistics')",
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "dispatch_parallel",
        "description": "Send tasks to multiple expert agents simultaneously. Use when a request benefits from multiple perspectives or specialties.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "List of agent-task pairs to dispatch in parallel",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent_name": {"type": "string"},
                            "task": {"type": "string"},
                        },
                        "required": ["agent_name", "task"],
                    },
                },
            },
            "required": ["tasks"],
        },
    },
]


def get_chief_tools() -> list[dict]:
    return CHIEF_TOOLS
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tool_definitions.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add tools/definitions.py tests/test_tool_definitions.py
git commit -m "feat: add Chief of Staff tool definitions (7 tools)"
```

---

### Task 10: Chief of Staff Orchestrator

**Files:**
- Create: `chief/orchestrator.py`
- Create: `tests/test_orchestrator.py`

**Step 1: Write the failing tests**

```python
# tests/test_orchestrator.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from chief.orchestrator import ChiefOfStaff
from memory.store import MemoryStore
from memory.models import Fact
from documents.store import DocumentStore
from agents.registry import AgentRegistry


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def doc_store(tmp_path):
    return DocumentStore(persist_dir=tmp_path / "chroma")


@pytest.fixture
def registry(tmp_path):
    return AgentRegistry(tmp_path / "agent_configs")


@pytest.fixture
def chief(memory_store, doc_store, registry):
    return ChiefOfStaff(
        memory_store=memory_store,
        document_store=doc_store,
        agent_registry=registry,
    )


class TestChiefOfStaff:
    def test_creation(self, chief):
        assert chief.memory_store is not None
        assert chief.document_store is not None
        assert chief.agent_registry is not None
        assert chief.conversation_history == []

    def test_handle_tool_query_memory(self, chief, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        result = chief.handle_tool_call("query_memory", {"query": "Jason"})
        assert len(result) >= 1
        assert result[0]["value"] == "Jason"

    def test_handle_tool_store_memory(self, chief, memory_store):
        result = chief.handle_tool_call(
            "store_memory",
            {"category": "personal", "key": "city", "value": "San Francisco"},
        )
        assert result["status"] == "stored"
        fact = memory_store.get_fact("personal", "city")
        assert fact.value == "San Francisco"

    def test_handle_tool_list_agents(self, chief):
        result = chief.handle_tool_call("list_agents", {})
        assert isinstance(result, list)

    def test_handle_tool_search_documents(self, chief, doc_store):
        doc_store.add_documents(
            texts=["Python is great for AI"],
            metadatas=[{"source": "test.txt"}],
            ids=["chunk_1"],
        )
        result = chief.handle_tool_call("search_documents", {"query": "Python AI"})
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_process_simple_message(self, chief):
        """Chief should process a simple message and return a response."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Hello! How can I help?")]
        mock_response.stop_reason = "end_turn"

        with patch.object(chief, "_call_api", return_value=mock_response):
            result = await chief.process("Hello")
            assert "Hello" in result or "help" in result.lower()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# chief/orchestrator.py
import asyncio
import json
import uuid
from typing import Any

import anthropic

import config as app_config
from agents.base import BaseExpertAgent
from agents.factory import AgentFactory
from agents.registry import AgentRegistry
from chief.dispatcher import AgentDispatcher
from documents.store import DocumentStore
from memory.models import Fact
from memory.store import MemoryStore
from tools.definitions import get_chief_tools

CHIEF_SYSTEM_PROMPT = """You are the Chief of Staff, an AI orchestrator that manages a team of expert agents.

Your responsibilities:
1. Understand user requests and decide the best way to handle them
2. Check shared memory for relevant context about the user
3. Delegate tasks to expert agents when specialized knowledge is needed
4. Create new expert agents when no existing agent has the right expertise
5. Dispatch multiple agents in parallel when a task benefits from multiple perspectives
6. Synthesize results from multiple agents into coherent responses
7. Store important facts and details in shared memory for future reference

Always check memory first for context. When you learn new facts about the user (name, preferences, etc.), store them.
When delegating, give agents clear, specific tasks. When creating new agents, describe the expertise needed clearly."""


class ChiefOfStaff:
    def __init__(
        self,
        memory_store: MemoryStore,
        document_store: DocumentStore,
        agent_registry: AgentRegistry,
    ):
        self.memory_store = memory_store
        self.document_store = document_store
        self.agent_registry = agent_registry
        self.agent_factory = AgentFactory(agent_registry)
        self.dispatcher = AgentDispatcher(timeout_seconds=app_config.AGENT_TIMEOUT_SECONDS)
        self.client = anthropic.Anthropic(api_key=app_config.ANTHROPIC_API_KEY)
        self.conversation_history: list[dict] = []
        self.session_id = str(uuid.uuid4())[:8]

    async def process(self, user_message: str) -> str:
        self.conversation_history.append({"role": "user", "content": user_message})
        messages = list(self.conversation_history)
        tools = get_chief_tools()

        while True:
            response = self._call_api(messages, tools)

            if response.stop_reason == "tool_use":
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        result = await self._handle_tool_call_async(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            # Extract final text response
            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text

            self.conversation_history.append({"role": "assistant", "content": text})
            return text

    def _call_api(self, messages: list, tools: list) -> Any:
        return self.client.messages.create(
            model=app_config.CHIEF_MODEL,
            max_tokens=4096,
            system=CHIEF_SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
        )

    async def _handle_tool_call_async(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name in ("dispatch_agent", "dispatch_parallel", "create_agent"):
            return await self._handle_async_tool(tool_name, tool_input)
        return self.handle_tool_call(tool_name, tool_input)

    def handle_tool_call(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name == "query_memory":
            query = tool_input["query"]
            category = tool_input.get("category")
            if category == "location":
                locations = self.memory_store.list_locations()
                return [{"name": l.name, "address": l.address} for l in locations
                        if query.lower() in (l.name or "").lower() or query.lower() in (l.address or "").lower()]
            if category:
                facts = self.memory_store.get_facts_by_category(category)
                facts = [f for f in facts if query.lower() in f.value.lower() or query.lower() in f.key.lower()]
            else:
                facts = self.memory_store.search_facts(query)
            return [{"category": f.category, "key": f.key, "value": f.value} for f in facts]

        elif tool_name == "store_memory":
            fact = Fact(
                category=tool_input["category"],
                key=tool_input["key"],
                value=tool_input["value"],
                source="chief_of_staff",
            )
            self.memory_store.store_fact(fact)
            return {"status": "stored", "key": tool_input["key"]}

        elif tool_name == "search_documents":
            query = tool_input["query"]
            top_k = tool_input.get("top_k", 5)
            results = self.document_store.search(query, top_k=top_k)
            return [{"text": r["text"], "source": r["metadata"].get("source", "unknown")} for r in results]

        elif tool_name == "list_agents":
            agents = self.agent_registry.list_agents()
            return [{"name": a.name, "description": a.description} for a in agents]

        return {"error": f"Unknown tool: {tool_name}"}

    async def _handle_async_tool(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name == "create_agent":
            config = self.agent_factory.create_agent(tool_input["description"])
            return {"status": "created", "name": config.name, "description": config.description}

        elif tool_name == "dispatch_agent":
            agent_name = tool_input["agent_name"]
            task = tool_input["task"]
            config = self.agent_registry.get_agent(agent_name)
            if config is None:
                return {"error": f"Agent '{agent_name}' not found"}
            agent = BaseExpertAgent(config, self.memory_store, self.document_store)
            results = await self.dispatcher.dispatch([(agent_name, agent, task)])
            r = results[0]
            if r.error:
                return {"error": r.error}
            return {"agent": agent_name, "response": r.result}

        elif tool_name == "dispatch_parallel":
            tasks_to_dispatch = []
            for item in tool_input["tasks"]:
                config = self.agent_registry.get_agent(item["agent_name"])
                if config is None:
                    continue
                agent = BaseExpertAgent(config, self.memory_store, self.document_store)
                tasks_to_dispatch.append((item["agent_name"], agent, item["task"]))

            if not tasks_to_dispatch:
                return {"error": "No valid agents found for dispatch"}

            results = await self.dispatcher.dispatch(tasks_to_dispatch)
            return [
                {"agent": r.agent_name, "response": r.result, "error": r.error}
                for r in results
            ]

        return {"error": f"Unknown async tool: {tool_name}"}
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add chief/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add Chief of Staff orchestrator with tool handling and agent dispatch"
```

---

### Task 11: CLI Interface

**Files:**
- Create: `main.py`
- Create: `tests/test_cli.py`

**Step 1: Write the failing tests**

```python
# tests/test_cli.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from main import create_chief, run_command


@pytest.fixture
def tmp_dirs(tmp_path):
    return {
        "data_dir": tmp_path / "data",
        "configs_dir": tmp_path / "agent_configs",
    }


class TestCLI:
    def test_create_chief(self, tmp_dirs):
        with patch("main.app_config") as mock_config:
            mock_config.DATA_DIR = tmp_dirs["data_dir"]
            mock_config.MEMORY_DB_PATH = tmp_dirs["data_dir"] / "memory.db"
            mock_config.CHROMA_PERSIST_DIR = tmp_dirs["data_dir"] / "chroma"
            mock_config.AGENT_CONFIGS_DIR = tmp_dirs["configs_dir"]
            chief = create_chief()
            assert chief is not None

    @pytest.mark.asyncio
    async def test_run_agents_command(self, tmp_dirs):
        with patch("main.app_config") as mock_config:
            mock_config.DATA_DIR = tmp_dirs["data_dir"]
            mock_config.MEMORY_DB_PATH = tmp_dirs["data_dir"] / "memory.db"
            mock_config.CHROMA_PERSIST_DIR = tmp_dirs["data_dir"] / "chroma"
            mock_config.AGENT_CONFIGS_DIR = tmp_dirs["configs_dir"]
            chief = create_chief()
            result = await run_command("agents", chief)
            assert result is not None
            assert "agent" in result.lower() or "no" in result.lower()

    @pytest.mark.asyncio
    async def test_run_memory_command(self, tmp_dirs):
        with patch("main.app_config") as mock_config:
            mock_config.DATA_DIR = tmp_dirs["data_dir"]
            mock_config.MEMORY_DB_PATH = tmp_dirs["data_dir"] / "memory.db"
            mock_config.CHROMA_PERSIST_DIR = tmp_dirs["data_dir"] / "chroma"
            mock_config.AGENT_CONFIGS_DIR = tmp_dirs["configs_dir"]
            chief = create_chief()
            result = await run_command("memory", chief)
            assert result is not None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# main.py
import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

import config as app_config
from agents.registry import AgentRegistry
from chief.orchestrator import ChiefOfStaff
from documents.ingestion import chunk_text, content_hash, load_text_file
from documents.store import DocumentStore
from memory.store import MemoryStore

console = Console()


def create_chief() -> ChiefOfStaff:
    app_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    app_config.AGENT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    memory_store = MemoryStore(app_config.MEMORY_DB_PATH)
    document_store = DocumentStore(persist_dir=app_config.CHROMA_PERSIST_DIR)
    agent_registry = AgentRegistry(app_config.AGENT_CONFIGS_DIR)

    return ChiefOfStaff(
        memory_store=memory_store,
        document_store=document_store,
        agent_registry=agent_registry,
    )


async def run_command(command: str, chief: ChiefOfStaff) -> str:
    if command == "agents":
        agents = chief.agent_registry.list_agents()
        if not agents:
            return "No expert agents configured yet. They'll be created on demand."
        lines = ["Available expert agents:"]
        for a in agents:
            lines.append(f"  - {a.name}: {a.description}")
        return "\n".join(lines)

    elif command == "memory":
        categories = ["personal", "preference", "work", "relationship"]
        lines = ["Stored facts:"]
        total = 0
        for cat in categories:
            facts = chief.memory_store.get_facts_by_category(cat)
            if facts:
                lines.append(f"\n  [{cat}]")
                for f in facts:
                    lines.append(f"    {f.key}: {f.value}")
                    total += 1
        if total == 0:
            return "No facts stored yet. I'll learn about you as we chat."
        return "\n".join(lines)

    elif command == "clear":
        chief.conversation_history.clear()
        return "Conversation cleared. Memory persists."

    elif command.startswith("ingest "):
        path = Path(command[7:].strip())
        if not path.exists():
            return f"Path not found: {path}"
        return ingest_path(path, chief.document_store)

    return None


def ingest_path(path: Path, document_store: DocumentStore) -> str:
    supported = {".txt", ".md", ".py", ".json", ".yaml", ".yml"}
    files = []

    if path.is_file():
        files = [path]
    elif path.is_dir():
        for ext in supported:
            files.extend(path.glob(f"**/*{ext}"))

    if not files:
        return f"No supported files found at {path}"

    total_chunks = 0
    for file in files:
        text = load_text_file(file)
        chunks = chunk_text(text)
        file_hash = content_hash(text)

        texts = []
        metadatas = []
        ids = []
        for i, chunk in enumerate(chunks):
            texts.append(chunk)
            metadatas.append({"source": str(file.name), "chunk_index": i})
            ids.append(f"{file_hash}_{i}")

        document_store.add_documents(texts=texts, metadatas=metadatas, ids=ids)
        total_chunks += len(chunks)

    return f"Ingested {len(files)} file(s), {total_chunks} chunks."


async def chat_loop():
    console.print(Panel(
        Text("Chief of Staff ready. Type your request.\n"
             "Commands: agents | memory | clear | ingest <path> | quit",
             style="bold"),
        title="Chief of Staff",
        border_style="blue",
    ))

    chief = create_chief()

    while True:
        try:
            user_input = console.input("[bold green]> [/]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            console.print("Goodbye!")
            break

        # Check for built-in commands
        cmd_result = await run_command(user_input.lower(), chief)
        if cmd_result is not None:
            console.print(cmd_result)
            continue

        # Send to Chief of Staff
        with console.status("[bold blue]Chief of Staff is thinking...[/]"):
            try:
                response = await chief.process(user_input)
                console.print(f"\n[bold blue]Chief of Staff:[/] {response}\n")
            except Exception as e:
                console.print(f"\n[bold red]Error:[/] {e}\n")


def cli_entry():
    asyncio.run(chat_loop())


if __name__ == "__main__":
    cli_entry()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add main.py tests/test_cli.py
git commit -m "feat: add CLI interface with chat loop, commands, and document ingestion"
```

---

### Task 12: Integration Test — Full Flow

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration tests**

```python
# tests/test_integration.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path

from chief.orchestrator import ChiefOfStaff
from memory.store import MemoryStore
from memory.models import Fact
from documents.store import DocumentStore
from agents.registry import AgentRegistry, AgentConfig


@pytest.fixture
def full_system(tmp_path):
    memory = MemoryStore(tmp_path / "memory.db")
    docs = DocumentStore(persist_dir=tmp_path / "chroma")
    configs_dir = tmp_path / "agent_configs"
    configs_dir.mkdir()
    registry = AgentRegistry(configs_dir)

    # Pre-create an agent
    registry.save_agent(AgentConfig(
        name="test_researcher",
        description="Research assistant for testing",
        system_prompt="You are a test research assistant.",
        capabilities=["memory_read", "document_search"],
    ))

    chief = ChiefOfStaff(memory_store=memory, document_store=docs, agent_registry=registry)

    yield {"chief": chief, "memory": memory, "docs": docs, "registry": registry}
    memory.close()


class TestIntegration:
    def test_memory_persists_across_agents(self, full_system):
        """Facts stored by one component are visible to others."""
        memory = full_system["memory"]
        memory.store_fact(Fact(category="personal", key="name", value="Jason", source="test"))
        chief = full_system["chief"]
        result = chief.handle_tool_call("query_memory", {"query": "Jason"})
        assert len(result) >= 1
        assert result[0]["value"] == "Jason"

    def test_document_ingest_and_search(self, full_system, tmp_path):
        """Ingested documents are searchable."""
        docs = full_system["docs"]
        docs.add_documents(
            texts=["Machine learning is a subset of artificial intelligence"],
            metadatas=[{"source": "ml_guide.txt"}],
            ids=["test_chunk_1"],
        )
        result = full_system["chief"].handle_tool_call(
            "search_documents", {"query": "machine learning"}
        )
        assert len(result) >= 1
        assert "machine learning" in result[0]["text"].lower()

    def test_agent_registry_visible_to_chief(self, full_system):
        """Chief can list agents from the registry."""
        result = full_system["chief"].handle_tool_call("list_agents", {})
        assert len(result) >= 1
        names = [a["name"] for a in result]
        assert "test_researcher" in names

    @pytest.mark.asyncio
    async def test_chief_end_to_end_with_mock_api(self, full_system):
        """Full message processing with mocked Claude API."""
        chief = full_system["chief"]

        # Mock a simple text response (no tool use)
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="I'm your Chief of Staff. How can I help?")]
        mock_response.stop_reason = "end_turn"

        with patch.object(chief, "_call_api", return_value=mock_response):
            response = await chief.process("Hello, who are you?")
            assert "Chief of Staff" in response

    @pytest.mark.asyncio
    async def test_chief_stores_memory_via_tool(self, full_system):
        """Chief processes a tool_use response to store memory."""
        chief = full_system["chief"]

        # First response: Claude wants to use store_memory tool
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "store_memory"
        tool_use_block.id = "tool_123"
        tool_use_block.input = {"category": "personal", "key": "pet", "value": "dog named Max"}

        tool_response = MagicMock()
        tool_response.content = [tool_use_block]
        tool_response.stop_reason = "tool_use"

        # Second response: final text
        text_response = MagicMock()
        text_response.content = [MagicMock(type="text", text="Got it! You have a dog named Max.")]
        text_response.stop_reason = "end_turn"

        with patch.object(chief, "_call_api", side_effect=[tool_response, text_response]):
            response = await chief.process("I have a dog named Max")
            assert "Max" in response

        # Verify fact was stored
        fact = full_system["memory"].get_fact("personal", "pet")
        assert fact is not None
        assert fact.value == "dog named Max"
```

**Step 2: Run test to verify it passes**

Run: `python -m pytest tests/test_integration.py -v`
Expected: All 5 tests PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: add integration tests for full Chief of Staff flow"
```

---

### Task 13: Run All Tests and Final Verification

**Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (approximately 38 tests)

**Step 2: Manual smoke test**

Run: `ANTHROPIC_API_KEY=your-key python main.py`

Test these interactions:
1. "Hello, my name is Jason" → should respond and store the fact
2. Type `memory` → should show the stored name
3. Type `agents` → should list available agents
4. "Help me plan a dinner party" → should create a new agent and dispatch
5. Type `quit` → clean exit

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: Chief of Staff v0.1.0 — complete initial implementation"
```
