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
import argparse
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
PROFILES = ("minimal", "personal", "full")


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
# PlaywrightStep — guided (user runs playwright install themselves)
# ---------------------------------------------------------------------------

_PERSONAL_FULL = {"personal", "full"}


@dataclass
class PlaywrightStep(SetupStep):
    """Ensure Playwright and its Chromium browser are installed.

    This is a *guided* step: the user must run ``playwright install chromium``
    themselves after pip-installing playwright.
    """

    name: str = field(default="Playwright browser", init=False)
    key: str = field(default="playwright", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_PERSONAL_FULL), init=False)

    _CACHE_DIRS: list[Path] = field(
        default_factory=lambda: [
            Path.home() / "Library" / "Caches" / "ms-playwright",
            Path.home() / ".cache" / "ms-playwright",
        ],
        init=False,
    )

    def check(self) -> Status:
        """MISSING if ``playwright`` binary not on PATH or no browser cache."""
        if shutil.which("playwright") is None:
            return Status.MISSING
        for cache_dir in self._CACHE_DIRS:
            if cache_dir.is_dir() and any(cache_dir.iterdir()):
                return Status.OK
        return Status.MISSING

    def guide(self) -> str:
        return "playwright install chromium"

    @property
    def is_auto(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# LaunchAgentsStep — auto (runs install-plists.sh)
# ---------------------------------------------------------------------------

@dataclass
class LaunchAgentsStep(SetupStep):
    """Install macOS LaunchAgent plist files for background daemons."""

    PLIST_LABELS = [
        "com.chg.inbox-monitor",
        "com.chg.jarvis-backup",
        "com.chg.alert-evaluator",
        "com.chg.imessage-daemon",
        "com.chg.scheduler-engine",
    ]

    project_dir: Path = field(default_factory=lambda: PROJECT_DIR)
    launch_agents_dir: Optional[Path] = None

    name: str = field(default="LaunchAgents", init=False)
    key: str = field(default="launch_agents", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_PERSONAL_FULL), init=False)

    def __post_init__(self) -> None:
        if self.launch_agents_dir is None:
            self.launch_agents_dir = Path.home() / "Library" / "LaunchAgents"

    def check(self) -> Status:
        """OK if all plist files exist in the LaunchAgents directory."""
        assert self.launch_agents_dir is not None  # satisfy type checker
        for label in self.PLIST_LABELS:
            plist_path = self.launch_agents_dir / f"{label}.plist"
            if not plist_path.exists():
                return Status.MISSING
        return Status.OK

    def install(self) -> bool:
        """Run ``scripts/install-plists.sh`` with JARVIS_PROJECT_DIR."""
        script = self.project_dir / "scripts" / "install-plists.sh"
        env = os.environ.copy()
        env["JARVIS_PROJECT_DIR"] = str(self.project_dir)
        try:
            subprocess.run(
                ["bash", str(script)],
                check=True,
                capture_output=True,
                env=env,
            )
            return True
        except (subprocess.CalledProcessError, OSError):
            return False

    def guide(self) -> str:
        return "./scripts/install-plists.sh"

    @property
    def is_auto(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# IMessagePermsStep — manual (macOS Full Disk Access)
# ---------------------------------------------------------------------------

@dataclass
class IMessagePermsStep(SetupStep):
    """Grant Full Disk Access to the iMessage reader script.

    This is a *manual* step: the user must open System Settings and
    add the appropriate binary to the Full Disk Access list.
    """

    name: str = field(default="iMessage permissions", init=False)
    key: str = field(default="imessage_perms", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_PERSONAL_FULL), init=False)

    def check(self) -> Status:
        """Always MISSING — cannot programmatically verify Full Disk Access."""
        return Status.MISSING

    def guide(self) -> str:
        return (
            "Grant Full Disk Access to the iMessage reader:\n"
            "  1. Open System Settings > Privacy & Security > Full Disk Access\n"
            "  2. Click '+' and add scripts/imessage-reader\n"
            "  3. Restart your terminal"
        )

    @property
    def is_manual(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# CalendarPermsStep — manual (Calendar & Reminders)
# ---------------------------------------------------------------------------

@dataclass
class CalendarPermsStep(SetupStep):
    """Grant Calendar and Reminders access to the Python process.

    This is a *manual* step: the user must approve the permission prompts
    or add the binary in System Settings.
    """

    name: str = field(default="Calendar & Reminders permissions", init=False)
    key: str = field(default="calendar_perms", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_PERSONAL_FULL), init=False)

    def check(self) -> Status:
        """Always MISSING — cannot programmatically verify TCC permissions."""
        return Status.MISSING

    def guide(self) -> str:
        return (
            "Grant Calendar and Reminders access:\n"
            "  1. Open System Settings > Privacy & Security > Calendars\n"
            "  2. Ensure your terminal / Python is allowed\n"
            "  3. Repeat for Privacy & Security > Reminders"
        )

    @property
    def is_manual(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# JarvisAppStep — auto (creates /Applications/Jarvis.app)
# ---------------------------------------------------------------------------

_LAUNCH_SH_ITERM2 = r"""#!/bin/bash
# Launch iTerm2 with Claude Code in chief_of_staff project
# Uses "Jarvis" profile (frosted glass Material theme)

osascript <<'APPLESCRIPT'
tell application "iTerm2"
    activate

    -- Create window with the Jarvis profile
    set newWindow to (create window with profile "Jarvis")

    tell current session of newWindow
        set name to "Jarvis — Chief of Staff"
        write text "cd {project_dir} && clear && {banner_path} && sleep 2 && {claude_bin} --dangerously-skip-permissions --teammate-mode tmux"
    end tell
end tell
APPLESCRIPT
"""

_LAUNCH_SH_TERMINAL = r"""#!/bin/bash
# Launch Terminal.app with Claude Code in chief_of_staff project

osascript <<'APPLESCRIPT'
tell application "Terminal"
    activate
    set jarvisCmd to "cd {project_dir} && clear && {banner_path} && sleep 2 && {claude_bin} --dangerously-skip-permissions --teammate-mode tmux"
    do script jarvisCmd
    -- Set the window title
    set custom title of front window to "Jarvis — Chief of Staff"
end tell
APPLESCRIPT
"""

_INFO_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launch.sh</string>
    <key>CFBundleIdentifier</key>
    <string>com.jarvis.chiefofstaff</string>
    <key>CFBundleName</key>
    <string>Jarvis</string>
    <key>CFBundleDisplayName</key>
    <string>Jarvis</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSUIElement</key>
    <true/>
    <key>LSBackgroundOnly</key>
    <false/>
</dict>
</plist>
"""


def _detect_terminal() -> str:
    """Detect the user's preferred terminal emulator.

    Returns 'iterm2' if iTerm.app exists, otherwise 'terminal'.
    """
    iterm_paths = [
        Path("/Applications/iTerm.app"),
        Path.home() / "Applications" / "iTerm.app",
    ]
    for p in iterm_paths:
        if p.exists():
            return "iterm2"
    return "terminal"


@dataclass
class JarvisAppStep(SetupStep):
    """Create /Applications/Jarvis.app with icon, terminal profile, and banner.

    Builds a macOS .app bundle that launches Claude Code in the project
    directory via the user's terminal (iTerm2 if installed, Terminal.app
    otherwise). Includes a custom icon, Material-theme iTerm2 profile
    (when applicable), and ASCII art splash screen.
    """

    project_dir: Path = field(default_factory=lambda: PROJECT_DIR)
    app_path: Path = field(default_factory=lambda: Path("/Applications/Jarvis.app"))

    name: str = field(default="Jarvis.app launcher", init=False)
    key: str = field(default="jarvis_app", init=False)
    profiles: set[str] = field(default_factory=lambda: set(_ALL_PROFILES), init=False)

    @property
    def is_auto(self) -> bool:
        return True

    def check(self) -> Status:
        """OK if Jarvis.app exists with its key files."""
        launch_sh = self.app_path / "Contents" / "MacOS" / "launch.sh"
        icon = self.app_path / "Contents" / "Resources" / "AppIcon.icns"
        if launch_sh.exists() and icon.exists():
            return Status.OK
        return Status.MISSING

    def install(self) -> bool:
        """Build the app bundle, icon, terminal profile, and banner."""
        try:
            terminal = _detect_terminal()
            print(f"  Detected terminal: {terminal}")
            self._create_app_bundle(terminal)
            self._convert_icon()
            self._install_banner(terminal)
            if terminal == "iterm2":
                self._install_iterm2_profile()
                self._generate_background_image()
            self._register_app()
            return True
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"  Error: {exc}")
            return False

    def _create_app_bundle(self, terminal: str) -> None:
        """Create the .app directory structure, Info.plist, and launch.sh."""
        macos_dir = self.app_path / "Contents" / "MacOS"
        macos_dir.mkdir(parents=True, exist_ok=True)

        # Info.plist
        plist_path = self.app_path / "Contents" / "Info.plist"
        plist_path.write_text(_INFO_PLIST_TEMPLATE)

        # Find claude binary
        claude_bin = shutil.which("claude") or "/opt/homebrew/bin/claude"
        # Resolve to actual binary (not shell function)
        try:
            result = subprocess.run(
                ["which", "claude"], capture_output=True, text=True, check=True,
            )
            resolved = result.stdout.strip()
            if resolved:
                claude_bin = resolved
        except (subprocess.CalledProcessError, OSError):
            pass

        # Banner path — stored alongside other jarvis config
        config_dir = Path.home() / ".config" / "jarvis"
        banner_path = config_dir / "jarvis-banner.sh"

        # Select the right launch template
        template = _LAUNCH_SH_ITERM2 if terminal == "iterm2" else _LAUNCH_SH_TERMINAL

        # launch.sh (templated with actual paths)
        launch_sh_path = macos_dir / "launch.sh"
        launch_sh_path.write_text(
            template.format(
                project_dir=self.project_dir,
                banner_path=banner_path,
                claude_bin=claude_bin,
            )
        )
        launch_sh_path.chmod(0o755)

    def _convert_icon(self) -> None:
        """Convert assets/jarvis-icon.png to .icns and install it."""
        src_png = self.project_dir / "assets" / "jarvis-icon.png"
        if not src_png.exists():
            print(f"  Warning: {src_png} not found, skipping icon")
            return

        resources_dir = self.app_path / "Contents" / "Resources"
        resources_dir.mkdir(parents=True, exist_ok=True)

        iconset = Path("/tmp/JarvisAppIcon.iconset")
        iconset.mkdir(parents=True, exist_ok=True)

        sizes = [
            (16, "icon_16x16.png"),
            (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"),
            (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"),
            (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"),
            (512, "icon_256x256@2x.png"),
            (512, "icon_512x512.png"),
            (1024, "icon_512x512@2x.png"),
        ]

        for size, filename in sizes:
            subprocess.run(
                ["sips", "-z", str(size), str(size), str(src_png),
                 "--out", str(iconset / filename)],
                capture_output=True, check=True,
            )

        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset),
             "-o", str(resources_dir / "AppIcon.icns")],
            capture_output=True, check=True,
        )

        # Cleanup
        shutil.rmtree(iconset, ignore_errors=True)

    def _install_iterm2_profile(self) -> None:
        """Copy the iTerm2 dynamic profile, injecting the background image path."""
        src = self.project_dir / "assets" / "iterm2-profile.json"
        if not src.exists():
            print(f"  Warning: {src} not found, skipping iTerm2 profile")
            return

        dest_dir = Path.home() / "Library" / "Application Support" / "iTerm2" / "DynamicProfiles"
        dest_dir.mkdir(parents=True, exist_ok=True)

        bg_image_path = Path.home() / ".config" / "jarvis" / "jarvis-bg.png"

        profile_text = src.read_text()
        # Inject background image path into the profile
        # Insert after the "Blend" line
        inject = f'      "Background Image Location": "{bg_image_path}",\n'
        profile_text = profile_text.replace(
            '      "Background Image Is Tiled": false,',
            inject + '      "Background Image Is Tiled": false,',
        )

        (dest_dir / "Jarvis.json").write_text(profile_text)

    def _install_banner(self, terminal: str) -> None:
        """Copy the banner script to ~/.config/jarvis/."""
        src = self.project_dir / "assets" / "jarvis-banner.sh"
        if not src.exists():
            print(f"  Warning: {src} not found, skipping banner")
            return

        config_dir = Path.home() / ".config" / "jarvis"
        config_dir.mkdir(parents=True, exist_ok=True)

        dest = config_dir / "jarvis-banner.sh"
        shutil.copy2(src, dest)
        dest.chmod(0o755)

        # Also install to legacy iterm2 path if iTerm2 is the terminal
        if terminal == "iterm2":
            legacy_dir = Path.home() / ".config" / "iterm2"
            legacy_dir.mkdir(parents=True, exist_ok=True)
            legacy_dest = legacy_dir / "jarvis-banner.sh"
            shutil.copy2(src, legacy_dest)
            legacy_dest.chmod(0o755)

    def _generate_background_image(self) -> None:
        """Generate the dark teal gradient background image for iTerm2."""
        config_dir = Path.home() / ".config" / "jarvis"
        config_dir.mkdir(parents=True, exist_ok=True)
        bg_path = config_dir / "jarvis-bg.png"

        if bg_path.exists():
            return  # Don't regenerate if already present

        try:
            from PIL import Image, ImageDraw

            width, height = 2560, 1600
            img = Image.new("RGB", (width, height))
            draw = ImageDraw.Draw(img)
            for y in range(height):
                ratio = y / height
                r = int(26 + (15 - 26) * ratio)
                g = int(43 + (30 - 43) * ratio)
                b = int(52 + (38 - 52) * ratio)
                draw.line([(0, y), (width, y)], fill=(r, g, b))
            img.save(str(bg_path))
        except ImportError:
            # Fallback: create a 1x1 dark teal PNG via sips
            subprocess.run(
                ["sips", "-z", "1600", "2560", "-s", "format", "png",
                 "--out", str(bg_path)],
                capture_output=True,
            )
            print("  Warning: Pillow not installed, background image may be missing")

    def _register_app(self) -> None:
        """Register the app with Launch Services for Spotlight indexing."""
        lsregister = (
            "/System/Library/Frameworks/CoreServices.framework/"
            "Frameworks/LaunchServices.framework/Support/lsregister"
        )
        subprocess.run(
            [lsregister, "-f", str(self.app_path)],
            capture_output=True,
        )
        # Touch the app to invalidate Finder icon cache
        self.app_path.touch()

    def guide(self) -> str:
        terminal = _detect_terminal()
        lines = ["python scripts/setup_jarvis.py  # will create /Applications/Jarvis.app"]
        if terminal == "terminal":
            lines.append(
                "  Note: iTerm2 not found — will use Terminal.app. "
                "For the full experience (custom theme, transparency, blur), "
                "install iTerm2: brew install --cask iterm2"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# M365BridgeStep — guided (Claude Desktop M365 connector)
# ---------------------------------------------------------------------------

@dataclass
class M365BridgeStep(SetupStep):
    """Verify that the Claude M365 MCP connector is configured.

    Checks by running ``claude mcp list`` and looking for a Microsoft 365
    entry in the output.
    """

    name: str = field(default="M365 bridge", init=False)
    key: str = field(default="m365_bridge", init=False)
    profiles: set[str] = field(default_factory=lambda: {"full"}, init=False)

    def check(self) -> Status:
        """OK if ``claude mcp list`` output contains a Microsoft 365 reference."""
        claude_bin = shutil.which("claude")
        if claude_bin is None:
            return Status.MISSING
        try:
            result = subprocess.run(
                [claude_bin, "mcp", "list"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            output = (result.stdout + result.stderr).lower()
            if "microsoft" in output or "365" in output:
                return Status.OK
            return Status.MISSING
        except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
            return Status.ERROR

    def guide(self) -> str:
        return (
            "Set up the Claude M365 bridge:\n"
            "  1. Install the Claude CLI: npm install -g @anthropic-ai/claude-cli\n"
            "  2. Run: claude mcp add microsoft-365\n"
            "  3. Follow the authentication prompts"
        )

    @property
    def is_auto(self) -> bool:
        return False


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


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Parameters
    ----------
    argv:
        Argument list (defaults to ``sys.argv[1:]``).

    Returns
    -------
    argparse.Namespace
        Parsed arguments with ``.profile`` and ``.check`` attributes.
    """
    parser = argparse.ArgumentParser(
        description="Jarvis (Chief of Staff) setup and environment checker.",
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
        default=False,
        help="Scan-only mode: report status without making changes",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Interactive profile prompt
# ---------------------------------------------------------------------------


def prompt_profile() -> str:
    """Interactively prompt the user to choose a setup profile.

    Displays a welcome message with three numbered options and loops
    until a valid selection (1/2/3 or profile name) is received.

    Returns
    -------
    str
        One of ``"minimal"``, ``"personal"``, or ``"full"``.
    """
    print()
    print("Welcome to Jarvis Setup")
    print("=======================")
    print()
    print("Choose a profile:")
    print("  1) minimal  — venv, pip, data dirs, env config, server verify")
    print("  2) personal — adds Playwright, LaunchAgents, iMessage & Calendar perms")
    print("  3) full     — adds M365 bridge, test suite")
    print()

    _map = {"1": "minimal", "2": "personal", "3": "full"}

    while True:
        choice = input("Profile [1/2/3]: ").strip().lower()
        if choice in _map:
            return _map[choice]
        if choice in PROFILES:
            return choice
        print(f"  Invalid choice: {choice!r}. Enter 1, 2, 3 or a profile name.")


# ---------------------------------------------------------------------------
# Step builder
# ---------------------------------------------------------------------------


def build_steps(
    project_dir: Path | None = None,
    profile: str = "full",
    interactive: bool = True,
) -> list[SetupStep]:
    """Build the ordered list of all setup steps.

    Parameters
    ----------
    project_dir:
        Project root directory (defaults to ``PROJECT_DIR``).
    profile:
        The selected profile (used to configure profile-aware steps).
    interactive:
        Whether the session is interactive (affects ``EnvConfigStep``).

    Returns
    -------
    list[SetupStep]
        Steps in dependency order: venv -> pip -> ... -> server_verify.
    """
    if project_dir is None:
        project_dir = PROJECT_DIR

    return [
        VenvStep(project_dir=project_dir),
        PipStep(project_dir=project_dir),
        SystemDepsStep(),
        EnvConfigStep(project_dir=project_dir, _profile=profile, interactive=interactive),
        DataDirsStep(project_dir=project_dir),
        JarvisAppStep(project_dir=project_dir),
        PlaywrightStep(),
        LaunchAgentsStep(project_dir=project_dir),
        IMessagePermsStep(),
        CalendarPermsStep(),
        M365BridgeStep(),
        TestSuiteStep(project_dir=project_dir),
        ServerVerifyStep(project_dir=project_dir),
    ]


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def run_setup(args: argparse.Namespace) -> int:
    """Run the full setup workflow.

    1. Determine the profile (from ``--profile`` flag or interactive prompt).
    2. Build steps and run the scan phase.
    3. In ``--check`` mode, return 0 if all OK, 1 if any missing.
    4. Otherwise, walk through actionable steps: auto-install, guided, or
       manual — then print the final summary.

    Returns
    -------
    int
        Exit code: 0 on success, 1 if ``--check`` found problems.
    """
    # -- Determine profile ---------------------------------------------------
    profile: str = args.profile if args.profile else prompt_profile()
    interactive = not args.check

    # -- Build steps and scan -----------------------------------------------
    steps = build_steps(profile=profile, interactive=interactive)
    runner = StepRunner(steps=steps, profile=profile, interactive=interactive)
    results = runner.scan()

    # -- Print scan results --------------------------------------------------
    print()
    print(f"Scan results ({profile} profile):")
    for step, status in results:
        print(format_scan_line(step.name, status))

    summary_data = [
        (step.name, status, step.is_auto, step.is_manual)
        for step, status in results
    ]
    print()
    print(format_scan_summary(summary_data))
    print()

    # -- Check mode: report and exit ----------------------------------------
    if args.check:
        has_missing = any(status != Status.OK for _, status in results)
        return 1 if has_missing else 0

    # -- Walkthrough phase ---------------------------------------------------
    completed = 0
    failed = 0
    manual_guides: list[str] = []

    for step, status in results:
        if status == Status.OK:
            completed += 1
            continue

        print(f"\n--- {step.name} ---")

        if step.is_manual:
            guide = step.guide()
            print(guide)
            manual_guides.append(step.name)
            continue

        if step.is_auto:
            print(f"  Installing {step.name}...")
            if step.install():
                print(f"  Done.")
                completed += 1
            else:
                print(f"  FAILED.")
                failed += 1
            continue

        # Guided step
        guide = step.guide()
        print(guide)
        if interactive:
            while True:
                answer = input("  Done? [Y/n/skip]: ").strip().lower()
                if answer in ("", "y", "yes"):
                    new_status = step.check()
                    if new_status == Status.OK:
                        print("  Verified.")
                        completed += 1
                    else:
                        print("  Still not detected — noted for follow-up.")
                        manual_guides.append(step.name)
                    break
                elif answer in ("n", "no"):
                    print("  Try again when ready.")
                    continue
                elif answer == "skip":
                    print("  Skipped.")
                    manual_guides.append(step.name)
                    break
                else:
                    print("  Enter Y, n, or skip.")
        else:
            manual_guides.append(step.name)

    # -- Final summary -------------------------------------------------------
    print()
    print(format_final_summary(completed, failed, manual_guides))

    return 0


def main() -> None:
    """Entry point: parse arguments and run setup."""
    args = parse_args()
    sys.exit(run_setup(args))


if __name__ == "__main__":
    main()
