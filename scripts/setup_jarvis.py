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
from typing import List, Tuple

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
