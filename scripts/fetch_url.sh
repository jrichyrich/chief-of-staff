#!/bin/bash
# fetch_url.sh -- Opens URL(s) in the default macOS browser and optionally
# watches a download directory for new files.
#
# Usage:
#   fetch_url.sh <url> [download_dir]
#   fetch_url.sh --watch <download_dir> <timeout_seconds>
#
# Examples:
#   fetch_url.sh "https://app.smartsheet.com/sheets/abc123"
#   fetch_url.sh "https://example.com/doc.pdf" ~/Downloads/Jarvis
#   fetch_url.sh --watch ~/Downloads/Jarvis 30
#
# Created by Jarvis (Chief of Staff) for the document_fetcher agent

set -euo pipefail

JARVIS_DOWNLOAD_DIR="${HOME}/Downloads/Jarvis"

# Ensure download directory exists
ensure_dir() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        echo "Created directory: $dir"
    fi
}

# Snapshot directory contents (for before/after comparison)
snapshot_dir() {
    local dir="$1"
    if [ -d "$dir" ]; then
        ls -1t "$dir" 2>/dev/null || true
    fi
}

# Open URL in default browser
open_url() {
    local url="$1"
    echo "Opening: $url"
    open "$url"
    echo "Opened in default browser at $(date '+%Y-%m-%d %H:%M:%S')"
}

# Watch directory for new files
watch_dir() {
    local dir="$1"
    local timeout="${2:-30}"
    local before_file
    before_file=$(mktemp)

    ensure_dir "$dir"
    snapshot_dir "$dir" > "$before_file"

    echo "Watching $dir for new files (timeout: ${timeout}s)..."

    local elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
        sleep 2
        elapsed=$((elapsed + 2))

        local after_file
        after_file=$(mktemp)
        snapshot_dir "$dir" > "$after_file"

        # Find new files (in after but not in before)
        local new_files
        new_files=$(comm -23 <(sort "$after_file") <(sort "$before_file") 2>/dev/null || true)

        if [ -n "$new_files" ]; then
            echo "New files detected:"
            echo "$new_files" | while read -r f; do
                local full_path="$dir/$f"
                local size
                size=$(stat -f%z "$full_path" 2>/dev/null || echo "unknown")
                echo "  - $f (${size} bytes)"
            done
            rm -f "$before_file" "$after_file"
            return 0
        fi

        rm -f "$after_file"

        # Check for partially downloaded files (.crdownload, .download, .part)
        local downloading
        downloading=$(find "$dir" -maxdepth 1 \( -name "*.crdownload" -o -name "*.download" -o -name "*.part" \) 2>/dev/null | head -1)
        if [ -n "$downloading" ]; then
            echo "  Download in progress... (${elapsed}s)"
        fi
    done

    rm -f "$before_file"
    echo "No new files detected within ${timeout}s timeout."
    return 1
}

# Main
case "${1:-}" in
    --watch)
        watch_dir "${2:-$JARVIS_DOWNLOAD_DIR}" "${3:-30}"
        ;;
    --help|-h)
        echo "Usage:"
        echo "  fetch_url.sh <url> [download_dir]     Open URL, optionally specify download dir"
        echo "  fetch_url.sh --watch <dir> [timeout]   Watch directory for new files"
        echo "  fetch_url.sh --help                    Show this help"
        ;;
    "")
        echo "Error: No URL provided. Use --help for usage."
        exit 1
        ;;
    *)
        url="$1"
        download_dir="${2:-$JARVIS_DOWNLOAD_DIR}"

        ensure_dir "$download_dir"

        # Snapshot before
        before_file=$(mktemp)
        snapshot_dir "$download_dir" > "$before_file"

        # Open URL
        open_url "$url"

        # Brief pause to let download start
        sleep 3

        # Check for new files
        after_file=$(mktemp)
        snapshot_dir "$download_dir" > "$after_file"

        new_files=$(comm -23 <(sort "$after_file") <(sort "$before_file") 2>/dev/null || true)

        if [ -n "$new_files" ]; then
            echo ""
            echo "New files detected in $download_dir:"
            echo "$new_files" | while read -r f; do
                echo "  - $download_dir/$f"
            done
        else
            echo ""
            echo "No immediate download detected."
            echo "If the page requires manual interaction, use:"
            echo "  fetch_url.sh --watch $download_dir 60"
        fi

        rm -f "$before_file" "$after_file"
        ;;
esac
