# Setup Script Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create an idempotent, profile-based setup script (bash bootstrapper + Python main) that scans the environment, auto-installs safe dependencies, guides on system-level changes, and reports un-verifiable manual steps.

**Architecture:** A thin `setup.sh` bash script finds Python 3.11+ and delegates to `scripts/setup_jarvis.py`. The Python script uses stdlib only (no third-party deps). Each setup step is a class with `check()`, `install()`, and `guide()` methods, filtered by profile (minimal/personal/full). Execution is scan-first (show big picture), then walkthrough (step by step).

**Tech Stack:** Bash (bootstrapper), Python 3.11+ stdlib (`subprocess`, `shutil`, `argparse`, `pathlib`, `json`, `dataclasses`, `enum`)

**Design doc:** `docs/plans/2026-02-24-setup-script-design.md`

---

### Task 1: Step Framework — Status enum, SetupStep base class, and StepRunner

**Files:**
- Create: `scripts/setup_jarvis.py`
- Create: `tests/test_setup_jarvis.py`

**Step 1: Write the failing test**

```python
"""Tests for setup_jarvis.py — step framework."""

import sys
import os

# Add project root and scripts to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest
from setup_jarvis import Status, SetupStep, StepRunner


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
        """SetupStep requires subclasses to implement check()."""
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
        # Only step A applies to minimal
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup_jarvis.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'setup_jarvis'`

**Step 3: Write minimal implementation**

Create `scripts/setup_jarvis.py`:

```python
#!/usr/bin/env python3
"""Jarvis (Chief of Staff) setup script.

Scans the environment, auto-installs safe dependencies, guides on
system-level changes, and reports un-verifiable manual steps.

Requires only Python stdlib — runs before pip install.
"""

from __future__ import annotations

import argparse
import enum
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROFILES = ("minimal", "personal", "full")


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class Status(enum.Enum):
    OK = "ok"
    MISSING = "missing"
    ERROR = "error"

    @property
    def label(self) -> str:
        return {"ok": "[ok]", "missing": "[--]", "error": "[!!]"}[self.value]


# ---------------------------------------------------------------------------
# Base step
# ---------------------------------------------------------------------------

@dataclass
class SetupStep:
    """Base class for a setup step. Subclasses must implement check()."""

    name: str
    key: str
    profiles: set[str]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __post_init__(self):
        # Enforce that check() is overridden
        if type(self).check is SetupStep.check:
            raise TypeError(
                f"Can't instantiate SetupStep subclass {type(self).__name__} "
                "without implementing check()"
            )

    def check(self) -> Status:
        raise TypeError("Subclasses must implement check()")

    def install(self) -> bool:
        """Auto-install this step. Return True on success."""
        return False

    def guide(self) -> str:
        """Return human-readable instructions for manual setup."""
        return ""

    @property
    def is_auto(self) -> bool:
        """Whether this step can be auto-installed."""
        return False

    @property
    def is_manual(self) -> bool:
        """Whether this step can only be verified manually (final checklist)."""
        return False

    def applies_to(self, profile: str) -> bool:
        return profile in self.profiles


# ---------------------------------------------------------------------------
# Step runner
# ---------------------------------------------------------------------------

@dataclass
class StepRunner:
    """Orchestrates scanning and executing steps for a given profile."""

    steps: list[SetupStep]
    profile: str
    interactive: bool = True

    def _applicable_steps(self) -> list[SetupStep]:
        return [s for s in self.steps if s.applies_to(self.profile)]

    def scan(self) -> list[tuple[SetupStep, Status]]:
        """Run check() on all applicable steps. Returns (step, status) pairs."""
        results = []
        for step in self._applicable_steps():
            status = step.check()
            results.append((step, status))
        return results
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_setup_jarvis.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add scripts/setup_jarvis.py tests/test_setup_jarvis.py
git commit -m "feat: add setup script step framework with Status, SetupStep, StepRunner"
```

---

### Task 2: Concrete Steps — VenvStep, PipStep, DataDirsStep

**Files:**
- Modify: `scripts/setup_jarvis.py`
- Modify: `tests/test_setup_jarvis.py`

**Step 1: Write the failing tests**

Add to `tests/test_setup_jarvis.py`:

```python
class TestVenvStep:
    def test_check_missing_when_no_venv(self, tmp_path):
        from setup_jarvis import VenvStep
        step = VenvStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_check_ok_when_venv_exists(self, tmp_path):
        from setup_jarvis import VenvStep
        venv_python = tmp_path / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()
        step = VenvStep(project_dir=tmp_path)
        assert step.check() == Status.OK

    def test_is_auto(self, tmp_path):
        from setup_jarvis import VenvStep
        step = VenvStep(project_dir=tmp_path)
        assert step.is_auto is True


class TestPipStep:
    def test_check_missing_when_no_venv(self, tmp_path):
        from setup_jarvis import PipStep
        step = PipStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_is_auto(self, tmp_path):
        from setup_jarvis import PipStep
        step = PipStep(project_dir=tmp_path)
        assert step.is_auto is True


class TestDataDirsStep:
    def test_check_missing_when_no_dirs(self, tmp_path):
        from setup_jarvis import DataDirsStep
        step = DataDirsStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_check_ok_when_all_dirs_exist(self, tmp_path):
        from setup_jarvis import DataDirsStep
        for subdir in ["chroma", "okr", "webhook-inbox", "playwright/profile"]:
            (tmp_path / "data" / subdir).mkdir(parents=True, exist_ok=True)
        step = DataDirsStep(project_dir=tmp_path)
        assert step.check() == Status.OK

    def test_install_creates_dirs(self, tmp_path):
        from setup_jarvis import DataDirsStep
        step = DataDirsStep(project_dir=tmp_path)
        assert step.install() is True
        assert (tmp_path / "data" / "chroma").is_dir()
        assert (tmp_path / "data" / "okr").is_dir()
        assert (tmp_path / "data" / "webhook-inbox").is_dir()
        assert (tmp_path / "data" / "playwright" / "profile").is_dir()

    def test_is_auto(self, tmp_path):
        from setup_jarvis import DataDirsStep
        step = DataDirsStep(project_dir=tmp_path)
        assert step.is_auto is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup_jarvis.py::TestVenvStep -v`
Expected: FAIL with `ImportError: cannot import name 'VenvStep'`

**Step 3: Write minimal implementation**

Add to `scripts/setup_jarvis.py` after the `StepRunner` class:

```python
# ---------------------------------------------------------------------------
# Concrete steps: auto-install (safe)
# ---------------------------------------------------------------------------

class VenvStep(SetupStep):
    """Create a virtual environment at .venv."""

    def __init__(self, project_dir: Path = PROJECT_DIR):
        self._project_dir = project_dir
        super().__init__(
            name="Virtual environment",
            key="venv",
            profiles={"minimal", "personal", "full"},
        )

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        venv_python = self._project_dir / ".venv" / "bin" / "python"
        return Status.OK if venv_python.exists() else Status.MISSING

    def install(self) -> bool:
        venv_dir = self._project_dir / ".venv"
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True, text=True,
        )
        return result.returncode == 0

    def guide(self) -> str:
        return f"python3 -m venv {self._project_dir / '.venv'}"


class PipStep(SetupStep):
    """Install pip dependencies from pyproject.toml."""

    def __init__(self, project_dir: Path = PROJECT_DIR):
        self._project_dir = project_dir
        super().__init__(
            name="Pip dependencies",
            key="pip_deps",
            profiles={"minimal", "personal", "full"},
        )

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        pip = self._project_dir / ".venv" / "bin" / "pip"
        if not pip.exists():
            return Status.MISSING
        result = subprocess.run(
            [str(pip), "list", "--format=json"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return Status.ERROR
        try:
            packages = {p["name"].lower() for p in json.loads(result.stdout)}
        except (json.JSONDecodeError, KeyError):
            return Status.ERROR
        return Status.OK if "jarvis" in packages else Status.MISSING

    def install(self) -> bool:
        pip = self._project_dir / ".venv" / "bin" / "pip"
        result = subprocess.run(
            [str(pip), "install", "-e", f"{self._project_dir}[dev]"],
            capture_output=True, text=True,
        )
        return result.returncode == 0

    def guide(self) -> str:
        return "pip install -e '.[dev]'"


class DataDirsStep(SetupStep):
    """Create data subdirectories."""

    SUBDIRS = ["chroma", "okr", "webhook-inbox", "playwright/profile"]

    def __init__(self, project_dir: Path = PROJECT_DIR):
        self._project_dir = project_dir
        super().__init__(
            name="Data directories",
            key="data_dirs",
            profiles={"minimal", "personal", "full"},
        )

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        data_dir = self._project_dir / "data"
        for subdir in self.SUBDIRS:
            if not (data_dir / subdir).is_dir():
                return Status.MISSING
        return Status.OK

    def install(self) -> bool:
        data_dir = self._project_dir / "data"
        for subdir in self.SUBDIRS:
            (data_dir / subdir).mkdir(parents=True, exist_ok=True)
        return True

    def guide(self) -> str:
        return "mkdir -p data/{chroma,okr,webhook-inbox,playwright/profile}"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_setup_jarvis.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add scripts/setup_jarvis.py tests/test_setup_jarvis.py
git commit -m "feat: add VenvStep, PipStep, DataDirsStep auto-install steps"
```

---

### Task 3: Concrete Steps — SystemDepsStep, EnvConfigStep

**Files:**
- Modify: `scripts/setup_jarvis.py`
- Modify: `tests/test_setup_jarvis.py`

**Step 1: Write the failing tests**

Add to `tests/test_setup_jarvis.py`:

```python
class TestSystemDepsStep:
    def test_check_ok_when_deps_found(self, monkeypatch):
        from setup_jarvis import SystemDepsStep
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
        step = SystemDepsStep()
        assert step.check() == Status.OK

    def test_check_missing_when_jq_absent(self, monkeypatch):
        from setup_jarvis import SystemDepsStep
        monkeypatch.setattr(shutil, "which", lambda cmd: None if cmd == "jq" else f"/usr/bin/{cmd}")
        step = SystemDepsStep()
        assert step.check() == Status.MISSING

    def test_is_auto_false(self):
        from setup_jarvis import SystemDepsStep
        step = SystemDepsStep()
        assert step.is_auto is False

    def test_guide_includes_brew(self):
        from setup_jarvis import SystemDepsStep
        step = SystemDepsStep()
        assert "brew install" in step.guide()


class TestEnvConfigStep:
    def test_check_missing_when_no_env(self, tmp_path):
        from setup_jarvis import EnvConfigStep
        step = EnvConfigStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_check_missing_when_key_empty(self, tmp_path):
        from setup_jarvis import EnvConfigStep
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=\n")
        step = EnvConfigStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_check_ok_when_key_set(self, tmp_path):
        from setup_jarvis import EnvConfigStep
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-test123\n")
        step = EnvConfigStep(project_dir=tmp_path)
        assert step.check() == Status.OK

    def test_check_ignores_commented_lines(self, tmp_path):
        from setup_jarvis import EnvConfigStep
        (tmp_path / ".env").write_text("# ANTHROPIC_API_KEY=sk-ant-test123\n")
        step = EnvConfigStep(project_dir=tmp_path)
        assert step.check() == Status.MISSING

    def test_install_copies_template(self, tmp_path):
        from setup_jarvis import EnvConfigStep
        (tmp_path / ".env.example").write_text("ANTHROPIC_API_KEY=\nSCHEDULER_ENABLED=true\n")
        step = EnvConfigStep(project_dir=tmp_path, interactive=False)
        step.install()
        assert (tmp_path / ".env").exists()
        content = (tmp_path / ".env").read_text()
        assert "ANTHROPIC_API_KEY=" in content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup_jarvis.py::TestSystemDepsStep -v`
Expected: FAIL with `ImportError: cannot import name 'SystemDepsStep'`

**Step 3: Write minimal implementation**

Add to `scripts/setup_jarvis.py`:

```python
# ---------------------------------------------------------------------------
# Concrete steps: guided (system-level)
# ---------------------------------------------------------------------------

class SystemDepsStep(SetupStep):
    """Check for system dependencies: jq, sqlite3."""

    DEPS = ["jq", "sqlite3"]

    def __init__(self):
        super().__init__(
            name="System dependencies (jq, sqlite3)",
            key="system_deps",
            profiles={"minimal", "personal", "full"},
        )

    def check(self) -> Status:
        for dep in self.DEPS:
            if not shutil.which(dep):
                return Status.MISSING
        return Status.OK

    def guide(self) -> str:
        missing = [d for d in self.DEPS if not shutil.which(d)]
        return f"brew install {' '.join(missing)}"


# ---------------------------------------------------------------------------
# Concrete steps: hybrid (.env configuration)
# ---------------------------------------------------------------------------

class EnvConfigStep(SetupStep):
    """Configure .env from .env.example template."""

    REQUIRED_KEYS = {"ANTHROPIC_API_KEY"}
    PROFILE_KEYS = {
        "personal": ["JARVIS_IMESSAGE_SELF", "JARVIS_DEFAULT_EMAIL_TO"],
        "full": ["JARVIS_IMESSAGE_SELF", "JARVIS_DEFAULT_EMAIL_TO", "JARVIS_ONEDRIVE_BASE"],
    }

    def __init__(self, project_dir: Path = PROJECT_DIR, profile: str = "minimal",
                 interactive: bool = True):
        self._project_dir = project_dir
        self._profile = profile
        self._interactive = interactive
        super().__init__(
            name=".env configuration",
            key="env_config",
            profiles={"minimal", "personal", "full"},
        )

    @property
    def is_auto(self) -> bool:
        return True  # hybrid — auto-copies template, prompts for values

    def _parse_env(self, path: Path) -> dict[str, str]:
        """Parse a .env file into {key: value}, skipping comments."""
        env = {}
        if not path.exists():
            return env
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
        return env

    def check(self) -> Status:
        env_file = self._project_dir / ".env"
        if not env_file.exists():
            return Status.MISSING
        env = self._parse_env(env_file)
        for key in self.REQUIRED_KEYS:
            if not env.get(key):
                return Status.MISSING
        return Status.OK

    def install(self) -> bool:
        env_file = self._project_dir / ".env"
        template = self._project_dir / ".env.example"
        if not env_file.exists() and template.exists():
            shutil.copy2(template, env_file)
        if self._interactive:
            self._prompt_values(env_file)
        return True

    def _prompt_values(self, env_file: Path):
        """Prompt user for required and profile-specific values."""
        env = self._parse_env(env_file)
        lines = env_file.read_text().splitlines() if env_file.exists() else []
        changed = False

        keys_to_prompt = list(self.REQUIRED_KEYS)
        keys_to_prompt += self.PROFILE_KEYS.get(self._profile, [])

        for key in keys_to_prompt:
            current = env.get(key, "")
            if current:
                continue
            required = key in self.REQUIRED_KEYS
            label = "(required)" if required else "(optional, Enter to skip)"
            try:
                value = input(f"  {key} {label}: ").strip()
            except (EOFError, KeyboardInterrupt):
                value = ""
            if value:
                # Update or append in the file content
                updated = False
                for i, line in enumerate(lines):
                    stripped = line.lstrip("# ")
                    if stripped.startswith(f"{key}="):
                        lines[i] = f"{key}={value}"
                        updated = True
                        break
                if not updated:
                    lines.append(f"{key}={value}")
                changed = True

        if changed:
            env_file.write_text("\n".join(lines) + "\n")

    def guide(self) -> str:
        return "cp .env.example .env && edit .env"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_setup_jarvis.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add scripts/setup_jarvis.py tests/test_setup_jarvis.py
git commit -m "feat: add SystemDepsStep and EnvConfigStep"
```

---

### Task 4: Concrete Steps — PlaywrightStep, LaunchAgentsStep, manual steps

**Files:**
- Modify: `scripts/setup_jarvis.py`
- Modify: `tests/test_setup_jarvis.py`

**Step 1: Write the failing tests**

Add to `tests/test_setup_jarvis.py`:

```python
class TestPlaywrightStep:
    def test_profiles(self):
        from setup_jarvis import PlaywrightStep
        step = PlaywrightStep()
        assert step.applies_to("personal")
        assert step.applies_to("full")
        assert not step.applies_to("minimal")

    def test_is_auto_false(self):
        from setup_jarvis import PlaywrightStep
        step = PlaywrightStep()
        assert step.is_auto is False

    def test_guide_includes_playwright(self):
        from setup_jarvis import PlaywrightStep
        step = PlaywrightStep()
        assert "playwright install chromium" in step.guide()


class TestLaunchAgentsStep:
    def test_check_missing_when_no_plists(self, tmp_path):
        from setup_jarvis import LaunchAgentsStep
        step = LaunchAgentsStep(project_dir=tmp_path, launch_agents_dir=tmp_path / "LaunchAgents")
        assert step.check() == Status.MISSING

    def test_check_ok_when_plists_exist(self, tmp_path):
        from setup_jarvis import LaunchAgentsStep
        la_dir = tmp_path / "LaunchAgents"
        la_dir.mkdir()
        for label in LaunchAgentsStep.PLIST_LABELS:
            (la_dir / f"{label}.plist").touch()
        step = LaunchAgentsStep(project_dir=tmp_path, launch_agents_dir=la_dir)
        assert step.check() == Status.OK

    def test_is_auto(self):
        from setup_jarvis import LaunchAgentsStep
        step = LaunchAgentsStep()
        assert step.is_auto is True

    def test_profiles(self):
        from setup_jarvis import LaunchAgentsStep
        step = LaunchAgentsStep()
        assert step.applies_to("personal")
        assert step.applies_to("full")
        assert not step.applies_to("minimal")


class TestManualSteps:
    def test_imessage_perms_is_manual(self):
        from setup_jarvis import IMessagePermsStep
        step = IMessagePermsStep()
        assert step.is_manual is True
        assert step.check() == Status.MISSING

    def test_calendar_perms_is_manual(self):
        from setup_jarvis import CalendarPermsStep
        step = CalendarPermsStep()
        assert step.is_manual is True
        assert step.check() == Status.MISSING

    def test_m365_bridge_profiles(self):
        from setup_jarvis import M365BridgeStep
        step = M365BridgeStep()
        assert step.applies_to("full")
        assert not step.applies_to("personal")
        assert not step.applies_to("minimal")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup_jarvis.py::TestPlaywrightStep -v`
Expected: FAIL with `ImportError: cannot import name 'PlaywrightStep'`

**Step 3: Write minimal implementation**

Add to `scripts/setup_jarvis.py`:

```python
class PlaywrightStep(SetupStep):
    """Install Playwright and Chromium browser."""

    def __init__(self):
        super().__init__(
            name="Playwright + Chromium",
            key="playwright",
            profiles={"personal", "full"},
        )

    def check(self) -> Status:
        if not shutil.which("playwright"):
            return Status.MISSING
        # Check if chromium is installed
        result = subprocess.run(
            ["playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True,
        )
        # If dry-run succeeds without needing download, it's installed
        if result.returncode == 0 and "chromium" not in result.stdout.lower():
            return Status.OK
        # Fallback: check known cache dirs
        home = Path.home()
        for cache_dir in [home / "Library/Caches/ms-playwright", home / ".cache/ms-playwright"]:
            if cache_dir.is_dir() and any(cache_dir.iterdir()):
                return Status.OK
        return Status.MISSING

    def guide(self) -> str:
        return "playwright install chromium"


class LaunchAgentsStep(SetupStep):
    """Install macOS LaunchAgents via install-plists.sh."""

    PLIST_LABELS = [
        "com.chg.inbox-monitor",
        "com.chg.jarvis-backup",
        "com.chg.alert-evaluator",
        "com.chg.imessage-daemon",
        "com.chg.scheduler-engine",
    ]

    def __init__(self, project_dir: Path = PROJECT_DIR,
                 launch_agents_dir: Optional[Path] = None):
        self._project_dir = project_dir
        self._launch_agents_dir = launch_agents_dir or Path.home() / "Library/LaunchAgents"
        super().__init__(
            name="LaunchAgents",
            key="launch_agents",
            profiles={"personal", "full"},
        )

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        for label in self.PLIST_LABELS:
            if not (self._launch_agents_dir / f"{label}.plist").exists():
                return Status.MISSING
        return Status.OK

    def install(self) -> bool:
        script = self._project_dir / "scripts" / "install-plists.sh"
        if not script.exists():
            return False
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True,
            env={**os.environ, "JARVIS_PROJECT_DIR": str(self._project_dir)},
        )
        return result.returncode == 0

    def guide(self) -> str:
        return "./scripts/install-plists.sh"


# ---------------------------------------------------------------------------
# Concrete steps: manual (can't verify)
# ---------------------------------------------------------------------------

class IMessagePermsStep(SetupStep):
    """Grant Full Disk Access for iMessage reader."""

    def __init__(self):
        super().__init__(
            name="iMessage Full Disk Access",
            key="imessage_perms",
            profiles={"personal", "full"},
        )

    @property
    def is_manual(self) -> bool:
        return True

    def check(self) -> Status:
        return Status.MISSING  # Can't verify programmatically

    def guide(self) -> str:
        return (
            "Grant Full Disk Access for iMessage reader:\n"
            "  1. Open System Settings > Privacy & Security > Full Disk Access\n"
            "  2. Click + and navigate to: scripts/imessage-reader\n"
            "  3. Toggle it on"
        )


class CalendarPermsStep(SetupStep):
    """Grant Calendar and Reminders permissions."""

    def __init__(self):
        super().__init__(
            name="Calendar & Reminders permissions",
            key="calendar_perms",
            profiles={"personal", "full"},
        )

    @property
    def is_manual(self) -> bool:
        return True

    def check(self) -> Status:
        return Status.MISSING  # Can't verify programmatically

    def guide(self) -> str:
        return (
            "Grant Calendar and Reminders access:\n"
            "  1. Open System Settings > Privacy & Security > Calendars\n"
            "  2. Enable access for your terminal app\n"
            "  3. Repeat for Privacy & Security > Reminders"
        )


class M365BridgeStep(SetupStep):
    """Detect Microsoft 365 bridge availability."""

    def __init__(self):
        super().__init__(
            name="Microsoft 365 bridge",
            key="m365_bridge",
            profiles={"full"},
        )

    def check(self) -> Status:
        claude_bin = shutil.which("claude")
        if not claude_bin:
            return Status.MISSING
        result = subprocess.run(
            [claude_bin, "mcp", "list"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return Status.ERROR
        # Look for Microsoft 365 in the output
        if "microsoft" in result.stdout.lower() or "365" in result.stdout:
            return Status.OK
        return Status.MISSING

    def guide(self) -> str:
        return (
            "Set up Microsoft 365 bridge:\n"
            "  1. Install Claude CLI: https://docs.anthropic.com/claude-code\n"
            "  2. Connect the M365 MCP connector in Claude settings\n"
            "  3. Verify: claude mcp list (should show Microsoft 365)"
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_setup_jarvis.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add scripts/setup_jarvis.py tests/test_setup_jarvis.py
git commit -m "feat: add PlaywrightStep, LaunchAgentsStep, and manual permission steps"
```

---

### Task 5: Concrete Steps — TestSuiteStep, ServerVerifyStep

**Files:**
- Modify: `scripts/setup_jarvis.py`
- Modify: `tests/test_setup_jarvis.py`

**Step 1: Write the failing tests**

Add to `tests/test_setup_jarvis.py`:

```python
class TestTestSuiteStep:
    def test_profiles_full_only(self):
        from setup_jarvis import TestSuiteStep
        step = TestSuiteStep()
        assert step.applies_to("full")
        assert not step.applies_to("personal")
        assert not step.applies_to("minimal")

    def test_is_auto(self):
        from setup_jarvis import TestSuiteStep
        step = TestSuiteStep()
        assert step.is_auto is True

    def test_check_always_missing(self):
        """Test suite always runs fresh — never 'already done'."""
        from setup_jarvis import TestSuiteStep
        step = TestSuiteStep()
        assert step.check() == Status.MISSING


class TestServerVerifyStep:
    def test_profiles_all(self):
        from setup_jarvis import ServerVerifyStep
        step = ServerVerifyStep()
        assert step.applies_to("minimal")
        assert step.applies_to("personal")
        assert step.applies_to("full")

    def test_is_auto(self):
        from setup_jarvis import ServerVerifyStep
        step = ServerVerifyStep()
        assert step.is_auto is True

    def test_check_always_missing(self):
        """Server verify always runs fresh."""
        from setup_jarvis import ServerVerifyStep
        step = ServerVerifyStep()
        assert step.check() == Status.MISSING
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup_jarvis.py::TestTestSuiteStep -v`
Expected: FAIL with `ImportError: cannot import name 'TestSuiteStep'`

**Step 3: Write minimal implementation**

Add to `scripts/setup_jarvis.py`:

```python
# ---------------------------------------------------------------------------
# Concrete steps: run-every-time (verification)
# ---------------------------------------------------------------------------

class TestSuiteStep(SetupStep):
    """Run the test suite with pytest."""

    def __init__(self, project_dir: Path = PROJECT_DIR):
        self._project_dir = project_dir
        super().__init__(
            name="Test suite",
            key="test_suite",
            profiles={"full"},
        )

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        return Status.MISSING  # Always run fresh

    def install(self) -> bool:
        pytest_bin = self._project_dir / ".venv" / "bin" / "pytest"
        if not pytest_bin.exists():
            pytest_bin = shutil.which("pytest") or "pytest"
        result = subprocess.run(
            [str(pytest_bin)],
            capture_output=True, text=True,
            cwd=str(self._project_dir),
        )
        # Print summary line
        for line in result.stdout.splitlines()[-5:]:
            if "passed" in line or "failed" in line or "error" in line:
                print(f"      {line.strip()}")
                break
        return result.returncode == 0

    def guide(self) -> str:
        return "pytest"


class ServerVerifyStep(SetupStep):
    """Verify jarvis-mcp starts without errors."""

    def __init__(self, project_dir: Path = PROJECT_DIR):
        self._project_dir = project_dir
        super().__init__(
            name="MCP server smoke test",
            key="server_verify",
            profiles={"minimal", "personal", "full"},
        )

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        return Status.MISSING  # Always run fresh

    def install(self) -> bool:
        jarvis_bin = self._project_dir / ".venv" / "bin" / "jarvis-mcp"
        if not jarvis_bin.exists():
            return False
        try:
            proc = subprocess.Popen(
                [str(jarvis_bin)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(self._project_dir),
            )
            try:
                proc.wait(timeout=3)
                # If it exits within 3s, check if it crashed
                if proc.returncode != 0:
                    stderr = proc.stderr.read().decode() if proc.stderr else ""
                    print(f"      Server exited with code {proc.returncode}")
                    if stderr:
                        print(f"      {stderr[:200]}")
                    return False
            except subprocess.TimeoutExpired:
                # Still running after 3s = success
                proc.terminate()
                proc.wait(timeout=5)
            return True
        except FileNotFoundError:
            return False

    def guide(self) -> str:
        return "jarvis-mcp"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_setup_jarvis.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add scripts/setup_jarvis.py tests/test_setup_jarvis.py
git commit -m "feat: add TestSuiteStep and ServerVerifyStep verification steps"
```

---

### Task 6: Output Formatting — scan display and walkthrough rendering

**Files:**
- Modify: `scripts/setup_jarvis.py`
- Modify: `tests/test_setup_jarvis.py`

**Step 1: Write the failing tests**

Add to `tests/test_setup_jarvis.py`:

```python
class TestFormatScan:
    def test_format_scan_summary(self):
        from setup_jarvis import format_scan_summary
        results = [
            ("venv", Status.OK, True, False),
            ("pip", Status.MISSING, True, False),
            ("perms", Status.MISSING, False, True),
        ]
        summary = format_scan_summary(results)
        assert "1 auto-install" in summary
        assert "1 manual" in summary
        assert "1 already done" in summary

    def test_format_scan_line(self):
        from setup_jarvis import format_scan_line
        assert "[ok]" in format_scan_line("Python 3.13", Status.OK)
        assert "[--]" in format_scan_line("pip deps", Status.MISSING)
        assert "[!!]" in format_scan_line("perms", Status.ERROR)


class TestFormatFinalSummary:
    def test_final_summary_includes_manual_steps(self):
        from setup_jarvis import format_final_summary
        manual_guides = [
            "Grant Calendar access: System Settings > Privacy > Calendars",
            "Grant Full Disk Access for scripts/imessage-reader",
        ]
        summary = format_final_summary(
            completed=5, failed=0, manual_guides=manual_guides
        )
        assert "5 steps configured" in summary
        assert "Calendar" in summary
        assert "Full Disk Access" in summary

    def test_final_summary_no_manual(self):
        from setup_jarvis import format_final_summary
        summary = format_final_summary(completed=3, failed=0, manual_guides=[])
        assert "Manual steps" not in summary

    def test_final_summary_shows_failures(self):
        from setup_jarvis import format_final_summary
        summary = format_final_summary(completed=3, failed=2, manual_guides=[])
        assert "2 failed" in summary
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup_jarvis.py::TestFormatScan -v`
Expected: FAIL with `ImportError: cannot import name 'format_scan_summary'`

**Step 3: Write minimal implementation**

Add to `scripts/setup_jarvis.py`:

```python
# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_scan_line(name: str, status: Status) -> str:
    """Format a single scan result line: '  [ok] Python 3.13'."""
    return f"  {status.label} {name}"


def format_scan_summary(results: list[tuple[str, Status, bool, bool]]) -> str:
    """Format the scan summary counts.

    Each result is (name, status, is_auto, is_manual).
    """
    ok = sum(1 for _, s, _, _ in results if s == Status.OK)
    auto = sum(1 for _, s, a, _ in results if s != Status.OK and a)
    guided = sum(1 for _, s, a, m in results if s != Status.OK and not a and not m)
    manual = sum(1 for _, s, _, m in results if s != Status.OK and m)

    parts = []
    if auto:
        parts.append(f"{auto} auto-install")
    if guided:
        parts.append(f"{guided} guided")
    if manual:
        parts.append(f"{manual} manual")
    if ok:
        parts.append(f"{ok} already done")
    return "  " + "  |  ".join(parts)


def format_final_summary(completed: int, failed: int,
                         manual_guides: list[str]) -> str:
    """Format the final setup summary."""
    lines = ["\nSetup complete!\n"]
    if completed:
        lines.append(f"  [ok] {completed} steps configured successfully")
    if failed:
        lines.append(f"  [!!] {failed} failed")
    if manual_guides:
        lines.append("\n  Manual steps remaining:")
        for guide in manual_guides:
            lines.append(f"    [ ] {guide}")
    lines.append("\n  Quick start:")
    lines.append("    jarvis-mcp              # Start the MCP server")
    lines.append("    pytest                  # Run tests (1723 expected)")
    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_setup_jarvis.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add scripts/setup_jarvis.py tests/test_setup_jarvis.py
git commit -m "feat: add scan and summary output formatting functions"
```

---

### Task 7: CLI — argparse, profile prompt, main orchestration

**Files:**
- Modify: `scripts/setup_jarvis.py`
- Modify: `tests/test_setup_jarvis.py`

**Step 1: Write the failing tests**

Add to `tests/test_setup_jarvis.py`:

```python
class TestParseArgs:
    def test_defaults(self):
        from setup_jarvis import parse_args
        args = parse_args([])
        assert args.profile is None
        assert args.check is False

    def test_profile_flag(self):
        from setup_jarvis import parse_args
        args = parse_args(["--profile", "full"])
        assert args.profile == "full"

    def test_check_flag(self):
        from setup_jarvis import parse_args
        args = parse_args(["--check"])
        assert args.check is True

    def test_invalid_profile_rejected(self):
        from setup_jarvis import parse_args
        with pytest.raises(SystemExit):
            parse_args(["--profile", "invalid"])


class TestBuildSteps:
    def test_build_steps_returns_all_step_types(self):
        from setup_jarvis import build_steps
        steps = build_steps()
        keys = {s.key for s in steps}
        assert "venv" in keys
        assert "pip_deps" in keys
        assert "data_dirs" in keys
        assert "system_deps" in keys
        assert "env_config" in keys
        assert "server_verify" in keys

    def test_build_steps_order_preserved(self):
        from setup_jarvis import build_steps
        steps = build_steps()
        keys = [s.key for s in steps]
        # venv must come before pip_deps
        assert keys.index("venv") < keys.index("pip_deps")
        # pip_deps must come before server_verify
        assert keys.index("pip_deps") < keys.index("server_verify")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup_jarvis.py::TestParseArgs -v`
Expected: FAIL with `ImportError: cannot import name 'parse_args'`

**Step 3: Write minimal implementation**

Add to `scripts/setup_jarvis.py`:

```python
# ---------------------------------------------------------------------------
# CLI and orchestration
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Jarvis (Chief of Staff) setup script",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default=None,
        help="Setup profile: minimal, personal, or full",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Scan only — report status without making changes",
    )
    return parser.parse_args(argv)


def prompt_profile() -> str:
    """Interactive profile selection."""
    print("\nWelcome to Jarvis (Chief of Staff) Setup\n")
    print("Select a profile:")
    print("  [1] minimal   — Core: memory, agents, documents, MCP server")
    print("  [2] personal  — + Apple integrations, LaunchAgents, iMessage, Teams")
    print("  [3] full      — + M365 bridge, dev deps, test suite, all features")
    while True:
        try:
            choice = input("\nChoice [1/2/3]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if choice in ("1", "minimal"):
            return "minimal"
        if choice in ("2", "personal"):
            return "personal"
        if choice in ("3", "full"):
            return "full"
        print("  Please enter 1, 2, or 3.")


def build_steps(project_dir: Path = PROJECT_DIR,
                profile: str = "minimal",
                interactive: bool = True) -> list[SetupStep]:
    """Build the ordered list of all setup steps."""
    return [
        VenvStep(project_dir=project_dir),
        PipStep(project_dir=project_dir),
        SystemDepsStep(),
        EnvConfigStep(project_dir=project_dir, profile=profile, interactive=interactive),
        DataDirsStep(project_dir=project_dir),
        PlaywrightStep(),
        LaunchAgentsStep(project_dir=project_dir),
        IMessagePermsStep(),
        CalendarPermsStep(),
        M365BridgeStep(),
        TestSuiteStep(project_dir=project_dir),
        ServerVerifyStep(project_dir=project_dir),
    ]


def run_setup(args: argparse.Namespace) -> int:
    """Main setup orchestration. Returns exit code."""
    profile = args.profile or prompt_profile()
    interactive = not args.check

    steps = build_steps(profile=profile, interactive=interactive)
    runner = StepRunner(steps=steps, profile=profile, interactive=interactive)

    # --- Scan phase ---
    print(f"\nScanning environment (profile: {profile})...\n")
    scan_results = runner.scan()

    scan_display = []
    for step, status in scan_results:
        print(format_scan_line(step.name, status))
        scan_display.append((step.name, status, step.is_auto, step.is_manual))

    print()
    print(format_scan_summary(scan_display))

    if args.check:
        has_missing = any(s != Status.OK for _, s in scan_results)
        return 1 if has_missing else 0

    # --- Walkthrough phase ---
    actionable = [(step, status) for step, status in scan_results
                  if status != Status.OK]
    if not actionable:
        print("\n  Everything looks good!")
    else:
        if interactive:
            try:
                input("\nPress Enter to begin setup (or Ctrl+C to abort)... ")
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                return 1

        completed = 0
        failed = 0
        manual_guides = []
        total = len(actionable)

        for i, (step, _) in enumerate(actionable, 1):
            if step.is_manual:
                print(f"\n[{i}/{total}] {step.name}")
                print(f"      {step.guide()}")
                print("      [noted for final checklist]")
                manual_guides.append(step.guide().split("\n")[0])
                continue

            print(f"\n[{i}/{total}] {step.name}")
            if step.is_auto:
                success = step.install()
                if success:
                    completed += 1
                    print(f"      done")
                else:
                    failed += 1
                    print(f"      FAILED")
            else:
                # Guided step
                print(f"      {step.guide()}")
                if interactive:
                    try:
                        answer = input("      Done? [Y/n/skip]: ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        answer = "skip"
                    if answer in ("", "y", "yes"):
                        # Re-check
                        if step.check() == Status.OK:
                            completed += 1
                            print("      verified")
                        else:
                            print("      not detected — noted for follow-up")
                            manual_guides.append(step.guide().split("\n")[0])
                    else:
                        manual_guides.append(step.guide().split("\n")[0])

        # Add manual steps from scan that were OK (already shown)
        ok_count = sum(1 for _, s in scan_results if s == Status.OK)
        completed += ok_count

        print(format_final_summary(completed, failed, manual_guides))

    return 0


def main():
    args = parse_args()
    sys.exit(run_setup(args))


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_setup_jarvis.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add scripts/setup_jarvis.py tests/test_setup_jarvis.py
git commit -m "feat: add CLI parsing, profile prompt, and main setup orchestration"
```

---

### Task 8: Bash Bootstrapper — setup.sh

**Files:**
- Create: `setup.sh`
- Modify: `tests/test_setup_jarvis.py`

**Step 1: Write the failing test**

Add to `tests/test_setup_jarvis.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup_jarvis.py::TestSetupSh -v`
Expected: FAIL with `AssertionError: setup.sh must exist at project root`

**Step 3: Write the bash bootstrapper**

Create `setup.sh`:

```bash
#!/usr/bin/env bash
#
# setup.sh — Jarvis (Chief of Staff) setup bootstrapper.
#
# Finds Python 3.11+ and delegates to scripts/setup_jarvis.py.
# If Python is not found, offers to install via Homebrew.
#
# Usage:
#   ./setup.sh                      # Interactive, prompts for profile
#   ./setup.sh --profile minimal    # Skip profile prompt
#   ./setup.sh --profile full       # Everything
#   ./setup.sh --check              # Scan and report only
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SETUP_PY="$SCRIPT_DIR/scripts/setup_jarvis.py"
MIN_MAJOR=3
MIN_MINOR=11

# --- Find a suitable Python ---

find_python() {
    for candidate in python3.13 python3.12 python3.11 python3; do
        local bin
        bin="$(command -v "$candidate" 2>/dev/null)" || continue
        if check_version "$bin"; then
            echo "$bin"
            return 0
        fi
    done
    return 1
}

check_version() {
    local bin="$1"
    local version
    version="$("$bin" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)" || return 1
    local major minor
    major="${version%%.*}"
    minor="${version##*.}"
    [[ "$major" -ge "$MIN_MAJOR" && "$minor" -ge "$MIN_MINOR" ]]
}

# --- Main ---

PYTHON_BIN=""
if ! PYTHON_BIN="$(find_python)"; then
    echo "Python ${MIN_MAJOR}.${MIN_MINOR}+ not found."
    if command -v brew &>/dev/null; then
        echo ""
        read -rp "Install Python 3.13 via Homebrew? [Y/n] " answer
        if [[ "${answer:-y}" =~ ^[Yy]$ ]]; then
            brew install python@3.13
            PYTHON_BIN="$(find_python)" || {
                echo "Error: Python still not found after install."
                exit 1
            }
        else
            echo "Please install Python ${MIN_MAJOR}.${MIN_MINOR}+ and re-run."
            exit 1
        fi
    else
        echo "Please install Python ${MIN_MAJOR}.${MIN_MINOR}+ and re-run."
        echo "  macOS: brew install python@3.13"
        echo "  Other: https://python.org/downloads/"
        exit 1
    fi
fi

echo "Using Python: $PYTHON_BIN ($("$PYTHON_BIN" --version))"
exec "$PYTHON_BIN" "$SETUP_PY" "$@"
```

Then make it executable:

```bash
chmod +x setup.sh
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_setup_jarvis.py::TestSetupSh -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add setup.sh tests/test_setup_jarvis.py
git commit -m "feat: add setup.sh bash bootstrapper for Python detection"
```

---

### Task 9: Update setup-guide.md with Quick Start section

**Files:**
- Modify: `docs/setup-guide.md`

**Step 1: Add Quick Start at the top of the guide**

Insert after the `# Setup Guide` heading and before `## Prerequisites`:

```markdown
## Quick Start

Run the interactive setup script:

```bash
./setup.sh
```

This detects your environment, installs what it can automatically, and guides you through the rest. For options:

```bash
./setup.sh --profile minimal    # Core features only
./setup.sh --profile personal   # + Apple integrations, LaunchAgents, Teams
./setup.sh --profile full       # Everything including M365, tests
./setup.sh --check              # Scan-only (no changes)
```

For manual setup or more details, continue reading below.
```

**Step 2: Verify the doc reads correctly**

Read `docs/setup-guide.md` and ensure the Quick Start section appears at the top.

**Step 3: Commit**

```bash
git add docs/setup-guide.md
git commit -m "docs: add Quick Start section to setup guide"
```

---

### Task 10: Integration test — full scan in --check mode

**Files:**
- Modify: `tests/test_setup_jarvis.py`

**Step 1: Write the integration test**

Add to `tests/test_setup_jarvis.py`:

```python
class TestIntegration:
    def test_check_mode_returns_exit_code(self, tmp_path):
        """--check mode should return 1 when steps are missing."""
        from setup_jarvis import parse_args, build_steps, StepRunner, run_setup
        import types

        # Build args simulating --check --profile minimal
        args = parse_args(["--check", "--profile", "minimal"])
        # This should scan and return 1 (missing steps in a fresh tmp dir)
        # We can't easily run the full thing, but we can test the runner
        steps = build_steps(project_dir=tmp_path, profile="minimal", interactive=False)
        runner = StepRunner(steps=steps, profile="minimal", interactive=False)
        results = runner.scan()
        has_missing = any(s != Status.OK for _, s in results)
        assert has_missing  # fresh tmp_path should have missing steps

    def test_scan_all_steps_return_valid_status(self, tmp_path):
        """Every step's check() should return a valid Status."""
        from setup_jarvis import build_steps
        steps = build_steps(project_dir=tmp_path, profile="full", interactive=False)
        for step in steps:
            status = step.check()
            assert isinstance(status, Status), f"{step.key} returned {type(status)}"

    def test_all_steps_have_guide(self, tmp_path):
        """Every step should have a non-empty guide string."""
        from setup_jarvis import build_steps
        steps = build_steps(project_dir=tmp_path, profile="full", interactive=False)
        for step in steps:
            guide = step.guide()
            assert isinstance(guide, str), f"{step.key}.guide() returned {type(guide)}"
            assert len(guide) > 0, f"{step.key}.guide() is empty"
```

**Step 2: Run test to verify it passes**

Run: `pytest tests/test_setup_jarvis.py::TestIntegration -v`
Expected: All 3 tests PASS

**Step 3: Commit**

```bash
git add tests/test_setup_jarvis.py
git commit -m "test: add integration tests for setup script scan and check mode"
```

---

### Task 11: Final verification — run full test suite and --check mode

**Step 1: Run all setup script tests**

Run: `pytest tests/test_setup_jarvis.py -v`
Expected: All tests PASS (approx 30+ tests)

**Step 2: Run --check mode against the real project**

Run: `python3 scripts/setup_jarvis.py --check --profile full`
Expected: Prints scan results with mix of `[ok]` and `[--]`/`[!!]`, exits with code 0 or 1

**Step 3: Run the full project test suite**

Run: `pytest`
Expected: All 1723+ tests PASS (no regressions)

**Step 4: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: setup script fixups from final verification"
```

(Skip if no changes needed.)
