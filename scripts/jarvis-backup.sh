#!/bin/bash
# ============================================================================
# jarvis-backup.sh -- Daily backup of all Jarvis/Chief of Staff data to OneDrive
# ============================================================================
# Backs up: memory database, ChromaDB, documents, agent configs, scripts,
# inbox state, and hooks. Uses sqlite3 .backup for safe DB snapshots and
# rsync for everything else. Keeps 14 days of database snapshots.
#
# Usage:  ./jarvis-backup.sh [--dry-run] [--verbose] [--restore]
# Schedule: Daily via launchd (com.chg.jarvis-backup.plist)
# ============================================================================

set -euo pipefail

# --- Configuration -----------------------------------------------------------

ONEDRIVE_BASE="${JARVIS_ONEDRIVE_BASE:-$HOME/Library/CloudStorage/OneDrive-CHGHealthcare}"
BACKUP_DIR="$ONEDRIVE_BASE/Jarvis-Backup"
SNAPSHOT_DIR="$BACKUP_DIR/snapshots"
PROJECT_DIR="${JARVIS_PROJECT_DIR:-$HOME/Documents/GitHub/chief_of_staff}"
JARVIS_DOCS="$HOME/Documents/Jarvis"
LOG_FILE="$PROJECT_DIR/data/backup.log"
DATE_STAMP=$(date '+%Y-%m-%d')
SNAPSHOT_RETENTION_DAYS=14
ERRORS=0

# Parse flags
DRY_RUN=false
VERBOSE=false
RESTORE=false
for arg in "$@"; do
    case $arg in
        --dry-run)  DRY_RUN=true ;;
        --verbose)  VERBOSE=true ;;
        --restore)  RESTORE=true ;;
    esac
done

RSYNC_OPTS="-av --delete"
if $DRY_RUN; then
    RSYNC_OPTS="$RSYNC_OPTS --dry-run"
fi

# --- Functions ---------------------------------------------------------------

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

log() {
    local msg="[$(timestamp)] $1"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

log_section() {
    log "--- $1 ---"
}

log_error() {
    log "ERROR: $1"
    ERRORS=$((ERRORS + 1))
}

escape_sql_value() {
    printf '%s' "$1" | sed "s/'/''/g"
}

escape_osascript() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/'"$(printf '\n')"'/\\n/g' -e 's/'"$(printf '\r')"'/\\r/g' -e 's/'"$(printf '\t')"'/\\t/g'
}

notify_failure() {
    local reason="$1"
    local escaped_reason
    escaped_reason="$(escape_osascript "$reason")"
    # macOS notification (best-effort -- may not work from launchd on all macOS versions)
    osascript -e "display notification \"$escaped_reason\" with title \"Jarvis Backup FAILED\" sound name \"Basso\"" 2>/dev/null || true
    # Store failure in Jarvis memory for later querying
    local escaped_sql_reason
    escaped_sql_reason="$(escape_sql_value "$reason")"
    sqlite3 "$PROJECT_DIR/data/memory.db" \
        "INSERT OR REPLACE INTO facts (category, key, value, confidence) VALUES ('work', 'backup_last_failure', '$(date +%Y-%m-%d): $escaped_sql_reason', 1.0);" 2>/dev/null || true
}

notify_success() {
    local summary="$1"
    local escaped_summary
    escaped_summary="$(escape_osascript "$summary")"
    osascript -e "display notification \"$escaped_summary\" with title \"Jarvis Backup\" subtitle \"Completed successfully\"" 2>/dev/null || true
    # Update last successful backup in memory
    local escaped_sql_summary
    escaped_sql_summary="$(escape_sql_value "$summary")"
    sqlite3 "$PROJECT_DIR/data/memory.db" \
        "INSERT OR REPLACE INTO facts (category, key, value, confidence) VALUES ('work', 'backup_last_success', '$(date +%Y-%m-%d): $escaped_sql_summary', 1.0);" 2>/dev/null || true
}

verify_sqlite() {
    local db_path="$1"
    local label="$2"
    if [ ! -s "$db_path" ]; then
        log_error "$label backup is empty or missing!"
        return 1
    fi
    local check
    check=$(sqlite3 "$db_path" "PRAGMA quick_check;" 2>&1)
    if [ "$check" != "ok" ]; then
        log_error "$label backup failed integrity check: $check"
        return 1
    fi
    log "$label integrity verified (quick_check: ok)"
    return 0
}

# --- Restore mode ------------------------------------------------------------

if $RESTORE; then
    echo ""
    echo "========== Jarvis Restore =========="
    echo ""
    echo "This will restore from: $BACKUP_DIR"
    echo "Into:                   $PROJECT_DIR"
    echo "And:                    $JARVIS_DOCS"
    echo ""
    echo "IMPORTANT: Stop all running Jarvis processes first!"
    echo "  - Kill any 'chief' CLI sessions"
    echo "  - Kill any 'chief-mcp' server processes"
    echo "  - Unload inbox monitor: launchctl unload ~/Library/LaunchAgents/com.chg.inbox-monitor.plist"
    echo ""

    if $DRY_RUN; then
        echo "[DRY RUN] Would restore the following:"
        echo "  1. memory.db (SQLite .backup)"
        echo "  2. ChromaDB vector store (SQLite .backup + rsync)"
        echo "  3. Inbox state (inbox-processed.json, inbox-log.md)"
        echo "  3b. Calendar routing database"
        echo "  3c. iMessage thread profiles database"
        echo "  3d. OKR snapshots"
        echo "  3e. Webhook inbox"
        echo "  4. Document library (~Documents/Jarvis/)"
        echo "  5. Agent configs (YAML files)"
        echo "  6. Scripts"
        echo "  7. Hooks"
        echo "  8. Config files (config.py, .mcp.json, manifest.json, pyproject.toml, CLAUDE.md)"
        echo ""
        echo "Run without --dry-run to execute."
        exit 0
    fi

    read -p "Proceed with restore? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Restore cancelled."
        exit 0
    fi

    echo ""
    # 1. Memory database
    if [ -f "$BACKUP_DIR/data/memory.db" ]; then
        cp "$BACKUP_DIR/data/memory.db" "$PROJECT_DIR/data/memory.db"
        echo "[OK] memory.db restored"
    fi

    # 2. ChromaDB
    if [ -d "$BACKUP_DIR/data/chroma" ]; then
        rsync -av "$BACKUP_DIR/data/chroma/" "$PROJECT_DIR/data/chroma/"
        echo "[OK] ChromaDB restored"
    fi

    # 3. Inbox state
    for f in inbox-processed.json inbox-log.md; do
        if [ -f "$BACKUP_DIR/data/$f" ]; then
            cp "$BACKUP_DIR/data/$f" "$PROJECT_DIR/data/$f"
            echo "[OK] $f restored"
        fi
    done

    # 3b. Calendar routing database
    if [ -f "$BACKUP_DIR/data/calendar-routing.db" ]; then
        cp "$BACKUP_DIR/data/calendar-routing.db" "$PROJECT_DIR/data/calendar-routing.db"
        echo "[OK] calendar-routing.db restored"
    fi

    # 3c. iMessage thread profiles
    if [ -f "$BACKUP_DIR/data/imessage-thread-profiles.db" ]; then
        cp "$BACKUP_DIR/data/imessage-thread-profiles.db" "$PROJECT_DIR/data/imessage-thread-profiles.db"
        echo "[OK] imessage-thread-profiles.db restored"
    fi

    # 3d. OKR snapshots
    if [ -d "$BACKUP_DIR/data/okr" ]; then
        mkdir -p "$PROJECT_DIR/data/okr"
        rsync -av "$BACKUP_DIR/data/okr/" "$PROJECT_DIR/data/okr/"
        echo "[OK] OKR snapshots restored"
    fi

    # 3e. Webhook inbox
    if [ -d "$BACKUP_DIR/data/webhook-inbox" ]; then
        mkdir -p "$PROJECT_DIR/data/webhook-inbox"
        rsync -av "$BACKUP_DIR/data/webhook-inbox/" "$PROJECT_DIR/data/webhook-inbox/"
        echo "[OK] Webhook inbox restored"
    fi

    # 4. Document library
    if [ -d "$BACKUP_DIR/documents" ]; then
        rsync -av "$BACKUP_DIR/documents/" "$JARVIS_DOCS/"
        echo "[OK] Document library restored"
    fi

    # 5. Agent configs
    if [ -d "$BACKUP_DIR/agent_configs" ]; then
        rsync -av "$BACKUP_DIR/agent_configs/" "$PROJECT_DIR/agent_configs/"
        echo "[OK] Agent configs restored"
    fi

    # 6. Scripts
    if [ -d "$BACKUP_DIR/scripts" ]; then
        rsync -av "$BACKUP_DIR/scripts/" "$PROJECT_DIR/scripts/"
        echo "[OK] Scripts restored"
    fi

    # 7. Hooks
    if [ -d "$BACKUP_DIR/hooks" ]; then
        rsync -av "$BACKUP_DIR/hooks/" "$PROJECT_DIR/hooks/"
        echo "[OK] Hooks restored"
    fi

    # 8. Config files
    for f in config.py .mcp.json manifest.json pyproject.toml CLAUDE.md; do
        if [ -f "$BACKUP_DIR/$f" ]; then
            cp "$BACKUP_DIR/$f" "$PROJECT_DIR/$f"
            echo "[OK] $f restored"
        fi
    done

    echo ""
    echo "========== Restore Complete =========="
    echo ""
    echo "Next steps:"
    echo "  1. Reload inbox monitor: launchctl load ~/Library/LaunchAgents/com.chg.inbox-monitor.plist"
    echo "  2. Start Jarvis: chief or chief-mcp"
    echo "  3. Verify: jarvis, what do you know about me?"
    exit 0
fi

# --- Pre-flight checks -------------------------------------------------------

if [ ! -d "$ONEDRIVE_BASE" ]; then
    # OneDrive may not be mounted yet after wake — wait and retry once
    log "OneDrive not found at $ONEDRIVE_BASE -- waiting 60s for mount..."
    sleep 60
    if [ ! -d "$ONEDRIVE_BASE" ]; then
        log_error "OneDrive still not found at $ONEDRIVE_BASE after retry"
        notify_failure "OneDrive not mounted"
        exit 1
    fi
    log "OneDrive mounted after retry"
fi

# --- Log rotation (keep under 1000 lines) ------------------------------------

if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE" | tr -d ' ')" -gt 1000 ]; then
    mv "$LOG_FILE" "$LOG_FILE.old"
    log "Log rotated (previous saved as backup.log.old)"
fi

if $DRY_RUN; then
    log "DRY RUN -- no files will be modified"
fi

log "========== Jarvis Backup Started =========="

# Create backup directory structure
if ! $DRY_RUN; then
    mkdir -p "$BACKUP_DIR"/{data,documents,agent_configs,scripts,hooks}
    mkdir -p "$SNAPSHOT_DIR/$DATE_STAMP"
fi

# --- 1. Memory Database (safe SQLite backup) ---------------------------------

log_section "Memory Database"
MEMORY_DB="$PROJECT_DIR/data/memory.db"
BACKUP_DB="$BACKUP_DIR/data/memory.db"
SNAPSHOT_MEMORY="$SNAPSHOT_DIR/$DATE_STAMP/memory.db"

if [ -f "$MEMORY_DB" ]; then
    if $DRY_RUN; then
        log "Would backup memory.db via sqlite3 .backup"
    else
        # Flush WAL to minimize SQLITE_BUSY risk
        sqlite3 "$MEMORY_DB" "PRAGMA wal_checkpoint(PASSIVE);" 2>/dev/null || true
        # Latest copy (overwritten daily)
        sqlite3 "$MEMORY_DB" ".backup '$BACKUP_DB'"
        # Dated snapshot for point-in-time recovery
        sqlite3 "$MEMORY_DB" ".backup '$SNAPSHOT_MEMORY'"
        # Verify both copies
        verify_sqlite "$BACKUP_DB" "memory.db (latest)"
        verify_sqlite "$SNAPSHOT_MEMORY" "memory.db (snapshot $DATE_STAMP)"
        log "memory.db backed up ($(du -h "$BACKUP_DB" | cut -f1))"
    fi
else
    log "WARN: memory.db not found at $MEMORY_DB"
fi

# --- 2. ChromaDB Vector Store ------------------------------------------------

log_section "ChromaDB Vector Store"
CHROMA_SRC="$PROJECT_DIR/data/chroma"
CHROMA_DST="$BACKUP_DIR/data/chroma"
SNAPSHOT_CHROMA="$SNAPSHOT_DIR/$DATE_STAMP/chroma.sqlite3"

if [ -d "$CHROMA_SRC" ]; then
    CHROMA_SQLITE="$CHROMA_SRC/chroma.sqlite3"
    if [ -f "$CHROMA_SQLITE" ]; then
        if $DRY_RUN; then
            log "Would backup chroma.sqlite3 via sqlite3 .backup"
        else
            mkdir -p "$CHROMA_DST"
            # Flush WAL
            sqlite3 "$CHROMA_SQLITE" "PRAGMA wal_checkpoint(PASSIVE);" 2>/dev/null || true
            # Latest copy
            sqlite3 "$CHROMA_SQLITE" ".backup '$CHROMA_DST/chroma.sqlite3'"
            # Dated snapshot
            sqlite3 "$CHROMA_SQLITE" ".backup '$SNAPSHOT_CHROMA'"
            # Verify
            verify_sqlite "$CHROMA_DST/chroma.sqlite3" "chroma.sqlite3 (latest)"
            verify_sqlite "$SNAPSHOT_CHROMA" "chroma.sqlite3 (snapshot $DATE_STAMP)"
            log "chroma.sqlite3 backed up"
        fi
    fi

    # rsync the HNSW index and other binary files (exclude the sqlite we already backed up)
    rsync $RSYNC_OPTS --exclude='chroma.sqlite3' "$CHROMA_SRC/" "$CHROMA_DST/" 2>&1 | \
        { if $VERBOSE; then cat; else tail -1; fi } >> "$LOG_FILE"
    log "ChromaDB vector store synced ($(du -sh "$CHROMA_DST" 2>/dev/null | cut -f1))"
else
    log "WARN: ChromaDB not found at $CHROMA_SRC"
fi

# --- 3. Inbox State ----------------------------------------------------------

log_section "Inbox State"
for f in inbox-processed.json inbox-log.md; do
    SRC="$PROJECT_DIR/data/$f"
    if [ -f "$SRC" ]; then
        if ! $DRY_RUN; then
            cp "$SRC" "$BACKUP_DIR/data/$f"
        fi
        log "$f backed up"
    fi
done

# --- 3b. Calendar Routing Database -------------------------------------------

log_section "Calendar Routing Database"
CAL_ROUTING_DB="$PROJECT_DIR/data/calendar-routing.db"
BACKUP_CAL_ROUTING="$BACKUP_DIR/data/calendar-routing.db"
SNAPSHOT_CAL_ROUTING="$SNAPSHOT_DIR/$DATE_STAMP/calendar-routing.db"

if [ -f "$CAL_ROUTING_DB" ]; then
    if $DRY_RUN; then
        log "Would backup calendar-routing.db via sqlite3 .backup"
    else
        sqlite3 "$CAL_ROUTING_DB" "PRAGMA wal_checkpoint(PASSIVE);" 2>/dev/null || true
        sqlite3 "$CAL_ROUTING_DB" ".backup '$BACKUP_CAL_ROUTING'"
        sqlite3 "$CAL_ROUTING_DB" ".backup '$SNAPSHOT_CAL_ROUTING'"
        verify_sqlite "$BACKUP_CAL_ROUTING" "calendar-routing.db (latest)"
        log "calendar-routing.db backed up ($(du -h "$BACKUP_CAL_ROUTING" | cut -f1))"
    fi
else
    log "SKIP: calendar-routing.db not found (M365 bridge not used)"
fi

# --- 3c. iMessage Thread Profiles Database -----------------------------------

log_section "iMessage Thread Profiles"
THREAD_PROFILES_DB="$PROJECT_DIR/data/imessage-thread-profiles.db"
BACKUP_THREAD_PROFILES="$BACKUP_DIR/data/imessage-thread-profiles.db"
SNAPSHOT_THREAD_PROFILES="$SNAPSHOT_DIR/$DATE_STAMP/imessage-thread-profiles.db"

if [ -f "$THREAD_PROFILES_DB" ]; then
    if $DRY_RUN; then
        log "Would backup imessage-thread-profiles.db via sqlite3 .backup"
    else
        sqlite3 "$THREAD_PROFILES_DB" "PRAGMA wal_checkpoint(PASSIVE);" 2>/dev/null || true
        sqlite3 "$THREAD_PROFILES_DB" ".backup '$BACKUP_THREAD_PROFILES'"
        sqlite3 "$THREAD_PROFILES_DB" ".backup '$SNAPSHOT_THREAD_PROFILES'"
        verify_sqlite "$BACKUP_THREAD_PROFILES" "imessage-thread-profiles.db (latest)"
        log "imessage-thread-profiles.db backed up ($(du -h "$BACKUP_THREAD_PROFILES" | cut -f1))"
    fi
else
    log "SKIP: imessage-thread-profiles.db not found"
fi

# --- 3d. OKR Snapshots ------------------------------------------------------

log_section "OKR Snapshots"
OKR_SRC="$PROJECT_DIR/data/okr"
OKR_DST="$BACKUP_DIR/data/okr"

if [ -d "$OKR_SRC" ]; then
    if ! $DRY_RUN; then
        mkdir -p "$OKR_DST"
    fi
    rsync $RSYNC_OPTS "$OKR_SRC/" "$OKR_DST/" 2>&1 | \
        { if $VERBOSE; then cat; else tail -1; fi } >> "$LOG_FILE"
    OKR_COUNT=$(find "$OKR_SRC" -type f 2>/dev/null | wc -l | tr -d ' ')
    log "OKR snapshots synced ($OKR_COUNT files)"
else
    log "SKIP: OKR directory not found"
fi

# --- 3e. Webhook Inbox -------------------------------------------------------

log_section "Webhook Inbox"
WEBHOOK_INBOX="$PROJECT_DIR/data/webhook-inbox"
WEBHOOK_DST="$BACKUP_DIR/data/webhook-inbox"

if [ -d "$WEBHOOK_INBOX" ]; then
    if ! $DRY_RUN; then
        mkdir -p "$WEBHOOK_DST"
    fi
    rsync $RSYNC_OPTS "$WEBHOOK_INBOX/" "$WEBHOOK_DST/" 2>&1 | \
        { if $VERBOSE; then cat; else tail -1; fi } >> "$LOG_FILE"
    WEBHOOK_COUNT=$(find "$WEBHOOK_INBOX" -type f 2>/dev/null | wc -l | tr -d ' ')
    log "Webhook inbox synced ($WEBHOOK_COUNT files)"
else
    log "SKIP: Webhook inbox not found"
fi

# --- 4. Document Library (~/Documents/Jarvis/) -------------------------------

log_section "Document Library"
if [ -d "$JARVIS_DOCS" ]; then
    rsync $RSYNC_OPTS "$JARVIS_DOCS/" "$BACKUP_DIR/documents/" 2>&1 | \
        { if $VERBOSE; then cat; else tail -1; fi } >> "$LOG_FILE"
    DOC_COUNT=$(find "$JARVIS_DOCS" -type f | wc -l | tr -d ' ')
    DOC_SIZE=$(du -sh "$JARVIS_DOCS" 2>/dev/null | cut -f1)
    log "Document library synced ($DOC_COUNT files, $DOC_SIZE)"
else
    log "WARN: Document library not found at $JARVIS_DOCS"
fi

# --- 5. Agent Configurations -------------------------------------------------

log_section "Agent Configurations"
AGENT_SRC="$PROJECT_DIR/agent_configs"
if [ -d "$AGENT_SRC" ]; then
    rsync $RSYNC_OPTS "$AGENT_SRC/" "$BACKUP_DIR/agent_configs/" 2>&1 | \
        { if $VERBOSE; then cat; else tail -1; fi } >> "$LOG_FILE"
    AGENT_COUNT=$(ls "$AGENT_SRC"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
    log "Agent configs synced ($AGENT_COUNT YAML files)"
else
    log "WARN: Agent configs not found at $AGENT_SRC"
fi

# --- 6. Scripts & Automation -------------------------------------------------

log_section "Scripts"
SCRIPTS_SRC="$PROJECT_DIR/scripts"
if [ -d "$SCRIPTS_SRC" ]; then
    rsync $RSYNC_OPTS \
        --exclude='*.o' \
        --exclude='.DS_Store' \
        "$SCRIPTS_SRC/" "$BACKUP_DIR/scripts/" 2>&1 | \
        { if $VERBOSE; then cat; else tail -1; fi } >> "$LOG_FILE"
    log "Scripts synced"
fi

# --- 7. Hooks ----------------------------------------------------------------

log_section "Hooks"
HOOKS_SRC="$PROJECT_DIR/hooks"
if [ -d "$HOOKS_SRC" ]; then
    rsync $RSYNC_OPTS "$HOOKS_SRC/" "$BACKUP_DIR/hooks/" 2>&1 | \
        { if $VERBOSE; then cat; else tail -1; fi } >> "$LOG_FILE"
    log "Hooks synced"
fi

# --- 8. Key Config Files ----------------------------------------------------

log_section "Config Files"
for f in config.py .mcp.json manifest.json pyproject.toml CLAUDE.md; do
    SRC="$PROJECT_DIR/$f"
    if [ -f "$SRC" ]; then
        if ! $DRY_RUN; then
            cp "$SRC" "$BACKUP_DIR/$f"
        fi
        log "$f backed up"
    fi
done

# --- 9. Snapshot Rotation (keep last N days) ---------------------------------

if ! $DRY_RUN; then
    log_section "Snapshot Rotation"
    PRUNED=$(find "$SNAPSHOT_DIR" -maxdepth 1 -type d -name "20*" -mtime +$SNAPSHOT_RETENTION_DAYS 2>/dev/null | wc -l | tr -d ' ')
    if [ "$PRUNED" -gt 0 ]; then
        find "$SNAPSHOT_DIR" -maxdepth 1 -type d -name "20*" -mtime +$SNAPSHOT_RETENTION_DAYS -exec rm -rf {} +
        log "Pruned $PRUNED snapshots older than $SNAPSHOT_RETENTION_DAYS days"
    else
        log "No snapshots to prune (retention: $SNAPSHOT_RETENTION_DAYS days)"
    fi
    SNAP_COUNT=$(find "$SNAPSHOT_DIR" -maxdepth 1 -type d -name "20*" 2>/dev/null | wc -l | tr -d ' ')
    SNAP_SIZE=$(du -sh "$SNAPSHOT_DIR" 2>/dev/null | cut -f1)
    log "Snapshots: $SNAP_COUNT days retained ($SNAP_SIZE)"
fi

# --- Summary -----------------------------------------------------------------

if ! $DRY_RUN; then
    TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
    TOTAL_FILES=$(find "$BACKUP_DIR" -type f | wc -l | tr -d ' ')

    # Write a manifest for quick reference
    cat > "$BACKUP_DIR/BACKUP_MANIFEST.md" << MANIFEST_EOF
# Jarvis Backup Manifest
**Last Backup:** $(timestamp)
**Backup Location:** $BACKUP_DIR
**Total Size:** $TOTAL_SIZE
**Total Files:** $TOTAL_FILES
**Snapshot Retention:** $SNAPSHOT_RETENTION_DAYS days
**Errors:** $ERRORS

## Contents
| Directory | Source | Description |
|-----------|--------|-------------|
| data/memory.db | chief_of_staff/data/memory.db | SQLite memory (facts, locations, decisions, delegations, alerts, agent_memory, skills, webhooks, scheduler) |
| data/chroma/ | chief_of_staff/data/chroma/ | ChromaDB vector store (document + fact embeddings) |
| data/calendar-routing.db | chief_of_staff/data/calendar-routing.db | Calendar event ownership tracking (Apple vs M365) |
| data/imessage-thread-profiles.db | chief_of_staff/data/imessage-thread-profiles.db | iMessage thread context and profiles |
| data/inbox-*.* | chief_of_staff/data/ | Inbox monitor state and logs |
| data/okr/ | chief_of_staff/data/okr/ | OKR snapshots (JSON) |
| data/webhook-inbox/ | chief_of_staff/data/webhook-inbox/ | File-drop webhook inbox (pending/processed/failed) |
| documents/ | ~/Documents/Jarvis/ | All project outputs (reports, charts, analysis) |
| agent_configs/ | chief_of_staff/agent_configs/ | Expert agent YAML definitions |
| scripts/ | chief_of_staff/scripts/ | Automation scripts and tools |
| hooks/ | chief_of_staff/hooks/ | Claude Code session hooks |
| *.py, *.json, *.toml | chief_of_staff/ | Key config files |
| snapshots/{date}/ | Dated DB snapshots | memory.db + calendar-routing.db + imessage-thread-profiles.db + chroma.sqlite3 per day (${SNAPSHOT_RETENTION_DAYS}-day retention) |

## Restore

**IMPORTANT: Stop all Jarvis processes before restoring!**

\`\`\`bash
# 1. Stop all processes
launchctl unload ~/Library/LaunchAgents/com.chg.inbox-monitor.plist 2>/dev/null
pkill -f "chief" 2>/dev/null || true

# 2. Automated restore (recommended)
$PROJECT_DIR/scripts/jarvis-backup.sh --restore

# 3. Or manual restore:
# Restore memory database
cp "$BACKUP_DIR/data/memory.db" "$PROJECT_DIR/data/memory.db"

# Restore ChromaDB
rsync -av "$BACKUP_DIR/data/chroma/" "$PROJECT_DIR/data/chroma/"

# Restore inbox state
cp "$BACKUP_DIR/data/inbox-processed.json" "$PROJECT_DIR/data/inbox-processed.json"
cp "$BACKUP_DIR/data/inbox-log.md" "$PROJECT_DIR/data/inbox-log.md"

# Restore documents
rsync -av "$BACKUP_DIR/documents/" "$JARVIS_DOCS/"

# Restore agent configs
rsync -av "$BACKUP_DIR/agent_configs/" "$PROJECT_DIR/agent_configs/"

# Restore scripts
rsync -av "$BACKUP_DIR/scripts/" "$PROJECT_DIR/scripts/"

# Restore hooks
rsync -av "$BACKUP_DIR/hooks/" "$PROJECT_DIR/hooks/"

# Restore config files
for f in config.py .mcp.json manifest.json pyproject.toml CLAUDE.md; do
    cp "$BACKUP_DIR/\$f" "$PROJECT_DIR/\$f" 2>/dev/null || true
done

# 4. Reload services
launchctl load ~/Library/LaunchAgents/com.chg.inbox-monitor.plist
\`\`\`

## Point-in-Time Recovery (from snapshots)

\`\`\`bash
# List available snapshots
ls $SNAPSHOT_DIR/

# Restore memory.db from a specific date
cp "$SNAPSHOT_DIR/2026-02-10/memory.db" "$PROJECT_DIR/data/memory.db"

# Restore ChromaDB from a specific date
cp "$SNAPSHOT_DIR/2026-02-10/chroma.sqlite3" "$PROJECT_DIR/data/chroma/chroma.sqlite3"
\`\`\`
MANIFEST_EOF

    if [ "$ERRORS" -gt 0 ]; then
        log "========== Backup Complete WITH $ERRORS ERROR(S): $TOTAL_FILES files, $TOTAL_SIZE =========="
        notify_failure "$ERRORS error(s) during backup -- check backup.log"
    else
        log "========== Backup Complete: $TOTAL_FILES files, $TOTAL_SIZE =========="
        notify_success "$TOTAL_FILES files, $TOTAL_SIZE"
    fi
else
    log "========== Dry Run Complete =========="
fi
