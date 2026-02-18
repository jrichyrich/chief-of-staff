# GitHub Private Repo Setup — Design

**Date:** 2026-02-17
**Goal:** Push project to a private GitHub repo without personal/instance-specific data.

## Decisions

- **Visibility:** Private repo
- **Git history:** Push existing commits as-is (no rewrite)
- **Data directory:** Gitignore all of `data/` with `.gitkeep` placeholder
- **Paths:** Templatize hardcoded `/Users/jasricha/...` with env vars

## Changes Required

### 1. .gitignore Overhaul

Replace current `.gitignore` with comprehensive version covering:
- `data/*` (all runtime data) with `!data/.gitkeep`
- `.DS_Store`, `uv.lock`, `*.mcpb`, `.mcp.json`

### 2. Path Templatization

| File | Change |
|------|--------|
| `scripts/inbox-monitor.sh` | `${JARVIS_PROJECT_DIR:-$HOME/Documents/GitHub/chief_of_staff}` |
| `scripts/jarvis-backup.sh` | Same + `${ONEDRIVE_BASE}` |
| `scripts/com.chg.*.plist` (4 files) | launchd `EnvironmentVariables` + `$HOME` references |
| `agent_configs/communications.yaml` | Relative or `$PROJECT_DIR` path |
| `agent_configs/security_metrics.yaml` | `$HOME`-based path |

### 3. New Files

- `.env.example` — Documents all required/optional environment variables
- `data/.gitkeep` — Preserves directory structure

### 4. Git Cleanup

- `git rm --cached` any tracked files that should now be ignored
- Commit all changes
- Create private repo on GitHub, add remote, push
