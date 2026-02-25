"""Tests for session.brain -- Session Brain persistent markdown context."""

import re
from datetime import date
from pathlib import Path

import pytest

from session.brain import SessionBrain


class TestSessionBrainInit:
    """SessionBrain construction and loading."""

    def test_creates_empty_brain_when_file_missing(self, tmp_path: Path):
        path = tmp_path / "brain.md"
        brain = SessionBrain(path)
        brain.load()

        assert brain.workstreams == []
        assert brain.action_items == []
        assert brain.decisions == []
        assert brain.people == []
        assert brain.handoff_notes == []

    def test_loads_existing_file(self, tmp_path: Path):
        path = tmp_path / "brain.md"
        path.write_text(
            "## Active Workstreams\n"
            "- Alpha: in_progress - building feature\n"
            "\n"
            "## Open Action Items\n"
            "- [ ] Write tests\n"
            "\n"
            "## Recent Decisions\n"
            "- 2026-02-24: Use SQLite for storage\n"
            "\n"
            "## Key People Context\n"
            "- Alice: PM on Alpha\n"
            "\n"
            "## Session Handoff Notes\n"
            "- Left off debugging issue #42\n"
        )
        brain = SessionBrain(path)
        brain.load()

        assert len(brain.workstreams) == 1
        assert brain.workstreams[0]["name"] == "Alpha"
        assert brain.workstreams[0]["status"] == "in_progress"
        assert brain.workstreams[0]["context"] == "building feature"

        assert len(brain.action_items) == 1
        assert brain.action_items[0]["text"] == "Write tests"
        assert brain.action_items[0]["done"] is False

        assert len(brain.decisions) == 1
        assert brain.decisions[0]["date"] == "2026-02-24"
        assert brain.decisions[0]["summary"] == "Use SQLite for storage"

        assert len(brain.people) == 1
        assert brain.people[0]["name"] == "Alice"
        assert brain.people[0]["context"] == "PM on Alpha"

        assert len(brain.handoff_notes) == 1
        assert brain.handoff_notes[0] == "Left off debugging issue #42"

    def test_skips_none_items(self, tmp_path: Path):
        path = tmp_path / "brain.md"
        path.write_text(
            "## Active Workstreams\n"
            "- (none)\n"
            "\n"
            "## Open Action Items\n"
            "- (none)\n"
        )
        brain = SessionBrain(path)
        brain.load()

        assert brain.workstreams == []
        assert brain.action_items == []


class TestWorkstreams:
    """Adding and updating workstreams."""

    def test_add_workstream(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_workstream("Alpha", "active", "building feature X")

        assert len(brain.workstreams) == 1
        assert brain.workstreams[0]["name"] == "Alpha"
        assert brain.workstreams[0]["status"] == "active"
        assert brain.workstreams[0]["context"] == "building feature X"

    def test_update_workstream_upserts(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_workstream("Alpha", "active", "initial")
        brain.update_workstream("Alpha", status="blocked", context="waiting on review")

        assert len(brain.workstreams) == 1
        assert brain.workstreams[0]["status"] == "blocked"
        assert brain.workstreams[0]["context"] == "waiting on review"

    def test_update_nonexistent_adds(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.update_workstream("Beta", status="active", context="new stream")

        assert len(brain.workstreams) == 1
        assert brain.workstreams[0]["name"] == "Beta"

    def test_update_partial_fields(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_workstream("Alpha", "active", "initial context")
        brain.update_workstream("Alpha", status="blocked")

        assert brain.workstreams[0]["status"] == "blocked"
        assert brain.workstreams[0]["context"] == "initial context"


class TestActionItems:
    """Adding and completing action items."""

    def test_add_action_item(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_action_item("Write tests", source="planning session")

        assert len(brain.action_items) == 1
        item = brain.action_items[0]
        assert item["text"] == "Write tests"
        assert item["done"] is False
        assert item["source"] == "planning session"
        assert item["added"] == date.today().isoformat()

    def test_add_action_item_default_source(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_action_item("Fix bug")

        assert brain.action_items[0]["source"] == ""

    def test_complete_action_item(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_action_item("Write tests")
        brain.complete_action_item("Write tests")

        assert brain.action_items[0]["done"] is True

    def test_complete_nonexistent_is_noop(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_action_item("Write tests")
        brain.complete_action_item("Nonexistent item")

        assert len(brain.action_items) == 1
        assert brain.action_items[0]["done"] is False


class TestDecisions:
    """Adding decisions."""

    def test_add_decision(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_decision("Use SQLite for storage")

        assert len(brain.decisions) == 1
        assert brain.decisions[0]["summary"] == "Use SQLite for storage"

    def test_decision_has_date(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_decision("Use SQLite for storage")

        assert brain.decisions[0]["date"] == date.today().isoformat()


class TestPeopleContext:
    """Adding and updating people context."""

    def test_add_person(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_person("Alice", "PM on Alpha project")

        assert len(brain.people) == 1
        assert brain.people[0]["name"] == "Alice"
        assert brain.people[0]["context"] == "PM on Alpha project"

    def test_update_deduplicates(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_person("Alice", "PM on Alpha project")
        brain.add_person("Alice", "Now leading Beta project")

        assert len(brain.people) == 1
        assert brain.people[0]["context"] == "Now leading Beta project"


class TestHandoffNotes:
    """Adding handoff notes."""

    def test_add_handoff_note(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_handoff_note("Left off debugging issue #42")

        assert len(brain.handoff_notes) == 1
        assert brain.handoff_notes[0] == "Left off debugging issue #42"

    def test_no_duplicates(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_handoff_note("Left off debugging issue #42")
        brain.add_handoff_note("Left off debugging issue #42")

        assert len(brain.handoff_notes) == 1


class TestRoundTrip:
    """Save then load preserves all data."""

    def test_round_trip(self, tmp_path: Path):
        path = tmp_path / "brain.md"
        brain = SessionBrain(path)

        brain.add_workstream("Alpha", "active", "building feature X")
        brain.add_workstream("Beta", "blocked", "waiting on review")
        brain.add_action_item("Write tests", source="planning")
        brain.add_action_item("Deploy to staging")
        brain.complete_action_item("Write tests")
        brain.add_decision("Use SQLite for storage")
        brain.add_decision("Ship by Friday")
        brain.add_person("Alice", "PM on Alpha")
        brain.add_person("Bob", "Tech lead")
        brain.add_handoff_note("Left off debugging issue #42")
        brain.add_handoff_note("Need to follow up on PR review")

        brain.save()

        # Load into a new instance
        brain2 = SessionBrain(path)
        brain2.load()

        assert len(brain2.workstreams) == 2
        assert brain2.workstreams[0]["name"] == "Alpha"
        assert brain2.workstreams[1]["name"] == "Beta"

        assert len(brain2.action_items) == 2
        assert brain2.action_items[0]["text"] == "Write tests"
        assert brain2.action_items[0]["done"] is True
        assert brain2.action_items[1]["text"] == "Deploy to staging"
        assert brain2.action_items[1]["done"] is False

        assert len(brain2.decisions) == 2
        assert brain2.decisions[0]["summary"] == "Use SQLite for storage"
        assert brain2.decisions[1]["summary"] == "Ship by Friday"

        assert len(brain2.people) == 2
        assert brain2.people[0]["name"] == "Alice"
        assert brain2.people[1]["name"] == "Bob"

        assert len(brain2.handoff_notes) == 2

    def test_round_trip_preserves_action_item_source(self, tmp_path: Path):
        path = tmp_path / "brain.md"
        brain = SessionBrain(path)
        brain.add_action_item("Write tests", source="planning session")
        brain.save()

        brain2 = SessionBrain(path)
        brain2.load()

        assert brain2.action_items[0]["source"] == "planning session"

    def test_round_trip_empty_brain(self, tmp_path: Path):
        path = tmp_path / "brain.md"
        brain = SessionBrain(path)
        brain.save()

        brain2 = SessionBrain(path)
        brain2.load()

        assert brain2.workstreams == []
        assert brain2.action_items == []
        assert brain2.decisions == []
        assert brain2.people == []
        assert brain2.handoff_notes == []


class TestRender:
    """Rendered output contains all sections and content."""

    def test_render_contains_all_sections(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        output = brain.render()

        assert "## Active Workstreams" in output
        assert "## Open Action Items" in output
        assert "## Recent Decisions" in output
        assert "## Key People Context" in output
        assert "## Session Handoff Notes" in output

    def test_render_contains_content(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_workstream("Alpha", "active", "building feature")
        brain.add_action_item("Write tests")
        brain.add_decision("Use SQLite")
        brain.add_person("Alice", "PM")
        brain.add_handoff_note("Left off debugging")

        output = brain.render()

        assert "Alpha" in output
        assert "active" in output
        assert "building feature" in output
        assert "Write tests" in output
        assert "[ ]" in output
        assert "Use SQLite" in output
        assert "Alice" in output
        assert "PM" in output
        assert "Left off debugging" in output

    def test_render_done_action_items(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_action_item("Done task")
        brain.complete_action_item("Done task")

        output = brain.render()
        assert "[x]" in output

    def test_render_empty_sections_show_none(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        output = brain.render()

        # Each empty section should have (none) placeholder
        assert output.count("(none)") == 5


class TestToDict:
    """to_dict returns all data."""

    def test_to_dict(self, tmp_path: Path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_workstream("Alpha", "active", "building")
        brain.add_action_item("Write tests")
        brain.add_decision("Use SQLite")
        brain.add_person("Alice", "PM")
        brain.add_handoff_note("Left off debugging")

        d = brain.to_dict()

        assert "workstreams" in d
        assert "action_items" in d
        assert "decisions" in d
        assert "people" in d
        assert "handoff_notes" in d
        assert len(d["workstreams"]) == 1
        assert len(d["action_items"]) == 1
        assert len(d["decisions"]) == 1
        assert len(d["people"]) == 1
        assert len(d["handoff_notes"]) == 1
