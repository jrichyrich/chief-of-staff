"""Tests for playbook YAML loader with input substitution and condition filtering."""

import pytest
from pathlib import Path

from playbooks.loader import Playbook, Workstream, PlaybookLoader


class TestPlaybookModel:
    """Test Playbook and Workstream dataclass basics."""

    def test_workstream_has_required_fields(self):
        ws = Workstream(name="research", prompt="Do research on $topic")
        assert ws.name == "research"
        assert ws.prompt == "Do research on $topic"
        assert ws.condition == ""

    def test_workstream_with_condition(self):
        ws = Workstream(
            name="security-review",
            prompt="Review security for $project",
            condition="type == security",
        )
        assert ws.condition == "type == security"

    def test_playbook_has_required_fields(self):
        ws = Workstream(name="stream1", prompt="Do $thing")
        pb = Playbook(
            name="test-playbook",
            description="A test playbook",
            inputs=["thing"],
            workstreams=[ws],
            synthesis_prompt="Synthesize the results",
        )
        assert pb.name == "test-playbook"
        assert pb.description == "A test playbook"
        assert pb.inputs == ["thing"]
        assert len(pb.workstreams) == 1
        assert pb.synthesis_prompt == "Synthesize the results"
        assert pb.delivery_default == "inline"
        assert pb.delivery_options == []

    def test_playbook_custom_delivery(self):
        pb = Playbook(
            name="pb",
            description="",
            inputs=[],
            workstreams=[],
            synthesis_prompt="",
            delivery_default="email",
            delivery_options=["email", "inline", "imessage"],
        )
        assert pb.delivery_default == "email"
        assert pb.delivery_options == ["email", "inline", "imessage"]

    def test_resolve_inputs_substitutes_variables(self):
        ws1 = Workstream(name="research", prompt="Research $topic in $domain")
        ws2 = Workstream(name="analyze", prompt="Analyze $topic trends")
        pb = Playbook(
            name="research-playbook",
            description="Research $topic",
            inputs=["topic", "domain"],
            workstreams=[ws1, ws2],
            synthesis_prompt="Combine findings about $topic in $domain",
        )
        resolved = pb.resolve_inputs({"topic": "AI safety", "domain": "healthcare"})

        # Original should be unchanged
        assert ws1.prompt == "Research $topic in $domain"
        assert pb.synthesis_prompt == "Combine findings about $topic in $domain"

        # Resolved should have substitutions
        assert resolved.workstreams[0].prompt == "Research AI safety in healthcare"
        assert resolved.workstreams[1].prompt == "Analyze AI safety trends"
        assert resolved.synthesis_prompt == "Combine findings about AI safety in healthcare"

    def test_resolve_inputs_safe_substitute_missing_keys(self):
        """Missing keys should be left as-is (safe_substitute behavior)."""
        ws = Workstream(name="ws", prompt="$known and $unknown")
        pb = Playbook(
            name="pb",
            description="",
            inputs=["known", "unknown"],
            workstreams=[ws],
            synthesis_prompt="$known only",
        )
        resolved = pb.resolve_inputs({"known": "hello"})
        assert resolved.workstreams[0].prompt == "hello and $unknown"
        assert resolved.synthesis_prompt == "hello only"

    def test_active_workstreams_no_conditions(self):
        ws1 = Workstream(name="a", prompt="do a")
        ws2 = Workstream(name="b", prompt="do b")
        pb = Playbook(
            name="pb",
            description="",
            inputs=[],
            workstreams=[ws1, ws2],
            synthesis_prompt="",
        )
        active = pb.active_workstreams(None)
        assert len(active) == 2
        assert active[0].name == "a"
        assert active[1].name == "b"

    def test_active_workstreams_with_conditions(self):
        ws1 = Workstream(name="always", prompt="always runs")
        ws2 = Workstream(
            name="only-security",
            prompt="security scan",
            condition="type == security",
        )
        ws3 = Workstream(
            name="only-perf",
            prompt="perf check",
            condition="type == performance",
        )
        pb = Playbook(
            name="pb",
            description="",
            inputs=[],
            workstreams=[ws1, ws2, ws3],
            synthesis_prompt="",
        )
        active = pb.active_workstreams({"type": "security"})
        names = [w.name for w in active]
        assert "always" in names
        assert "only-security" in names
        assert "only-perf" not in names

    def test_active_workstreams_none_context_only_unconditional(self):
        ws1 = Workstream(name="always", prompt="always runs")
        ws2 = Workstream(
            name="conditional",
            prompt="maybe",
            condition="mode == debug",
        )
        pb = Playbook(
            name="pb",
            description="",
            inputs=[],
            workstreams=[ws1, ws2],
            synthesis_prompt="",
        )
        active = pb.active_workstreams(None)
        assert len(active) == 1
        assert active[0].name == "always"


class TestPlaybookLoader:
    """Test PlaybookLoader YAML loading and parsing."""

    def _write_playbook(self, tmp_path: Path, filename: str, content: str) -> Path:
        path = tmp_path / filename
        path.write_text(content)
        return path

    def test_list_playbooks_empty_dir(self, tmp_path: Path):
        loader = PlaybookLoader(tmp_path)
        assert loader.list_playbooks() == []

    def test_list_playbooks_finds_yaml_and_yml(self, tmp_path: Path):
        self._write_playbook(
            tmp_path,
            "brief.yaml",
            "name: brief\nworkstreams:\n  - name: ws\n    prompt: do it\n",
        )
        self._write_playbook(
            tmp_path,
            "review.yml",
            "name: review\nworkstreams:\n  - name: ws\n    prompt: do it\n",
        )
        # Non-yaml file should be ignored
        self._write_playbook(tmp_path, "readme.txt", "not a playbook")

        loader = PlaybookLoader(tmp_path)
        names = sorted(loader.list_playbooks())
        assert names == ["brief", "review"]

    def test_get_playbook_existing(self, tmp_path: Path):
        self._write_playbook(
            tmp_path,
            "daily-brief.yaml",
            (
                "name: daily-brief\n"
                "description: Morning briefing\n"
                "inputs:\n"
                "  - date\n"
                "  - focus_area\n"
                "workstreams:\n"
                "  - name: calendar\n"
                "    prompt: Get events for $date\n"
                "  - name: email\n"
                "    prompt: Summarize emails for $date\n"
                "synthesis:\n"
                "  prompt: Combine calendar and email for $date\n"
                "delivery:\n"
                "  default: inline\n"
                "  options:\n"
                "    - inline\n"
                "    - email\n"
            ),
        )

        loader = PlaybookLoader(tmp_path)
        pb = loader.get_playbook("daily-brief")

        assert pb is not None
        assert pb.name == "daily-brief"
        assert pb.description == "Morning briefing"
        assert pb.inputs == ["date", "focus_area"]
        assert len(pb.workstreams) == 2
        assert pb.workstreams[0].name == "calendar"
        assert pb.workstreams[0].prompt == "Get events for $date"
        assert pb.workstreams[1].name == "email"
        assert pb.synthesis_prompt == "Combine calendar and email for $date"
        assert pb.delivery_default == "inline"
        assert pb.delivery_options == ["inline", "email"]

    def test_get_playbook_nonexistent_returns_none(self, tmp_path: Path):
        loader = PlaybookLoader(tmp_path)
        assert loader.get_playbook("does-not-exist") is None

    def test_get_playbook_bad_yaml_returns_none(self, tmp_path: Path):
        self._write_playbook(tmp_path, "broken.yaml", "{{{{invalid yaml: [")

        loader = PlaybookLoader(tmp_path)
        assert loader.get_playbook("broken") is None

    def test_get_playbook_missing_required_fields_returns_none(self, tmp_path: Path):
        # Missing workstreams
        self._write_playbook(
            tmp_path,
            "incomplete.yaml",
            "name: incomplete\ndescription: no workstreams\n",
        )
        loader = PlaybookLoader(tmp_path)
        assert loader.get_playbook("incomplete") is None

    def test_get_playbook_missing_name_returns_none(self, tmp_path: Path):
        self._write_playbook(
            tmp_path,
            "noname.yaml",
            "workstreams:\n  - name: ws\n    prompt: do it\n",
        )
        loader = PlaybookLoader(tmp_path)
        assert loader.get_playbook("noname") is None

    def test_get_playbook_with_conditions(self, tmp_path: Path):
        self._write_playbook(
            tmp_path,
            "conditional.yaml",
            (
                "name: conditional\n"
                "workstreams:\n"
                "  - name: always\n"
                "    prompt: always runs\n"
                "  - name: sometimes\n"
                "    prompt: conditional run\n"
                "    condition: mode == advanced\n"
                "synthesis:\n"
                "  prompt: combine\n"
            ),
        )

        loader = PlaybookLoader(tmp_path)
        pb = loader.get_playbook("conditional")
        assert pb is not None
        assert pb.workstreams[0].condition == ""
        assert pb.workstreams[1].condition == "mode == advanced"

    def test_get_playbook_minimal_yaml(self, tmp_path: Path):
        """Minimal valid playbook: just name and workstreams."""
        self._write_playbook(
            tmp_path,
            "minimal.yaml",
            "name: minimal\nworkstreams:\n  - name: ws\n    prompt: do it\n",
        )
        loader = PlaybookLoader(tmp_path)
        pb = loader.get_playbook("minimal")
        assert pb is not None
        assert pb.name == "minimal"
        assert pb.description == ""
        assert pb.inputs == []
        assert pb.synthesis_prompt == ""
        assert pb.delivery_default == "inline"
        assert pb.delivery_options == []

    def test_get_playbook_tries_yml_extension(self, tmp_path: Path):
        self._write_playbook(
            tmp_path,
            "alt.yml",
            "name: alt\nworkstreams:\n  - name: ws\n    prompt: do it\n",
        )
        loader = PlaybookLoader(tmp_path)
        pb = loader.get_playbook("alt")
        assert pb is not None
        assert pb.name == "alt"

    def test_substitute_inputs_end_to_end(self, tmp_path: Path):
        self._write_playbook(
            tmp_path,
            "research.yaml",
            (
                "name: research\n"
                "description: Research $topic\n"
                "inputs:\n"
                "  - topic\n"
                "workstreams:\n"
                "  - name: web\n"
                "    prompt: Search web for $topic\n"
                "  - name: papers\n"
                "    prompt: Find papers on $topic\n"
                "synthesis:\n"
                "  prompt: Combine research on $topic\n"
            ),
        )

        loader = PlaybookLoader(tmp_path)
        pb = loader.get_playbook("research")
        assert pb is not None

        resolved = pb.resolve_inputs({"topic": "quantum computing"})
        assert resolved.workstreams[0].prompt == "Search web for quantum computing"
        assert resolved.workstreams[1].prompt == "Find papers on quantum computing"
        assert resolved.synthesis_prompt == "Combine research on quantum computing"

    def test_condition_filtering_end_to_end(self, tmp_path: Path):
        self._write_playbook(
            tmp_path,
            "review.yaml",
            (
                "name: review\n"
                "workstreams:\n"
                "  - name: code\n"
                "    prompt: review code\n"
                "  - name: security\n"
                "    prompt: security scan\n"
                "    condition: scope == full\n"
                "  - name: perf\n"
                "    prompt: perf test\n"
                "    condition: scope == full\n"
                "synthesis:\n"
                "  prompt: combine\n"
            ),
        )

        loader = PlaybookLoader(tmp_path)
        pb = loader.get_playbook("review")
        assert pb is not None

        # With scope == full, all 3 workstreams active
        active = pb.active_workstreams({"scope": "full"})
        assert len(active) == 3

        # Without context, only unconditional workstreams
        active = pb.active_workstreams(None)
        assert len(active) == 1
        assert active[0].name == "code"

        # With scope != full, only unconditional
        active = pb.active_workstreams({"scope": "quick"})
        assert len(active) == 1
        assert active[0].name == "code"
