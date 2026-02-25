#!/usr/bin/env python3
"""Jarvis (Chief of Staff) setup and environment checker.

Provides a step-based framework for verifying and configuring the Jarvis
environment. Each step checks a prerequisite (Python version, API key,
database, etc.) and optionally offers auto-install or manual guidance.

Usage:
    python scripts/setup_jarvis.py [--profile PROFILE] [--non-interactive]
"""

from __future__ import annotations

import abc
import enum
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Project root
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class Status(enum.Enum):
    """Result of a single setup-step check."""

    OK = "ok"
    MISSING = "missing"
    ERROR = "error"

    @property
    def label(self) -> str:
        """Human-readable label for terminal output."""
        _labels = {
            "ok": "[ok]",
            "missing": "[--]",
            "error": "[!!]",
        }
        return _labels[self.value]


# ---------------------------------------------------------------------------
# SetupStep base class
# ---------------------------------------------------------------------------

@dataclass
class SetupStep(abc.ABC):
    """Base class for a single setup check/action.

    Subclasses *must* override ``check()``.  Optionally override
    ``install()``, ``guide()``, ``is_auto``, or ``is_manual``.
    """

    name: str
    key: str
    profiles: set[str]

    @abc.abstractmethod
    def check(self) -> Status:
        """Return the current status of this step."""
        ...

    def install(self) -> bool:
        """Attempt automatic installation.  Return True on success."""
        return False

    def guide(self) -> str:
        """Return a human-readable manual-fix instruction string."""
        return ""

    @property
    def is_auto(self) -> bool:
        """Whether this step supports automatic installation."""
        return False

    @property
    def is_manual(self) -> bool:
        """Whether this step requires manual user action."""
        return False

    def applies_to(self, profile: str) -> bool:
        """Return True if this step is relevant to *profile*."""
        return profile in self.profiles


# ---------------------------------------------------------------------------
# StepRunner
# ---------------------------------------------------------------------------

@dataclass
class StepRunner:
    """Runs a sequence of :class:`SetupStep` instances for a given profile."""

    steps: List[SetupStep]
    profile: str
    interactive: bool = True

    def scan(self) -> List[Tuple[SetupStep, Status]]:
        """Check every applicable step and return ``(step, status)`` pairs."""
        results: List[Tuple[SetupStep, Status]] = []
        for step in self.steps:
            if step.applies_to(self.profile):
                status = step.check()
                results.append((step, status))
        return results


# ---------------------------------------------------------------------------
# Concrete steps — auto-install
# ---------------------------------------------------------------------------

_ALL_PROFILES = {"minimal", "personal", "full"}


@dataclass
class VenvStep(SetupStep):
    """Ensure a Python virtual environment exists at ``<project>/.venv``."""

    project_dir: Path = field(default_factory=lambda: PROJECT_DIR)
    name: str = field(default="Python venv", init=False)
    key: str = field(default="venv", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_ALL_PROFILES), init=False)

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        venv_python = self.project_dir / ".venv" / "bin" / "python"
        return Status.OK if venv_python.exists() else Status.MISSING

    def install(self) -> bool:
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(self.project_dir / ".venv")],
                check=True,
                capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, OSError):
            return False

    def guide(self) -> str:
        return f"python -m venv {self.project_dir / '.venv'}"


@dataclass
class PipStep(SetupStep):
    """Ensure the project is pip-installed in the venv (editable mode)."""

    project_dir: Path = field(default_factory=lambda: PROJECT_DIR)
    name: str = field(default="pip install", init=False)
    key: str = field(default="pip", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_ALL_PROFILES), init=False)

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        pip_bin = self.project_dir / ".venv" / "bin" / "pip"
        if not pip_bin.exists():
            return Status.MISSING
        try:
            result = subprocess.run(
                [str(pip_bin), "list", "--format=json"],
                capture_output=True,
                text=True,
                check=True,
            )
            packages = json.loads(result.stdout)
            pkg_names = {pkg["name"].lower() for pkg in packages}
            return Status.OK if "jarvis" in pkg_names else Status.MISSING
        except (subprocess.CalledProcessError, OSError, json.JSONDecodeError, KeyError):
            return Status.ERROR

    def install(self) -> bool:
        pip_bin = self.project_dir / ".venv" / "bin" / "pip"
        try:
            subprocess.run(
                [str(pip_bin), "install", "-e", ".[dev]"],
                cwd=str(self.project_dir),
                check=True,
                capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, OSError):
            return False

    def guide(self) -> str:
        return f"{self.project_dir / '.venv' / 'bin' / 'pip'} install -e '.[dev]'"


@dataclass
class DataDirsStep(SetupStep):
    """Ensure required data sub-directories exist."""

    SUBDIRS: list[str] = field(
        default_factory=lambda: ["chroma", "okr", "webhook-inbox", "playwright/profile"],
        init=False,
    )

    project_dir: Path = field(default_factory=lambda: PROJECT_DIR)
    name: str = field(default="Data directories", init=False)
    key: str = field(default="data_dirs", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_ALL_PROFILES), init=False)

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        data_dir = self.project_dir / "data"
        for subdir in self.SUBDIRS:
            if not (data_dir / subdir).is_dir():
                return Status.MISSING
        return Status.OK

    def install(self) -> bool:
        data_dir = self.project_dir / "data"
        try:
            for subdir in self.SUBDIRS:
                (data_dir / subdir).mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False

    def guide(self) -> str:
        data_dir = self.project_dir / "data"
        cmds = [f"mkdir -p {data_dir / subdir}" for subdir in self.SUBDIRS]
        return "\n".join(cmds)


# ---------------------------------------------------------------------------
# SystemDepsStep — guided (user runs brew themselves)
# ---------------------------------------------------------------------------

@dataclass
class SystemDepsStep(SetupStep):
    """Check that required system-level dependencies are installed.

    This is a *guided* step: ``is_auto`` is ``False`` because the user
    must run ``brew install`` (or equivalent) themselves.
    """

    DEPS: list[str] = field(
        default_factory=lambda: ["jq", "sqlite3"],
        init=False,
    )

    name: str = field(default="System dependencies", init=False)
    key: str = field(default="system_deps", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_ALL_PROFILES), init=False)

    # -- check ---------------------------------------------------------------

    def check(self) -> Status:
        """OK if every dep is on ``$PATH``; MISSING otherwise."""
        for dep in self.DEPS:
            if shutil.which(dep) is None:
                return Status.MISSING
        return Status.OK

    # -- guide ---------------------------------------------------------------

    def guide(self) -> str:
        """Return a ``brew install`` command for whatever is missing."""
        missing = [dep for dep in self.DEPS if shutil.which(dep) is None]
        if not missing:
            return "brew install jq sqlite3"
        return f"brew install {' '.join(missing)}"

    @property
    def is_auto(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# EnvConfigStep — hybrid (auto-copy template, prompt for values)
# ---------------------------------------------------------------------------

@dataclass
class EnvConfigStep(SetupStep):
    """Ensure a ``.env`` file exists and contains required keys.

    * ``is_auto`` is ``True`` because the step can copy ``.env.example``
      automatically and optionally prompt for values.
    * ``check()`` returns OK only when ``.env`` exists **and**
      ``ANTHROPIC_API_KEY`` has a non-empty value.
    """

    REQUIRED_KEYS: set[str] = field(
        default_factory=lambda: {"ANTHROPIC_API_KEY"},
        init=False,
    )
    PROFILE_KEYS: dict[str, list[str]] = field(default_factory=lambda: {
        "minimal": [],
        "personal": [
            "JARVIS_IMESSAGE_SELF",
        ],
        "full": [
            "JARVIS_IMESSAGE_SELF",
            "CLAUDE_BIN",
            "CLAUDE_MCP_CONFIG",
            "M365_BRIDGE_MODEL",
            "JARVIS_ONEDRIVE_BASE",
        ],
    }, init=False)

    project_dir: Path = field(default_factory=lambda: PROJECT_DIR)
    _profile: str = field(default="minimal")
    interactive: bool = True

    name: str = field(default="Environment config (.env)", init=False)
    key: str = field(default="env_config", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_ALL_PROFILES), init=False)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _parse_env(path: Path) -> dict[str, str]:
        """Parse a ``.env`` file into a dict, skipping comments and blanks."""
        env: dict[str, str] = {}
        if not path.exists():
            return env
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            env[key.strip()] = value.strip()
        return env

    # -- check ---------------------------------------------------------------

    def check(self) -> Status:
        """MISSING if ``.env`` absent or ``ANTHROPIC_API_KEY`` is empty."""
        env_path = self.project_dir / ".env"
        if not env_path.exists():
            return Status.MISSING
        env = self._parse_env(env_path)
        for key in self.REQUIRED_KEYS:
            if not env.get(key):
                return Status.MISSING
        return Status.OK

    # -- install -------------------------------------------------------------

    def install(self) -> bool:
        """Copy ``.env.example`` to ``.env`` if missing, optionally prompt."""
        env_path = self.project_dir / ".env"
        example_path = self.project_dir / ".env.example"

        if not env_path.exists() and example_path.exists():
            shutil.copy2(example_path, env_path)

        if self.interactive:
            self._prompt_values(env_path)

        return True

    def _prompt_values(self, env_file: Path) -> None:
        """Prompt the user for required + profile-specific keys."""
        env = self._parse_env(env_file)
        profile_keys = self.PROFILE_KEYS.get(self._profile, [])
        keys_to_prompt = list(self.REQUIRED_KEYS) + profile_keys

        updated = False
        for key in keys_to_prompt:
            current = env.get(key, "")
            prompt_msg = f"  {key} [{current}]: " if current else f"  {key}: "
            value = input(prompt_msg).strip()
            if value:
                env[key] = value
                updated = True

        if updated:
            # Rewrite the env file preserving keys we know about
            lines: list[str] = []
            if env_file.exists():
                lines = env_file.read_text().splitlines()

            written_keys: set[str] = set()
            new_lines: list[str] = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _, _ = stripped.partition("=")
                    k = k.strip()
                    if k in env:
                        new_lines.append(f"{k}={env[k]}")
                        written_keys.add(k)
                        continue
                new_lines.append(line)

            # Append any new keys not already in the file
            for k, v in env.items():
                if k not in written_keys:
                    new_lines.append(f"{k}={v}")

            env_file.write_text("\n".join(new_lines) + "\n")

    # -- guide ---------------------------------------------------------------

    def guide(self) -> str:
        return "cp .env.example .env && edit .env"

    @property
    def is_auto(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# TestSuiteStep — run pytest from the venv
# ---------------------------------------------------------------------------

@dataclass
class TestSuiteStep(SetupStep):
    """Run the full test suite via pytest from the project venv.

    Always returns MISSING from ``check()`` so the suite runs fresh every time.
    Only applies to the ``full`` profile.
    """

    project_dir: Path = field(default_factory=lambda: PROJECT_DIR)
    name: str = field(default="Test suite (pytest)", init=False)
    key: str = field(default="test_suite", init=False)
    profiles: set[str] = field(default_factory=lambda: {"full"}, init=False)

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        return Status.MISSING

    def install(self) -> bool:
        pytest_bin = self.project_dir / ".venv" / "bin" / "pytest"
        try:
            result = subprocess.run(
                [str(pytest_bin)],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
            )
            # Print summary line (last non-empty line of stdout)
            lines = [l for l in result.stdout.splitlines() if l.strip()]
            if lines:
                print(lines[-1])
            return result.returncode == 0
        except OSError:
            return False

    def guide(self) -> str:
        return "pytest"


# ---------------------------------------------------------------------------
# ServerVerifyStep — smoke-test jarvis-mcp startup
# ---------------------------------------------------------------------------

@dataclass
class ServerVerifyStep(SetupStep):
    """Smoke-test the MCP server by spawning ``jarvis-mcp`` briefly.

    Always returns MISSING from ``check()`` so the smoke test runs fresh.
    Applies to all profiles.
    """

    project_dir: Path = field(default_factory=lambda: PROJECT_DIR)
    name: str = field(default="Server verify (jarvis-mcp)", init=False)
    key: str = field(default="server_verify", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_ALL_PROFILES), init=False)

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        return Status.MISSING

    def install(self) -> bool:
        mcp_bin = self.project_dir / ".venv" / "bin" / "jarvis-mcp"
        try:
            proc = subprocess.Popen(
                [str(mcp_bin)],
                cwd=str(self.project_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                proc.wait(timeout=3)
                # Process exited within 3 seconds — failure if non-zero
                return proc.returncode == 0
            except subprocess.TimeoutExpired:
                # Still running after 3 seconds — success
                proc.terminate()
                proc.wait(timeout=5)
                return True
        except OSError:
            return False

    def guide(self) -> str:
        return "jarvis-mcp"


# ---------------------------------------------------------------------------
# Output formatting functions
# ---------------------------------------------------------------------------


def format_scan_line(name: str, status: Status) -> str:
    """Return a formatted scan result line.

    Examples::

        "  [ok] Python 3.13"
        "  [--] pip deps"
        "  [!!] perms"
    """
    return f"  {status.label} {name}"


def format_scan_summary(results: list[tuple[str, Status, bool, bool]]) -> str:
    """Return a one-line summary of scan results.

    Each element of *results* is ``(name, status, is_auto, is_manual)``.

    Buckets:

    * **auto-install** — status != OK and is_auto
    * **guided**       — status != OK and not is_auto and not is_manual
    * **manual**       — status != OK and is_manual
    * **already done** — status == OK

    Example output::

        "  4 auto-install  |  2 guided  |  2 manual  |  3 already done"
    """
    auto = 0
    guided = 0
    manual = 0
    done = 0

    for _name, status, is_auto, is_manual in results:
        if status == Status.OK:
            done += 1
        elif is_auto:
            auto += 1
        elif is_manual:
            manual += 1
        else:
            guided += 1

    parts = [
        f"{auto} auto-install",
        f"{guided} guided",
        f"{manual} manual",
        f"{done} already done",
    ]
    return "  " + "  |  ".join(parts)


def format_final_summary(
    completed: int,
    failed: int,
    manual_guides: list[str],
) -> str:
    """Return the final setup summary block.

    Sections (only included when relevant):

    * ``[ok] N steps configured successfully``
    * ``[!!] N failed``
    * ``Manual steps remaining:`` with a bulleted list
    * ``Quick start:`` with ``jarvis-mcp`` and ``pytest`` commands
    """
    lines: list[str] = []

    if completed > 0:
        lines.append(f"[ok] {completed} steps configured successfully")

    if failed > 0:
        lines.append(f"[!!] {failed} failed")

    if manual_guides:
        lines.append("")
        lines.append("Manual steps remaining:")
        for guide in manual_guides:
            lines.append(f"  - {guide}")

    lines.append("")
    lines.append("Quick start:")
    lines.append("  jarvis-mcp          # start MCP server")
    lines.append("  pytest              # run test suite")

    return "\n".join(lines)
