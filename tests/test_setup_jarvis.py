"""Tests for setup_jarvis.py — step framework."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import shutil

import pytest
from setup_jarvis import (
    Status, SetupStep, StepRunner, VenvStep, PipStep, DataDirsStep,
    SystemDepsStep, EnvConfigStep,
)


class TestStatus:
    def test_status_values(self):
        assert Status.OK.value == "ok"
        assert Status.MISSING.value == "missing"
        assert Status.ERROR.value == "error"

    def test_status_label(self):
        assert Status.OK.label == "[ok]"
        assert Status.MISSING.label == "[--]"
        assert Status.ERROR.label == "[!!]"


class TestSetupStep:
    def test_abstract_methods_exist(self):
        with pytest.raises(TypeError):
            SetupStep(name="test", key="test", profiles={"minimal"})

    def test_applies_to_profile(self):
        class DummyStep(SetupStep):
            def check(self): return Status.OK
        step = DummyStep(name="test", key="test", profiles={"minimal", "personal"})
        assert step.applies_to("minimal")
        assert step.applies_to("personal")
        assert not step.applies_to("full")

    def test_is_auto_default_false(self):
        class DummyStep(SetupStep):
            def check(self): return Status.OK
        step = DummyStep(name="test", key="test", profiles={"minimal"})
        assert step.is_auto is False

    def test_is_manual_default_false(self):
        class DummyStep(SetupStep):
            def check(self): return Status.OK
        step = DummyStep(name="test", key="test", profiles={"minimal"})
        assert step.is_manual is False


class TestStepRunner:
    def test_scan_filters_by_profile(self):
        class OkStep(SetupStep):
            def check(self): return Status.OK
        class MissingStep(SetupStep):
            def check(self): return Status.MISSING
        steps = [
            OkStep(name="A", key="a", profiles={"minimal", "full"}),
            MissingStep(name="B", key="b", profiles={"full"}),
        ]
        runner = StepRunner(steps=steps, profile="minimal", interactive=False)
        results = runner.scan()
        assert len(results) == 1
        assert results[0][0].key == "a"
        assert results[0][1] == Status.OK

    def test_scan_returns_all_for_full_profile(self):
        class OkStep(SetupStep):
            def check(self): return Status.OK
        steps = [
            OkStep(name="A", key="a", profiles={"minimal", "full"}),
            OkStep(name="B", key="b", profiles={"full"}),
        ]
        runner = StepRunner(steps=steps, profile="full", interactive=False)
        results = runner.scan()
        assert len(results) == 2


# ---------------------------------------------------------------------------
# VenvStep
# ---------------------------------------------------------------------------

class TestVenvStep:
    def test_check_missing_when_no_venv(self, tmp_path):
        step = VenvStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_check_ok_when_venv_exists(self, tmp_path):
        venv_python = tmp_path / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()
        step = VenvStep(project_dir=tmp_path)
        assert step.check() == Status.OK

    def test_is_auto(self, tmp_path):
        step = VenvStep(project_dir=tmp_path)
        assert step.is_auto is True

    def test_profiles(self, tmp_path):
        step = VenvStep(project_dir=tmp_path)
        assert step.applies_to("minimal")
        assert step.applies_to("personal")
        assert step.applies_to("full")

    def test_guide_returns_command(self, tmp_path):
        step = VenvStep(project_dir=tmp_path)
        assert "python -m venv" in step.guide()
        assert ".venv" in step.guide()


# ---------------------------------------------------------------------------
# PipStep
# ---------------------------------------------------------------------------

class TestPipStep:
    def test_check_missing_when_no_venv(self, tmp_path):
        step = PipStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_is_auto(self, tmp_path):
        step = PipStep(project_dir=tmp_path)
        assert step.is_auto is True

    def test_profiles(self, tmp_path):
        step = PipStep(project_dir=tmp_path)
        assert step.applies_to("minimal")
        assert step.applies_to("personal")
        assert step.applies_to("full")

    def test_guide_returns_command(self, tmp_path):
        step = PipStep(project_dir=tmp_path)
        assert "pip" in step.guide()
        assert "install" in step.guide()
        assert ".[dev]" in step.guide()


# ---------------------------------------------------------------------------
# DataDirsStep
# ---------------------------------------------------------------------------

class TestDataDirsStep:
    def test_check_missing_when_no_dirs(self, tmp_path):
        step = DataDirsStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_check_ok_when_all_dirs_exist(self, tmp_path):
        for subdir in ["chroma", "okr", "webhook-inbox", "playwright/profile"]:
            (tmp_path / "data" / subdir).mkdir(parents=True, exist_ok=True)
        step = DataDirsStep(project_dir=tmp_path)
        assert step.check() == Status.OK

    def test_install_creates_dirs(self, tmp_path):
        step = DataDirsStep(project_dir=tmp_path)
        assert step.install() is True
        assert (tmp_path / "data" / "chroma").is_dir()
        assert (tmp_path / "data" / "okr").is_dir()
        assert (tmp_path / "data" / "webhook-inbox").is_dir()
        assert (tmp_path / "data" / "playwright" / "profile").is_dir()

    def test_is_auto(self, tmp_path):
        step = DataDirsStep(project_dir=tmp_path)
        assert step.is_auto is True

    def test_profiles(self, tmp_path):
        step = DataDirsStep(project_dir=tmp_path)
        assert step.applies_to("minimal")
        assert step.applies_to("personal")
        assert step.applies_to("full")

    def test_check_missing_when_partial_dirs(self, tmp_path):
        (tmp_path / "data" / "chroma").mkdir(parents=True)
        step = DataDirsStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_install_idempotent(self, tmp_path):
        step = DataDirsStep(project_dir=tmp_path)
        assert step.install() is True
        assert step.install() is True
        assert step.check() == Status.OK


# ---------------------------------------------------------------------------
# SystemDepsStep
# ---------------------------------------------------------------------------


class TestSystemDepsStep:
    def test_check_ok_when_deps_found(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
        step = SystemDepsStep()
        assert step.check() == Status.OK

    def test_check_missing_when_jq_absent(self, monkeypatch):
        monkeypatch.setattr(
            shutil, "which",
            lambda cmd: None if cmd == "jq" else f"/usr/bin/{cmd}",
        )
        step = SystemDepsStep()
        assert step.check() == Status.MISSING

    def test_is_auto_false(self):
        step = SystemDepsStep()
        assert step.is_auto is False

    def test_guide_includes_brew(self):
        step = SystemDepsStep()
        assert "brew install" in step.guide()

    def test_profiles(self):
        step = SystemDepsStep()
        assert step.applies_to("minimal")
        assert step.applies_to("personal")
        assert step.applies_to("full")

    def test_guide_lists_missing_deps(self, monkeypatch):
        monkeypatch.setattr(
            shutil, "which",
            lambda cmd: None if cmd == "jq" else f"/usr/bin/{cmd}",
        )
        step = SystemDepsStep()
        guide = step.guide()
        assert "jq" in guide
        assert "brew install" in guide


# ---------------------------------------------------------------------------
# EnvConfigStep
# ---------------------------------------------------------------------------


class TestEnvConfigStep:
    def test_check_missing_when_no_env(self, tmp_path):
        step = EnvConfigStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_check_missing_when_key_empty(self, tmp_path):
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=\n")
        step = EnvConfigStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_check_ok_when_key_set(self, tmp_path):
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-test123\n")
        step = EnvConfigStep(project_dir=tmp_path)
        assert step.check() == Status.OK

    def test_check_ignores_commented_lines(self, tmp_path):
        (tmp_path / ".env").write_text("# ANTHROPIC_API_KEY=sk-ant-test123\n")
        step = EnvConfigStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_install_copies_template(self, tmp_path):
        (tmp_path / ".env.example").write_text(
            "ANTHROPIC_API_KEY=\nSCHEDULER_ENABLED=true\n"
        )
        step = EnvConfigStep(project_dir=tmp_path, interactive=False)
        step.install()
        assert (tmp_path / ".env").exists()
        content = (tmp_path / ".env").read_text()
        assert "ANTHROPIC_API_KEY=" in content

    def test_is_auto_true(self):
        step = EnvConfigStep()
        assert step.is_auto is True

    def test_profiles(self):
        step = EnvConfigStep()
        assert step.applies_to("minimal")
        assert step.applies_to("personal")
        assert step.applies_to("full")

    def test_guide_returns_cp_command(self):
        step = EnvConfigStep()
        guide = step.guide()
        assert "cp .env.example .env" in guide
        assert "edit .env" in guide

    def test_install_does_not_overwrite_existing(self, tmp_path):
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-existing\n")
        (tmp_path / ".env.example").write_text("ANTHROPIC_API_KEY=\n")
        step = EnvConfigStep(project_dir=tmp_path, interactive=False)
        step.install()
        content = (tmp_path / ".env").read_text()
        assert "sk-existing" in content

    def test_parse_env_skips_blank_lines(self, tmp_path):
        (tmp_path / ".env").write_text("\n\nANTHROPIC_API_KEY=test\n\n")
        env = EnvConfigStep._parse_env(tmp_path / ".env")
        assert env == {"ANTHROPIC_API_KEY": "test"}

    def test_parse_env_returns_empty_for_missing_file(self, tmp_path):
        env = EnvConfigStep._parse_env(tmp_path / ".env")
        assert env == {}


# ---------------------------------------------------------------------------
# setup.sh (bash bootstrapper)
# ---------------------------------------------------------------------------

from pathlib import Path


class TestSetupSh:
    def test_setup_sh_exists(self):
        setup_sh = Path(__file__).parent.parent / "setup.sh"
        assert setup_sh.exists(), "setup.sh must exist at project root"

    def test_setup_sh_is_executable(self):
        setup_sh = Path(__file__).parent.parent / "setup.sh"
        assert os.access(setup_sh, os.X_OK), "setup.sh must be executable"

    def test_setup_sh_has_shebang(self):
        setup_sh = Path(__file__).parent.parent / "setup.sh"
        first_line = setup_sh.read_text().splitlines()[0]
        assert first_line.startswith("#!/"), "setup.sh must have a shebang line"

    def test_setup_sh_shebang_is_env_bash(self):
        setup_sh = Path(__file__).parent.parent / "setup.sh"
        first_line = setup_sh.read_text().splitlines()[0]
        assert first_line == "#!/usr/bin/env bash", "shebang must use /usr/bin/env bash"

    def test_setup_sh_has_strict_mode(self):
        setup_sh = Path(__file__).parent.parent / "setup.sh"
        content = setup_sh.read_text()
        assert "set -euo pipefail" in content, "setup.sh must set strict mode"

    def test_setup_sh_references_setup_jarvis_py(self):
        setup_sh = Path(__file__).parent.parent / "setup.sh"
        content = setup_sh.read_text()
        assert "setup_jarvis.py" in content, "setup.sh must reference setup_jarvis.py"
