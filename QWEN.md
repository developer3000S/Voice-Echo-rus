# QWEN.md - Project Overview for Voice Echo

Last Updated: September 8, 2026

This file provides a comprehensive overview of the Voice Echo project structure and key components. It's intended to serve as instructional context for future interactions.

## Project Overview

Voice Echo is an open-source Windows desktop AI assistant that combines voice and text control with automated workflows, screen-aware intelligence, and rich content generation. Designed for advanced desktop productivity, Voice Echo delivers voice-first command and desktop automation, application control, browser workflows, file handling, contextual screen inspection, adaptive task execution, presentation/document/report generation, and remote control via Discord and Voice Connect.

## Key Features

### Intelligent Assistant

- Unified voice and typed command handling
- Wake-word listening ("Voice Echo") and responsive assistant activation
- Dynamic screen inspection for context-aware answers
- **Unified Gemini Native Voice** for all system alerts and daily briefings
- **True Interruption (Barge-in)** with dynamic noise-gating
- **Proactive Engine** for spontaneous, context-aware interaction when idle
- Gemini-first AI with OpenRouter fallback resilience

### Productivity & Automation

- **System Health & Resource Manager** — monitor CPU/RAM and forcefully close frozen apps
- **Background Monitors & Alerts** — poll crypto prices, system RAM/CPU, or website uptime autonomously
- **Smart Clipboard Analyzer** — instantly read and process copied text natively
- Open and control Windows apps, windows, files, and system actions
- Browser automation with Playwright-driven workflows
- Contextual automation based on screen content and notifications
- **Instagram AI Assistant** — poll DMs, notify, and seamlessly take over chats or reply
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

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11/3.12 |
| UI Framework | PyQt6 (custom glassmorphic dark theme) |
| Primary AI | Google Gemini 2.5 Flash (Native Audio) |
| Fallback AI | OpenRouter (40+ free models) |
| Local AI | Ollama/LM Studio via OpenAI-compatible API |
| Browser Automation | Playwright |
| Smart Home | TP-Link Kasa, Philips Hue, LG ThinQ, Daikin, Tuya, Nest, SmartThings, Atomberg |
| Voice | sounddevice + PyAudio |
| Clipboard | pyperclip |
| Screen Capture | mss + OpenCV + MediaPipe |
| Desktop Control | pyautogui, pygetwindow, psutil, comtypes, pycaw |
| Discord | discord.py |
| Instagram | instagrapi |
| Document Gen | python-pptx, python-docx, openpyxl, reportlab |
| Backend | FastAPI + Uvicorn (dashboard server) |
| Config | JSON-based in `config/` |

## Project Structure

```
Voice-Echo-rus/
├── main.py                  # App startup, AI orchestration, command routing (3433 lines)
├── ui.py                    # Qt desktop interface (12933 lines)
├── smart_home_page_new.py   # Smart home dashboard page
├── discord_bot.py           # Discord bridge service
├── llm_client.py            # Unified AI client (Local/OpenRouter)
├── or_client.py             # OpenRouter client with fallback pool
├── plugin_manager.py        # Plugin loader with hook dispatch
├── updater.py               # GitHub fast-forward updater
├── gesture_utils.py         # Gesture detection for camera
├── workspace_store.py       # Workspace/memory persistence
├── bootstrap.ps1            # Windows admin bootstrap installer
├── start_voice.bat/.vbs    # Launch shortcuts
├── requirements.txt         # Python dependencies
├── actions/                 # Modular automation tools (~35 modules)
│   ├── attention_monitor.py # Wake-word, screen awareness, proactive engine
│   ├── background_monitor.py# Crypto/system/website monitors
│   ├── browser_control.py   # Playwright browser automation
│   ├── clipboard_processor.py
│   ├── computer_control.py
│   ├── computer_settings.py # Brightness, volume, Wi-Fi, lock, shutdown
│   ├── daily_briefing.py
│   ├── dev_agent.py         # Autonomous coding agent
│   ├── docx_tools.py        # Word document generation
│   ├── file_controller.py   # File/folder operations
│   ├── file_processor.py
│   ├── flight_finder.py
│   ├── instagram_chat.py    # Instagram DM bridge
│   ├── meeting_assistant.py
│   ├── office_builder.py    # PPTX/XLSX generation
│   ├── open_app.py
│   ├── pdf_tools.py
│   ├── proactive.py         # Proactive interaction engine
│   ├── screen_processor.py
│   ├── send_message.py
│   ├── system_manager.py
│   ├── web_search.py
│   ├── weather_report.py
│   └── website_builder.py
├── agent/                   # Autonomous agent components
│   ├── error_handler.py
│   ├── executor.py
│   ├── planner.py
│   └── task_queue.py
├── voice_connect/          # Local network device discovery & control
│   ├── agents/
│   ├── gateway/
│   ├── service.py
│   └── README.md
├── voice-connect-android/  # Android companion app
├── config/                  # Settings & credentials (gitignored)
│   ├── api_keys.json
│   ├── app_settings.json
│   ├── voice_connect.json
│   ├── voice_connect/
│   ├── models/
│   └── create_desktop_shortcut.ps1
├── core/                    # Core infrastructure
│   ├── identity.py          # Assistant/owner identity management
│   ├── prompt.txt           # System prompt template
│   └── updater.py
├── dashboard/               # FastAPI dashboard server
│   ├── server.py
│   └── static/
├── extra/                   # Experimental/utility scripts
├── memory/                  # Memory manager (short/long-term)
│   └── memory_manager.py
├── plugins/                 # Plugin extensions (hooks: on_voice_created, on_startup, on_text_command)
├── smart_home/              # Smart home service & providers
│   ├── service.py
│   ├── smart_device_manager.py
│   ├── storage.py
│   └── providers/
├── tests/                   # Integration tests
│   ├── conftest.py
│   ├── test_voice_connect.py
│   ├── test_voice_connect_actions.py
│   ├── test_gesture_utils.py
│   └── test_screen_processor.py
├── homescreen background/   # Next.js homescreen web app
│   ├── app/, components/, lib/
│   ├── next.config.ts
│   └── package.json
├── assets/                  # Images, logos, web background
└── auth/                    # Authentication module
```

## Core Architecture

### VoiceLive (main.py:1449)

The central orchestration class. Handles:
- Voice input via `sounddevice` (16kHz send, 24kHz receive)
- Gemini Native Voice LLM with OpenRouter fallback
- Command routing to tool handlers
- Memory extraction and context building
- Task plan generation per request type
- Idle/proactive engagement
- Screen/window inspection
- Meeting mode with barge-in support
- Instagram DM monitoring and reply flow
- Attention monitoring (calls, messages)
- Smart home command dispatch
- Voice Connect device commands

### VoiceUI (ui.py:10713 / 12205)

The Qt main window with:
- Glassmorphic dark theme (gold `#ffb300` accent, dynamically recolorable)
- Background widget with WebEngine animated background or static image fallback
- Remote key overlay with QR code for phone pairing
- System metrics display
- Gesture camera preview
- HUD canvas with metric bars
- Message/task/attachment/event/artifact/chat bubbles
- Workspace sidebar, inline chat, launcher control panel
- Settings hub, system connectivity page
- Smart devices section
- Boot sequence, scanning, incoming alert, meeting overlays
- Floating launcher and gesture card

### UnifiedAIClient (llm_client.py)

Provider-agnostic AI client:
- `chat()` — text completion with Local/OpenRouter routing
- `chat_json()` — structured JSON output
- `vision()` — image analysis from base64
- `vision_from_file()` — image analysis from file path
- `multi_turn()` — conversation history support
- Falls back to OpenRouter if local AI fails

### OpenRouterClient (or_client.py)

OpenRouter API client with:
- 30+ text models + 9 vision models in fallback pool
- Rate-limit tracking with 60s cooldown
- Retry logic (2 attempts per model, 2s delay)
- JSON mode with markdown stripping
- `vision_from_file()` for file-based image analysis

### Plugin System

`plugin_manager.py` loads `.py` files from `plugins/` and dispatches hooks:
- `on_voice_created(voice)` — when assistant instance initializes
- `on_startup(voice)` — after startup when plugins registered
- `on_text_command(text, source, voice=None)` — each incoming text command; return `True` to indicate handled

### Memory System

`memory/memory_manager.py` — short-term and long-term memory with extraction, formatting, and context building for requests.

## Running the Application

```powershell
# Manual start
python main.py

# Clean startup (Windows)
start_voice.vbs

# Bootstrap installer (admin, installs Python + Node + venv + deps)
bootstrap.ps1

# Quick setup
python setup.py
```

## Development Conventions

- **Monolithic architecture**: Main logic lives in `main.py` and `ui.py` (large files, intentionally consolidated)
- **Tool-first design**: Always call the appropriate tool rather than simulate results
- **Gemini fallback chain**: Gemini Native Audio → Gemini text → OpenRouter → local AI
- **JSON config**: All settings stored in `config/*.json` (gitignored for secrets)
- **No committed secrets**: `config/api_keys.json` and `config/discord_bot.json` are in `.gitignore`
- **Virtual environment**: Required for all development and runtime (`.venv/` in `.gitignore`)
- **Windows-first**: Some paths hardcode Windows-specific locations (e.g., `pythonw.exe` in `ui.py`)
- **Testing**: `pytest` with `conftest.py` for path setup; tests in `tests/`
- **Plugin hooks**: Return `True` from `on_text_command` to indicate the command was handled and stop propagation

## Configuration Files

| File | Purpose |
|---|---|
| `config/api_keys.json` | Gemini and OpenRouter API keys |
| `config/app_settings.json` | Voice, UI, startup, automation preferences |
| `config/voice_connect.json` | Device pairing, gateway, discovery settings |
| `config/discord_bot.json` | Discord bridge credentials (gitignored) |
| `core/prompt.txt` | System prompt template loaded at startup |
| `core/identity.py` | Dynamic identity injection (assistant name, owner, role, mode) |

## Known Characteristics

- **Large files**: `main.py` (3.4K lines) and `ui.py` (12.9K lines) are intentionally consolidated; refactoring into smaller modules is out of scope unless explicitly requested
- **Windows dependency**: `start_voice.vbs`, `bootstrap.ps1`, and some `ui.py` paths assume Windows; Linux/macOS support is limited
- **Gemini API key required**: Primary AI provider; OpenRouter is fallback-only without Gemini
- **Playwright browsers**: Must run `playwright install` after `pip install -r requirements.txt`

## Community & Support

- Discord: https://discord.gg/gEYmJKKtq3
- GitHub: https://github.com/titechprabhasolutions/Voice-AI---Lite.git

## License

Custom source-available license. See `LICENSE` for details.

## Maintainer

Suryaansh Tiwari

> Preserve attribution and keep credentials secure when building on top of Voice Echo.