"""Session manager for tracking interactions and structured memory flush."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from memory.models import ContextEntry, Fact
from memory.store import MemoryStore


@dataclass
class Interaction:
    role: str
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


# Keyword patterns for extraction (case-insensitive)
_DECISION_PATTERNS = re.compile(
    r"\b(decided|decision|agreed|will do)\b", re.IGNORECASE
)
_ACTION_PATTERNS = re.compile(
    r"\b(TODO|action item|need to|should)\b", re.IGNORECASE
)
_FACT_PATTERNS = re.compile(
    r"\b(important|note that|remember)\b", re.IGNORECASE
)


class SessionManager:
    """Manages session lifecycle: tracking, extraction, flush, and restore."""

    def __init__(self, memory_store: MemoryStore, session_id: Optional[str] = None, session_brain=None):
        self.memory_store = memory_store
        self.session_id = session_id or str(uuid.uuid4())
        self._buffer: list[Interaction] = []
        self._created_at = datetime.now().isoformat()
        self._session_brain = session_brain

    def track_interaction(
        self,
        role: str,
        content: str,
        tool_name: Optional[str] = None,
        tool_args: Optional[dict] = None,
    ) -> None:
        """Record an interaction in the session buffer."""
        self._buffer.append(Interaction(
            role=role,
            content=content,
            tool_name=tool_name,
            tool_args=tool_args,
        ))

    def estimate_tokens(self) -> int:
        """Rough token estimate of the current session buffer (word_count * 1.3)."""
        total_words = 0
        for interaction in self._buffer:
            total_words += len(interaction.content.split())
            if interaction.tool_name:
                total_words += len(interaction.tool_name.split())
            if interaction.tool_args:
                total_words += len(str(interaction.tool_args).split())
        return int(total_words * 1.3)

    def extract_structured_data(self) -> dict:
        """Pull out structured items from session buffer using keyword matching.

        Returns dict with keys: decisions, action_items, key_facts, general.
        Priority: decisions > action_items > key_facts > general.
        """
        decisions = []
        action_items = []
        key_facts = []
        general = []

        for interaction in self._buffer:
            content = interaction.content
            if not content or not content.strip():
                continue

            # Classify each interaction by priority (highest match wins)
            if _DECISION_PATTERNS.search(content):
                decisions.append(content.strip())
            elif _ACTION_PATTERNS.search(content):
                action_items.append(content.strip())
            elif _FACT_PATTERNS.search(content):
                key_facts.append(content.strip())
            else:
                general.append(content.strip())

        return {
            "decisions": decisions,
            "action_items": action_items,
            "key_facts": key_facts,
            "general": general,
        }

    def flush(self, priority_threshold: str = "all") -> dict:
        """Persist extracted data to memory store.

        Args:
            priority_threshold: "all", "decisions", "action_items", or "key_facts".
                Controls which categories are flushed. "all" flushes everything.

        Returns:
            Dict with counts: decisions_stored, actions_stored, facts_stored, summary_length.
        """
        extracted = self.extract_structured_data()
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")

        decisions_stored = 0
        actions_stored = 0
        facts_stored = 0

        # Always flush decisions (highest priority)
        for i, content in enumerate(extracted["decisions"]):
            fact = Fact(
                category="work",
                key=f"session_decision_{timestamp}_{i}",
                value=content,
                confidence=0.9,
                source="session_flush",
            )
            self.memory_store.store_fact(fact)
            decisions_stored += 1

        # Flush action items if threshold allows
        if priority_threshold in ("all", "action_items", "key_facts"):
            for i, content in enumerate(extracted["action_items"]):
                fact = Fact(
                    category="work",
                    key=f"session_action_{timestamp}_{i}",
                    value=content,
                    confidence=0.85,
                    source="session_flush",
                )
                self.memory_store.store_fact(fact)
                actions_stored += 1

        # Flush key facts if threshold allows
        if priority_threshold in ("all", "key_facts"):
            for i, content in enumerate(extracted["key_facts"]):
                fact = Fact(
                    category="work",
                    key=f"session_fact_{timestamp}_{i}",
                    value=content,
                    confidence=0.8,
                    source="session_flush",
                )
                self.memory_store.store_fact(fact)
                facts_stored += 1

        # Store session summary as a context checkpoint
        summary = self.get_session_summary()
        entry = ContextEntry(
            topic="session_checkpoint",
            summary=f"[Session Flush] {summary}",
            session_id=self.session_id,
            agent="jarvis",
        )
        self.memory_store.store_context(entry)

        # Update session brain if available
        if self._session_brain is not None:
            for content in extracted["decisions"]:
                self._session_brain.add_decision(content[:200])
            for content in extracted["action_items"]:
                self._session_brain.add_action_item(content[:200], source="session_flush")
            self._session_brain.save()

        return {
            "decisions_stored": decisions_stored,
            "actions_stored": actions_stored,
            "facts_stored": facts_stored,
            "summary_length": len(summary),
        }

    def get_session_summary(self) -> str:
        """Generate a concise summary of the session so far."""
        if not self._buffer:
            return "Empty session — no interactions recorded."

        extracted = self.extract_structured_data()
        parts = []

        total = len(self._buffer)
        parts.append(f"Session {self.session_id[:8]}: {total} interactions")

        tokens = self.estimate_tokens()
        parts.append(f"~{tokens} tokens")

        if extracted["decisions"]:
            parts.append(f"{len(extracted['decisions'])} decision(s)")
        if extracted["action_items"]:
            parts.append(f"{len(extracted['action_items'])} action item(s)")
        if extracted["key_facts"]:
            parts.append(f"{len(extracted['key_facts'])} key fact(s)")

        summary = ", ".join(parts) + "."

        # Add first decision/action as detail
        if extracted["decisions"]:
            first = extracted["decisions"][0]
            if len(first) > 100:
                first = first[:100] + "..."
            summary += f" Key decision: {first}"
        elif extracted["action_items"]:
            first = extracted["action_items"][0]
            if len(first) > 100:
                first = first[:100] + "..."
            summary += f" Key action: {first}"

        return summary

    def restore_from_checkpoint(self, session_id: str) -> dict:
        """Load previous session context from memory.

        Returns dict with context_entries and related_facts.
        """
        entries = self.memory_store.list_context(session_id=session_id, limit=10)
        # Search for facts created by session flush (keyed with session_ prefix)
        decision_facts = self.memory_store.search_facts("session_decision")
        action_facts = self.memory_store.search_facts("session_action")
        fact_facts = self.memory_store.search_facts("session_fact")
        all_facts = decision_facts + action_facts + fact_facts
        # Deduplicate by id
        seen_ids = set()
        unique_facts = []
        for f in all_facts:
            if f.id not in seen_ids:
                seen_ids.add(f.id)
                unique_facts.append(f)

        return {
            "session_id": session_id,
            "context_entries": [
                {
                    "id": e.id,
                    "topic": e.topic,
                    "summary": e.summary,
                    "created_at": e.created_at,
                }
                for e in entries
            ],
            "related_facts": [
                {
                    "category": f.category,
                    "key": f.key,
                    "value": f.value,
                    "confidence": f.confidence,
                }
                for f in unique_facts
            ],
        }

    @property
    def interaction_count(self) -> int:
        return len(self._buffer)

    @property
    def created_at(self) -> str:
        return self._created_at
