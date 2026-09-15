#!/usr/bin/env bash
# Voice Echo launcher for macOS / Linux.
# Creates .venv on first run, installs deps, then launches main.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
    echo "[setup] Creating virtual environment in .venv ..."
    python3 -m venv "$VENV"
    echo "[setup] Installing dependencies ..."
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r requirements.txt
    echo "[setup] Installing Playwright browsers (optional, for browser automation) ..."
    "$PY" -m playwright install chromium || echo "[setup] Playwright install skipped."
fi

exec "$PY" main.py "$@"
