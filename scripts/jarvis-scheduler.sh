#!/bin/bash
# ============================================================================
# jarvis-scheduler.sh -- Run the Jarvis scheduler engine to evaluate due tasks
# ============================================================================
# Evaluates all due scheduled tasks (alert_eval, webhook_poll, skill_analysis,
# etc.) and executes their handlers. Designed to be run by launchd every 5 min.
#
# Usage:  ./jarvis-scheduler.sh
# Schedule: Every 5 minutes via launchd (com.chg.jarvis-scheduler.plist)
# ============================================================================

set -euo pipefail

PROJECT_DIR="${JARVIS_PROJECT_DIR:-$HOME/Documents/GitHub/chief_of_staff}"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_FILE="$PROJECT_DIR/data/scheduler.log"

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Log rotation (keep under 500 lines)
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE" | tr -d ' ')" -gt 500 ]; then
    mv "$LOG_FILE" "$LOG_FILE.old"
    echo "[$(timestamp)] Log rotated" > "$LOG_FILE"
fi

# Verify python exists
if [ ! -x "$PYTHON" ]; then
    echo "[$(timestamp)] ERROR: Python not found at $PYTHON" >> "$LOG_FILE"
    exit 1
fi

# Verify memory.db exists
if [ ! -f "$PROJECT_DIR/data/memory.db" ]; then
    echo "[$(timestamp)] SKIP: memory.db not found" >> "$LOG_FILE"
    exit 0
fi

# Run the scheduler engine
cd "$PROJECT_DIR"
"$PYTHON" -m scheduler.engine >> "$LOG_FILE" 2>&1
