<div align="center">
  <img src="assets/Voice_Lite_Logo.png" alt="Voice Echo" width="260" />

  <h1>Voice Echo</h1>

  <p><strong>Open-source desktop AI assistant for Windows, macOS, and Linux</strong></p>
  <p>Voice-first automation · contextual desktop intelligence · productivity workflows</p>

  <p>
    <a href="#overview"><img src="https://img.shields.io/badge/experience-open%20source-blue?style=for-the-badge" alt="Open Source" /></a>
    <a href="#getting-started"><img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=for-the-badge" alt="Platforms" /></a>
    <a href="#features"><img src="https://img.shields.io/badge/tech-Gemini%20%2B%20OpenRouter-green?style=for-the-badge" alt="Gemini + OpenRouter" /></a>
    <a href="#offline-voice"><img src="https://img.shields.io/badge/voice-offline%20%28Vosk%20%2B%20Piper%29-orange?style=for-the-badge" alt="Offline Voice" /></a>
  </p>

  <p>
    <a href="#quick-start"><img src="https://img.shields.io/badge/Quick%20Start-Install%20%26%20Run-success?style=flat-square" alt="Quick Start" /></a>
    <a href="#project-structure"><img src="https://img.shields.io/badge/Project%20Structure-Clean%20Architecture-lightgrey?style=flat-square" alt="Project Structure" /></a>
    <a href="#community"><img src="https://img.shields.io/badge/Community-Discord-purple?style=flat-square" alt="Community" /></a>
  </p>
</div>

---

## Overview

Voice Echo is a premium desktop assistant for Windows, macOS, and Linux that combines voice and text control with automated workflows, screen-aware intelligence, and rich content generation.

Designed for advanced desktop productivity, Voice Echo delivers:

- Voice-first command and desktop automation
- Application control, browser workflows, and file handling
- Contextual screen inspection and adaptive task execution
- Presentation, document, and report generation
- Remote control via Discord and Voice Connect
- Fully offline voice (speech-to-text and text-to-speech) with no Google dependency

## Quick Highlights

| Core capability | Why it matters |
|---|---|
| Voice-first assistant | Speak commands naturally and stay hands-free |
| Gemini + OpenRouter | Fast responses with resilient fallback support |
| Offline local voice | STT (Vosk/sherpa) and TTS (Piper) run 100% on-device |
| Screen-aware context | Ask about visible windows and on-screen content |
| Document automation | Create presentations, docs, spreadsheets, and PDFs |
| Plugin-ready | Extend features with lightweight Python plugins |

## Key Benefits

- Wake-word support for “Voice Echo” and responsive assistant activation
- Gemini 2.5 Flash-powered AI with OpenRouter fallback resilience
- **Fully offline voice engine** (Vosk/sherpa STT + Piper TTS) that requires no cloud services
- Polished Qt interface with live status displays and workflow cards
- Modular action architecture for clean extensibility and automation
- Secure local configuration with file-based credential storage
- Device pairing and remote routing through Voice Connect

## Features

### Intelligent Assistant

- Unified voice and typed command handling
- Wake-word listening and responsive assistant activation
- Dynamic screen inspection for context-aware answers
- **Offline local voice** (speech-to-text and text-to-speech) with no Google dependency
- **Unified Gemini Native Voice** for all system alerts and daily briefings
- **True Interruption (Barge-in)** with dynamic noise-gating
- **Proactive Engine** for spontaneous, context-aware interaction when idle
- Gemini-first AI with OpenRouter fallback resilience

### Productivity & Automation

- **System Health & Resource Manager** to monitor CPU/RAM and forcefully close frozen apps
- **Background Monitors & Alerts** for polling crypto prices, website uptime, or memory spikes autonomously
- **Smart Clipboard Analyzer** to instantly read and process copied text natively
- Open and control Windows apps, windows, files, and system actions
- Browser automation with Playwright-driven workflows
- Contextual automation based on screen content and notifications
- **Instagram AI Assistant** to poll DMs, notify you, and seamlessly take over chats or reply on your behalf
- Reminder, meeting assistance, and notification management

### Content & Office Tools

- Generate presentation decks, summaries, and slide content
- Create Word documents and spreadsheets from prompts
- Export polished reports and deliverables as PDF
- Build landing pages and website workspaces locally

### Integrations

- Instagram DM bridge for reading and auto-replying to messages natively
- Discord bridge for remote commands and collaboration
- OpenRouter fallback for uninterrupted AI access
- Configurable voice, UI, startup, and notification settings
- Voice Connect for device discovery and command routing

## Offline Voice

By default Voice Echo uses a **fully offline voice engine** — no Google/Gemini
endpoint is contacted for speech. This avoids “Gemini unreachable” errors on
networks where Google services are blocked or unavailable.

- **Speech-to-text:** sherpa-onnx streaming Zipformer, the engine behind the modern Vosk streaming models (`sherpa-onnx-streaming-zipformer-small-ru-vosk`). Real-time recognition from the microphone with silence/endpoint detection and wake-word support.
- **Text-to-speech:** Piper with the Russian neural voice `ru_RU-irina-medium`.

Models are stored under `config/models/`:

```
config/models/piper/      Piper TTS voice (ru_RU-irina-medium.onnx + .json)
config/models/sherpa-ru/  Vosk/sherpa STT model (encoder/decoder/joiner, tokens, bpe)
```

Download them with:

```bash
.venv/bin/python download_voice_models.py
```

The feature is managed from **Settings → System & Connectivity → Local Voice
Engine** (`local_voice_engine` in `config/app_settings.json`, enabled by
default). Toggle it off to return to the cloud Gemini Native Voice path; a
restart is required either way.

**Requirements:** `sherpa-onnx` and `piper-tts` are part of
`requirements.txt`. If a model file or package is missing the app falls back
gracefully to its previous online behaviour instead of crashing.

## Getting Started

### Prerequisites

- Windows 10/11, macOS 12+, or a modern Linux distribution
- Python 3.11 or Python 3.12
- Git installed
- Gemini API key
- OpenRouter API key (optional but recommended)

> **Linux notes:** voice/audio uses `sounddevice` (PortAudio). Install it with your package manager (e.g. `sudo apt install libportaudio2`). Screen features that rely on `pyautogui` need an active X11/Wayland session. Desktop autostart is Windows-only; on Linux/macOS launch via the commands below.

### 1. Clone the repository

```bash
git clone https://github.com/titechprabhasolutions/Voice-AI---Lite.git
cd "Voice AI - Lite"
```

### 2. Create and activate a virtual environment

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
pip install -r requirements-optional.txt   # optional: gesture camera (mediapipe)
playwright install
python download_voice_models.py            # offline voice models (Piper + Vosk/sherpa)
```

> `mediapipe` (used only for the gesture camera and push-up tracking) publishes
> wheels for a narrower range of interpreters than the rest of the stack. It
> lives in `requirements-optional.txt` so a missing wheel never aborts the
> install — the app starts and the gesture camera simply stays disabled.
> On Python 3.14 (e.g. macOS Intel) mediapipe has no wheel; use Python 3.11 or
> 3.12 if you need gestures.

### 4. Configure API credentials

Create `config/api_keys.json` with your keys:

```json
{
  "gemini_api_key": "YOUR_GEMINI_API_KEY",
  "openrouter_api_key": "YOUR_OPENROUTER_API_KEY",
  "instagram_username": "YOUR_IG_USERNAME",
  "instagram_password": "YOUR_IG_PASSWORD"
}
```

#### Gemini API Key

1. Create a Google Cloud or Gemini account.
2. Enable Gemini API access for your project.
3. Add the generated key to `gemini_api_key`.

#### OpenRouter API Key

1. Register at https://openrouter.ai.
2. Generate an `sk-or-` API key.
3. Add the key to `openrouter_api_key`.

### 5. Optional: Configure Discord integration

If you want Discord remote control, populate `config/discord_bot.json` with your bot credentials and connection settings.

### 6. Launch Voice Echo

```bash
python main.py
```

**macOS / Linux:** `run.sh` sets up `.venv` and installs dependencies on first run, then launches the app:

```bash
./run.sh
```

For a cleaner startup experience on Windows:

```powershell
start_voice.vbs
```

## Configuration

Core configuration files:

- `config/api_keys.json` — Gemini and OpenRouter credentials
- `config/app_settings.json` — voice, UI, startup, and automation preferences
- `config/voice_connect.json` — device pairing, gateway, and discovery settings
- `config/discord_bot.json` — Discord bridge configuration
- `config/models/` — offline voice models (Piper TTS + Vosk/sherpa STT)

## Project Structure

- `main.py` — application startup, AI orchestration, and command routing
- `local_voice.py` — offline STT/TTS engine (Vosk/sherpa + Piper) and voice loop
- `download_voice_models.py` — fetches the offline voice model files into `config/models/`
- `ui.py` — Qt-based desktop interface and live assistant controls
- `actions/` — modular automation, document, and assistant tools
- `voice_connect/` — local gateway, pairing, and remote routing
- `config/` — local settings, credentials, and runtime configuration
- `plugins/` — optional plugin extensions
- `tests/` — integration and validation tests

## Plugin System

Extend Voice Echo with custom Python plugins by adding files to `plugins/`.

Supported hooks:

- `on_voice_created(voice)` — called when the assistant instance is initialized
- `on_startup(voice)` — called after startup when plugins are registered
- `on_text_command(text, source, voice=None)` — called for each incoming text command; return `True` to indicate the command was handled

## Best Practices

- Keep credentials in `config/api_keys.json` and avoid committing secrets.
- Use the virtual environment for all development and runtime sessions.
- Restart the app after changing config or adding plugins.
- Review `config/app_settings.json` to tune voice, UI, and automation behavior.

## Community & Support

- Discord: https://discord.gg/gEYmJKKtq3

## License

This project is published under a custom source-available license. See `LICENSE` for details.

## Maintainer

- Suryaansh Tiwari

> Preserve attribution and keep credentials secure when building on top of Voice Echo.
