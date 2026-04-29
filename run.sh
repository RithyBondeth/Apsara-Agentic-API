#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src"
export NVIDIA_API_KEY="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"

cd "$SCRIPT_DIR"

# Default to 'chat' if no arguments provided
if [ $# -eq 0 ]; then
    python3 -c "from apsara_cli.cli import main; import sys; sys.exit(main(['chat']))"
else
    python3 -c "from apsara_cli.cli import main; import sys; sys.exit(main(sys.argv[1:]))" "$@"
fi
