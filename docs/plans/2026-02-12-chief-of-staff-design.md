# Chief of Staff — System Design

**Date:** 2026-02-12
**Status:** Approved

## Overview

A Python-based AI orchestration system where a "Chief of Staff" agent manages a team of expert agents. The Chief of Staff interprets user requests, decides which experts to involve, dispatches them in parallel, and synthesizes their results into a cohesive response.

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python |
| LLM | Anthropic Claude API |
| Vector DB | ChromaDB (local, embedded) |
| Memory DB | SQLite + JSON |
| Agent configs | YAML files |
| Interface | CLI chat |

## Architecture

Hybrid approach: tool-based decision making + async parallel dispatch.

```
User <-> CLI <-> ChiefOfStaff (Claude-powered decision maker)
                    |-- AgentDispatcher (async task manager)
                    |     |-- ExpertAgent A (running) --+
                    |     |-- ExpertAgent B (running) --+-- all share:
                    |     +-- ExpertAgent C (running) --+
                    |-- SharedMemory (SQLite + JSON)
                    |-- DocumentStore (ChromaDB)
                    +-- AgentRegistry (YAML configs in /agent_configs/)
```

**Why this architecture:**
- Diverse expertise: each agent has its own YAML config with specialized system prompts and capabilities
- Parallel work: asyncio-based dispatcher runs multiple agents concurrently
- Central management: Chief of Staff decides who to involve, monitors progress, synthesizes results

## Project Structure

```
chief_of_staff/
|-- main.py                    # CLI entry point
|-- config.py                  # App-wide settings (API keys, paths)
|-- chief/
|   |-- __init__.py
|   |-- orchestrator.py        # ChiefOfStaff brain
|   +-- dispatcher.py          # Async agent dispatcher
|-- agents/
|   |-- __init__.py
|   |-- registry.py            # Loads/saves/discovers agent YAML configs
|   |-- base.py                # BaseExpertAgent class
|   +-- factory.py             # Creates new agent configs dynamically
|-- memory/
|   |-- __init__.py
|   |-- store.py               # SQLite-backed shared memory
|   +-- models.py              # Memory data models
|-- documents/
|   |-- __init__.py
|   |-- store.py               # ChromaDB vector store wrapper
|   +-- ingestion.py           # Document loading, chunking, embedding
|-- tools/
|   |-- __init__.py
|   +-- definitions.py         # Tool schemas for the Chief of Staff
|-- agent_configs/             # YAML files for each expert agent
|   +-- example_agent.yaml
|-- data/
|   |-- memory.db              # SQLite database (auto-created)
|   +-- chroma/                # ChromaDB persistence directory
|-- requirements.txt
+-- pyproject.toml
```

## Component Designs

### 1. Chief of Staff Orchestrator

The orchestrator is the brain. Processing flow:

1. **Check shared memory** — "Do I already know context about this?"
2. **Classify the request** — Claude decides: handle directly, delegate, or create new agent
3. **Plan execution** — Which agents? What tasks? Parallel or sequential?
4. **Dispatch** — Send tasks to AgentDispatcher
5. **Collect results** — Await all agent responses
6. **Synthesize response** — Merge results into a coherent answer
7. **Update memory** — Store any new facts learned

**Chief of Staff tools:**

| Tool | Purpose |
|------|---------|
| `query_memory` | Look up facts, locations, personal details from SQLite |
| `store_memory` | Save new facts to shared memory |
| `search_documents` | Semantic search over ChromaDB |
| `list_agents` | See what expert agents exist |
| `dispatch_agent` | Send a task to an existing expert agent |
| `create_agent` | Dynamically create a new expert agent config |
| `dispatch_parallel` | Send tasks to multiple agents simultaneously |

### 2. Expert Agent System

Each expert is defined by a YAML config file and executed as an async task.

**Config format** (`agent_configs/research_analyst.yaml`):

```yaml
name: research_analyst
description: "Expert at web research, fact-checking, and synthesizing information"
system_prompt: |
  You are a research analyst. You excel at finding information,
  cross-referencing sources, and presenting clear, accurate summaries.
  Always cite your sources and flag uncertainty.
capabilities:
  - web_search
  - document_search
  - memory_read
  - memory_write
temperature: 0.3
max_tokens: 4096
created_by: chief_of_staff
created_at: "2026-02-12"
```

**Dynamic agent creation flow:**

1. User asks something no existing agent covers
2. Chief of Staff recognizes the gap and calls `create_agent`
3. Claude generates the YAML config (name, description, system prompt, capabilities)
4. Config saved to `agent_configs/`
5. AgentRegistry picks it up immediately
6. Chief of Staff dispatches the task to the new agent

**Capability-to-tool mapping:**

| Capability | What it gives the agent |
|-----------|------------------------|
| `web_search` | Access to web search tool |
| `document_search` | Query ChromaDB |
| `memory_read` | Read from shared memory |
| `memory_write` | Write to shared memory |
| `file_operations` | Read/write local files |
| `code_execution` | Run Python code in sandbox |

### 3. Shared Memory Layer

SQLite with structured tables. All agents read from and write to the same database.

**Schema:**

```sql
CREATE TABLE facts (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,      -- 'personal', 'preference', 'work', 'relationship'
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 1.0, -- 0-1 scale, allows corrections
    source TEXT,                  -- Which agent stored this
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(category, key)
);

CREATE TABLE locations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,           -- 'home', 'office', 'favorite restaurant'
    address TEXT,
    latitude REAL,
    longitude REAL,
    notes TEXT,                   -- JSON for flexible metadata
    created_at TIMESTAMP
);

CREATE TABLE context (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    agent TEXT,
    created_at TIMESTAMP
);
```

**Key behaviors:**
- Every agent gets a `MemoryStore` instance injected at creation
- Read/write methods are thread-safe (SQLite with WAL mode)
- Conflicting facts: newer wins, old one is logged
- Chief of Staff checks memory at the start of every request

### 4. Document Retrieval (ChromaDB)

Semantic search over ingested documents (PDFs, text files, notes, web pages).

**Pipeline:**

```
Documents (PDF, TXT, MD, etc.)
    -> Ingestion Pipeline (chunk + embed)
    -> ChromaDB Collection (store)
    -> search_documents() (query by any agent)
```

**Design decisions:**
- **Embedding model:** `all-MiniLM-L6-v2` via `sentence-transformers` (free, local)
- **Chunking:** ~500 token chunks, 50 token overlap
- **Metadata:** source filename, page number, ingestion date, tags
- **Collections:** Single collection initially
- **Deduplication:** Content hash prevents re-ingesting unchanged files

**Ingestion:** `chief ingest /path/to/documents/` (supports PDF, TXT, MD, DOCX)

### 5. CLI Interface

```
$ chief
Chief of Staff ready. Type your request.

> Help me plan a team offsite in March

Chief of Staff: I don't have an event planning agent yet. Creating one...
  Created: event_planner
  Dispatching to: event_planner, research_analyst

[event_planner] Working on venue options...
[research_analyst] Searching for team-building activities...

Chief of Staff: Here's what I've put together:
...
```

**CLI commands:**
- Default: conversational chat with the Chief of Staff
- `chief ingest <path>` — ingest documents
- `chief agents` — list available expert agents
- `chief memory` — browse stored facts
- `chief clear` — reset conversation (memory persists)

### 6. Error Handling

- Agent failure: Chief of Staff reports it and continues with available results
- Agent timeout: 60 seconds default, configurable per-agent in YAML
- API rate limiting: exponential backoff with retry
- Full API outage: graceful error message, no crash

### 7. Testing Strategy

- **Unit tests:** memory store, document store, agent registry
- **Integration tests:** orchestrator flow with mocked Claude API
- **End-to-end tests:** real API calls (marked as slow/optional)
