#!/bin/bash
# join-call: Quick launcher for the meeting bridge
#
# Usage:
#   ./scripts/run.sh "https://meet.google.com/abc" --name "Agent"
#
# Requires Python 3.10+ with aiohttp and websockets installed:
#   pip install aiohttp websockets

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

python_ok() {
    command -v python3 &>/dev/null && python3 -c "import aiohttp, websockets" &>/dev/null
}

if python_ok; then
    exec python3 "$SCRIPT_DIR/join.py" "$@"
else
    echo "Error: Python 3 with required dependencies not found." >&2
    if command -v python3 &>/dev/null; then
        echo "  python3 is on PATH but missing deps — run: pip install aiohttp websockets" >&2
    else
        echo "  python3 was not found on PATH" >&2
    fi
    exit 1
fi
