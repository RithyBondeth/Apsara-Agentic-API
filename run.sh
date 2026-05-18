#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src"

# Read API key from .env file
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | grep NVIDIA_NIM_API_KEY | head -1 | xargs)
fi

cd "$SCRIPT_DIR"

# Default to 'chat' if no arguments provided
if [ $# -eq 0 ]; then
    python3 -c "from apsara_cli.cli import main; import sys; sys.exit(main(['chat']))"
else
    python3 -c "from apsara_cli.cli import main; import sys; sys.exit(main(sys.argv[1:]))" "$@"
fi
