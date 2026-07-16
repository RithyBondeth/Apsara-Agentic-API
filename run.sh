#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src"

# --- Load .env ---
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# --- Check Python3 ---
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python 3.9+ first."
    exit 1
fi

# --- Auto-install dependencies if needed ---
if ! python3 -c "import rich" 2>/dev/null; then
    echo "Installing dependencies..."
    pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet
fi

cd "$SCRIPT_DIR"

# --- Default to 'chat' if no arguments provided ---
if [ $# -eq 0 ]; then
    exec python3 -c "from apsara_cli.cli import main; import sys; sys.exit(main(['chat']))"
else
    exec python3 -c "from apsara_cli.cli import main; import sys; sys.exit(main(sys.argv[1:]))" "$@"
fi
