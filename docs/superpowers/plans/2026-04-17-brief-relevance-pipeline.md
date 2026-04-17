# Brief Relevance & Context Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make daily and weekly CIO briefs surface *relevant* information instead of dumping raw data, by fixing the synthesis prompt, adding structured source-context to delegations/decisions, reconstructing email/Teams conversations instead of treating messages as islands, introducing a heuristic + LLM triage layer that ranks inputs before synthesis, and wiring the identity graph into person mentions.

**Architecture:** Six focused modules, mostly additive. Core changes: (1) rewrite the synthesis prompt with explicit ranking/filtering rules; (2) add a structured `SourceRef` type to `Delegation` and `Decision` so stored items carry conversation links; (3) new `orchestration/thread_reconstruction.py` groups messages into threads; (4) new `orchestration/triage.py` filters noise heuristically then scores remaining items with Haiku using context pulled from memory/facts/identities/session brain; (5) new `orchestration/person_enrichment.py` resolves name mentions to Identity records; (6) the briefing agent markdown files are updated so they call triage/enrichment between data-gathering and synthesis.

**Tech Stack:** Python 3.13, pytest, asyncio, anthropic SDK (Haiku for triage), SQLite (source_ref column migration), existing FastMCP tool surface.

---

## File Map

| File | Change |
|------|--------|
| `orchestration/synthesis.py` | Rewrite `_SYNTHESIS_SYSTEM` + the per-call instruction block; accept optional `brief_type` hint |
| `memory/models.py` | Add `SourceRef` dataclass; add `source_ref` (JSON) field to `Delegation` and `Decision` |
| `memory/store.py` | ALTER TABLE migration to add `source_ref TEXT` column on decisions + delegations; serialize/deserialize in create/update/get |
| `mcp_tools/lifecycle_tools.py` | Accept `source_ref` dict in `create_delegation` / `create_decision` tools |
| `orchestration/thread_reconstruction.py` | NEW — group emails by `conversationId`; group Teams messages by chat/channel + reply chains |
| `orchestration/triage.py` | NEW — `heuristic_filter`, `build_triage_context`, `llm_triage` using Haiku |
| `orchestration/person_enrichment.py` | NEW — `enrich_person_mention`, `enrich_brief_text` wrapping mentions with parenthetical context |
| `.claude/agents/daily-briefing.md` | Update instructions to call threading → triage → enrichment → synthesis |
| `.claude/agents/weekly-cio-briefing.md` | Same |
| `tests/test_synthesis_prompt.py` | NEW — validates new prompt content + dedup/priority behavior |
| `tests/test_source_ref.py` | NEW — dataclass round-trip + migration safety |
| `tests/test_thread_reconstruction.py` | NEW |
| `tests/test_triage.py` | NEW |
| `tests/test_person_enrichment.py` | NEW |

---

## Task 1: Rewrite synthesis prompt with explicit ranking rules

**Files:**
- Modify: `orchestration/synthesis.py:14-19` (system prompt) and `orchestration/synthesis.py:58` (per-call instruction)
- Create: `tests/test_synthesis_prompt.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_synthesis_prompt.py`:

```python
"""Tests for the synthesis prompt content and behavior."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestration.synthesis import _SYNTHESIS_SYSTEM, synthesize_results


def test_synthesis_system_prompt_includes_ranking_rules():
    """System prompt must specify ranking criteria, not just 'summarize'."""
    prompt = _SYNTHESIS_SYSTEM.lower()
    assert "relevance" in prompt, "prompt must mention relevance-based ranking"
    assert "deduplicat" in prompt, "prompt must instruct deduplication"
    assert "escalation" in prompt or "priority" in prompt, (
        "prompt must establish priority ordering"
    )
    assert "action" in prompt, "prompt must surface action items"


def test_synthesis_system_prompt_forbids_raw_dump():
    """Prompt must explicitly forbid dumping unfiltered agent output."""
    prompt = _SYNTHESIS_SYSTEM.lower()
    assert "do not dump" in prompt or "never dump" in prompt or "no raw" in prompt


@pytest.mark.asyncio
async def test_synthesis_instruction_contains_output_contract():
    """The per-call instruction block must specify output structure."""
    from orchestration import synthesis as s

    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        mock = MagicMock()
        mock.content = [MagicMock(text="ok")]
        mock.usage = MagicMock(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0
        )
        return mock

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch.object(s, "AsyncAnthropic", return_value=mock_client):
        await synthesize_results(
            task="daily brief",
            dispatches=[
                {"agent_name": "a", "status": "success", "result": "x"},
                {"agent_name": "b", "status": "success", "result": "y"},
            ],
        )

    user_content = captured["messages"][0]["content"].lower()
    assert "dedupl" in user_content or "merge" in user_content, (
        "instruction must tell the model how to handle duplicates"
    )
    assert "category" in user_content or "priority" in user_content, (
        "instruction must tell the model how to order items"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_synthesis_prompt.py -v`
Expected: FAIL — current `_SYNTHESIS_SYSTEM` says "merge findings into a single, coherent, concise summary" with no ranking/dedup vocabulary; current instruction on line 58 is "Synthesize the above into a unified summary."

- [ ] **Step 3: Rewrite the system prompt**

In `orchestration/synthesis.py`, replace lines 14-19:

```python
_SYNTHESIS_SYSTEM = (
    "You are the synthesis pass for a Chief of Staff briefing system. "
    "Multiple data-gathering agents have produced raw findings; your job is "
    "to produce a ranked, deduplicated brief that surfaces what matters.\n\n"
    "Ranking rules:\n"
    "1. RELEVANCE FIRST. Each input item may carry a relevance score (0.0-1.0) "
    "and category from an upstream triage pass. Respect them. Drop items below "
    "0.5 unless their category is 'escalation' or 'decision-needed'.\n"
    "2. DEDUPLICATE. If two inputs describe the same underlying event (same "
    "email thread, same incident, same meeting), merge them into one bullet "
    "with the combined context.\n"
    "3. PRIORITIZE BY CATEGORY: escalation > decision-needed > action-for-you "
    "> action-for-report > fyi. Within a category, order by relevance desc.\n"
    "4. NEVER dump raw agent output. Every line must lead with the "
    "action/implication, not the source tool.\n"
    "5. When a person is mentioned, keep any identity enrichment already "
    "attached (role, team) on first mention; drop it on repeats.\n\n"
    "Output style: executive summary tone. Outcomes over activities. "
    "Honest about yellows/reds. No hedging. If an item is a 0.9-relevance "
    "escalation, say so. Do not dump raw data under any circumstance."
)
```

- [ ] **Step 4: Rewrite the per-call instruction**

In `orchestration/synthesis.py`, replace line 58:

```python
parts.append(
    "## Instructions\n"
    "Apply the ranking rules from your system prompt. Deduplicate across "
    "agents (same event → one bullet). Merge overlapping findings. Drop "
    "low-relevance items unless they are escalations or decisions. Preserve "
    "identity enrichment on first mention of each person. Produce a brief "
    "whose top line is the single most important thing the user needs to "
    "know right now; every subsequent line descends in priority.\n\n"
    "If `brief_type` context was provided (e.g. 'daily' or 'cio-weekly'), "
    "follow that format. Otherwise produce a priority-ordered bullet list."
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_synthesis_prompt.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 6: Confirm no regressions in existing synthesis tests**

Run: `pytest tests/test_synthesis.py -v` (if it exists) and `pytest tests/ -k synthesis -v`
Expected: PASS — existing tests should still pass; the prompt change is an expansion, not a signature change.

- [ ] **Step 7: Commit**

```bash
git add orchestration/synthesis.py tests/test_synthesis_prompt.py
git commit -m "feat(synthesis): add explicit ranking, dedup, and priority rules to prompt

Replaces the 12-word 'synthesize the above' stub with a structured prompt
that specifies relevance thresholds, deduplication, category priority,
and a no-raw-dump rule. This is the upstream fix that lets downstream
triage/enrichment work actually show up in briefs."
```

---

## Task 2: Add `SourceRef` dataclass and wire into `Delegation` / `Decision`

**Files:**
- Modify: `memory/models.py` (add `SourceRef`, extend `Delegation` and `Decision`)
- Create: `tests/test_source_ref.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_source_ref.py`:

```python
"""Tests for SourceRef dataclass and its integration on Delegation/Decision."""

import json
import pytest

from memory.models import Decision, Delegation, SourceRef


def test_source_ref_minimum_construction():
    ref = SourceRef(provider="m365_email")
    assert ref.provider == "m365_email"
    assert ref.thread_id is None
    assert ref.url is None


def test_source_ref_full_construction():
    ref = SourceRef(
        provider="m365_teams",
        thread_id="19:abc@thread.v2",
        message_id="1713292800000",
        url="https://teams.microsoft.com/l/message/...",
        quote="Can you own the PST remediation?",
        timestamp="2026-04-17T14:00:00Z",
        from_identity="shawn.farnworth",
    )
    assert ref.quote.startswith("Can you own")
    assert ref.from_identity == "shawn.farnworth"


def test_source_ref_json_roundtrip():
    ref = SourceRef(
        provider="m365_email",
        thread_id="AAMkAD...",
        quote="Need decision on Okta rollback",
    )
    as_json = ref.to_json()
    assert isinstance(as_json, str)
    restored = SourceRef.from_json(as_json)
    assert restored == ref


def test_delegation_accepts_source_ref():
    ref = SourceRef(provider="m365_teams", thread_id="19:abc", url="https://...")
    d = Delegation(
        task="Own PST remediation rollback",
        delegated_to="shawn.farnworth",
        source_ref=ref,
    )
    assert d.source_ref.provider == "m365_teams"


def test_decision_accepts_source_ref():
    ref = SourceRef(provider="m365_email", quote="We're going with option B.")
    dec = Decision(title="Adopt Option B for Okta rollback", source_ref=ref)
    assert dec.source_ref.quote == "We're going with option B."


def test_delegation_source_ref_defaults_none():
    """Backward-compat: existing code creating Delegation without source_ref still works."""
    d = Delegation(task="t", delegated_to="x")
    assert d.source_ref is None
    assert d.source == ""  # legacy string field unchanged


def test_decision_source_ref_defaults_none():
    dec = Decision(title="t")
    assert dec.source_ref is None
    assert dec.source == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_source_ref.py -v`
Expected: FAIL — `SourceRef` does not exist; `Delegation`/`Decision` have no `source_ref` field.

- [ ] **Step 3: Add `SourceRef` to `memory/models.py`**

Insert after the imports block (near the top of the file) and before the existing dataclasses:

```python
@dataclass
class SourceRef:
    """Structured reference to the conversation/message an item came from.

    Replaces the plain-string `source` field on Decision/Delegation.
    Carry this alongside stored items so 'why was this saved?' is answerable.
    """
    provider: str  # m365_email | m365_teams | imessage | calendar | manual
    thread_id: Optional[str] = None
    message_id: Optional[str] = None
    url: Optional[str] = None
    quote: Optional[str] = None
    timestamp: Optional[str] = None  # ISO8601
    from_identity: Optional[str] = None  # canonical_name from identities table

    def to_json(self) -> str:
        from dataclasses import asdict
        import json as _json
        return _json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "SourceRef":
        import json as _json
        return cls(**_json.loads(raw))
```

- [ ] **Step 4: Add `source_ref` field to `Delegation`**

In `memory/models.py`, modify the `Delegation` dataclass (currently lines 177-191). Add one field:

```python
@dataclass
class Delegation:
    task: str
    delegated_to: str
    description: str = ""
    delegated_by: str = ""
    due_date: Optional[str] = None
    priority: DelegationPriority = DelegationPriority.medium
    status: DelegationStatus = DelegationStatus.active
    source: str = ""  # legacy free-text; new code should use source_ref
    source_ref: Optional[SourceRef] = None
    notes: str = ""
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
```

- [ ] **Step 5: Add `source_ref` field to `Decision`**

In `memory/models.py`, modify the `Decision` dataclass (currently lines 160-174):

```python
@dataclass
class Decision:
    title: str
    description: str = ""
    context: str = ""
    alternatives_considered: str = ""
    decided_by: str = ""
    owner: str = ""
    status: DecisionStatus = DecisionStatus.pending_execution
    follow_up_date: Optional[str] = None
    tags: str = ""
    source: str = ""  # legacy free-text; new code should use source_ref
    source_ref: Optional[SourceRef] = None
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_source_ref.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 7: Run existing model tests for regressions**

Run: `pytest tests/ -k "models or delegation or decision" -v`
Expected: PASS — adding an optional field with default `None` is backward compatible.

- [ ] **Step 8: Commit**

```bash
git add memory/models.py tests/test_source_ref.py
git commit -m "feat(models): add SourceRef and attach to Delegation/Decision

Structured source reference replaces the free-text source field for new
code paths (old field kept for backward compat). Enables 'why was this
saved?' traceability from stored items back to the originating email or
Teams conversation."
```

---

## Task 3: Persist `source_ref` in SQLite and expose it through lifecycle tools

**Files:**
- Modify: `memory/store.py` (schema migration + serialize/deserialize in delegation/decision CRUD)
- Modify: `mcp_tools/lifecycle_tools.py` (accept `source_ref` in `create_delegation` and `create_decision`)
- Modify: `tests/test_source_ref.py` (add persistence tests)

- [ ] **Step 1: Find the current delegation/decision schema**

Run: `grep -n "CREATE TABLE.*\(delegations\|decisions\)" memory/store.py`
Note the column list so you know what `_row_to_delegation` / `_row_to_decision` expect.

- [ ] **Step 2: Write failing persistence tests**

Append to `tests/test_source_ref.py`:

```python
import tempfile
from pathlib import Path

from memory.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test.db"
    return MemoryStore(db_path=str(db))


def test_delegation_source_ref_persists(store):
    ref = SourceRef(
        provider="m365_teams",
        thread_id="19:abc@thread.v2",
        url="https://teams.microsoft.com/l/message/x",
        quote="Own PST remediation",
    )
    d = Delegation(task="PST remediation", delegated_to="shawn", source_ref=ref)
    saved = store.create_delegation(d)
    assert saved.id is not None
    reloaded = store.get_delegation(saved.id)
    assert reloaded.source_ref == ref


def test_decision_source_ref_persists(store):
    ref = SourceRef(provider="m365_email", quote="Going with option B")
    dec = Decision(title="Adopt option B", source_ref=ref)
    saved = store.create_decision(dec)
    reloaded = store.get_decision(saved.id)
    assert reloaded.source_ref == ref


def test_legacy_delegation_without_source_ref_still_loads(store):
    """Existing rows (no source_ref column value) must load with source_ref=None."""
    d = Delegation(task="t", delegated_to="x")  # source_ref defaults to None
    saved = store.create_delegation(d)
    reloaded = store.get_delegation(saved.id)
    assert reloaded.source_ref is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_source_ref.py -v`
Expected: FAIL on the three new tests — the column doesn't exist and CRUD doesn't handle it.

- [ ] **Step 4: Add idempotent column migration**

In `memory/store.py`, find the `MemoryStore.__init__` (or `_init_schema` / `_migrate` method — whichever runs at startup). After the `CREATE TABLE` for delegations and decisions, add an idempotent ALTER:

```python
def _migrate_source_ref(self, conn) -> None:
    """Add source_ref column to delegations/decisions if missing (idempotent)."""
    for table in ("delegations", "decisions"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "source_ref" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN source_ref TEXT")
```

Call `self._migrate_source_ref(conn)` from the init path (after the `CREATE TABLE IF NOT EXISTS` statements run).

- [ ] **Step 5: Serialize/deserialize `source_ref` in delegation CRUD**

In `memory/store.py`, find `create_delegation`, `get_delegation`, and `update_delegation`. Wherever a `Delegation` is written to SQL, add:

```python
source_ref_json = d.source_ref.to_json() if d.source_ref else None
# include source_ref_json in the INSERT/UPDATE params and the column list
```

Wherever a row is converted back to a `Delegation`, add:

```python
from memory.models import SourceRef
source_ref = SourceRef.from_json(row["source_ref"]) if row["source_ref"] else None
# pass source_ref=source_ref into Delegation(...)
```

- [ ] **Step 6: Do the same for decisions**

Mirror Step 5 for `create_decision`, `get_decision`, `update_decision`, and `search_decisions` row-to-model conversion.

- [ ] **Step 7: Run persistence tests**

Run: `pytest tests/test_source_ref.py -v`
Expected: PASS (all 10 tests — original 7 plus 3 new)

- [ ] **Step 8: Run lifecycle tool tests for regressions**

Run: `pytest tests/test_lifecycle_tools.py tests/test_memory_store.py -v` (adjust paths if naming differs)
Expected: PASS — the column addition is backward compatible.

- [ ] **Step 9: Accept `source_ref` in `create_delegation` and `create_decision` MCP tools**

In `mcp_tools/lifecycle_tools.py`, find the `create_delegation` `@mcp.tool()` function. Add `source_ref` as an optional dict parameter:

```python
@mcp.tool()
async def create_delegation(
    task: str,
    delegated_to: str,
    description: str = "",
    delegated_by: str = "",
    due_date: str = "",
    priority: str = "medium",
    source: str = "",
    notes: str = "",
    source_ref: dict | None = None,  # NEW
) -> dict:
    """...existing docstring, add:
    source_ref: Optional structured reference to the originating conversation.
        Keys: provider (required), thread_id, message_id, url, quote,
        timestamp, from_identity.
    """
    from memory.models import SourceRef
    ref = SourceRef(**source_ref) if source_ref else None
    # ... existing code, but pass source_ref=ref when constructing Delegation
```

Do the same for `create_decision`.

- [ ] **Step 10: Test the MCP tool signatures**

Run: `pytest tests/test_lifecycle_tools.py -v -k "create_delegation or create_decision"`
Expected: PASS. If the tests don't cover `source_ref`, add one case per tool asserting a round-trip through the tool handler.

- [ ] **Step 11: Commit**

```bash
git add memory/store.py mcp_tools/lifecycle_tools.py tests/test_source_ref.py
git commit -m "feat(storage): persist source_ref for delegations/decisions

Adds idempotent column migration, JSON serialization in store CRUD, and
source_ref parameter on the create_delegation/create_decision MCP tools.
Backward compatible with existing rows (column defaults to NULL)."
```

---

## Task 4: Email thread reconstruction helper

**Files:**
- Create: `orchestration/thread_reconstruction.py`
- Create: `tests/test_thread_reconstruction.py`

- [ ] **Step 1: Write the failing test for email threading**

Create `tests/test_thread_reconstruction.py`:

```python
"""Tests for email/Teams thread reconstruction."""

import pytest

from orchestration.thread_reconstruction import (
    EmailThread,
    reconstruct_email_threads,
)


SAMPLE_EMAILS = [
    {
        "id": "AAMkAD-1",
        "conversationId": "conv-abc",
        "subject": "PST incident — next steps",
        "from": {"emailAddress": {"address": "shawn@chg.com", "name": "Shawn F"}},
        "receivedDateTime": "2026-04-17T10:00:00Z",
        "bodyPreview": "We need a decision on the rollback window.",
        "webLink": "https://outlook.office.com/mail/id/AAMkAD-1",
    },
    {
        "id": "AAMkAD-2",
        "conversationId": "conv-abc",
        "subject": "RE: PST incident — next steps",
        "from": {"emailAddress": {"address": "jason@chg.com", "name": "Jason R"}},
        "receivedDateTime": "2026-04-17T10:30:00Z",
        "bodyPreview": "Going with option B. Ship tonight.",
        "webLink": "https://outlook.office.com/mail/id/AAMkAD-2",
    },
    {
        "id": "AAMkAD-3",
        "conversationId": "conv-xyz",
        "subject": "Weekly roll-up",
        "from": {"emailAddress": {"address": "theresa@chg.com", "name": "Theresa O"}},
        "receivedDateTime": "2026-04-17T09:00:00Z",
        "bodyPreview": "Send the CIO weekly by Friday.",
        "webLink": "https://outlook.office.com/mail/id/AAMkAD-3",
    },
]


def test_reconstruct_email_threads_groups_by_conversation_id():
    threads = reconstruct_email_threads(SAMPLE_EMAILS)
    assert len(threads) == 2
    by_id = {t.conversation_id: t for t in threads}
    assert len(by_id["conv-abc"].messages) == 2
    assert len(by_id["conv-xyz"].messages) == 1


def test_thread_orders_messages_by_received_date():
    threads = reconstruct_email_threads(SAMPLE_EMAILS)
    abc = next(t for t in threads if t.conversation_id == "conv-abc")
    assert abc.messages[0]["id"] == "AAMkAD-1"
    assert abc.messages[1]["id"] == "AAMkAD-2"


def test_thread_latest_message_properties():
    threads = reconstruct_email_threads(SAMPLE_EMAILS)
    abc = next(t for t in threads if t.conversation_id == "conv-abc")
    assert abc.latest_received == "2026-04-17T10:30:00Z"
    assert abc.latest_sender_email == "jason@chg.com"
    assert "option B" in abc.latest_preview


def test_thread_participants_unique():
    threads = reconstruct_email_threads(SAMPLE_EMAILS)
    abc = next(t for t in threads if t.conversation_id == "conv-abc")
    emails = {p["email"] for p in abc.participants}
    assert emails == {"shawn@chg.com", "jason@chg.com"}


def test_empty_input_returns_empty_list():
    assert reconstruct_email_threads([]) == []


def test_missing_conversation_id_falls_back_to_subject():
    """Some tenants don't return conversationId; fall back to normalized subject."""
    items = [
        {
            "id": "1",
            "subject": "RE: Foo",
            "from": {"emailAddress": {"address": "a@x.com"}},
            "receivedDateTime": "2026-04-17T10:00:00Z",
            "bodyPreview": "",
        },
        {
            "id": "2",
            "subject": "FW: Foo",
            "from": {"emailAddress": {"address": "b@x.com"}},
            "receivedDateTime": "2026-04-17T11:00:00Z",
            "bodyPreview": "",
        },
    ]
    threads = reconstruct_email_threads(items)
    assert len(threads) == 1
    assert len(threads[0].messages) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_thread_reconstruction.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the email reconstruction module**

Create `orchestration/thread_reconstruction.py`:

```python
"""Email + Teams thread reconstruction.

Groups individual messages returned by Graph-style search endpoints into
coherent conversation threads so downstream brief-generation operates on
'what was the exchange about' rather than 'here are N floating messages'.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|fw|fwd):\s*", re.IGNORECASE)


def _normalize_subject(subject: str) -> str:
    prev = None
    s = subject or ""
    while prev != s:
        prev = s
        s = _SUBJECT_PREFIX_RE.sub("", s)
    return s.strip().lower()


def _extract_sender(msg: dict[str, Any]) -> tuple[str, str]:
    """Return (email, name) for an email message dict."""
    fr = msg.get("from") or {}
    ea = fr.get("emailAddress") or {}
    return ea.get("address", ""), ea.get("name", "")


@dataclass
class EmailThread:
    conversation_id: str
    subject: str
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def participants(self) -> list[dict[str, str]]:
        seen: dict[str, str] = {}
        for m in self.messages:
            email, name = _extract_sender(m)
            if email and email not in seen:
                seen[email] = name
        return [{"email": e, "name": n} for e, n in seen.items()]

    @property
    def latest(self) -> dict[str, Any]:
        return self.messages[-1] if self.messages else {}

    @property
    def latest_received(self) -> str:
        return self.latest.get("receivedDateTime", "")

    @property
    def latest_sender_email(self) -> str:
        return _extract_sender(self.latest)[0]

    @property
    def latest_preview(self) -> str:
        return self.latest.get("bodyPreview", "")


def reconstruct_email_threads(messages: list[dict[str, Any]]) -> list[EmailThread]:
    """Group email messages into threads keyed by conversationId (or normalized subject)."""
    if not messages:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    for m in messages:
        key = m.get("conversationId") or _normalize_subject(m.get("subject", ""))
        if not key:
            key = m.get("id", "")
        groups.setdefault(key, []).append(m)

    threads: list[EmailThread] = []
    for key, items in groups.items():
        items.sort(key=lambda x: x.get("receivedDateTime", ""))
        subject = items[-1].get("subject", "")
        threads.append(EmailThread(conversation_id=key, subject=subject, messages=items))
    threads.sort(key=lambda t: t.latest_received, reverse=True)
    return threads
```

- [ ] **Step 4: Run email tests to verify they pass**

Run: `pytest tests/test_thread_reconstruction.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestration/thread_reconstruction.py tests/test_thread_reconstruction.py
git commit -m "feat(orchestration): email thread reconstruction

Groups emails returned by outlook_email_search by conversationId (with
normalized-subject fallback) so briefs reason about conversations, not
isolated messages."
```

---

## Task 5: Teams thread reconstruction

**Files:**
- Modify: `orchestration/thread_reconstruction.py` (add Teams support)
- Modify: `tests/test_thread_reconstruction.py` (add Teams tests)

- [ ] **Step 1: Write the failing test for Teams threading**

Append to `tests/test_thread_reconstruction.py`:

```python
from orchestration.thread_reconstruction import (
    TeamsThread,
    reconstruct_teams_threads,
)


SAMPLE_TEAMS = [
    {
        "id": "1713292800000",
        "chatId": "19:abc@thread.v2",
        "chatType": "oneOnOne",
        "from": {"user": {"id": "shawn-id", "displayName": "Shawn F"}},
        "createdDateTime": "2026-04-17T10:00:00Z",
        "body": {"content": "<p>Can you own PST rollback?</p>", "contentType": "html"},
        "webUrl": "https://teams.microsoft.com/l/message/19:abc/1713292800000",
        "replyToId": None,
    },
    {
        "id": "1713292860000",
        "chatId": "19:abc@thread.v2",
        "chatType": "oneOnOne",
        "from": {"user": {"id": "jason-id", "displayName": "Jason R"}},
        "createdDateTime": "2026-04-17T10:01:00Z",
        "body": {"content": "<p>Yes. Ship tonight.</p>", "contentType": "html"},
        "webUrl": "https://teams.microsoft.com/l/message/19:abc/1713292860000",
        "replyToId": "1713292800000",
    },
    {
        "id": "1713293000000",
        "chatId": "19:xyz@thread.v2",
        "chatType": "group",
        "from": {"user": {"id": "theresa-id", "displayName": "Theresa O"}},
        "createdDateTime": "2026-04-17T09:00:00Z",
        "body": {"content": "<p>Weekly roll-up due Friday</p>", "contentType": "html"},
        "webUrl": "https://teams.microsoft.com/l/message/19:xyz/1713293000000",
        "replyToId": None,
    },
]


def test_reconstruct_teams_threads_groups_by_chat_id():
    threads = reconstruct_teams_threads(SAMPLE_TEAMS)
    assert len(threads) == 2


def test_teams_thread_exposes_latest_message_text():
    threads = reconstruct_teams_threads(SAMPLE_TEAMS)
    abc = next(t for t in threads if t.chat_id == "19:abc@thread.v2")
    # latest = jason's reply
    assert "Ship tonight" in abc.latest_preview


def test_teams_thread_strips_html():
    threads = reconstruct_teams_threads(SAMPLE_TEAMS)
    abc = next(t for t in threads if t.chat_id == "19:abc@thread.v2")
    assert "<p>" not in abc.latest_preview
    assert "</p>" not in abc.latest_preview


def test_teams_thread_chat_type_preserved():
    threads = reconstruct_teams_threads(SAMPLE_TEAMS)
    abc = next(t for t in threads if t.chat_id == "19:abc@thread.v2")
    xyz = next(t for t in threads if t.chat_id == "19:xyz@thread.v2")
    assert abc.chat_type == "oneOnOne"
    assert xyz.chat_type == "group"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_thread_reconstruction.py -v -k teams`
Expected: FAIL — `TeamsThread` and `reconstruct_teams_threads` don't exist.

- [ ] **Step 3: Extend the reconstruction module**

Append to `orchestration/thread_reconstruction.py`:

```python
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    return _HTML_TAG_RE.sub("", html or "").strip()


@dataclass
class TeamsThread:
    chat_id: str
    chat_type: str
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def latest(self) -> dict[str, Any]:
        return self.messages[-1] if self.messages else {}

    @property
    def latest_preview(self) -> str:
        body = self.latest.get("body") or {}
        return _strip_html(body.get("content", ""))

    @property
    def latest_created(self) -> str:
        return self.latest.get("createdDateTime", "")

    @property
    def latest_sender_name(self) -> str:
        return ((self.latest.get("from") or {}).get("user") or {}).get("displayName", "")

    @property
    def participants(self) -> list[dict[str, str]]:
        seen: dict[str, str] = {}
        for m in self.messages:
            user = (m.get("from") or {}).get("user") or {}
            uid = user.get("id", "")
            name = user.get("displayName", "")
            if uid and uid not in seen:
                seen[uid] = name
        return [{"id": u, "name": n} for u, n in seen.items()]


def reconstruct_teams_threads(messages: list[dict[str, Any]]) -> list[TeamsThread]:
    """Group Teams chat messages by chatId and order by createdDateTime."""
    if not messages:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    chat_types: dict[str, str] = {}
    for m in messages:
        cid = m.get("chatId") or m.get("channelIdentity", {}).get("channelId") or m.get("id", "")
        groups.setdefault(cid, []).append(m)
        chat_types[cid] = m.get("chatType", chat_types.get(cid, "unknown"))

    threads: list[TeamsThread] = []
    for cid, items in groups.items():
        items.sort(key=lambda x: x.get("createdDateTime", ""))
        threads.append(TeamsThread(chat_id=cid, chat_type=chat_types[cid], messages=items))
    threads.sort(key=lambda t: t.latest_created, reverse=True)
    return threads
```

- [ ] **Step 4: Run Teams tests to verify they pass**

Run: `pytest tests/test_thread_reconstruction.py -v`
Expected: PASS (all 10 tests — 6 email + 4 Teams)

- [ ] **Step 5: Commit**

```bash
git add orchestration/thread_reconstruction.py tests/test_thread_reconstruction.py
git commit -m "feat(orchestration): Teams thread reconstruction

Groups Teams messages from chat_message_search by chatId, strips HTML,
preserves chat_type (1:1 vs group) for downstream triage."
```

---

## Task 6: Heuristic noise filter (first pass of triage)

**Files:**
- Create: `orchestration/triage.py`
- Create: `tests/test_triage.py`

- [ ] **Step 1: Write failing tests for the heuristic filter**

Create `tests/test_triage.py`:

```python
"""Tests for triage heuristic filter + LLM scoring."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestration.triage import (
    FilterConfig,
    TriageContext,
    TriagedItem,
    heuristic_filter,
)


def test_filter_drops_noreply_senders():
    items = [
        {"kind": "email", "from_email": "noreply@domain.com", "subject": "Deploy OK"},
        {"kind": "email", "from_email": "shawn@chg.com", "subject": "PST fix"},
    ]
    config = FilterConfig()
    out = heuristic_filter(items, config)
    assert len(out) == 1
    assert out[0]["from_email"] == "shawn@chg.com"


def test_filter_drops_common_newsletters():
    items = [
        {"kind": "email", "from_email": "digest@substack.com", "subject": "Weekly"},
        {"kind": "email", "from_email": "notifications@github.com", "subject": "PR x"},
        {"kind": "email", "from_email": "shawn@chg.com", "subject": "Real"},
    ]
    config = FilterConfig(noise_senders_contains=("substack.com", "notifications@github.com"))
    out = heuristic_filter(items, config)
    assert [x["from_email"] for x in out] == ["shawn@chg.com"]


def test_filter_keeps_item_from_key_person_even_if_older():
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    items = [
        {"kind": "email", "from_email": "random@x.com", "subject": "stale", "timestamp": old},
        {"kind": "email", "from_email": "theresa@chg.com", "subject": "old ask", "timestamp": old},
        {"kind": "email", "from_email": "random@x.com", "subject": "fresh", "timestamp": recent},
    ]
    config = FilterConfig(max_age_days=14, key_people_emails=("theresa@chg.com",))
    out = heuristic_filter(items, config)
    subjects = {x["subject"] for x in out}
    assert "stale" not in subjects  # too old, not key person → dropped
    assert "old ask" in subjects     # old but key person → kept
    assert "fresh" in subjects       # recent → kept


def test_filter_preserves_unknown_kinds():
    """Items without an explicit kind (e.g., delegation status) should pass through."""
    items = [{"kind": "delegation", "task": "x"}]
    out = heuristic_filter(items, FilterConfig())
    assert out == items


def test_filter_drops_self_sent():
    items = [
        {"kind": "email", "from_email": "jason@chg.com", "subject": "self"},
        {"kind": "email", "from_email": "shawn@chg.com", "subject": "other"},
    ]
    config = FilterConfig(user_email="jason@chg.com")
    out = heuristic_filter(items, config)
    assert len(out) == 1 and out[0]["from_email"] == "shawn@chg.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_triage.py -v`
Expected: FAIL — `orchestration.triage` module does not exist.

- [ ] **Step 3: Implement `FilterConfig`, `TriageContext`, `TriagedItem`, and `heuristic_filter`**

Create `orchestration/triage.py`:

```python
"""Triage: rank and filter brief inputs before synthesis.

Two passes:
  1. heuristic_filter — drop obvious noise (newsletters, self-sent, stale)
  2. llm_triage — Haiku scores each surviving item 0.0-1.0 with category + why

Synthesis consumes the output of llm_triage; this replaces the current
'synthesis sees raw dump' behavior that yields low-signal briefs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

logger = logging.getLogger("jarvis-triage")


_DEFAULT_NOISE_SENDERS = (
    "noreply@", "no-reply@", "donotreply@",
    "notifications@github.com", "notifications@",
    "substack.com", "mailchimp.com", "mailgun",
)


@dataclass
class FilterConfig:
    user_email: str = ""
    max_age_days: int = 14
    key_people_emails: tuple[str, ...] = ()
    noise_senders_contains: tuple[str, ...] = _DEFAULT_NOISE_SENDERS


@dataclass
class TriageContext:
    user_role: str
    active_projects: list[str] = field(default_factory=list)
    current_focus: list[str] = field(default_factory=list)
    key_people: list[str] = field(default_factory=list)  # canonical names


@dataclass
class TriagedItem:
    item: dict[str, Any]
    relevance: float
    category: str  # escalation | decision-needed | action-for-you | action-for-report | fyi
    why: str


def _is_noise_sender(email_addr: str, config: FilterConfig) -> bool:
    addr = (email_addr or "").lower()
    if not addr:
        return False
    return any(token.lower() in addr for token in config.noise_senders_contains)


def _is_stale(item: dict[str, Any], config: FilterConfig) -> bool:
    ts = item.get("timestamp") or item.get("receivedDateTime") or item.get("createdDateTime")
    if not ts:
        return False
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.max_age_days)
    return when < cutoff


def _is_key_person(email_addr: str, config: FilterConfig) -> bool:
    return email_addr.lower() in {e.lower() for e in config.key_people_emails}


def heuristic_filter(
    items: Sequence[dict[str, Any]],
    config: FilterConfig,
) -> list[dict[str, Any]]:
    """Drop obvious noise. Keeps anything whose kind we don't know how to filter."""
    kept: list[dict[str, Any]] = []
    for item in items:
        kind = item.get("kind", "")
        if kind not in {"email", "teams"}:
            kept.append(item)
            continue
        sender = item.get("from_email") or item.get("latest_sender_email") or ""
        if config.user_email and sender.lower() == config.user_email.lower():
            continue
        if _is_noise_sender(sender, config):
            continue
        if _is_stale(item, config) and not _is_key_person(sender, config):
            continue
        kept.append(item)
    return kept
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_triage.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestration/triage.py tests/test_triage.py
git commit -m "feat(triage): heuristic noise filter

First pass of the triage pipeline: drops automated senders, self-sent
mail, and stale items that aren't from key people. Saves downstream
Haiku tokens by filtering obvious garbage before LLM scoring."
```

---

## Task 7: Triage context builder

**Files:**
- Modify: `orchestration/triage.py` (add `build_triage_context`)
- Modify: `tests/test_triage.py` (add context builder tests)

- [ ] **Step 1: Write failing tests for context assembly**

Append to `tests/test_triage.py`:

```python
from orchestration.triage import build_triage_context


class FakeMemory:
    def __init__(self, facts):
        self._facts = facts

    def list_facts(self, category=None, limit=None):
        if category:
            return [f for f in self._facts if f["category"] == category]
        return self._facts


class FakeBrain:
    def __init__(self, text):
        self._text = text

    def get_current_focus(self):
        return self._text


def test_build_triage_context_pulls_user_role():
    mem = FakeMemory([
        {"category": "personal", "key": "role", "value": "VP/Chief of Staff to the CIO"},
    ])
    ctx = build_triage_context(memory_store=mem, brain=FakeBrain(""))
    assert "VP" in ctx.user_role or "Chief of Staff" in ctx.user_role


def test_build_triage_context_includes_active_projects():
    mem = FakeMemory([
        {"category": "work", "key": "project.pst_remediation", "value": "Active — sev-0 rollback"},
        {"category": "work", "key": "project.dmo_conf_2026", "value": "Panel co-owner"},
        {"category": "personal", "key": "role", "value": "VP"},
    ])
    ctx = build_triage_context(memory_store=mem, brain=FakeBrain(""))
    joined = " ".join(ctx.active_projects).lower()
    assert "pst" in joined
    assert "dmo" in joined


def test_build_triage_context_pulls_current_focus_from_brain():
    mem = FakeMemory([])
    brain = FakeBrain("## Focus\n- Ship CIO weekly brief Friday\n- Close PST rollback")
    ctx = build_triage_context(memory_store=mem, brain=brain)
    joined = " ".join(ctx.current_focus).lower()
    assert "cio weekly" in joined or "pst rollback" in joined


def test_build_triage_context_tolerates_empty_sources():
    ctx = build_triage_context(memory_store=FakeMemory([]), brain=FakeBrain(""))
    assert ctx.user_role  # falls back to default
    assert ctx.active_projects == []
    assert ctx.current_focus == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_triage.py -v -k context`
Expected: FAIL — `build_triage_context` not defined.

- [ ] **Step 3: Implement context builder**

Append to `orchestration/triage.py`:

```python
_DEFAULT_ROLE = "VP / Chief of Staff"


def _extract_focus_bullets(brain_text: str) -> list[str]:
    lines = [ln.strip() for ln in (brain_text or "").splitlines()]
    bullets: list[str] = []
    for ln in lines:
        if ln.startswith("- ") or ln.startswith("* "):
            bullets.append(ln[2:].strip())
    return bullets


def build_triage_context(
    memory_store,
    brain=None,
    key_people: list[str] | None = None,
) -> TriageContext:
    """Assemble the TriageContext from memory + session brain.

    Expects memory_store to have a list_facts(category=...) method that
    returns iterables of dicts with 'category', 'key', 'value'.
    """
    role = _DEFAULT_ROLE
    active_projects: list[str] = []
    try:
        for f in memory_store.list_facts(category="personal") or []:
            if (f.get("key") or "") == "role":
                role = f.get("value") or role
                break
    except Exception as exc:
        logger.debug("triage: failed to load role fact: %s", exc)

    try:
        for f in memory_store.list_facts(category="work") or []:
            key = f.get("key") or ""
            if key.startswith("project."):
                label = key[len("project."):].replace("_", " ")
                val = f.get("value") or ""
                active_projects.append(f"{label}: {val}" if val else label)
    except Exception as exc:
        logger.debug("triage: failed to load work facts: %s", exc)

    current_focus: list[str] = []
    if brain is not None:
        try:
            text = brain.get_current_focus() if hasattr(brain, "get_current_focus") else str(brain)
            current_focus = _extract_focus_bullets(text)
        except Exception as exc:
            logger.debug("triage: failed to pull brain focus: %s", exc)

    return TriageContext(
        user_role=role,
        active_projects=active_projects,
        current_focus=current_focus,
        key_people=list(key_people or []),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_triage.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestration/triage.py tests/test_triage.py
git commit -m "feat(triage): context builder from memory + session brain

Assembles user role, active projects (facts with key prefix 'project.'),
and current focus bullets (from session brain) into a TriageContext the
LLM triage pass can reference when scoring relevance."
```

---

## Task 8: LLM triage pass (Haiku)

**Files:**
- Modify: `orchestration/triage.py` (add `llm_triage`)
- Modify: `tests/test_triage.py` (add LLM triage tests with mocked Anthropic client)

- [ ] **Step 1: Write failing tests for LLM triage**

Append to `tests/test_triage.py`:

```python
@pytest.mark.asyncio
async def test_llm_triage_parses_haiku_json_response():
    from orchestration import triage as t

    items = [
        {"kind": "email", "subject": "PST rollback decision", "from_email": "shawn@chg.com"},
        {"kind": "email", "subject": "Lunch menu", "from_email": "cafe@chg.com"},
    ]
    ctx = TriageContext(
        user_role="VP/CoS",
        active_projects=["pst_remediation"],
        current_focus=["close PST rollback"],
        key_people=["shawn.farnworth"],
    )

    fake_response_text = json.dumps([
        {"index": 0, "relevance": 0.95, "category": "decision-needed",
         "why": "Blocks PST rollback close; aligns with current focus"},
        {"index": 1, "relevance": 0.1, "category": "fyi",
         "why": "Cafe menu, no action"},
    ])

    async def fake_create(**kwargs):
        mock = MagicMock()
        mock.content = [MagicMock(text=fake_response_text)]
        mock.usage = MagicMock(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        return mock

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch.object(t, "AsyncAnthropic", return_value=mock_client):
        results = await t.llm_triage(items, ctx)

    assert len(results) == 2
    assert results[0].relevance == 0.95
    assert results[0].category == "decision-needed"
    assert "PST" in results[0].why
    # Returned sorted by relevance desc
    assert results[0].relevance >= results[1].relevance


@pytest.mark.asyncio
async def test_llm_triage_empty_input_skips_llm_call():
    from orchestration import triage as t

    ctx = TriageContext(user_role="VP/CoS")
    with patch.object(t, "AsyncAnthropic") as mock_client_cls:
        results = await t.llm_triage([], ctx)
    assert results == []
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_llm_triage_falls_back_gracefully_on_bad_json():
    from orchestration import triage as t

    items = [{"kind": "email", "subject": "X"}]
    ctx = TriageContext(user_role="VP/CoS")

    async def fake_create(**kwargs):
        mock = MagicMock()
        mock.content = [MagicMock(text="not json at all")]
        mock.usage = MagicMock(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        return mock

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch.object(t, "AsyncAnthropic", return_value=mock_client):
        results = await t.llm_triage(items, ctx)

    # Expect: one item per input, default-scored at 0.5/fyi so nothing is silently dropped
    assert len(results) == 1
    assert results[0].category == "fyi"
    assert 0 <= results[0].relevance <= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_triage.py -v -k llm_triage`
Expected: FAIL — `llm_triage` not defined.

- [ ] **Step 3: Implement `llm_triage`**

Append to `orchestration/triage.py`:

```python
from anthropic import AsyncAnthropic
import config as app_config


_TRIAGE_SYSTEM = (
    "You are the triage pass for a Chief of Staff briefing system. You will "
    "receive a JSON array of inbound items (emails, Teams messages, delegation "
    "updates, calendar items) and a JSON context object describing the user's "
    "role, active projects, current focus, and key people.\n\n"
    "Your job: return a JSON array, one object per input (preserving index), "
    "each with: index (int), relevance (float 0.0-1.0), category (one of: "
    "'escalation','decision-needed','action-for-you','action-for-report','fyi'), "
    "why (one sentence citing which context signal drove the score).\n\n"
    "Scoring rubric:\n"
    "- 0.9-1.0: directly blocks or advances an active project / current focus item\n"
    "- 0.7-0.9: from a key person, or directly tied to a project without blocking it\n"
    "- 0.5-0.7: tangentially relevant; action-for-report or dependency visibility\n"
    "- 0.2-0.5: fyi\n"
    "- 0.0-0.2: noise; would not be missed if dropped\n\n"
    "Return ONLY the JSON array — no prose, no markdown fences."
)


def _default_triaged(items: Sequence[dict[str, Any]]) -> list[TriagedItem]:
    """Safe default when the LLM fails: everything is fyi at 0.5."""
    return [
        TriagedItem(item=dict(it), relevance=0.5, category="fyi",
                    why="triage unavailable; defaulted")
        for it in items
    ]


async def llm_triage(
    items: Sequence[dict[str, Any]],
    context: TriageContext,
    model: str = "",
    memory_store=None,
) -> list[TriagedItem]:
    """Score each item 0.0-1.0 using Haiku. Sorted by relevance desc."""
    if not items:
        return []

    from dataclasses import asdict
    payload = {
        "context": asdict(context),
        "items": [
            {"index": i, **{k: v for k, v in item.items() if k != "raw"}}
            for i, item in enumerate(items)
        ],
    }
    user_content = json.dumps(payload, default=str)

    triage_model = model or getattr(app_config, "TRIAGE_MODEL", "claude-haiku-4-5-20251001")

    try:
        client = AsyncAnthropic(api_key=app_config.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=triage_model,
            max_tokens=2048,
            system=_TRIAGE_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        if memory_store is not None:
            try:
                usage = response.usage
                memory_store.log_api_call(
                    model_id=triage_model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                    agent_name=None,
                    caller="triage",
                )
            except Exception:
                pass
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        scored_rows = json.loads(raw)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("llm_triage failed, using defaults: %s", exc)
        return _default_triaged(items)

    by_index = {int(row.get("index", -1)): row for row in scored_rows}
    out: list[TriagedItem] = []
    for i, item in enumerate(items):
        row = by_index.get(i) or {}
        out.append(TriagedItem(
            item=dict(item),
            relevance=float(row.get("relevance", 0.5)),
            category=str(row.get("category", "fyi")),
            why=str(row.get("why", "")),
        ))
    out.sort(key=lambda r: r.relevance, reverse=True)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_triage.py -v`
Expected: PASS (12 tests total)

- [ ] **Step 5: Commit**

```bash
git add orchestration/triage.py tests/test_triage.py
git commit -m "feat(triage): Haiku-backed LLM relevance scoring

llm_triage scores each item 0.0-1.0 with a category and one-sentence
reason, using TriageContext (user role, active projects, current focus,
key people) as scoring signal. Falls back to fyi/0.5 on JSON/API errors
rather than silently dropping items."
```

---

## Task 9: Identity graph enrichment for person mentions

**Files:**
- Create: `orchestration/person_enrichment.py`
- Create: `tests/test_person_enrichment.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_person_enrichment.py`:

```python
"""Tests for person enrichment using the identity graph."""

import pytest

from orchestration.person_enrichment import (
    EnrichedPerson,
    enrich_person_mention,
)


class FakeMemory:
    def __init__(self, facts):
        self._facts = facts

    def list_facts(self, category=None, limit=None):
        if category:
            return [f for f in self._facts if f["category"] == category]
        return self._facts


class FakeIdentity:
    def __init__(self, records):
        self._records = records

    def search(self, q: str):
        ql = q.lower()
        return [
            r for r in self._records
            if ql in (r.get("canonical_name") or "").lower()
            or ql in (r.get("display_name") or "").lower()
        ]


def test_enrich_person_returns_none_when_not_found():
    mem = FakeMemory([])
    idents = FakeIdentity([])
    assert enrich_person_mention("Unknown Person", mem, idents) is None


def test_enrich_person_consolidates_across_providers():
    idents = FakeIdentity([
        {"canonical_name": "shawn.farnworth", "provider": "m365_email",
         "display_name": "Shawn Farnworth", "email": "shawn@chg.com"},
        {"canonical_name": "shawn.farnworth", "provider": "m365_teams",
         "display_name": "Shawn F.", "email": ""},
        {"canonical_name": "shawn.farnworth", "provider": "imessage",
         "display_name": "Shawn", "email": ""},
    ])
    mem = FakeMemory([])
    enriched = enrich_person_mention("Shawn Farnworth", mem, idents)
    assert enriched is not None
    assert enriched.canonical_name == "shawn.farnworth"
    assert set(enriched.providers) == {"m365_email", "m365_teams", "imessage"}
    assert "shawn@chg.com" in enriched.emails


def test_enrich_person_pulls_role_fact():
    idents = FakeIdentity([
        {"canonical_name": "shawn.farnworth", "provider": "m365_email",
         "display_name": "Shawn Farnworth", "email": "shawn@chg.com"},
    ])
    mem = FakeMemory([
        {"category": "relationship", "key": "person.shawn.farnworth.role",
         "value": "Director of Identity Engineering"},
        {"category": "relationship", "key": "person.shawn.farnworth.manager",
         "value": "Jason Richards"},
    ])
    enriched = enrich_person_mention("Shawn Farnworth", mem, idents)
    assert enriched.role == "Director of Identity Engineering"
    assert enriched.manager == "Jason Richards"


def test_enrich_person_inline_rendering():
    enriched = EnrichedPerson(
        canonical_name="shawn.farnworth",
        display_names=["Shawn Farnworth"],
        emails=["shawn@chg.com"],
        providers=["m365_email"],
        role="Director of Identity Engineering",
    )
    rendered = enriched.inline()
    assert "Shawn Farnworth" in rendered
    assert "Director of Identity Engineering" in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_person_enrichment.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the enrichment module**

Create `orchestration/person_enrichment.py`:

```python
"""Identity-graph enrichment for person mentions in briefs.

Turns raw name strings ('Shawn Farnworth') into contextual labels
('Shawn Farnworth — Director of Identity Engineering') using the
identities table + relationship facts in memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EnrichedPerson:
    canonical_name: str
    display_names: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    role: Optional[str] = None
    team: Optional[str] = None
    manager: Optional[str] = None

    def inline(self) -> str:
        """Produce a short 'Name — Role' string suitable for briefs."""
        name = self.display_names[0] if self.display_names else self.canonical_name
        if self.role:
            return f"{name} — {self.role}"
        if self.team:
            return f"{name} ({self.team})"
        return name


def _facts_for(memory_store, canonical_name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for f in memory_store.list_facts(category="relationship") or []:
            key = f.get("key") or ""
            prefix = f"person.{canonical_name}."
            if key.startswith(prefix):
                out[key[len(prefix):]] = f.get("value") or ""
    except Exception:
        pass
    return out


def enrich_person_mention(
    name: str,
    memory_store,
    identity_store,
) -> Optional[EnrichedPerson]:
    """Look up an identity record by name and fold in relationship facts."""
    if not name:
        return None
    matches = identity_store.search(name) if identity_store else []
    if not matches:
        return None

    canonical = matches[0].get("canonical_name", name)
    display_names: list[str] = []
    emails: list[str] = []
    providers: list[str] = []
    for r in matches:
        if r.get("canonical_name") != canonical:
            continue
        dn = r.get("display_name") or ""
        if dn and dn not in display_names:
            display_names.append(dn)
        em = r.get("email") or ""
        if em and em not in emails:
            emails.append(em)
        pr = r.get("provider") or ""
        if pr and pr not in providers:
            providers.append(pr)

    facts = _facts_for(memory_store, canonical)
    return EnrichedPerson(
        canonical_name=canonical,
        display_names=display_names,
        emails=emails,
        providers=providers,
        role=facts.get("role"),
        team=facts.get("team"),
        manager=facts.get("manager"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_person_enrichment.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestration/person_enrichment.py tests/test_person_enrichment.py
git commit -m "feat(orchestration): identity-graph person enrichment

Resolves name mentions to Identity records (consolidating across
providers), folds in role/team/manager from relationship facts, and
exposes an inline() rendering for brief bodies. Previously the identity
table was defined but never consulted at brief time."
```

---

## Task 10: Wire threading → triage → enrichment into the briefing agents

**Files:**
- Modify: `.claude/agents/daily-briefing.md`
- Modify: `.claude/agents/weekly-cio-briefing.md`

**Note:** These are instruction files for the Claude Code subagent, not Python. There is no failing-test step; the change is reviewed by running the subagent and inspecting output. We still commit atomically.

- [ ] **Step 1: Read the current daily-briefing.md**

Run: `cat .claude/agents/daily-briefing.md`
Identify the section that describes data gathering and synthesis. Our new instructions slot between those.

- [ ] **Step 2: Update `.claude/agents/daily-briefing.md`**

Replace the "Synthesis" / equivalent section (or add a new "Triage & enrichment" section immediately before synthesis) with:

```markdown
## Triage & enrichment (REQUIRED before synthesis)

After all parallel data-gathering tools return, before you write the brief:

1. **Reconstruct conversations** — call `orchestration.thread_reconstruction.reconstruct_email_threads(emails)` and `reconstruct_teams_threads(teams_messages)`. Work with `EmailThread` / `TeamsThread` objects from this point on, never raw messages.

2. **Build triage context** — call `orchestration.triage.build_triage_context(memory_store=store, brain=session_brain)` to assemble user role, active projects, and current focus.

3. **Apply heuristic filter then LLM triage** —
   - `items = heuristic_filter(threads_as_items, FilterConfig(user_email="jason.richards@chghealthcare.com", key_people_emails=KEY_EMAILS))`
   - `scored = await llm_triage(items, context)`
   - Discard anything with `relevance < 0.5` whose category is not `escalation` or `decision-needed`.

4. **Enrich person mentions** — for each distinct name that appears in the remaining items, call `orchestration.person_enrichment.enrich_person_mention(name, memory_store, identity_store)`. Keep the first-mention rendering; drop the enrichment on repeat mentions.

5. **Hand off to synthesis** — pass the scored, enriched items to `orchestration.synthesis.synthesize_results(task="daily brief", dispatches=[...])`. The synthesis prompt now enforces ranking/dedup/priority.

**Do NOT** produce a daily brief from raw search results. If any of the above steps fails, degrade gracefully (log + continue) but surface the degradation in a footer note ("triage unavailable — brief is a raw dump").
```

- [ ] **Step 3: Update `.claude/agents/weekly-cio-briefing.md`**

Apply the same triage/enrichment block before the weekly-brief synthesis step. Additionally, add to the weekly brief's "People & Org Context" instruction:

```markdown
For every person mentioned in any section, use `enrich_person_mention` and
render them as `Name — Role` on first mention. This is what separates a
CIO-quality brief ("Shawn Farnworth — Director of Identity Engineering is
blocked on …") from a task list ("Shawn is blocked on …").
```

- [ ] **Step 4: Verify agent files parse**

Run: `pytest tests/ -k "agent_configs or briefing" -v` (whatever test the project uses for agent manifest validation)
Expected: PASS — the files are still valid markdown with frontmatter.

- [ ] **Step 5: Smoke test the daily brief end-to-end**

Run: spawn the `daily-briefing` subagent (via Claude Code `/agent daily-briefing` or equivalent) on a real workday morning. Verify:
- The brief does not dump 30 emails verbatim.
- At least one email or Teams thread is referenced as a thread, not a single message.
- First mention of a known person includes their role.
- The "Top 3 focus" items match what you'd actually prioritize.

If output is poor, tune the triage or synthesis prompt (small iteration — do NOT rewrite the pipeline).

- [ ] **Step 6: Commit**

```bash
git add .claude/agents/daily-briefing.md .claude/agents/weekly-cio-briefing.md
git commit -m "feat(agents): wire threading + triage + enrichment into briefs

Both the daily and weekly CIO briefing subagents now: (1) reconstruct
email/Teams threads before reasoning, (2) apply heuristic filter + Haiku
triage to rank inputs, (3) enrich person mentions using the identity
graph, and (4) hand structured scored items to the rewritten synthesis
prompt. Closes the loop so the downstream synthesis rules actually have
something worth ranking."
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Synthesis relevance — Task 1
- ✅ Task/delegation context — Tasks 2-3
- ✅ Email context reconstruction — Task 4
- ✅ Teams context reconstruction — Task 5
- ✅ Relevance scoring (hybrid heuristic + LLM) — Tasks 6-8
- ✅ Identity graph activation — Task 9
- ✅ Integration into briefing agents — Task 10

**Out-of-scope items** (by design — separate future plans):
- Teams outbound Graph reliability (needs reproduction first)
- Learned-from-edits ranking (YAGNI for a single user)
- Proactive autonomous action from brief output

**Execution expectations:**
- All 10 tasks follow TDD: failing test → minimal impl → passing test → commit.
- Each task produces a standalone, shippable change.
- Total estimated time: 10–12 hours of focused work.
- Backward compatibility preserved: the `source` string field stays; column migration is idempotent; agents degrade gracefully if new modules fail.
