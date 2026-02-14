#!/bin/bash
# organize_documents.sh -- Creates and manages the Jarvis document library structure.
# Moves documents into project folders and maintains a master index.
#
# Usage:
#   organize_documents.sh init                           Create base folder structure
#   organize_documents.sh move <file> <project>          Move file to project folder
#   organize_documents.sh list [project]                 List documents (optionally by project)
#   organize_documents.sh index                          Regenerate _index.md
#   organize_documents.sh scan                           Find unorganized Jarvis documents
#
# Examples:
#   organize_documents.sh init
#   organize_documents.sh move ~/Documents/RBAC_Deep_Dive.md RBAC
#   organize_documents.sh list
#   organize_documents.sh list RBAC
#   organize_documents.sh scan
#
# Created by Jarvis (Chief of Staff) for the document_librarian agent

set -euo pipefail

JARVIS_DOCS="${HOME}/Documents/Jarvis"
INDEX_FILE="${JARVIS_DOCS}/_index.md"

# Initialize the base folder structure
init_library() {
    echo "Initializing Jarvis document library at $JARVIS_DOCS..."

    mkdir -p "$JARVIS_DOCS"
    mkdir -p "$JARVIS_DOCS/General"
    mkdir -p "${HOME}/Downloads/Jarvis"

    if [ ! -f "$INDEX_FILE" ]; then
        cat > "$INDEX_FILE" << 'HEREDOC'
# Jarvis Document Index

> Auto-maintained by the document_librarian agent. Last updated: $(date '+%Y-%m-%d %H:%M:%S')

## By Project

_No documents indexed yet. Run `organize_documents.sh index` to populate._

---

*Maintained by Jarvis (Chief of Staff)*
HEREDOC
        echo "Created master index at $INDEX_FILE"
    fi

    echo "Library initialized."
    echo "  Documents: $JARVIS_DOCS"
    echo "  Downloads: ${HOME}/Downloads/Jarvis"
    echo "  Index:     $INDEX_FILE"
}

# Move a file to a project folder
move_to_project() {
    local file="$1"
    local project="$2"
    local project_dir="$JARVIS_DOCS/$project"

    if [ ! -f "$file" ]; then
        echo "Error: File not found: $file"
        exit 1
    fi

    mkdir -p "$project_dir"

    local filename
    filename=$(basename "$file")
    local dest="$project_dir/$filename"

    if [ -f "$dest" ]; then
        echo "Warning: $dest already exists. Skipping to avoid overwrite."
        echo "  Source: $file"
        echo "  Dest:   $dest"
        return 1
    fi

    mv "$file" "$dest"
    echo "Moved: $file"
    echo "  To:  $dest"
}

# List documents in the library
list_documents() {
    local project="${1:-}"

    if [ -n "$project" ]; then
        local project_dir="$JARVIS_DOCS/$project"
        if [ ! -d "$project_dir" ]; then
            echo "No project folder found: $project"
            return 1
        fi
        echo "Documents in $project:"
        find "$project_dir" -type f ! -name '_index.md' ! -name '.DS_Store' | sort | while read -r f; do
            local size
            size=$(stat -f%z "$f" 2>/dev/null || echo "?")
            local mod
            mod=$(stat -f%Sm -t"%Y-%m-%d" "$f" 2>/dev/null || echo "?")
            printf "  %-50s %8s bytes  %s\n" "$(basename "$f")" "$size" "$mod"
        done
    else
        echo "Jarvis Document Library: $JARVIS_DOCS"
        echo ""

        # List each project folder
        find "$JARVIS_DOCS" -mindepth 1 -maxdepth 1 -type d | sort | while read -r dir; do
            local proj
            proj=$(basename "$dir")
            local count
            count=$(find "$dir" -type f ! -name '.DS_Store' | wc -l | tr -d ' ')
            echo "  $proj/ ($count files)"
            find "$dir" -type f ! -name '.DS_Store' | sort | while read -r f; do
                echo "    - $(basename "$f")"
            done
        done

        # Count total
        local total
        total=$(find "$JARVIS_DOCS" -type f ! -name '_index.md' ! -name '.DS_Store' | wc -l | tr -d ' ')
        echo ""
        echo "Total: $total documents"
    fi
}

# Regenerate the _index.md file
generate_index() {
    echo "Generating index at $INDEX_FILE..."

    cat > "$INDEX_FILE" << HEREDOC
# Jarvis Document Index

> Auto-maintained by the document_librarian agent.
> Last updated: $(date '+%Y-%m-%d %H:%M:%S')

## By Project

HEREDOC

    find "$JARVIS_DOCS" -mindepth 1 -maxdepth 1 -type d | sort | while read -r dir; do
        local proj
        proj=$(basename "$dir")

        echo "### $proj" >> "$INDEX_FILE"
        echo "" >> "$INDEX_FILE"
        echo "| Document | Size | Modified |" >> "$INDEX_FILE"
        echo "|----------|------|----------|" >> "$INDEX_FILE"

        find "$dir" -type f ! -name '.DS_Store' | sort | while read -r f; do
            local fname
            fname=$(basename "$f")
            local size
            size=$(stat -f%z "$f" 2>/dev/null || echo "?")
            local mod
            mod=$(stat -f%Sm -t"%Y-%m-%d" "$f" 2>/dev/null || echo "?")
            local rel_path
            rel_path="./$proj/$fname"
            echo "| [$fname]($rel_path) | ${size} bytes | $mod |" >> "$INDEX_FILE"
        done

        echo "" >> "$INDEX_FILE"
    done

    echo "---" >> "$INDEX_FILE"
    echo "" >> "$INDEX_FILE"
    echo "*Maintained by Jarvis (Chief of Staff)*" >> "$INDEX_FILE"

    echo "Index generated with $(find "$JARVIS_DOCS" -type f ! -name '_index.md' ! -name '.DS_Store' | wc -l | tr -d ' ') documents."
}

# Scan for unorganized Jarvis documents
scan_unorganized() {
    echo "Scanning for unorganized Jarvis documents..."
    echo ""

    local found=0

    # Check ~/Documents for known patterns
    for pattern in "*Talking_Points*" "*Deep_Dive*" "*Prep*" "*Briefing*" "*Status_Report*"; do
        find "${HOME}/Documents" -maxdepth 1 -name "$pattern" -type f 2>/dev/null | while read -r f; do
            echo "  UNORGANIZED: $f"
            found=1
        done
    done

    # Check ~/Downloads/Jarvis for unfiled downloads
    if [ -d "${HOME}/Downloads/Jarvis" ]; then
        find "${HOME}/Downloads/Jarvis" -type f ! -name '.DS_Store' 2>/dev/null | while read -r f; do
            echo "  UNFILED DOWNLOAD: $f"
            found=1
        done
    fi

    if [ "$found" -eq 0 ]; then
        echo "  No unorganized documents found."
    fi
}

# Main
case "${1:-}" in
    init)
        init_library
        ;;
    move)
        if [ -z "${2:-}" ] || [ -z "${3:-}" ]; then
            echo "Usage: organize_documents.sh move <file> <project>"
            exit 1
        fi
        move_to_project "$2" "$3"
        ;;
    list)
        list_documents "${2:-}"
        ;;
    index)
        generate_index
        ;;
    scan)
        scan_unorganized
        ;;
    --help|-h)
        echo "Usage:"
        echo "  organize_documents.sh init                    Create base folder structure"
        echo "  organize_documents.sh move <file> <project>   Move file to project folder"
        echo "  organize_documents.sh list [project]          List documents"
        echo "  organize_documents.sh index                   Regenerate _index.md"
        echo "  organize_documents.sh scan                    Find unorganized documents"
        ;;
    *)
        echo "Unknown command: ${1:-}"
        echo "Use --help for usage."
        exit 1
        ;;
esac
