#!/usr/bin/env bash
#
# install-plists.sh — Generate and install launchd plist files from templates.
#
# Replaces __PROJECT_DIR__ placeholder in scripts/com.chg.*.plist templates
# with the actual project directory, then copies to ~/Library/LaunchAgents/.
#
# Usage:
#   ./scripts/install-plists.sh              # Install all plists
#   ./scripts/install-plists.sh --uninstall  # Unload and remove all plists
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${JARVIS_PROJECT_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_LABELS=(
    com.chg.inbox-monitor
    com.chg.jarvis-backup
    com.chg.alert-evaluator
    com.chg.imessage-daemon
)

if [[ "${1:-}" == "--uninstall" ]]; then
    echo "Uninstalling launchd plists..."
    for label in "${PLIST_LABELS[@]}"; do
        plist="$LAUNCH_AGENTS_DIR/${label}.plist"
        if [[ -f "$plist" ]]; then
            launchctl unload "$plist" 2>/dev/null || true
            rm "$plist"
            echo "  Removed $label"
        fi
    done
    echo "Done."
    exit 0
fi

echo "Installing launchd plists..."
echo "  PROJECT_DIR=$PROJECT_DIR"
mkdir -p "$LAUNCH_AGENTS_DIR"

for label in "${PLIST_LABELS[@]}"; do
    template="$SCRIPT_DIR/${label}.plist"
    if [[ ! -f "$template" ]]; then
        echo "  SKIP: $template not found"
        continue
    fi
    dest="$LAUNCH_AGENTS_DIR/${label}.plist"
    # Unload existing if running
    launchctl unload "$dest" 2>/dev/null || true
    # Replace placeholder and install
    sed "s|__PROJECT_DIR__|${PROJECT_DIR}|g" "$template" > "$dest"
    launchctl load "$dest"
    echo "  Installed $label"
done

echo "Done. All plists installed and loaded."
