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
from dataclasses import dataclass
from typing import List, Tuple


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
