#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src"
VENV_DIR="$SCRIPT_DIR/.venv"

python_is_supported() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
        >/dev/null 2>&1
}

# Prefer the project environment, then an explicit override, then supported
# Python executables commonly available on macOS/Linux.
PYTHON_BIN=""
if [ -x "$VENV_DIR/bin/python" ] && python_is_supported "$VENV_DIR/bin/python"; then
    PYTHON_BIN="$VENV_DIR/bin/python"
else
    candidates=()
    if [ -n "${APSARA_PYTHON:-}" ]; then
        candidates+=("$APSARA_PYTHON")
    fi
    candidates+=(
        "python3.13"
        "python3.12"
        "python3.11"
        "python3.10"
        "python3"
        "/opt/homebrew/bin/python3"
        "/usr/local/bin/python3"
    )

    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" >/dev/null 2>&1; then
            resolved_candidate="$(command -v "$candidate")"
            if python_is_supported "$resolved_candidate"; then
                PYTHON_BIN="$resolved_candidate"
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON_BIN" ]; then
    detected_version="$(python3 --version 2>&1 || echo 'not installed')"
    echo "Error: Apsara requires Python 3.10 or newer."
    echo "Detected: $detected_version"
    echo
    echo "On macOS with Homebrew:"
    echo "  brew install python@3.12"
    echo "  mv .venv .venv-backup  # only if an older environment exists"
    echo "  ./run.sh"
    echo
    echo "Or select an installed interpreter explicitly:"
    echo "  APSARA_PYTHON=/path/to/python3.12 ./run.sh"
    exit 1
fi

# Create an isolated environment instead of installing into system Python.
if [ "$PYTHON_BIN" != "$VENV_DIR/bin/python" ]; then
    if [ -e "$VENV_DIR" ]; then
        echo "Error: $VENV_DIR exists but uses an unsupported Python version."
        echo "Preserve it, then run again: mv .venv .venv-backup && ./run.sh"
        exit 1
    fi
    echo "Creating Python environment..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    PYTHON_BIN="$VENV_DIR/bin/python"
fi

# Check the complete runtime surface; install only when something is missing.
if ! "$PYTHON_BIN" -c "import apsara_cli, litellm, mcp, prompt_toolkit, rich" \
    >/dev/null 2>&1; then
    echo "Installing Apsara dependencies..."
    "$PYTHON_BIN" -m pip install --upgrade pip --quiet
    "$PYTHON_BIN" -m pip install -e "$SCRIPT_DIR" --quiet
fi

cd "$SCRIPT_DIR"

# --- Default to 'chat' if no arguments provided ---
if [ $# -eq 0 ]; then
    exec "$PYTHON_BIN" -c "from apsara_cli.cli import main; import sys; sys.exit(main(['chat']))"
else
    exec "$PYTHON_BIN" -c "from apsara_cli.cli import main; import sys; sys.exit(main(sys.argv[1:]))" "$@"
fi
