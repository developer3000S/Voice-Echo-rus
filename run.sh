#!/usr/bin/env bash
# Voice Echo launcher for macOS / Linux.
# Starts the offline local LLM (Ollama), then launches main.py.
# Creates .venv on first run, installs deps.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Local LLM server ------------------------------------------------
if command -v ollama >/dev/null 2>&1; then
    if ! curl -sf --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
        echo "[setup] Starting local LLM server (Ollama) ..."
        nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
        for _ in $(seq 1 30); do
            curl -sf --max-time 1 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
            sleep 1
        done
        if ! curl -sf --max-time 1 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
            echo "[ERROR] Ollama failed to start; see /tmp/ollama-serve.log" >&2
            exit 1
        fi
    fi
    echo "[setup] Local LLM server ready."
else
    echo "[ERROR] 'ollama' is not installed. Voice Echo runs fully offline via Ollama.
Install it: curl -fsSL https://ollama.com/install.sh | sh" >&2
    exit 1
fi

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
    if ! "$PY" -c "import sounddevice, requests, PyQt6"; then
        echo "[setup] Core imports failed; run ./run.sh again to retry." >&2
        exit 1
    fi
    touch "$STAMP"
fi

# --- Local model -------------------------------------------------------
# Import the bundled GGUF into Ollama on first launch (idempotent).
if ! curl -sf --max-time 2 http://127.0.0.1:11434/api/tags | grep -q minicpm5-2b; then
    echo "[setup] Creating local model minicpm5-2b from models/minicpm5-2b/ ..."
    "$PY" -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR')
from llm_client import client
ok = client.ensure_local_model()
sys.exit(0 if ok else 1)
" || {
        echo "[WARN] Could not auto-import the local model. Falling back to 'ollama create'." >&2
        ollama create minicpm5-2b -f "$SCRIPT_DIR/models/minicpm5-2b/Modelfile" || \
            echo "[WARN] Model import failed; run ./setup_local_model.py after launch." >&2
    }
else
    echo "[setup] Local model minicpm5-2b ready."
fi

exec "$PY" main.py "$@"