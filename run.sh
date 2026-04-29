#!/bin/bash
export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/src"
export NVIDIA_API_KEY="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"

cd "$(dirname "$0")"
python3 -m apsara_cli.cli chat "$@"
