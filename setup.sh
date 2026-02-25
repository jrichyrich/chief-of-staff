#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_PY="$SCRIPT_DIR/scripts/setup_jarvis.py"

# Minimum Python version required
MIN_MAJOR=3
MIN_MINOR=11

check_version() {
    local candidate="$1"
    if ! command -v "$candidate" &>/dev/null; then
        return 1
    fi
    local version
    version=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null) || return 1
    local major minor
    major="${version%%.*}"
    minor="${version##*.}"
    if [[ "$major" -ge "$MIN_MAJOR" && "$minor" -ge "$MIN_MINOR" ]]; then
        echo "$version"
        return 0
    fi
    return 1
}

# Try candidates in order of preference
PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if version=$(check_version "$candidate"); then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    echo "Error: Python $MIN_MAJOR.$MIN_MINOR+ is required but not found."
    if command -v brew &>/dev/null; then
        echo ""
        read -r -p "Homebrew detected. Install python@3.13? [y/N] " answer
        if [[ "$answer" =~ ^[Yy]$ ]]; then
            brew install python@3.13
            PYTHON_BIN="python3.13"
            version=$(check_version "$PYTHON_BIN") || {
                echo "Error: Installation succeeded but python3.13 is not on PATH."
                echo "Try: brew link python@3.13"
                exit 1
            }
        else
            echo "Aborted."
            exit 1
        fi
    else
        echo ""
        echo "Install Python $MIN_MAJOR.$MIN_MINOR+ from one of:"
        echo "  - https://www.python.org/downloads/"
        echo "  - brew install python@3.13  (after installing Homebrew)"
        echo "  - Your system package manager (apt, dnf, etc.)"
        exit 1
    fi
fi

echo "Using Python: $PYTHON_BIN ($version)"
exec "$PYTHON_BIN" "$SETUP_PY" "$@"
