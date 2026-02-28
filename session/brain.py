"""Session Brain -- persistent markdown file that carries context across sessions.

Maintains structured data about workstreams, action items, decisions, people,
and handoff notes in a human-readable markdown format that survives session
boundaries.
"""

import fcntl
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional


class SessionBrain:
    """Persistent cross-session context stored as a markdown file.

    The brain file uses a simple markdown format with ## section headers
    and - prefixed list items. It can be read by humans and parsed back
    into structured data.
    """

    # Section header names (order matters for rendering)
    _SECTIONS = [
        "Active Workstreams",
        "Open Action Items",
        "Recent Decisions",
        "Key People Context",
        "Session Handoff Notes",
    ]

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock_path = self.path.parent / ".brain.lock"
        self.workstreams: list[dict] = []
        self.action_items: list[dict] = []
        self.decisions: list[dict] = []
        self.people: list[dict] = []
        self.handoff_notes: list[str] = []

    def load(self) -> None:
        """Parse existing markdown file into structured data.

        If the file does not exist, all fields remain empty.
        """
        if not self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lf = open(self._lock_path, "w")
        try:
            fcntl.flock(lf, fcntl.LOCK_SH)
            text = self.path.read_text(encoding="utf-8")
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
            lf.close()
        self._parse(text)

    def save(self) -> None:
        """Render and write the brain to the markdown file atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = self.render()
        lf = open(self._lock_path, "w")
        try:
            fcntl.flock(lf, fcntl.LOCK_EX)
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.tmp', dir=str(self.path.parent),
                delete=False, encoding="utf-8"
            ) as f:
                f.write(content)
                tmp = f.name
            os.replace(tmp, str(self.path))
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
            lf.close()

    def render(self) -> str:
        """Generate markdown with all sections.

        Sections: Active Workstreams, Open Action Items, Recent Decisions,
        Key People Context, Session Handoff Notes.
        """
        parts: list[str] = []

        # Active Workstreams
        parts.append("## Active Workstreams")
        if self.workstreams:
            for ws in self.workstreams:
                parts.append(f"- {ws['name']}: {ws['status']} - {ws['context']}")
        else:
            parts.append("- (none)")

        parts.append("")

        # Open Action Items
        parts.append("## Open Action Items")
        if self.action_items:
            for item in self.action_items:
                check = "x" if item["done"] else " "
                line = f"- [{check}] {item['text']}"
                # Encode source and added date as trailing metadata
                meta_parts = []
                if item.get("source"):
                    meta_parts.append(f"source={item['source']}")
                if item.get("added"):
                    meta_parts.append(f"added={item['added']}")
                if meta_parts:
                    line += f" <!-- {'|'.join(meta_parts)} -->"
                parts.append(line)
        else:
            parts.append("- (none)")

        parts.append("")

        # Recent Decisions
        parts.append("## Recent Decisions")
        if self.decisions:
            for dec in self.decisions:
                parts.append(f"- {dec['date']}: {dec['summary']}")
        else:
            parts.append("- (none)")

        parts.append("")

        # Key People Context
        parts.append("## Key People Context")
        if self.people:
            for person in self.people:
                parts.append(f"- {person['name']}: {person['context']}")
        else:
            parts.append("- (none)")

        parts.append("")

        # Session Handoff Notes
        parts.append("## Session Handoff Notes")
        if self.handoff_notes:
            for note in self.handoff_notes:
                parts.append(f"- {note}")
        else:
            parts.append("- (none)")

        parts.append("")  # trailing newline
        return "\n".join(parts)

    # -- Mutation methods --

    def add_workstream(self, name: str, status: str, context: str) -> None:
        """Upsert a workstream by name."""
        for ws in self.workstreams:
            if ws["name"] == name:
                ws["status"] = status
                ws["context"] = context
                return
        self.workstreams.append({
            "name": name,
            "status": status,
            "context": context,
        })

    def update_workstream(
        self,
        name: str,
        *,
        status: Optional[str] = None,
        context: Optional[str] = None,
    ) -> None:
        """Update an existing workstream or add it if it doesn't exist.

        Only provided keyword arguments are updated; None values leave the
        existing field unchanged.
        """
        for ws in self.workstreams:
            if ws["name"] == name:
                if status is not None:
                    ws["status"] = status
                if context is not None:
                    ws["context"] = context
                return
        # Not found -- delegate to add_workstream with defaults
        self.add_workstream(
            name,
            status=status or "",
            context=context or "",
        )

    def add_action_item(self, text: str, source: str = "") -> None:
        """Append a new action item with done=False and today's date."""
        self.action_items.append({
            "text": text,
            "done": False,
            "source": source,
            "added": date.today().isoformat(),
        })

    def complete_action_item(self, text: str) -> None:
        """Mark the first action item matching `text` as done.

        If no match is found, this is a no-op.
        """
        for item in self.action_items:
            if item["text"] == text:
                item["done"] = True
                return

    def add_decision(self, summary: str) -> None:
        """Append a decision with today's date."""
        self.decisions.append({
            "date": date.today().isoformat(),
            "summary": summary,
        })

    def add_person(self, name: str, context: str) -> None:
        """Upsert a person by name."""
        for person in self.people:
            if person["name"] == name:
                person["context"] = context
                return
        self.people.append({
            "name": name,
            "context": context,
        })

    def add_handoff_note(self, note: str) -> None:
        """Append a handoff note if it's not already present."""
        if note not in self.handoff_notes:
            self.handoff_notes.append(note)

    def to_dict(self) -> dict:
        """Return all data as a dict."""
        return {
            "workstreams": list(self.workstreams),
            "action_items": list(self.action_items),
            "decisions": list(self.decisions),
            "people": list(self.people),
            "handoff_notes": list(self.handoff_notes),
        }

    # -- Parsing --

    # Regex patterns for parsing items
    _RE_WORKSTREAM = re.compile(
        r"^-\s+(.+?):\s+(\S+)\s+-\s+(.+)$"
    )
    _RE_ACTION_ITEM = re.compile(
        r"^-\s+\[([ xX])\]\s+(.+?)(?:\s*<!--\s*(.*?)\s*-->)?$"
    )
    _RE_DECISION = re.compile(
        r"^-\s+(\d{4}-\d{2}-\d{2}):\s+(.+)$"
    )
    _RE_PERSON = re.compile(
        r"^-\s+(.+?):\s+(.+)$"
    )
    _RE_HANDOFF = re.compile(
        r"^-\s+(.+)$"
    )

    def _parse(self, text: str) -> None:
        """Parse markdown back into structured data.

        Uses ## section headers to identify sections, then parses
        - prefixed lines under each section.
        """
        self.workstreams = []
        self.action_items = []
        self.decisions = []
        self.people = []
        self.handoff_notes = []

        current_section: Optional[str] = None
        for line in text.splitlines():
            stripped = line.strip()

            # Detect section headers
            if stripped.startswith("## "):
                header = stripped[3:].strip()
                if header in self._SECTIONS:
                    current_section = header
                else:
                    current_section = None
                continue

            # Skip empty lines and (none) placeholders
            if not stripped or stripped == "- (none)":
                continue

            # Parse based on current section
            if current_section == "Active Workstreams":
                m = self._RE_WORKSTREAM.match(stripped)
                if m:
                    self.workstreams.append({
                        "name": m.group(1).strip(),
                        "status": m.group(2).strip(),
                        "context": m.group(3).strip(),
                    })

            elif current_section == "Open Action Items":
                m = self._RE_ACTION_ITEM.match(stripped)
                if m:
                    done = m.group(1).lower() == "x"
                    text_val = m.group(2).strip()
                    meta_str = m.group(3) or ""
                    # Parse metadata from HTML comment
                    source = ""
                    added = ""
                    for part in meta_str.split("|"):
                        part = part.strip()
                        if part.startswith("source="):
                            source = part[len("source="):]
                        elif part.startswith("added="):
                            added = part[len("added="):]
                    self.action_items.append({
                        "text": text_val,
                        "done": done,
                        "source": source,
                        "added": added,
                    })

            elif current_section == "Recent Decisions":
                m = self._RE_DECISION.match(stripped)
                if m:
                    self.decisions.append({
                        "date": m.group(1),
                        "summary": m.group(2).strip(),
                    })

            elif current_section == "Key People Context":
                m = self._RE_PERSON.match(stripped)
                if m:
                    self.people.append({
                        "name": m.group(1).strip(),
                        "context": m.group(2).strip(),
                    })

            elif current_section == "Session Handoff Notes":
                m = self._RE_HANDOFF.match(stripped)
                if m:
                    note = m.group(1).strip()
                    if note and note != "(none)":
                        self.handoff_notes.append(note)
