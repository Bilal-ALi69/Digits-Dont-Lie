#!/usr/bin/env bash
# Digits Dont Lie - Linux/macOS entry point for starting both servers.
#   ./scripts/run.sh            production build
#   ./scripts/run.sh --dev      Next.js dev server
set -eu
cd "$(dirname "$0")/.."

for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
        exec "$py" scripts/run.py "$@"
    fi
done

echo "  Python 3.11+ was not found on this machine. Run scripts/setup.py first." >&2
exit 1
