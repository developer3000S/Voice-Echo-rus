#!/usr/bin/env bash
# Voice Echo launcher for macOS / Linux.
# Creates .venv on first run, installs deps, then launches main.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv"
PY="$VENV/bin/python"
# Stamp marks a *completed* setup. Its absence (even when .venv/bin/python
# exists) means a previous run died mid-install, so we resume rather than
# silently skipping setup and crashing on the first `import` in main.py.
STAMP="$VENV/.setup-complete"

if [ ! -f "$STAMP" ]; then
    if [ ! -x "$PY" ]; then
        echo "[setup] Creating virtual environment in .venv ..."
        python3 -m venv "$VENV"
    else
        echo "[setup] Resuming an incomplete setup in .venv ..."
    fi

    echo "[setup] Installing dependencies ..."
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r requirements.txt

    # mediapipe (gesture camera / push-up tracking) ships no wheels for some
    # interpreters (e.g. Python 3.14 on macOS Intel) and only those two
    # features use it, both guarded by try/except. Install it best-effort and
    # wheels-only so a missing wheel never aborts setup or drags in a
    # multi-hundred-MB source build.
    echo "[setup] Installing optional dependencies (best-effort) ..."
    if ! "$PY" -m pip install --only-binary=:all: -r requirements-optional.txt; then
        echo "[setup] mediapipe is unavailable for $("$PY" -V 2>&1); gesture camera stays disabled."
        echo "[setup] To enable gestures, recreate .venv with Python 3.11 or 3.12."
    fi

    echo "[setup] Installing Playwright browsers (optional, for browser automation) ..."
    "$PY" -m playwright install chromium || echo "[setup] Playwright install skipped."

    # Gate completion on the packages main.py imports at startup.
    if ! "$PY" -c "import sounddevice, requests, google.genai, PyQt6"; then
        echo "[setup] Core imports failed; run ./run.sh again to retry." >&2
        exit 1
    fi
    touch "$STAMP"
fi

exec "$PY" main.py "$@"
