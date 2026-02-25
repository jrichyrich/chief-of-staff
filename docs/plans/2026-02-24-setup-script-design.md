# Setup Script Design

**Date:** 2026-02-24
**Status:** Approved

## Overview

A setup script for Chief of Staff (Jarvis) that serves three audiences: personal convenience (fresh machine/clone), developer onboarding, and end-user installation. Uses a scan + walkthrough hybrid flow with profile-based feature selection.

## File Structure

| File | Purpose |
|------|---------|
| `setup.sh` | Bash bootstrapper (~40 lines). Checks for Python 3.11+, installs via Homebrew if missing, then execs `scripts/setup_jarvis.py` |
| `scripts/setup_jarvis.py` | Python main script. All logic. Zero non-stdlib dependencies (runs before pip install) |

## Usage

```bash
./setup.sh                      # Interactive, prompts for profile
./setup.sh --profile minimal    # Skip profile prompt
./setup.sh --profile full       # Everything
./setup.sh --check              # Non-interactive: scan and report only
./setup.sh --profile personal --check  # Scan a specific profile
```

## Profiles

| Profile | Audience | What it sets up |
|---------|----------|-----------------|
| `minimal` | End user / quick test | Core: venv, pip deps, `.env`, data dirs, verify `jarvis-mcp` starts |
| `personal` | Personal fresh clone | + Apple integrations, LaunchAgents, iMessage, Playwright/Teams |
| `full` | Developer / everything | + M365 bridge, dev deps, run test suite, all optional features |

## Step Model

Each setup step is a dataclass with three methods:

```python
@dataclass
class SetupStep:
    name: str           # "Virtual environment"
    key: str            # "venv"
    profiles: set       # {"minimal", "personal", "full"}

    def check(self) -> Status:   # OK, MISSING, ERROR
    def install(self) -> bool:   # Auto-install (safe things)
    def guide(self) -> str:      # Instructions for manual steps
```

Status values:

| Status | Meaning | Scan display | Action |
|--------|---------|------|--------|
| `OK` | Already configured | `[ok]` | Skip |
| `MISSING` | Needs setup | `[--]` (auto) or `[!!]` (manual) | Run `install()` or show `guide()` |
| `ERROR` | Something wrong | `[!!]` | Show `guide()` with diagnostic info |

## Steps (in execution order)

| # | Step | Profiles | Auto? |
|---|------|----------|-------|
| 1 | Python version check | all | n/a (handled by bash bootstrapper) |
| 2 | Virtual environment (.venv) | all | Yes — `python -m venv .venv` |
| 3 | Pip dependencies | all | Yes — `pip install -e ".[dev]"` |
| 4 | System deps (jq, sqlite3) | all | Guide — `brew install jq sqlite3` |
| 5 | .env configuration | all | Hybrid — generate from template, prompt for required values |
| 6 | Data directories | all | Yes — `mkdir -p data/{chroma,okr,webhook-inbox,playwright/profile}` |
| 7 | Playwright + Chromium | personal, full | Guide — `playwright install chromium` |
| 8 | LaunchAgents | personal, full | Yes — calls `./scripts/install-plists.sh` |
| 9 | iMessage reader permissions | personal, full | Guide — Full Disk Access instructions |
| 10 | macOS Calendar/Reminders perms | personal, full | Guide — permission grant instructions |
| 11 | M365 bridge detection | full | Guide — check `claude mcp list` |
| 12 | Run test suite | full | Yes — `pytest` with pass/fail summary |
| 13 | Verify MCP server starts | all | Yes — spawn `jarvis-mcp`, check it doesn't crash in 3s |

## Automation Tiers

- **Auto-install (safe/reversible):** venv creation, pip install, mkdir data dirs, call install-plists.sh, run tests, smoke-test server
- **Guided (system-level):** Homebrew packages, Playwright install, M365 bridge setup
- **Manual checklist (can't verify):** macOS Calendar/Reminders permissions, Full Disk Access for iMessage reader

## Interactive Flow

### Profile Selection (no --profile flag)

```
Welcome to Jarvis (Chief of Staff) Setup

Select a profile:
  [1] minimal   — Core: memory, agents, documents, MCP server
  [2] personal  — + Apple integrations, LaunchAgents, iMessage, Teams
  [3] full      — + M365 bridge, dev deps, test suite, all features

Choice [1/2/3]:
```

### Scan Phase

```
Scanning environment (profile: personal)...

  [ok] Python 3.13         [ok] Homebrew
  [ok] .venv exists         [--] pip deps outdated
  [--] .env missing         [ok] data/ dirs
  [--] Playwright           [--] LaunchAgents
  [!!] Calendar perms       [!!] Full Disk Access

  4 auto-install  |  2 guided  |  2 manual  |  3 already done

Press Enter to begin setup (or Ctrl+C to abort)...
```

### Auto-install Steps

```
[1/8] Installing pip dependencies...
      pip install -e ".[dev]" ... done (23 packages, 4.2s)
```

### Guided Steps

```
[5/8] Playwright + Chromium
      Not installed. Run this command:

        playwright install chromium

      Done? [Y/n/skip]:
```

### Manual Steps (collected for checklist)

```
[7/8] macOS Calendar permissions
      Cannot verify programmatically. After setup completes:
        1. Open System Settings > Privacy & Security > Calendars
        2. Enable access for your terminal app
      [noted for final checklist]
```

### Final Summary

```
Setup complete!

  [ok] 9 steps configured successfully
  [ok] MCP server verified — jarvis-mcp starts cleanly

  Manual steps remaining:
    [ ] Grant Calendar access: System Settings > Privacy > Calendars
    [ ] Grant Reminders access: System Settings > Privacy > Reminders
    [ ] Grant Full Disk Access for scripts/imessage-reader

  Quick start:
    jarvis-mcp              # Start the MCP server
    pytest                  # Run tests (1723 expected)
```

## .env Generation

**If `.env` exists:** Don't overwrite. Scan for required values, prompt for missing ones.

**If `.env` doesn't exist:** Copy `.env.example`, prompt for values based on profile:

| Variable | Profile | Prompt behavior |
|----------|---------|-----------------|
| `ANTHROPIC_API_KEY` | all | Required — won't continue without it |
| `JARVIS_IMESSAGE_SELF` | personal, full | Optional — prompt, Enter to skip |
| `JARVIS_DEFAULT_EMAIL_TO` | personal, full | Optional — prompt, Enter to skip |
| `JARVIS_ONEDRIVE_BASE` | full | Optional — prompt, Enter to skip |
| All others | — | Keep defaults from `.env.example` |

## Idempotency

No state file. Every `check()` detects current system state directly:

| Step | How check() detects completion |
|------|--------------------------------|
| venv | `.venv/bin/python` exists and is correct Python version |
| pip deps | `pip list --format=json` contains `jarvis` package |
| system deps | `which jq` and `which sqlite3` |
| .env | File exists + required keys have non-empty values |
| data dirs | All expected subdirectories exist |
| Playwright | `playwright --version` succeeds + chromium dir exists |
| LaunchAgents | Plist files exist in `~/Library/LaunchAgents/` |
| macOS perms | Can't verify — always shows in final checklist |
| M365 bridge | `claude mcp list` output contains Microsoft 365 |
| test suite | Runs fresh each time (never "already done") |
| MCP server | Runs fresh each time (quick smoke test) |

## --check Mode

Prints the scan phase only and exits with code 0 (all OK) or 1 (steps missing). No prompts, no installs.

## Relationship to Existing Artifacts

- **Orchestrates** `install-plists.sh` — calls it during LaunchAgents step
- **Uses** `.env.example` as template for `.env` generation
- **Complements** `setup-guide.md` — guide gets a "Quick Start" section pointing to the script; manual steps remain documented
- Does NOT replace or duplicate existing scripts

## Key Principles

- Bash bootstrapper + Python main (zero deps before pip install)
- Interactive by default, `--check` for non-interactive
- Tiered automation: auto for safe, guide for system-level, checklist for unverifiable
- Fully idempotent: detect state on every run, skip what's done
- Profile-based: minimal/personal/full
