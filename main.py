import asyncio
import threading
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import random
import traceback
import os
import pyperclip
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import os
import sounddevice as sd
from google import genai
from google.genai import types
from ui import VoiceUI
from proxy_manager import get_httpx_client, set_proxy_url as _set_proxy
from proxy_manager import get_proxy_url
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    should_extract_memory, extract_memory
)

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.meeting_assistant import MeetingAssistant
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.website_builder   import website_builder
from actions.office_builder     import create_presentation, create_spreadsheet
from actions.docx_tools        import word_document
from actions.pdf_tools         import create_pdf
from actions.voice_connect    import (
    connect_list_devices,
    connect_get_device,
    connect_get_capabilities,
    connect_execute,
    connect_pair_device,
    connect_disconnect_device,
)
from PyQt6.QtCore import QTimer
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.attention_monitor import AttentionMonitor, speak_native, stop_native_speech, handle_call_action, read_event_preview, set_speech_sink

try:
    from local_voice import LocalTTS, LocalVoiceEngine, voice_setting_enabled
except Exception:
    LocalTTS = None
    LocalVoiceEngine = None
    voice_setting_enabled = lambda: False
# from actions.daily_briefing import compile_daily_briefing
from llm_client import client as openrouter_client
from workspace_store import store as workspace_store
from smart_home.service import SmartHomeService
from plugin_manager import PluginManager
from updater import restart_application, update_from_github

try:
    from dashboard.server import DashboardServer
except Exception:
    DashboardServer = None

try:
    from actions.instagram_chat import start_daemon as start_ig_daemon, set_ig_prompt_callback
except ImportError:
    start_ig_daemon = None

try:
    from voice_connect.service import get_service as get_voice_connect_service
except Exception:
    get_voice_connect_service = None


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
STARTUP_LOG     = Path(os.environ.get("LOCALAPPDATA", str(BASE_DIR))) / "Voice Echo" / "startup.log"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024
LIVE_CONNECT_TIMEOUT = 12


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _startup_log(message: str) -> None:
    try:
        STARTUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(STARTUP_LOG, "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception:
        pass


def _ensure_desktop_shortcut() -> None:
    if os.name != "nt":
        return

    marker_path = BASE_DIR / "config" / ".desktop_shortcut_created"
    if marker_path.exists():
        return

    try:
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
            desktop_raw, _ = winreg.QueryValueEx(key, "Desktop")
            winreg.CloseKey(key)
            desktop_dir = Path(os.path.expandvars(desktop_raw))
        except Exception:
            desktop_dir = Path(os.path.expanduser("~")) / "Desktop"
            
        desktop_dir.mkdir(parents=True, exist_ok=True)
        shortcut_path = desktop_dir / "Voice Echo.lnk"
        script_path = BASE_DIR / "main.py"
        icon_path = BASE_DIR / "assets" / "Voice_Lite_Logo.ico"

        if not icon_path.exists():
            icon_path = None

        python_exe = sys.executable
        if not python_exe:
            python_exe = shutil.which("python") or shutil.which("py") or "python"

        shortcut_target = python_exe
        shortcut_args = f'"{script_path}"'
        if getattr(sys, "frozen", False):
            shortcut_target = python_exe
            shortcut_args = ""

        powershell_exe = shutil.which("powershell.exe") or shutil.which("powershell")
        if powershell_exe is None:
            raise RuntimeError("PowerShell is not available")

        def _ps_escape(value: str) -> str:
            return value.replace("'", "''")

        icon_value = str(icon_path) if icon_path and icon_path.exists() else ""
        ps1_path = BASE_DIR / "config" / "create_desktop_shortcut.ps1"
        ps1_script = "\n".join([
            "$WshShell = New-Object -ComObject WScript.Shell",
            f"$Shortcut = $WshShell.CreateShortcut('{_ps_escape(str(shortcut_path))}')",
            f"$Shortcut.TargetPath = '{_ps_escape(shortcut_target)}'",
            f"$Shortcut.Arguments = '{_ps_escape(shortcut_args)}'",
            f"$Shortcut.WorkingDirectory = '{_ps_escape(str(BASE_DIR))}'",
            "$Shortcut.WindowStyle = 7",
            "$Shortcut.Description = 'Launch Voice Echo'",
            f"if ('{_ps_escape(icon_value)}') {{ $Shortcut.IconLocation = '{_ps_escape(icon_value)},0' }}",
            "$Shortcut.Save()",
        ])
        ps1_path.write_text(ps1_script, encoding="utf-8")

        subprocess.run(
            [powershell_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        marker_path.write_text("created", encoding="utf-8")
        _startup_log(f"desktop shortcut created at {shortcut_path}")
    except Exception as exc:
        _startup_log(f"desktop shortcut creation skipped: {exc}")


def _load_system_prompt() -> str:
    try:
        base_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        base_prompt = (
            "Ты — Voice Echo, спокойный, прямой и профессиональный ИИ-ассистент. "
            "Общайся с пользователем на русском языке и отвечай по-русски. "
            "Будь кратким и по делу, всегда используй предоставленные инструменты для выполнения задач. "
            "Никогда не симулируй и не догадывайся о результатах — всегда вызывай подходящий инструмент. "
            "Если пользователь просит создать, собрать, запустить или открыть сайт — всегда используй выбранную рабочую папку."
        )
        
    try:
        from core.identity import identity
        ast_name = identity.get_assistant_name() or "Voice Echo"
        own_name = identity.get_owner_name() or "the user"
        role = identity.get_owner_role()
        mode = identity.get_behavior_mode()
        
        identity_str = f"Ты — {ast_name}. Ты помогаешь {own_name}"
        if role:
            identity_str += f" (Роль: {role}).\n"
        else:
            identity_str += ".\n"
            
        identity_str += f"Твой текущий режим поведения: {mode}.\n"
        
        custom = identity.get_custom_instructions()
        if custom:
            identity_str += f"Пользовательские инструкции: {custom}\n\n"
            
        return identity_str + base_prompt
    except Exception as e:
        print(f"Error injecting identity: {e}")
        return base_prompt


def _speak_daily_briefing(ui=None) -> None:
    if ui and getattr(ui, "_overlay", None) and ui._overlay.isVisible():
        return
    try:
        from actions.daily_briefing import compile_daily_briefing
        from actions.attention_monitor import speak_native
        text = compile_daily_briefing()
        if ui:
            ui.show_daily_briefing(text)
            ui.write_log(f"Voice Echo: {text}")
        speak_native(text)
    except Exception as e:
        print(f"[DailyBriefing] Error: {e}")
    
def _extract_gemini_text(response) -> str:
    text_parts: list[str] = []
    try:
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []) or []:
                part_text = getattr(part, "text", None)
                if part_text:
                    text_parts.append(part_text)
    except Exception:
        pass

    text = "".join(text_parts).strip()
    if text:
        return text

    try:
        return (getattr(response, "text", "") or "").strip()
    except Exception:
        return ""


def _gemini_text_reply(prompt: str) -> str:
    client = _get_gemini_client()
    system_prompt = (
        "Ты — Voice Echo, краткий и полезный настольный ассистент. "
        "Отвечай естественно, кратко и всегда на русском языке. "
        "Не упоминай внутренние детали реализации."
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"{system_prompt}\n\nUser: {prompt}",
        config={"temperature": 0.6},
    )
    return _extract_gemini_text(response)


def _ig_gemini_reply(username: str, text: str) -> str:
    system_prompt = (
        "Ты — Voice Echo, ИИ-личный ассистент, действующий от имени своего пользователя. "
        "Ты ведёшь их чат в Instagram с разрешения пользователя. "
        "Отвечай естественно, кратко и по-русски, живому собеседнику. "
        "Не звучи как бот. Держи ответы короче двух предложений."
    )
    prompt = f"Instagram DM from {username}: {text}"
    
    try:
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"},
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{system_prompt}\n\nUser: {prompt}",
            config={"temperature": 0.6},
        )
        return _extract_gemini_text(response)
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or _is_gemini_limit_error(e):
            print("[InstagramChat] Gemini Rate Limit hit, falling back to OpenRouter...")
            try:
                from llm_client import client as openrouter_client
                return openrouter_client.chat(prompt, system=system_prompt)
            except Exception as or_e:
                print(f"[InstagramChat] OpenRouter fallback failed: {or_e}")
                return "Hey, I'm currently busy. I will get back to you later!"
        print(f"[InstagramChat] Gemini Reply Error: {e}")
        return "Hey, I'm currently busy. I will get back to you later!"


def _clipboard_gemini_reply(text: str) -> str:
    system_prompt = (
        "Ты — Voice Echo, остроумный и полезный ИИ-ассистент. "
        "Пользователь только что скопировал в буфер обмена следующий текст. "
        "Сделай очень короткий, интересный или полезный комментарий или вопрос об этом (одно предложение). "
        "Не предлагай «помощь» и не спрашивай «чем помочь» — просто дай самостоятельное остроумное наблюдение или краткую суть на русском языке."
    )
    prompt = text
    try:
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"},
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{system_prompt}\n\nClipboard Text: {prompt}",
            config={"temperature": 0.8},
        )
        return _extract_gemini_text(response)
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or _is_gemini_limit_error(e):
            try:
                from llm_client import client as openrouter_client
                return openrouter_client.chat(prompt, system=system_prompt)
            except Exception:
                pass
        return "Interesting stuff you copied there!"


def _looks_like_code_request(text: str) -> bool:
    low = (text or "").lower()
    code_words = (
        "build", "create", "write", "implement", "code", "python", "app",
        "module", "function", "class", "project", "script", "api",
        "ui", "webpage", "bot", "server", "service"
    )
    return any(word in low for word in code_words)


def _looks_like_website_request(text: str) -> bool:
    low = (text or "").lower()
    website_words = (
        "website",
        "web site",
        "landing page",
        "homepage",
        "home page",
        "portfolio",
        "product site",
        "business site",
        "marketing site",
        "web app",
        "frontend",
        "site",
    )
    return any(word in low for word in website_words)


def _is_gemini_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in (
        "429",
        "resource_exhausted",
        "quota",
        "rate limit",
        "too many requests",
        "exceeded",
        "1008",
        "access denied",
        "permission denied",
    ))


def _is_network_unreachable(exc: Exception) -> bool:
    """Return True for network errors that won't recover by retrying (DNS/proxy/host misconfiguration)."""
    msg = str(exc).lower()
    return any(token in msg for token in (
        "no route to host",
        "net unreachable",
        "host unreachable",
        "connection refused",
        "name or service not known",
        "nodename nor servname",
        "temporary failure in name resolution",
        "eai_again",
        "eai_nodata",
        "errno 113",
        "errno 101",
    ))


def _looks_like_screen_request(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    direct_phrases = (
        "what's on my screen",
        "whats on my screen",
        "what is on my screen",
        "check my screen",
        "look at my screen",
        "analyze my screen",
        "analyse my screen",
        "tell me what's on my screen",
        "tell me what is on my screen",
        "read my screen",
        "what does my screen say",
    )
    if any(p in t for p in direct_phrases):
        return True
    screen_words = ("screen", "display", "monitor", "window")
    request_words = ("what", "check", "look", "analy", "analyse", "analyze", "read", "tell", "answer", "see")
    return any(sw in t for sw in screen_words) and any(rw in t for rw in request_words)


def _wakeword_detected(text: str) -> bool:
    t = re.sub(r"[^a-z0-9\s]+", " ", (text or "").lower())
    words = [w for w in t.split() if w]
    if not words:
        return False
    phrases = (
        "voice echo",
        "hey voice echo",
        "hi voice echo",
        "hello voice echo",
        "hey",
        "hi",
        "hello",
    )
    compact = " ".join(words)
    if compact in phrases or any(p in compact for p in phrases):
        return True
    return any(word in {"voice echo", "hey", "hi", "hello"} for word in words)


def _build_task_plan(text: str) -> list[str]:
    t = (text or "").lower()
    if any(word in t for word in ("presentation", "ppt", "slides", "deck")):
        return [
            "Понять тему и цель",
            "Построить структуру слайдов",
            "Сгенерировать и оформить презентацию",
            "Открыть готовую презентацию",
        ]
    if any(word in t for word in ("spreadsheet", "excel", "sheet", "table", "tracker", "budget")):
        return [
            "Разобрать запрос по данным",
            "Составить листы и колонки",
            "Применить формулы и форматирование",
            "Открыть таблицу",
        ]
    if any(word in t for word in ("word", "docx", "document", "report", "letter")):
        return [
            "Определить тип документа",
            "Подготовить структуру и содержание",
            "Сохранить форматирование",
            "Сохранить редактируемый файл",
        ]
    if any(word in t for word in ("website", "web site", "landing page", "saaS", "saas", "dashboard", "app")):
        return [
            "Интерпретировать задание",
            "Создать файлы фронтенда и бэкенда",
            "Запустить локальный предпросмотр",
            "Отладить проблемы запуска при необходимости",
        ]
    if any(word in t for word in ("browser", "website", "google", "search", "open url", "navigate")):
        return [
            "Открыть браузер",
            "Перейти на нужную страницу",
            "Собрать необходимую информацию",
            "Сообщить результат",
        ]
    if any(word in t for word in ("screen", "camera", "meeting", "call", "analyze", "analyse", "analyze")):
        return [
            "Захватить живой экран или камеру",
            "Изучить, что видно на экране",
            "Ответить с важными деталями",
            "Продолжать слушать дальнейшие команды",
        ]
    if any(word in t for word in ("fan", "light", "plug", "kasa", "atomberg", "smart home", "home device", "room", "bedroom", "living room", "kitchen", "office", "bathroom", "balcony")):
        return [
            "Определить устройство или комнату",
            "Выбрать нужное действие",
            "Отправить команду подключённому провайдеру",
            "Сообщить пользователю результат",
        ]
    return [
        "Понять команду",
        "Выбрать нужный инструмент",
        "Выполнить задачу",
        "Сообщить результат",
    ]


_last_memory_input = ""

def _update_memory_async(user_text: str, voice_text: str) -> None:
    global _last_memory_input

    user_text   = (user_text   or "").strip()
    voice_text = (voice_text or "").strip()

    if len(user_text) < 5 or user_text == _last_memory_input:
        return
    _last_memory_input = user_text

    try:
        api_key = _get_api_key()
        if not should_extract_memory(user_text, voice_text, api_key):
            return
        data = extract_memory(user_text, voice_text, api_key)
        if data:
            update_memory(data)
            print(f"[Memory] ✅ {list(data.keys())}")
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ {e}")

def _memory_context_for_request(text: str) -> str:
    try:
        return workspace_store().memory_context(text, limit=5)
    except Exception:
        return ""


TOOL_DECLARATIONS = [
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer's OS-level settings and hardware. Use this to change brightness, "
            "toggle Wi-Fi, change volume, lock the screen, sleep the display, or shut down/restart the computer. "
            "Also handles keyboard inputs (scrolling, typing, taking screenshots, window snapping)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Specific action if known (e.g., 'volume_up', 'volume_set', 'brightness_down', 'lock_screen', 'shutdown')"
                },
                "description": {
                    "type": "STRING",
                    "description": "Natural language description of what to do (e.g., 'turn the volume to 50%', 'put the computer to sleep')"
                },
                "value": {
                    "type": "STRING",
                    "description": "Any value associated with the action (e.g., '50' for volume level)"
                },
                "confirmed": {
                    "type": "STRING",
                    "description": "Pass 'yes' if the user explicitly confirmed a dangerous action like 'shutdown' or 'restart'."
                }
            },
            "required": []
        }
    },
    {
        "name": "dev_agent",
        "description": (
            "An autonomous coding agent that builds full projects, writes code, installs dependencies, "
            "runs the project, and automatically fixes errors. Use this when the user asks you to 'write a script', "
            "'build an app', 'code a program', or 'run a project'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description": {
                    "type": "STRING",
                    "description": "A very detailed description of what the project should do."
                },
                "language": {
                    "type": "STRING",
                    "description": "The programming language to use (e.g., 'python', 'javascript')"
                },
                "project_name": {
                    "type": "STRING",
                    "description": "A short, snake_case name for the project folder."
                }
            },
            "required": ["description"]
        }
    },
    {
        "name": "background_monitor",
        "description": (
            "Sets up a background monitor to check crypto prices, system RAM/CPU, or website uptime. "
            "Use this when the user asks to be alerted when a condition is met (e.g., 'tell me if RAM goes over 90%' or 'alert me if bitcoin drops below 50000')."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "'add' to create a monitor (default), 'list' to see active monitors."
                },
                "type": {
                    "type": "STRING",
                    "description": "One of: 'system', 'crypto', 'website'"
                },
                "target": {
                    "type": "STRING",
                    "description": "What to monitor (e.g. 'ram', 'cpu', 'bitcoin', 'https://example.com')"
                },
                "threshold": {
                    "type": "NUMBER",
                    "description": "The threshold value (e.g. 90 for 90%, 50000 for $50k)"
                },
                "condition": {
                    "type": "STRING",
                    "description": "'above' or 'below'"
                },
                "interval": {
                    "type": "INTEGER",
                    "description": "How often to check in seconds (default 60)"
                }
            },
            "required": []
        }
    },
    {
        "name": "system_manager",
        "description": (
            "Checks the system health (CPU, RAM, disk, battery) and lists top resource-hogging apps. "
            "Can also be used to forcefully close or kill frozen or heavy applications."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "What to do: 'status' to check system health (default), or 'kill' to close an app."
                },
                "process_name": {
                    "type": "STRING",
                    "description": "The exact name of the process to kill (if action is 'kill'), e.g. 'chrome.exe' or 'Spotify'"
                },
                "pid": {
                    "type": "INTEGER",
                    "description": "The PID of the process to kill (if action is 'kill')"
                }
            },
            "required": []
        }
    },
    {
        "name": "check_instagram_messages",
        "description": (
            "Checks your Instagram inbox for any recent unread or direct messages. "
            "Use this when the user asks 'do I have any messages', 'check my instagram', or similar."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "clipboard_processor",
        "description": (
            "Instantly reads the current text copied to the user's Windows clipboard. "
            "Use this whenever the user asks you to read, analyze, or fix what they just copied to their clipboard."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "instagram_reply",
        "description": "Replies to a pending Instagram message or takes over the Instagram chat in auto-mode.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Must be 'take_over' to handle it automatically, or 'manual_reply' to send a specific text message."
                },
                "reply_text": {
                    "type": "STRING",
                    "description": "The exact message to send to the user if action is 'manual_reply'."
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "open_app",
        "description": (
            "Opens any application on the Windows computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) or compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, Instagram DMs, or other messaging platform. Can also upload media to Instagram when mode=upload and media_path is supplied.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name for DMs"},
                "message_text": {"type": "STRING", "description": "The message to send or Instagram caption"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, Instagram, etc."},
                "mode":         {"type": "STRING", "description": "dm | upload (Instagram only; default: dm)"},
                "media_path":   {"type": "STRING", "description": "Optional image/video path for Instagram uploads"}
            },
            "required": ["platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "smart_home_control",
        "description": (
            "Controls connected smart-home devices such as Atomberg fans and TP-Link Kasa lights/plugs. "
            "Use when the user asks to turn devices on or off, set fan speed, change brightness, or control a room."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {"type": "STRING", "description": "Natural language smart-home command"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "connect_list_devices",
        "description": (
            "Lists devices connected to Voice Connect. Use when the user asks what devices are connected, "
            "what is online, or wants a simple inventory of paired devices."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "connect_get_device",
        "description": (
            "Gets the details for one connected device by name, id, or natural reference such as my phone, "
            "my laptop, my PC, or my tablet."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "device": {"type": "STRING", "description": "Device name, id, or natural reference"},
                "target": {"type": "STRING", "description": "Alias for device"},
                "device_id": {"type": "STRING", "description": "Exact device id"},
                "name": {"type": "STRING", "description": "Exact device name"},
                "query": {"type": "STRING", "description": "Search query"},
            },
            "required": ["device"]
        }
    },
    {
        "name": "connect_get_capabilities",
        "description": (
            "Returns the capabilities and permissions reported by a connected device. "
            "Use before trying any device command."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "device": {"type": "STRING", "description": "Device name, id, or natural reference"},
                "target": {"type": "STRING", "description": "Alias for device"},
                "device_id": {"type": "STRING", "description": "Exact device id"},
                "name": {"type": "STRING", "description": "Exact device name"},
                "query": {"type": "STRING", "description": "Search query"},
            },
            "required": ["device"]
        }
    },
    {
        "name": "connect_execute",
        "description": (
            "Routes a Voice Connect command to a paired device through the gateway. "
            "Use for actions such as launch_app, open_url, get_battery, capture_screen, take_photo, "
            "clipboard_get, clipboard_set, send_file, receive_file, media_play, media_pause, volume_set, "
            "notification_list, get_device_info, close_app, mouse_move, keyboard_type, unlock_phone, file_list, file_read, file_write, file_delete."
            "Do not execute device operations directly anywhere else."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "device": {"type": "STRING", "description": "Target device name, id, or natural reference"},
                "target": {"type": "STRING", "description": "Alias for device"},
                "device_id": {"type": "STRING", "description": "Exact device id"},
                "name": {"type": "STRING", "description": "Exact device name"},
                "query": {"type": "STRING", "description": "Search query"},
                "action": {"type": "STRING", "description": "Command to execute on the device"},
                "parameters": {"type": "OBJECT", "description": "Action parameters"},
            },
            "required": ["device", "action"]
        }
    },
    {
        "name": "unlock_device",
        "description": "Unlocks a paired Android device using its saved PIN.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "target": {"type": "STRING", "description": "Device name or ID to unlock"}
            },
            "required": ["target"]
        }
    },
    {
        "name": "connect_pair_device",
        "description": (
            "Creates or approves Voice Connect pairing. Use to generate a QR code / pairing code for a new device, "
            "or to approve a pending pairing request."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "device_name": {"type": "STRING", "description": "Optional device name shown in the pairing flow"},
                "platform": {"type": "STRING", "description": "android | windows | ios | tablet | other"},
                "pending_id": {"type": "STRING", "description": "Pending request id to approve"},
            },
            "required": []
        }
    },
    {
        "name": "connect_disconnect_device",
        "description": (
            "Disconnects a device from Voice Connect and marks it offline. "
            "Use when the user asks to disconnect, log out, or stop a paired device."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "device": {"type": "STRING", "description": "Target device name, id, or natural reference"},
                "target": {"type": "STRING", "description": "Alias for device"},
                "device_id": {"type": "STRING", "description": "Exact device id"},
                "name": {"type": "STRING", "description": "Exact device name"},
                "query": {"type": "STRING", "description": "Search query"},
                "reason": {"type": "STRING", "description": "Optional reason for disconnect"},
            },
            "required": ["device"]
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls the web browser. Use for: opening websites, searching the web, "
            "navigating pages, clicking elements, filling forms, scrolling, tabs, back/forward, "
            "refreshing, and any web-based task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | navigate | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | back | forward | refresh | open_tab | new_tab | switch_tab | list_tabs | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up or down for scroll"},
                "key":         {"type": "STRING", "description": "Key name for press action"},
                "tab":         {"type": "INTEGER", "description": "1-based tab index for switch_tab"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": (
            "Manages files and folders: open, close, list, create, delete, move, copy, rename, read, write, find, disk usage, "
            "and organizing a desktop or any folder into subfolders by type/date. Can also be used to explore and manage files on a connected Android phone."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "open | close | list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | organize_folder | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home. For android, use paths like downloads, documents, photos, movies, root."},
                "target":      {"type": "STRING", "description": "If operating on an Android device, provide the device name or ID. Leave empty for PC local files."},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
                "mode":        {"type": "STRING", "description": "by_type or by_date for organize actions"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic — use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "file_processor",
        "description": (
            "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
            "text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
            "ALWAYS call this tool when a non-Word file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx via word_document; txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
        }
    },
    {
        "name": "presentation_builder",
        "description": (
            "Creates editable PowerPoint presentations (.pptx) from a structured slide outline. "
            "Voice Echo automatically infers the best visual style from the topic, searches for a matching online template when available, "
            "reuses cached templates, and falls back to the built-in designer if no suitable template is found. "
            "Use when the user asks for a deck, slideshow, presentation, pitch deck, or report slides."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING", "description": "Presentation title"},
                "subtitle": {"type": "STRING", "description": "Optional subtitle or audience line"},
                "theme": {
                    "type": "STRING",
                    "description": "Optional presentation theme or visual direction such as neon, corporate, luxury, academic, sunset, or creative. If omitted, Voice Echo infers the best style automatically."
                },
                "outline": {
                    "type": "STRING",
                    "description": "Slide-by-slide outline. Use blank lines to separate slides if slides array is omitted."
                },
                "slides": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "title": {"type": "STRING", "description": "Slide title"},
                            "kicker": {"type": "STRING", "description": "Short all-caps kicker"},
                            "bullets": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"},
                                "description": "Bullet points for the slide"
                            },
                            "notes": {"type": "STRING", "description": "Optional speaker note or footnote"}
                        },
                        "required": ["title"]
                    },
                    "description": "Structured slides. Preferred when the model can format the deck directly."
                },
                "output_path": {"type": "STRING", "description": "Optional output path for the .pptx"},
                "auto_open": {"type": "BOOLEAN", "description": "Open the file after creating it (default: true)"},
            },
            "required": ["title"]
        }
    },
    {
        "name": "spreadsheet_builder",
        "description": (
            "Creates editable Excel workbooks (.xlsx) from structured sheet data. "
            "Use for trackers, tables, analysis workbooks, budgets, planners, and other spreadsheet requests."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING", "description": "Workbook title"},
                "worksheets": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "name": {"type": "STRING", "description": "Worksheet name"},
                            "title": {"type": "STRING", "description": "Optional sheet title row"},
                            "headers": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"},
                                "description": "Column headers"
                            },
                            "rows": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "ARRAY",
                                    "items": {"type": "STRING"},
                                },
                                "description": "Data rows"
                            },
                            "chart": {
                                "type": "OBJECT",
                                "properties": {
                                    "type": {"type": "STRING", "description": "bar | line | pie"},
                                    "title": {"type": "STRING", "description": "Chart title"},
                                    "anchor": {"type": "STRING", "description": "Cell anchor such as E2"},
                                    "x_axis": {"type": "STRING", "description": "Optional x-axis title"},
                                    "y_axis": {"type": "STRING", "description": "Optional y-axis title"},
                                }
                            }
                        },
                        "required": ["name"]
                    },
                    "description": "One or more worksheets to create."
                },
                "output_path": {"type": "STRING", "description": "Optional output path for the .xlsx"},
                "auto_open": {"type": "BOOLEAN", "description": "Open the file after creating it (default: true)"},
            },
            "required": ["title"]
        }
    },
    {
        "name": "word_document",
        "description": (
            "Creates, edits, reads, summarizes, extracts text from, and opens editable Word documents (.docx). "
            "Use for Word document requests, letters, reports, headings, bullets, formatting edits, and preserving existing formatting."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "create | create_letter | create_report | read | summarize | extract_text | append | replace_text | add_heading | add_bullets | reformat | open"
                },
                "file_path": {"type": "STRING", "description": "Existing .docx file path for read/edit/open actions"},
                "output_path": {"type": "STRING", "description": "Optional output path for the saved .docx"},
                "title": {"type": "STRING", "description": "Document title"},
                "doc_type": {"type": "STRING", "description": "letter | report | generic"},
                "content": {"type": "STRING", "description": "Main body content or text to append"},
                "body": {"type": "STRING", "description": "Body text for letter/report creation"},
                "paragraphs": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Paragraphs to add"},
                "bullets": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Bullet items to add"},
                "numbered": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Numbered items to add"},
                "sections": {"type": "ARRAY", "items": {"type": "OBJECT"}, "description": "Structured sections with heading/body/bullets"},
                "replacements": {"type": "OBJECT", "description": "Find/replace mapping for formatting-preserving edits"},
                "find": {"type": "STRING", "description": "Text to find for simple replace_text edits"},
                "replace": {"type": "STRING", "description": "Replacement text for simple replace_text edits"},
                "heading": {"type": "STRING", "description": "Heading text to append"},
                "level": {"type": "INTEGER", "description": "Heading level 1-3"},
                "recipient": {"type": "STRING", "description": "Letter recipient"},
                "salutation": {"type": "STRING", "description": "Custom letter salutation"},
                "closing": {"type": "STRING", "description": "Custom letter closing"},
                "date": {"type": "STRING", "description": "Letter date"},
                "author": {"type": "STRING", "description": "Document author"},
                "subject": {"type": "STRING", "description": "Document subject"},
                "open_after": {"type": "BOOLEAN", "description": "Open the saved document after writing (default: true)"},
                "save": {"type": "BOOLEAN", "description": "Save large generated summaries to a text file"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "pdf_document",
        "description": (
            "Creates editable-style PDF documents (.pdf) from structured content or converts DOCX / text files into PDFs. "
            "Use for PDF creation, PDF exports, and PDF generation requests that need a direct file output."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "create | create_report | create_letter | convert"
                },
                "file_path": {"type": "STRING", "description": "Existing file to convert, typically .docx or .txt"},
                "output_path": {"type": "STRING", "description": "Optional output path for the saved .pdf"},
                "title": {"type": "STRING", "description": "PDF title"},
                "subtitle": {"type": "STRING", "description": "Optional subtitle"},
                "content": {"type": "STRING", "description": "Main body content"},
                "body": {"type": "STRING", "description": "Main body content"},
                "paragraphs": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Paragraphs to add"},
                "bullets": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Bullet items to add"},
                "numbered": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Numbered items to add"},
                "sections": {"type": "ARRAY", "items": {"type": "OBJECT"}, "description": "Structured sections with heading/body/bullets"},
                "recipient": {"type": "STRING", "description": "Letter recipient"},
                "salutation": {"type": "STRING", "description": "Custom letter salutation"},
                "closing": {"type": "STRING", "description": "Custom letter closing"},
                "date": {"type": "STRING", "description": "Letter date"},
                "author": {"type": "STRING", "description": "Document author"},
                "subject": {"type": "STRING", "description": "Document subject"},
                "auto_open": {"type": "BOOLEAN", "description": "Open the file after creating it (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "shutdown_voice",
        "description": (
            "Shuts down the assistant completely. "
        "Call this when the user expresses intent to end the conversation, "
        "close the assistant, say goodbye, or stop Voice Echo. "
        "The user can say this in ANY language."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Suryaansh, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "spotify_controller",
        "description": (
            "Plays and controls music via Spotify and Google Chrome. "
            "ALWAYS use this tool whenever the user asks to play any song, music, track, or artist "
            "(e.g. 'play Starboy', 'play music on Spotify'), or control playback "
            "('pause the music', 'resume', 'skip song', 'next track', 'volume up', 'volume down', 'mute'). "
            "Do NOT use open_app for playing songs."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "search_play | play | pause | toggle | next | previous | volume_up | volume_down | mute | open_spotify (default: search_play)"
                },
                "query": {
                    "type": "STRING",
                    "description": "Song title, artist name, album, or playlist to search and play"
                },
                "volume": {
                    "type": "NUMBER",
                    "description": "Volume level (optional)"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "calendar_scheduler",
        "description": (
            "Manages calendar events, appointments, and schedules. "
            "Use whenever the user asks to schedule a meeting, check upcoming events, "
            "view schedule for today/tomorrow, or remove an event."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "add_event | list_events | check_day | delete_event | get_upcoming | export_ics"
                },
                "title": {
                    "type": "STRING",
                    "description": "Title or summary of the meeting/event"
                },
                "date": {
                    "type": "STRING",
                    "description": "Date (YYYY-MM-DD or 'today', 'tomorrow')"
                },
                "time": {
                    "type": "STRING",
                    "description": "Time (HH:MM in 24h format, e.g. '14:30')"
                },
                "duration_minutes": {
                    "type": "NUMBER",
                    "description": "Duration in minutes (default: 30)"
                },
                "location": {
                    "type": "STRING",
                    "description": "Location or meeting link (optional)"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "daily_briefing",
        "description": (
            "Delivers a complete daily briefing including time, date, today's schedule/calendar events, "
            "and top world & tech headlines. Use whenever the user asks for their daily briefing, morning update, "
            "or what's happening today."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": "Optional news category: all (default), tech, world"
                }
            },
            "required": []
        }
    },
]


class VoiceLive:

    def __init__(self, ui: VoiceUI, dashboard=None, dashboard_started: bool = False, enable_dashboard: bool = True):
        self.ui             = ui
        self._smart_home    = SmartHomeService()
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._use_openrouter_first = False
        self._local_voice_enabled = False
        self._local_tts = LocalTTS() if LocalTTS is not None else None
        self._local_engine = None
        try:
            if LocalVoiceEngine is not None and voice_setting_enabled():
                stt_ok = False
                try:
                    from local_voice import LocalSTT
                    stt_ok = LocalSTT().available
                except Exception:
                    stt_ok = False
                tts_ok = bool(self._local_tts is not None and self._local_tts.available)
                self._local_voice_enabled = stt_ok or tts_ok
        except Exception:
            self._local_voice_enabled = False
        if self._local_voice_enabled:
            # Local mode: never prefer Google for the chat brain either
            # (Gemini text generation falls back to OpenRouter automatically).
            self._use_openrouter_first = True
        self._pending_attention: dict | None = None
        self._pending_reply_event: dict | None = None
        self._reply_mode = False
        self._attention_lock = threading.Lock()
        self._attention_monitor = AttentionMonitor(on_event=self._on_external_notification)
        try:
            set_speech_sink(self.speak)
        except Exception:
            pass
            
        try:
            from actions.background_monitor import set_monitor_speech_sink
            set_monitor_speech_sink(self.speak)
        except Exception as e:
            print(f"[Main] Failed to init background monitor: {e}")
        self._meeting_lock = threading.Lock()
        self._meeting_active = False
        self._meeting_event: dict | None = None
        self._meeting_assistant = MeetingAssistant(
            on_update=self._on_meeting_update,
            on_state=self._on_meeting_state,
        )
        self._phone_active = False
        self._dashboard = dashboard if dashboard is not None else (DashboardServer() if (enable_dashboard and DashboardServer is not None) else None)
        self._dashboard_started = bool(dashboard_started and self._dashboard is not None)
        self.ui.on_text_command = self._on_text_command
        self.ui.on_attention_action = self._on_attention_action
        self.ui.on_remote_clicked = self._make_remote_key
        self._last_activity = time.monotonic()
        self._idle_prompts = [
            "Hey, you there?",
            "Yo, get alive.",
            "How may I help, bro?",
            "Need anything?",
            "I'm here if you want me.",
        ]
        self._idle_speech_thread = threading.Thread(target=self._idle_speech_loop, daemon=True)
        self._idle_speech_thread.start()

    def _reset_idle_activity(self):
        self._last_activity = time.monotonic()

    def _should_announce_idle(self) -> bool:
        if self.ui.muted:
            return False
        if self._is_speaking:
            return False
        if self._meeting_active:
            return False
        if self._pending_attention:
            return False
        if time.monotonic() - self._last_activity < 240:
            return False
        return True

    def _idle_speech_loop(self):
        try:
            from actions.proactive import ProactiveEngine
            engine = ProactiveEngine(min_silence_secs=300, check_cooldown=600)  # Shorter defaults for testing
        except ImportError:
            engine = None

        while True:
            time.sleep(60.0)
            if not engine:
                continue
            
            try:
                if self.ui.muted or self._is_speaking or self._meeting_active or self._pending_attention:
                    continue
                
                # Check if it should trigger using the engine's time monotonic logic
                if engine.should_trigger(self._last_activity):
                    engine.mark_triggered()
                    prompt = engine.build_prompt(memory={})
                    
                    if self.session and self._loop:
                        import asyncio
                        async def _send():
                            try:
                                await self.session.send(input=prompt, end_of_turn=True)
                            except Exception as e:
                                print(f"[Proactive] Error: {e}")
                        asyncio.run_coroutine_threadsafe(_send(), self._loop)
                        self._reset_idle_activity()
                    
            except Exception as e:
                print(f"[Proactive] Error: {e}")

    def _make_remote_key(self):
        if self._dashboard is None:
            self.ui.write_log("ERR: Mobile Connect недоступен. Установите fastapi, uvicorn, cryptography и qrcode[pil].")
            return None
        key = self._dashboard.new_key()
        url = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, f"{url}/auto-login?key={key}", manual

    def _on_phone_connected(self):
        try:
            self.ui.notify_phone_connected()
        except Exception:
            pass

    def _on_text_command(self, text: str, source: str = "local"):
        self._reset_idle_activity()
        text = (text or "").strip()
        if not text:
            return
        try:
            stop_native_speech()
        except Exception:
            pass
        # allow plugins to handle the incoming text command first
        try:
            pm = getattr(self, "plugin_manager", None)
            if pm is not None:
                handled = pm.dispatch("on_text_command", text, source)
                if handled:
                    return
        except Exception:
            pass
        if self._reply_mode:
            if self._handle_pending_reply(text):
                return
            # Still in reply mode but no pending reply event means reset and continue
            self._reply_mode = False

        if getattr(self, "_ig_reply_mode", False):
            if self._handle_ig_reply_flow(text):
                return

        if getattr(self, "_email_mode", False):
            if self._handle_email_flow(text):
                return

        # Check for email command initiation
        lower = text.lower()
        if lower.startswith("email ") or lower.startswith("mail ") or "send email" in lower or "write email" in lower or "compose email" in lower:
            # Extract recipient
            rem = text
            for prefix in ("send email", "send an email", "write email", "write an email", "compose email", "compose an email", "email", "mail"):
                if rem.lower().strip().startswith(prefix):
                    rem = rem.strip()[len(prefix):].strip()
                    break
            
            # Remove leading "to " if present
            if rem.lower().startswith("to "):
                rem = rem[3:].strip()
                
            recipient = rem.strip()
            self._email_mode = True
            self._email_recipient = recipient
            
            try:
                self.ui.begin_task_workspace(
                    text,
                    [
                        "Определить получателя",
                        "Выбрать почтовое приложение",
                        "Собрать текст сообщения",
                        "Открыть приложение и составить письмо",
                    ],
                    source=source or "local",
                )
            except Exception:
                pass
                
            if not recipient:
                self._email_step = 0
                prompt = "Кому вы хотите отправить письмо?"
                self.ui.write_log(f"Voice Echo: {prompt}")
                self.speak(prompt)
                try:
                    self.ui.update_task_workspace(
                        status="Определение получателя",
                        output="Запрашиваю получателя письма...",
                        percent=10,
                    )
                except Exception:
                    pass
            else:
                self._email_step = 1
                prompt = "Каким почтовым приложением воспользоваться? (Gmail, стандартная почта и т. д.)"
                self.ui.write_log(f"Voice Echo: {prompt}")
                self.speak(prompt)
                try:
                    self.ui.update_task_workspace(
                        status="Выбор почтового приложения",
                        output=f"Получатель: {recipient}. Запрашиваю почтовое приложение...",
                        percent=25,
                    )
                except Exception:
                    pass
            return

        try:
            from smart_home.smart_device_manager import SmartDeviceManager
            sd_mgr = SmartDeviceManager()
            devices = self._smart_home.list_devices()
            routed_text_home = sd_mgr.route_command(text, devices)
            if routed_text_home != text:
                print(f"[VOICE ECHO] Redirection: '{text}' -> '{routed_text_home}'")
                text = routed_text_home
        except Exception as e:
            print(f"[VOICE ECHO] Redirection error: {e}")

        developer_settings = self.ui._load_app_settings() if hasattr(self.ui, "_load_app_settings") else {}
        developer_enabled = bool(developer_settings.get("developer_mode_enabled", False))
        developer_workspace = str(developer_settings.get("developer_mode_workspace", "")).strip()
        website_request = _looks_like_website_request(text)
        if website_request and not (developer_enabled and developer_workspace):
            message = "Website builds need developer mode enabled and a workspace folder selected first."
            self.ui.write_log(f"ERR: {message}")
            self.speak(message)
            return

        if website_request and developer_enabled and developer_workspace:
            try:
                self.speak("Собираю ваш сайт...")
                if hasattr(self.ui, "_developer_status_lbl"):
                    self.ui._developer_status_lbl.setText("Building website with Gemini in the selected workspace")
                    self.ui._developer_card.show()
                    self.ui._developer_card.raise_()
                result = website_builder(
                    parameters={
                        "action": "create",
                        "description": text,
                        "title": text,
                        "output_dir": developer_workspace,
                        "auto_open": True,
                    },
                    player=self.ui,
                )
                self.ui.write_log(f"[WebsiteBuilder] {result[:400]}")
                self.speak(result[:800])
                return
            except Exception as exc:
                self.ui.write_log(f"ERR: Не удалось собрать сайт: {exc}")

        memory_ctx = _memory_context_for_request(text)
        routed_text = f"{memory_ctx}\n\nCurrent User Request:\n{text}" if memory_ctx else text
        if source == "instagram":
            routed_text = f"Owner sent this via Instagram DM: {text}\n(SYSTEM: If this is an action like opening an app or running a command, you MUST execute it using your tools rather than just replying with text.)"
        if text.lower() in {"stop meeting mode", "end meeting mode", "close meeting mode"}:
            self._stop_meeting_mode("Режим встречи закрыт.")
            return
        if self._handle_attention_response(text):
            return
        try:
            self.ui.begin_task_workspace(text, _build_task_plan(text), source=source or "local")
        except Exception:
            pass
        if source != "instagram" and self._handle_voice_connect_command(text, source=source or "local"):
            return
        if self._handle_smart_home_command(text, source=source or "local"):
            return
        if _looks_like_screen_request(text):
            try:
                self.ui.update_task_workspace(
                    status="Анализ экрана",
                    output="Voice Echo изучает экран по вашему запросу.",
                    percent=40,
                )
            except Exception:
                pass
            print("[Main] Screen analysis request received")
            img_bytes = None
            if hasattr(self.ui, "capture_screen_bytes"):
                print("[Main] Capturing screenshot from UI")
                img_bytes = self.ui.capture_screen_bytes()
                print(f"[Main] UI screenshot capture returned {len(img_bytes) if img_bytes is not None else 'None'} bytes")
            else:
                print("[Main] UI object has no capture_screen_bytes method")

            def _run_screen_process():
                print("[Main] Starting screen_process thread")
                success = screen_process(
                    parameters={"angle": "screen", "text": text},
                    response=None,
                    player=self.ui,
                    session_memory=None,
                    image_bytes=img_bytes,
                )
                print(f"[Main] screen_process finished: {success}")
                if not success:
                    try:
                        self.ui.update_task_workspace(
                            status="Не удалось проанализировать экран",
                            output=(
                                "Не удалось завершить анализ экрана. "
                                "Проверьте подключение к интернету, API-ключ или разрешения на запись экрана."
                            ),
                            percent=0,
                        )
                    except Exception:
                        pass

            threading.Thread(target=_run_screen_process, daemon=True).start()
            return
        if self._use_openrouter_first or not self._loop or not self.session:
            threading.Thread(target=self._fallback_reply, args=(text, memory_ctx), daemon=True).start()
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": routed_text}]},
                turn_complete=True
            ),
            self._loop
        )


    def _handle_smart_home_command(self, text: str, source: str = "local") -> bool:
        normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s%]", " ", text.lower())).strip()
        connect_words = (
            "phone", "mobile", "android", "tablet", "device", "devices", "voice connect",
            "my phone", "my mobile", "my tablet", "my android", "turn on flashlight", "flashlight",
            "volume", "open url", "launch app", "get battery", "device info",
        )
        smart_home_words = (
            "fan", "light", "lights", "lamp", "plug", "switch", "socket", "bulb",
            "kasa", "atomberg", "room", "bedroom", "living room", "kitchen", "office",
            "balcony", "bathroom", "home device", "smart home", "smart-home",
        )
        action_words = ("turn on", "turn off", "switch on", "switch off", "power on", "power off", "set", "speed", "brightness", "restart", "reboot", "toggle")
        if any(word in normalized for word in connect_words):
            return False
        if not any(word in normalized for word in smart_home_words) and not any(word in normalized for word in action_words):
            return False
        try:
            result = self._smart_home.execute_command(text)
            detail = str(result.get("detail") or "Команда умного дома выполнена.")
            title = f"Умный дом: {result.get('action', 'управление')}"
            plan = [
                "Определить устройство или комнату",
                "Отправить команду в умный дом",
                "Проверить новое состояние",
                "Сообщить результат",
            ]
            self.ui.update_task_workspace(
                title=title,
                command=text,
                plan=plan,
                status="Выполнение команды умного дома",
                output=detail,
                percent=100,
                source=source,
            )
            self.ui.write_log(f"Voice Echo: {detail}")
            self.speak(detail)
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return True
        except Exception as exc:
            message = f"Не удалось управлять устройством умного дома: {exc}"
            self.ui.write_log(f"ERR: {message}")
            self.ui.update_task_workspace(
                title="Управление умным домом",
                command=text,
                plan=[
                    "Определить устройство или комнату",
                    "Отправить команду в умный дом",
                    "Проверить новое состояние",
                ],
                status="Команда умного дома не выполнена",
                output=message,
                percent=100,
                source=source,
            )
            self.speak(message)
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return True

    def _extract_launch_app_name(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s%]", " ", text.lower())).strip()
        if not normalized:
            return ""

        prefixes = (
            "launch app ",
            "open app ",
            "start app ",
            "open the app ",
            "launch the app ",
            "start the app ",
            "open ",
            "launch ",
            "start ",
            "run ",
            "bring up ",
        )

        candidate = normalized
        for prefix in prefixes:
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix):]
                break

        candidate = re.sub(r"\s+(?:on|in|to)\s+(?:my\s+)?(?:phone|mobile|tablet|android|device)\b.*$", "", candidate).strip()
        candidate = re.sub(r"\b(?:app|application|please|the)\b", " ", candidate).strip()
        candidate = re.sub(r"\s+", " ", candidate)
        return candidate

    def _handle_voice_connect_command(self, text: str, source: str = "local") -> bool:
        normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s%]", " ", text.lower())).strip()
        connect_words = (
            "phone", "mobile", "android", "tablet", "device", "devices", "voice connect",
            "my phone", "my mobile", "my tablet", "my android", "turn on flashlight",
            "turn off flashlight", "flashlight", "volume", "get battery", "battery", "launch app",
            "open url", "device info", "my laptop", "my pc", "my computer",
        )
        if not any(word in normalized for word in connect_words):
            return False

        try:
            devices_json = connect_list_devices(parameters={}, player=self.ui)
            devices = json.loads(devices_json).get("devices", [])
        except Exception:
            devices = []

        if not devices:
            return False

        try:
            target = ""
            for device in devices:
                name = str(device.get("name", "")).lower()
                device_id = str(device.get("device_id", "")).lower()
                platform = str(device.get("platform", "")).lower()
                if any(token in normalized for token in (name, device_id, platform, "phone", "mobile", "android", "tablet")):
                    target = str(device.get("device_id") or device.get("name") or "").strip()
                    break
            if not target and len(devices) == 1:
                target = str(devices[0].get("device_id") or devices[0].get("name") or "").strip()
            if not target:
                return False

            action = None
            params: dict[str, object] = {}
            if "flashlight" in normalized and ("turn on" in normalized or "switch on" in normalized or "power on" in normalized or "on" == normalized):
                action = "flashlight_on"
            elif "flashlight" in normalized and ("turn off" in normalized or "switch off" in normalized or "power off" in normalized or "off" == normalized):
                action = "flashlight_off"
            elif "battery" in normalized or "charge" in normalized:
                action = "get_battery"
            elif "open url" in normalized or "open website" in normalized or "go to" in normalized:
                action = "open_url"
            elif any(word in normalized for word in ("launch app", "open app", "start app", "open ", "launch ", "start ", "run ", "bring up ")):
                app_name = self._extract_launch_app_name(text)
                if app_name:
                    action = "launch_app"
                    params["app_name"] = app_name
            elif "volume" in normalized and ("set" in normalized or "change" in normalized or "to " in normalized):
                action = "volume_set"
                match = re.search(r"\b(\d{1,3})\b", normalized)
                if match:
                    params["value"] = int(match.group(1))
            elif "volume" in normalized:
                action = "volume_get"
            elif "info" in normalized or "status" in normalized:
                action = "get_device_info"
                
            if not action:
                return False

            if action == "launch_app":
                app_name = str(params.get("app_name") or "").strip()
                if not app_name:
                    return False
            if action == "open_url":
                m = re.search(r"(https?://\S+)", text, re.IGNORECASE)
                if m:
                    params["url"] = m.group(1)
                else:
                    return False

            payload = {
                "device": target,
                "action": action,
                "parameters": params,
            }
            result_json = connect_execute(parameters=payload, player=self.ui)
            result = json.loads(result_json)
            if result.get("success", False):
                detail = str(result.get("detail") or result.get("error") or "Команда устройства выполнена.")
                title = f"Voice Connect: {action}"
                self.ui.update_task_workspace(
                    title=title,
                    command=text,
                    plan=[
                        "Определить сопряжённый телефон или устройство",
                        "Отправить команду через Voice Connect",
                        "Проверить ответ устройства",
                        "Сообщить результат",
                    ],
                    status="Выполнение команды на устройстве",
                    output=detail,
                    percent=100,
                    source=source,
                )
                self.ui.write_log(f"Voice Echo: {detail}")
                self.speak(detail)
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")
                return True

            self.ui.write_log(f"ERR: Ошибка Voice Connect: {result.get('error') or 'Неизвестная ошибка'}")
            return False
        except Exception:
            return False

    def _connect_tool_voice(self, name: str, raw_result: str) -> str | None:
        if not str(name or "").startswith("connect_"):
            return None
        try:
            data = json.loads(raw_result) if isinstance(raw_result, str) else dict(raw_result or {})
        except Exception:
            data = {}

        if name == "connect_list_devices":
            count = int(data.get("count") or len(data.get("devices") or []))
            return f"Найдено подключённых устройств: {count}."

        if name == "connect_get_device":
            device = data.get("device") or {}
            label = str(device.get("name") or "устройство")
            status = "онлайн" if device.get("online") else "офлайн"
            return f"{label} — {status}."

        if name == "connect_get_capabilities":
            device = data.get("device") or {}
            label = str(device.get("name") or "Устройство")
            return f"Возможности {label} готовы."

        if name == "connect_pair_device":
            pairing = data.get("pairing") or data
            code = str(pairing.get("pairing_code") or "").strip()
            if code:
                return f"Код сопряжения готов: {code}."
            return "Сопряжение готово."

        if name == "connect_disconnect_device":
            return "Устройство отключено."

        if name == "connect_execute":
            if data.get("success", False):
                detail = data.get("detail")
                if isinstance(detail, dict):
                    detail = detail.get("message") or detail.get("status") or detail.get("result")
                if not detail and isinstance(data.get("data"), dict):
                    payload = data.get("data") or {}
                    detail = payload.get("message") or payload.get("status") or payload.get("result")
                if not detail:
                    detail = data.get("error") or "Задача выполнена."
                return str(detail)
            return str(data.get("error") or "Не удалось выполнить команду на устройстве.")

        return None

    def _attention_message(self, event: dict) -> str:
        app = (event.get("app") or "приложении").strip()
        kind = (event.get("kind") or "message").strip().lower()
        if kind == "call":
            return f"Обнаружен входящий звонок в {app}. Ответить, проигнорировать или сбросить?"
        title = (event.get("title") or "").strip()
        preview = (event.get("preview") or "").strip()
        if title:
            return f"Вам пришло сообщение в {app} от {title}. Текст: {preview}"
        return f"Вам пришло сообщение в {app}. Текст: {preview}"

    def _announce_attention(self, event: dict):
        msg = self._attention_message(event)
        self.ui.write_log(f"Voice Echo: {msg}")
        if self.session and self._loop:
            self.speak(msg)
        else:
            threading.Thread(target=speak_native, args=(msg,), daemon=True).start()
        self.ui.show_attention_alert(event)

    def _on_external_notification(self, event: dict):
        if not isinstance(event, dict):
            return
        kind = (event.get("kind") or "message").strip().lower()
        app = (event.get("app") or "Приложение").strip()
        preview = (event.get("preview") or "").strip()
        settings = {}
        try:
            settings = self.ui._load_app_settings()
        except Exception:
            settings = {}

        if kind == "call" and not bool(settings.get("attention_call_prompts", True)):
            return
        if kind == "message" and not bool(settings.get("attention_message_prompts", True)):
            return

        with self._attention_lock:
            current = self._pending_attention
            if current:
                same_app = (current.get("app") or "").strip().lower() == app.lower()
                same_kind = (current.get("kind") or "").strip().lower() == kind
                if same_app and same_kind:
                    return
            self._pending_attention = dict(event)

        self._announce_attention(event)
        if preview:
            self.ui.write_log(f"[Attention] {app}: {preview}")
        if kind == "call" and app.lower() in {"zoom", "teams", "whatsapp"}:
            self._start_meeting_mode(event)

    def _start_meeting_mode(self, event: dict):
        event = dict(event or {})
        app = (event.get("app") or "приложении").strip()
        title = event.get("title") or f"Встреча в {app}"
        summary = f"В {app}: слежу и отвечаю на вопросы."
        with self._meeting_lock:
            self._meeting_active = True
            self._meeting_event = event
        self.ui.set_meeting_mode(True, title, summary, "Жду вопросов, читаю экран.", self._meeting_assistant.latest_speech())
        self._meeting_assistant.start(title=title, context=summary)
        self.ui.write_log(f"SYS: Режим встречи включён в {app}.")

    def _stop_meeting_mode(self, reason: str = "Режим встречи остановлен."):
        with self._meeting_lock:
            was_active = self._meeting_active
            self._meeting_active = False
            self._meeting_event = None
        if was_active:
            self._meeting_assistant.stop()
            self.ui.set_meeting_mode(False, "", "", "")
            self.ui.write_log(f"SYS: {reason}")

    def _on_meeting_update(self, payload: dict):
        if not isinstance(payload, dict):
            return
        active = bool(payload.get("active"))
        title = payload.get("title") or "Режим встречи"
        summary = payload.get("summary") or ""
        answer = payload.get("answer") or ""
        speech = payload.get("speech") or ""
        self.ui.set_meeting_mode(active, title, summary, answer, speech)
        if summary:
            self.ui.write_log(f"[Meeting] {summary}")
        if answer:
            self.ui.write_log(f"Voice Echo: {answer}")

    def _on_meeting_state(self, state: str):
        if state == "LISTENING":
            self.ui.set_state("LISTENING")
        elif state == "MEETING":
            self.ui.set_state("THINKING")

    def _attention_matches(self, text: str, words: tuple[str, ...]) -> bool:
        t = (text or "").lower()
        return any(word in t for word in words)

    def _prompt_message_reply(self, event: dict) -> bool:
        if not isinstance(event, dict):
            return False
        with self._attention_lock:
            self._pending_reply_event = dict(event)
            self._pending_attention = None
            self._reply_mode = True

        message = "Что вы хотите ответить?"
        self.ui.write_log(f"Voice Echo: {message}")
        if self.session and self._loop:
            self.speak(message)
        else:
            threading.Thread(target=speak_native, args=(message,), daemon=True).start()
        try:
            self.ui.begin_task_workspace(
                "Подготовка ответа",
                [
                    "Введите ваш ответ",
                    "Я придам ему естественный вид",
                    f"Отправка через {event.get('app', 'приложение')}",
                ],
                source="reply",
            )
            self.ui.update_task_workspace(
                status="Ожидание ответа",
                output="Введите сообщение для отправки — я придам ему естественный вид перед отправкой.",
                percent=10,
            )
        except Exception:
            pass
        return True

    def _handle_pending_reply(self, text: str) -> bool:
        with self._attention_lock:
            event = dict(self._pending_reply_event or {})
            self._pending_reply_event = None
        if not event:
            return False

        lower = (text or "").lower()
        if self._attention_matches(lower, ("cancel", "never mind", "skip", "do not send", "don't send")):
            self._reply_mode = False
            self.ui.write_log("SYS: Ответ отменён.")
            try:
                self.ui.finish_task_workspace("Ответ отменён.", "Отменено", 100)
            except Exception:
                pass
            return True

        self.ui.write_log(f"SYS: Готовлю ответ: {event.get('title') or event.get('app')}.")
        threading.Thread(target=self._draft_and_send_reply, args=(event, text), daemon=True).start()
        return True

    def _rewrite_reply_text(self, user_text: str, event: dict) -> str:
        prompt = (
            "You are a friendly assistant helping a user rewrite their draft reply for a chat message. "
            "Keep the same meaning and intent, expand the wording slightly, and make it sound natural and human. "
            "Do not mention the notification, app, or any internal system details. "
            "Return only the rewritten reply text.\n\n"
            "Notification context:\n"
            f"App: {event.get('app', '')}\n"
            f"Sender: {event.get('title', '')}\n"
            f"Preview: {event.get('preview', '')}\n\n"
            "User draft reply:\n"
            f"{user_text}\n\n"
            "Reply text:"
        )
        try:
            return _gemini_text_reply(prompt) or user_text
        except Exception:
            try:
                return openrouter_client.chat(
                    prompt,
                    system="You are a friendly assistant. Rewrite the reply naturally and humanely.",
                )
            except Exception:
                return user_text

    def _draft_and_send_reply(self, event: dict, text: str):
        try:
            reply_text = self._rewrite_reply_text(text, event)
            if not reply_text:
                reply_text = text
            self.ui.update_task_workspace(
                status="Отправка ответа",
                output="Отправляю ваш расширенный ответ...",
                percent=70,
            )
            receiver = (event.get("title") or "").strip()
            platform = (event.get("app") or "whatsapp").strip()
            if not receiver:
                self.ui.write_log("ERR: Не удалось определить получателя ответа.")
                try:
                    self.ui.finish_task_workspace("Ответ не отправлен: получатель не найден.", "Ответ не отправлен", 100)
                except Exception:
                    pass
                return
            result = send_message(
                parameters={
                    "receiver": receiver,
                    "message_text": reply_text,
                    "platform": platform,
                },
                player=self.ui,
            )
            self._reply_mode = False
            self.ui.write_log(f"SYS: {result}")
            try:
                self.ui.finish_task_workspace(reply_text, "Ответ доставлен.", 100)
            except Exception:
                pass
        except Exception as e:
            self._reply_mode = False
            self.ui.write_log(f"ERR: Reply failed: {e}")
            try:
                self.ui.finish_task_workspace(f"Ответ не отправлен: {e}", "Ответ не отправлен", 100)
            except Exception:
                pass
        finally:
            if not self.ui.muted:
                self.ui.set_state("LISTENING")

    def _parse_ig_reply_intent(self, text: str) -> tuple[str, str]:
        system_prompt = (
            "You are an intent parser. The user received an Instagram DM. I asked: 'What should I reply, or should I take over?'. "
            "The user responded, possibly in Russian. Determine their intent.\n"
            "1. If they want me to take over/handle it, return TAKE_OVER.\n"
            "2. If they want to cancel/skip, return CANCEL.\n"
            "3. If they dictate a specific message to send (e.g. 'tell them I am busy', 'say hi'), return MANUAL_REPLY and the exact text.\n"
            "4. If they are just greeting me (e.g. 'hi') or making small talk, return IGNORE.\n"
            "Output ONLY valid JSON: {\"intent\": \"...\", \"reply_text\": \"...\"}"
        )
        try:
            client = genai.Client(api_key=_get_api_key(), http_options={"api_version": "v1beta"})
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"{system_prompt}\n\nUser Response: {text}",
                config={"temperature": 0.1, "response_mime_type": "application/json"}
            )
            data = json.loads(response.text.strip())
            return data.get("intent", "IGNORE"), data.get("reply_text", "")
        except Exception:
            lower = text.lower()
            if any(c in lower for c in ("cancel", "stop", "skip", "never mind", "abort", "отмена", "отменить", "стоп", "прекрати", "не надо",
                                         "не нужно", "пропустить", "забудь")):
                return "CANCEL", ""
            if any(a in lower for a in ("take over", "auto mode", "handle it", "you reply", "возьми", "прими", "управляй", "отвечай ты",
                                         "отвечай за меня", "возьми на себя", "авторежим", "ты ответь")):
                return "TAKE_OVER", ""
            if lower.startswith("tell ") or lower.startswith("reply ") or lower.startswith("say ") or lower.startswith("send "):
                import re
                cleaned = re.sub(r"^(tell (him|her|them)?|reply( saying)?|say|send) ", "", text, flags=re.IGNORECASE)
                return "MANUAL_REPLY", cleaned
            if re.search(r"^(ответь|напиши|передай|скажи|отправь|сообщи)( ему| ей| им)?\s+(?:что|что-то|следующее|так)?\s*", text, flags=re.IGNORECASE):
                import re
                cleaned = re.sub(r"^(ответь|напиши|передай|скажи|отправь|сообщи)( ему| ей| им)?\s+(?:что|что-то|следующее|так)?\s*", "", text, flags=re.IGNORECASE)
                return "MANUAL_REPLY", cleaned
            return "IGNORE", ""

    def _handle_ig_reply_flow(self, text: str) -> bool:
        if getattr(self, "_ig_pending_thread", None):
            thread_id = self._ig_pending_thread.get("thread_id")
            username = self._ig_pending_thread.get("username")
            message_text = self._ig_pending_thread.get('message')
            
            intent, payload = self._parse_ig_reply_intent(text)
            
            if intent == "CANCEL":
                self._ig_reply_mode = False
                msg = "Instagram reply cancelled."
                self.ui.write_log(f"Voice Echo: {msg}")
                self.speak(msg)
                self._ig_pending_thread = None
                return True
                
            if intent == "TAKE_OVER":
                self.ui.write_log("SYS: Беру управление перепиской в Instagram.")
                self.speak(f"Теперь я беру на себя общение с {username}.")
                from actions.instagram_chat import add_auto_thread, send_direct_reply
                add_auto_thread(thread_id)
                def _generate_and_send():
                    try:
                        reply = _ig_gemini_reply(username, message_text)
                        send_direct_reply(thread_id, reply)
                    except Exception as e:
                        print(f"Error taking over thread: {e}")
                threading.Thread(target=_generate_and_send, daemon=True).start()
                
            elif intent == "MANUAL_REPLY":
                self.ui.write_log(f"SYS: Отправляю ручной ответ: {username}.")
                self.speak("Сообщение отправлено.")
                from actions.instagram_chat import send_direct_reply
                send_direct_reply(thread_id, payload)
                
            elif intent == "IGNORE":
                return False # Let the main command loop handle this input
                
            self._ig_reply_mode = False
            self._ig_pending_thread = None
            return True
        return False

        lower = text.lower()
        if any(cancel in lower for cancel in ("cancel", "never mind", "skip", "stop", "abort")):
            self._email_mode = False
            self._email_step = 0
            self._email_profiles = {}
            msg = "Отправка письма отменена."
            self.ui.write_log(f"Voice Echo: {msg}")
            self.speak(msg)
            try:
                self.ui.finish_task_workspace("Отправка письма отменена.", "Отменено", 100)
            except Exception:
                pass
            return True

        if self._email_step == 0:
            # We just collected the recipient
            self._email_recipient = text.strip()
            self._email_step = 1
            prompt = "Каким почтовым приложением воспользоваться? (Gmail, стандартная почта и т. д.)"
            self.ui.write_log(f"Voice Echo: {prompt}")
            self.speak(prompt)
            try:
                self.ui.update_task_workspace(
                    status="Выбор почтового приложения",
                    output=f"Получатель: {self._email_recipient}. Запрашиваю почтовое приложение...",
                    percent=40,
                )
            except Exception:
                pass
            return True

        elif self._email_step == 1:
            # We just collected the app name
            self._email_app = text.strip()
            self._email_step = 2
            
            prompt = "Какое сообщение вы хотите отправить?"
            self.ui.write_log(f"Voice Echo: {prompt}")
            self.speak(prompt)
            try:
                self.ui.update_task_workspace(
                    status="Сбор сообщения",
                    output=f"Получатель: {self._email_recipient} | Приложение: {self._email_app}. Запрашиваю текст сообщения...",
                    percent=70,
                )
            except Exception:
                pass
            return True

        elif self._email_step == 2:
            # We just collected the message
            self._email_message = text.strip()
            self._email_mode = False
            self._email_step = 0
            
            # Now let's execute composing!
            msg = f"Открываю {self._email_app} и составляю письмо для {self._email_recipient}..."
            self.ui.write_log(f"Voice Echo: {msg}")
            self.speak(msg)
            try:
                self.ui.update_task_workspace(
                    status="Составление письма",
                    output=f"Составляю письмо для {self._email_recipient} через {self._email_app}...",
                    percent=90,
                )
            except Exception:
                pass
            
            try:
                import urllib.parse
                import webbrowser
                subject = "Message from Voice Echo"
                quoted_recipient = urllib.parse.quote(self._email_recipient)
                quoted_subject = urllib.parse.quote(subject)
                quoted_body = urllib.parse.quote(self._email_message)
                
                import os
                import subprocess
                import shutil

                app_lower = self._email_app.lower()
                chrome_opened = False

                if "gmail" in app_lower or "chrome" in app_lower:
                    import urllib.parse
                    quoted_recipient = urllib.parse.quote(self._email_recipient)
                    quoted_subject = urllib.parse.quote("Message from Voice Echo")
                    quoted_body = urllib.parse.quote(self._email_message)
                    url = f"https://mail.google.com/mail/?view=cm&fs=1&to={quoted_recipient}&su={quoted_subject}&body={quoted_body}"
                    
                    # Use webbrowser to naturally open a new tab in the already running Chrome window
                    import webbrowser
                    webbrowser.open(url)

                elif "outlook" in app_lower:
                    url = f"https://outlook.live.com/default/?path=/mail/action/compose&to={quoted_recipient}&subject={quoted_subject}&body={quoted_body}"
                    webbrowser.open(url)
                else:
                    url = f"mailto:{quoted_recipient}?subject={quoted_subject}&body={quoted_body}"
                    webbrowser.open(url)
                
                try:
                    self.ui.finish_task_workspace("Письмо успешно составлено.", "Составлено", 100)
                except Exception:
                    pass
            except Exception as e:
                err_msg = f"Не удалось составить письмо: {e}"
                self.ui.write_log(f"ERR: {err_msg}")
                self.speak(err_msg)
                try:
                    self.ui.finish_task_workspace(err_msg, "Не удалось", 100)
                except Exception:
                    pass
            return True

        return False

    def _handle_attention_response(self, text: str) -> bool:
        with self._attention_lock:
            event = dict(self._pending_attention or {})
        if not event:
            return False

        kind = (event.get("kind") or "message").strip().lower()
        lower = (text or "").lower()

        if kind == "message":
            if self._attention_matches(lower, ("reply", "respond", "answer", "write back", "send reply", "send a reply")):
                return self._prompt_message_reply(event)
            if self._attention_matches(lower, ("hear", "read", "what is it", "tell me", "show it", "open it")):
                preview = read_event_preview(event)
                self.ui.write_log(f"Voice Echo: {preview}")
                threading.Thread(target=speak_native, args=(preview,), daemon=True).start()
                with self._attention_lock:
                    self._pending_attention = None
                return True
            if self._attention_matches(lower, ("ignore", "dismiss", "skip", "no", "not now")):
                self.ui.write_log("SYS: Уведомление о сообщении отклонено.")
                with self._attention_lock:
                    self._pending_attention = None
                return True
            return False

        if kind == "call":
            if self._attention_matches(lower, ("pick up", "answer", "accept", "take it", "join")):
                result = handle_call_action(event, "accept")
                self.ui.write_log(f"SYS: {result}")
                threading.Thread(target=speak_native, args=(result,), daemon=True).start()
                with self._attention_lock:
                    self._pending_attention = None
                return True
            if self._attention_matches(lower, ("ignore", "decline", "reject", "cut", "hang up", "end")):
                result = handle_call_action(event, "decline")
                self.ui.write_log(f"SYS: {result}")
                threading.Thread(target=speak_native, args=(result,), daemon=True).start()
                with self._attention_lock:
                    self._pending_attention = None
                return True
            if self._attention_matches(lower, ("x", "nothing", "do nothing", "close")):
                self.ui.write_log("SYS: Уведомление о звонке отклонено.")
                with self._attention_lock:
                    self._pending_attention = None
                return True
            return False

        return False

    def _on_attention_action(self, event: dict, decision: str):
        if not isinstance(event, dict):
            return
        kind = (event.get("kind") or "message").strip().lower()
        decision = (decision or "").strip().lower()

        if kind == "meeting":
            if decision == "stop":
                self._stop_meeting_mode()
            return

        if kind == "message":
            if decision == "hear":
                preview = read_event_preview(event)
                self.ui.write_log(f"Voice Echo: {preview}")
                threading.Thread(target=speak_native, args=(preview,), daemon=True).start()
            elif decision == "reply":
                self._prompt_message_reply(event)
                return
            else:
                self.ui.write_log("SYS: Уведомление о сообщении отклонено.")
            with self._attention_lock:
                self._pending_attention = None
            return

        if kind == "call":
            if decision in {"accept", "answer", "pick_up"}:
                result = handle_call_action(event, "accept")
                self.ui.write_log(f"SYS: {result}")
                threading.Thread(target=speak_native, args=(result,), daemon=True).start()
            elif decision in {"noop", "x", "none"}:
                self.ui.write_log("SYS: Уведомление о звонке отклонено.")
            else:
                result = handle_call_action(event, "decline")
                self.ui.write_log(f"SYS: {result}")
                threading.Thread(target=speak_native, args=(result,), daemon=True).start()
            with self._attention_lock:
                self._pending_attention = None


    def _fallback_reply(self, text: str, memory_ctx: str = ""):
        try:
            self.ui.set_state("THINKING")
            try:
                self.ui.update_task_workspace(
                    status="Думаю...",
                    output="Voice Echo готовит прямой ответ.",
                    percent=35,
                )
            except Exception:
                pass
            reply = ""
            gemini_first = not self._use_openrouter_first
            request_text = f"{memory_ctx}\n\nCurrent User Request:\n{text}" if memory_ctx else text

            if gemini_first:
                try:
                    reply = _gemini_text_reply(request_text)
                except Exception as e:
                    print(f"[VOICE ECHO] ⚠️ Gemini fallback failed: {e}")
                    if _is_gemini_limit_error(e) or _is_network_unreachable(e):
                        self._use_openrouter_first = True

            if not reply:
                try:
                    reply = openrouter_client.chat(
                        request_text,
                        system=(
                            "You are Voice Echo, a concise, helpful desktop assistant. "
                            "Reply naturally and briefly. Do not mention internal implementation details."
                        ),
                    )
                except Exception as e:
                    print(f"[VOICE ECHO] ⚠️ OpenRouter fallback failed: {e}")
                    if gemini_first and not self._use_openrouter_first and _is_gemini_limit_error(e):
                        self._use_openrouter_first = True
            reply = (reply or "").strip()
            if not reply:
                reply = "Я готов."
            self.ui.write_log(f"Voice Echo: {reply}")
            try:
                self.ui.finish_task_workspace(reply, "Ответ доставлен.", 100)
            except Exception:
                pass
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
        except Exception as e:
            msg = f"Fallback reply failed: {e}"
            print(f"[VOICE ECHO] ⚠️ {msg}")
            self.ui.write_log(f"ERR: {msg}")
            try:
                self.ui.finish_task_workspace(msg, "Ответ не отправлен.", 100)
            except Exception:
                pass
            if not self.ui.muted:
                self.ui.set_state("LISTENING")

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        text = (text or "").strip()
        if not text:
            return

        if self._local_voice_enabled and self._local_tts is not None and self._local_tts.available:
            # Local offline TTS (Piper).
            def _speak_thread():
                try:
                    self.set_speaking(True)
                    self._local_tts.speak(text)
                except Exception as e:
                    print(f"[LocalVoice] speak failed: {e}")
                finally:
                    self.set_speaking(False)
            threading.Thread(target=_speak_thread, daemon=True).start()
            return

        if self.session and self._loop:
            # Route text through Gemini Live API for a unified native voice
            import asyncio
            async def _send():
                try:
                    prompt = f"System Alert / Context: {text}\n\nPlease relay this information to me naturally now."
                    await self.session.send(input=prompt, end_of_turn=True)
                except Exception as e:
                    print(f"[VOICE ECHO] Unified Speak err: {e}")
            asyncio.run_coroutine_threadsafe(_send(), self._loop)
        else:
            # Fallback to Edge TTS if Gemini Live is disconnected
            def _speak_thread():
                try:
                    self.set_speaking(True)
                    from actions.attention_monitor import _speak_edge_native
                    _speak_edge_native(text)
                finally:
                    self.set_speaking(False)
            threading.Thread(target=_speak_thread, daemon=True).start()

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Во время выполнения «{tool_name.replace('_', ' ')}» произошла ошибка. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)
        parts.append(
            "Wake-word mode: if the microphone is muted, still listen for the words 'Voice Echo', 'hey', 'hi', and 'hello'. "
            "When you hear one of these activation cues, keep the session friendly and concise, "
            "and wait for the user's next command. "
            "IMPORTANT: Do NOT speak an unprompted generic greeting (like 'Thank you, how can I help you?') upon connecting. "
            "Remain completely silent until the user speaks to you or asks a question."
        )

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[VOICE ECHO] 🔧 {name}  {args}")
        self.speak(f"Выполняю: {name.replace('_', ' ')}...")
        self.ui.set_state("THINKING")
        try:
            self.ui.update_task_workspace(
                title=f"Выполнение: {name}",
                status=f"Выполняется: {name}",
                output="Ожидание завершения инструмента.",
                percent=45,
            )
        except Exception:
            pass
        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
                try:
                    self.ui.finish_task_workspace("Запоминаю.", "Память обновлена.", 100)
                except Exception:
                    pass
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Готово."

        try:
            if name == "computer_settings":
                from actions.computer_settings import computer_settings as cs_run
                r = await loop.run_in_executor(None, lambda: cs_run(parameters=args, player=self.ui))
                result = r or "Настройки обновлены."

            elif name == "dev_agent":
                from actions.dev_agent import dev_agent as da_run
                r = await loop.run_in_executor(None, lambda: da_run(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Готово."

            elif name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Приложение открыто: {args.get('app_name')}."
                
            elif name == "check_instagram_messages":
                self.ui.write_log("SYS: Проверяю сообщения в Instagram...")
                from actions.instagram_chat import get_recent_messages
                result = await loop.run_in_executor(None, get_recent_messages, 5)

            elif name == "instagram_reply":
                action = args.get("action")
                reply_text = args.get("reply_text")
                if getattr(self, "_ig_pending_thread", None):
                    thread_id = self._ig_pending_thread.get("thread_id")
                    username = self._ig_pending_thread.get("username")
                    if action == "take_over":
                        self.ui.write_log("SYS: Беру управление перепиской (инструмент).")
                        from actions.instagram_chat import add_auto_thread, send_direct_reply
                        add_auto_thread(thread_id)
                        message_text = self._ig_pending_thread.get('message')
                        def _generate_and_send():
                            try:
                                reply = _ig_gemini_reply(username, message_text)
                                send_direct_reply(thread_id, reply)
                            except Exception as e:
                                print(f"Error taking over thread: {e}")
                        threading.Thread(target=_generate_and_send, daemon=True).start()
                        result = f"Управление перепиской с {username} передано мне. Теперь я буду отвечать им автоматически."
                    else:
                        self.ui.write_log(f"SYS: Отправляю ручной ответ: {username}.")
                        from actions.instagram_chat import send_direct_reply
                        send_direct_reply(thread_id, reply_text)
                        result = f"Ручной ответ отправлен: {username}."
                        
                    self._ig_reply_mode = False
                    self._ig_pending_thread = None
                else:
                    result = "Ошибка: сейчас нет ожидающего сообщения в Instagram, на которое можно ответить."

            elif name == "system_manager":
                from actions.system_manager import run as sm_run
                r = await loop.run_in_executor(None, lambda: sm_run(parameters=args, player=self.ui))
                result = r or "Информация о системе получена."

            elif name == "background_monitor":
                from actions.background_monitor import run as bm_run
                r = await loop.run_in_executor(None, lambda: bm_run(parameters=args, player=self.ui))
                result = r or "Готово."

            elif name == "clipboard_processor":
                from actions.clipboard_processor import process_clipboard
                r = await loop.run_in_executor(None, lambda: process_clipboard(parameters=args, player=self.ui))
                result = r or "Буфер обмена прочитан."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Прогноз погоды готов."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Готово."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Готово."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Сообщение отправлено: {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Напоминание установлено."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Готово."
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Готово."

            elif name == "presentation_builder":
                r = await loop.run_in_executor(
                    None,
                    lambda: create_presentation(parameters=args, player=self.ui)
                )
                result = r or "Презентация создана."

            elif name == "spreadsheet_builder":
                r = await loop.run_in_executor(
                    None,
                    lambda: create_spreadsheet(parameters=args, player=self.ui)
                )
                result = r or "Таблица создана."


            elif name == "word_document":
                if not args.get("file_path") and self.ui.current_file:
                    current_file = Path(self.ui.current_file)
                    if current_file.suffix.lower() == ".docx":
                        args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: word_document(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Документ Word обработан."

            elif name == "pdf_document":
                r = await loop.run_in_executor(
                    None,
                    lambda: create_pdf(parameters=args, player=self.ui)
                )
                result = r or "PDF создан."

            elif name == "screen_process":
                if hasattr(self, "set_scanning"):
                    self.ui.set_scanning(True, "SCANNING SCREEN")
                threading.Thread(
                    target=screen_process,
                    kwargs={
                        "parameters": args,
                        "response": None,
                        "player": self.ui,
                        "session_memory": None,
                    },
                    daemon=True,
                ).start()
                result = "Модуль зрения активирован. Храните полную тишину — модуль зрения ответит сам."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Готово."

            elif name == "smart_home_control":
                command_text = str(args.get("command") or "").strip()
                r = await loop.run_in_executor(None, lambda: self._smart_home.execute_command(command_text))
                result = str((r or {}).get("detail") or "Команда умного дома выполнена.")

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Готово."

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Задача запущена (ID: {task_id})."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Готово."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Готово."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Готово."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Готово."
            elif name == "connect_list_devices":
                r = await loop.run_in_executor(None, lambda: connect_list_devices(parameters=args, player=self.ui))
                result = r or "Готово."
            elif name == "connect_get_device":
                r = await loop.run_in_executor(None, lambda: connect_get_device(parameters=args, player=self.ui))
                result = r or "Готово."
            elif name == "connect_get_capabilities":
                r = await loop.run_in_executor(None, lambda: connect_get_capabilities(parameters=args, player=self.ui))
                result = r or "Готово."
            elif name == "connect_execute":
                r = await loop.run_in_executor(None, lambda: connect_execute(parameters=args, player=self.ui))
                result = r or "Готово."
            elif name == "connect_pair_device":
                r = await loop.run_in_executor(None, lambda: connect_pair_device(parameters=args, player=self.ui))
                result = r or "Готово."
            elif name == "connect_disconnect_device":
                r = await loop.run_in_executor(None, lambda: connect_disconnect_device(parameters=args, player=self.ui))
                result = r or "Готово."
            elif name in ("spotify_controller", "spotify", "music"):
                from actions.spotify_controller import spotify_controller
                r = await loop.run_in_executor(None, lambda: spotify_controller(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Готово."
            elif name in ("calendar_scheduler", "calendar", "schedule"):
                from actions.calendar_scheduler import calendar_scheduler
                r = await loop.run_in_executor(None, lambda: calendar_scheduler(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Готово."
            elif name in ("daily_briefing", "briefing"):
                from actions.daily_briefing import daily_briefing
                r = await loop.run_in_executor(None, lambda: daily_briefing(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Дневное резюме готово."
            elif name == "unlock_device":
                from actions.unlock_device import unlock_device
                r = await loop.run_in_executor(None, lambda: unlock_device(parameters=args, player=self.ui))
                result = r or "Готово."
            elif name == "shutdown_voice":
                self.ui.write_log("SYS: Запрошено завершение работы.")
                self.speak("До свидания.")

                def _shutdown():
                    import time, sys, os
                    time.sleep(1)
                    os._exit(0)

                threading.Thread(target=_shutdown, daemon=True).start()
            else:
                result = f"Неизвестный инструмент: {name}"

        except Exception as e:
            result = f"Инструмент «{name}» не сработал: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        try:
            self.speak(f"Готово: {name.replace('_', ' ')}.")
            self.ui.finish_task_workspace(result, "Задача выполнена.", 100)
        except Exception:
            pass

        tool_voice = self._connect_tool_voice(name, result)
        if tool_voice:
            try:
                self.ui.write_log(f"Voice Echo: {tool_voice}")
            except Exception:
                pass
            try:
                self.speak(tool_voice)
            except Exception:
                pass

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[VOICE ECHO] 📤 {name} → {str(result)[:80]}")

        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _serve_dashboard(self):
        if self._dashboard is None:
            self.ui.write_log("ERR: Mobile Connect отключён, так как отсутствуют зависимости панели управления.")
            return
        try:
            self._dashboard.set_connect_callback(self._on_phone_connected)
            self._dashboard.set_wake_callback(lambda: None)
            await self._dashboard.serve()
        except Exception as e:
            self.ui.write_log(f"ERR: Ошибка сервера Mobile Connect: {e}")
            traceback.print_exc()

    async def _consume_remote_commands(self):
        if self._dashboard is None:
            return
        while True:
            text = await self._dashboard._command_queue.get()
            if text:
                try:
                    self.ui.submit_external_command(text, source="mobile")
                except Exception:
                    self._on_text_command(text, source="mobile")

    async def _relay_phone_audio(self):
        if self._dashboard is None:
            return
        while True:
            frame = await self._dashboard._phone_audio_queue.get()
            if not self.out_queue:
                continue
            self._phone_active = True
            try:
                await self.out_queue.put(frame)
            finally:
                await asyncio.sleep(0.08)
                if self._dashboard._phone_audio_queue.empty():
                    self._phone_active = False

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[VOICE ECHO] 🎤 Mic started")
        loop = asyncio.get_event_loop()
        import numpy as np

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                voice_speaking = self._is_speaking
            if self._phone_active:
                return
            
            if not self.ui.muted or getattr(self.ui, "_wakeword_listening", False):
                # Calculate RMS volume of the chunk
                rms = np.sqrt(np.mean(np.square(indata, dtype=np.float32)))
                
                # Smart Echo Gate: High threshold if AI is speaking, very low if silent
                threshold = 1200.0 if voice_speaking else 10.0
                
                if rms > threshold:
                    data = indata.tobytes()
                else:
                    # Stream pure silence to keep timeline intact but prevent echo
                    data = np.zeros_like(indata).tobytes()
                    
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[VOICE ECHO] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[VOICE ECHO] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[VOICE ECHO] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            self.set_speaking(True)
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                try:
                                    from actions.attention_monitor import stop_native_speech
                                    stop_native_speech()
                                except Exception:
                                    pass
                                in_buf.append(txt)
                                if self.ui.muted and _wakeword_detected(txt):
                                    try:
                                        self.ui.set_muted_state(False, wakeword=True)
                                        self.ui.write_log("SYS: Активировано wake-word. Микрофон активен.")
                                    except Exception:
                                        pass

                        if sc.turn_complete:
                            self.set_speaking(False)

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"Вы: {full_in}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Voice Echo: {full_out}")
                            out_buf = []

                            if full_in and len(full_in) > 5:
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[VOICE ECHO] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )

        except Exception as e:
            print(f"[VOICE ECHO] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[VOICE ECHO] 🔊 Play started")
        loop = asyncio.get_event_loop()

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[VOICE ECHO] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        # announce boot steps to UI overlay (thread-safe wrappers)
        try:
            self.ui.boot_add_step("Загрузка конфигурации")
            self.ui.boot_add_step("Запуск монитора внимания")
            self.ui.boot_add_step("Запуск сервера Mobile Connect")
            self.ui.boot_add_step("Инициализация аудио")
            self.ui.boot_add_step("Подключение к AI backend")
            self.ui.boot_add_step("Завершение запуска")
            self.ui.boot_set_progress(3, "Подготовка к запуску...")
        except Exception:
            pass

        self._attention_monitor.start()
        try:
            self.ui.boot_set_step_status("Запуск монитора внимания", "done")
            self.ui.boot_set_progress(12, "Монитор внимания запущен")
        except Exception:
            pass
        if self._dashboard is not None:
            if not self._dashboard_started:
                self._dashboard_started = True
                asyncio.create_task(self._serve_dashboard())
                try:
                    self.ui.boot_set_step_status("Запуск сервера Mobile Connect", "done")
                    self.ui.boot_set_progress(22, "Сервер Mobile Connect запущен")
                except Exception:
                    pass
            asyncio.create_task(self._consume_remote_commands())
            asyncio.create_task(self._relay_phone_audio())
        try:
            self.ui.boot_set_progress(36, "Инициализация AI-клиента")
        except Exception:
            pass

        if self._local_voice_enabled:
            # Fully offline voice loop: local STT (Vosk/sherpa) + local TTS (Piper).
            # No Google/Gemini endpoint is contacted for speech.
            try:
                self.ui.boot_set_step_status("Подключение к AI backend", "done")
                self.ui.boot_set_progress(70, "Загрузка офлайн-голосового движка")
            except Exception:
                pass
            self.ui.set_state("LISTENING")
            self.ui.write_log("SYS: Voice Echo онлайн (офлайн-голос — Vosk/Piper).")

            def _local_submit(text):
                try:
                    self.ui.submit_external_command(text, source="local")
                except Exception:
                    try:
                        self._on_text_command(text, source="local")
                    except Exception:
                        pass

            self._local_engine = LocalVoiceEngine(
                submit=_local_submit,
                muted=lambda: bool(getattr(self.ui, "muted", False)),
                wakeword=_wakeword_detected,
                on_wakeword=lambda: self.ui.set_muted_state(False, wakeword=True),
                speaking=lambda: self._is_speaking,
            )
            if self._local_engine.stt_available:
                self._local_engine.start()
                try:
                    self.ui.boot_set_step_status("Инициализация аудио", "done")
                    self.ui.boot_set_progress(92, "Офлайн STT + Piper запущены")
                except Exception:
                    pass
            else:
                self.ui.write_log(
                    "ERR: Файлы локальных речевых моделей не найдены в config/models. "
                    "Запустите загрузчик моделей или установите модели перед включением локального голоса."
                )
            try:
                self.ui.boot_set_step_status("Завершение запуска", "done")
                self.ui.boot_set_progress(100, "Запуск завершён")
            except Exception:
                pass
            while True:
                await asyncio.sleep(3600)

        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta", "httpx_client": get_httpx_client()}
        )

        while True:
            fatal_hint = False
            try:
                print("[VOICE ECHO] 🔌 Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                connect_cm = client.aio.live.connect(model=LIVE_MODEL, config=config)
                session = await asyncio.wait_for(connect_cm.__aenter__(), timeout=LIVE_CONNECT_TIMEOUT)
                try:
                    async with asyncio.TaskGroup() as tg:
                        self.session        = session
                        self._loop          = asyncio.get_event_loop()
                        self.audio_in_queue = asyncio.Queue()
                        self.out_queue      = asyncio.Queue()  # Fix: removed maxsize=10 to prevent dropping packets
                        
                        print("[VOICE ECHO] ✅ Connected.")
                        try:
                            self.ui.boot_set_step_status("Подключение к AI backend", "done")
                            self.ui.boot_set_progress(75, "AI backend подключён")
                        except Exception:
                            pass
                        self.ui.set_state("LISTENING")
                        self.ui.write_log("SYS: Voice Echo онлайн.")

                        tg.create_task(self._send_realtime())
                        tg.create_task(self._listen_audio())
                        tg.create_task(self._relay_phone_audio())
                        tg.create_task(self._receive_audio())
                        tg.create_task(self._play_audio())
                        try:
                            self.ui.boot_set_step_status("Инициализация аудио", "done")
                            self.ui.boot_set_progress(92, "Аудио-подсистемы запущены")
                        except Exception:
                            pass
                        # finalize
                        try:
                            self.ui.boot_set_step_status("Завершение запуска", "done")
                            self.ui.boot_set_progress(100, "Запуск завершён")
                        except Exception:
                            pass
                finally:
                    try:
                        await connect_cm.__aexit__(None, None, None)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[VOICE ECHO] ⚠️ {e}")
                traceback.print_exc()
                fatal_hint = _is_network_unreachable(e)
                if _is_gemini_limit_error(e):
                    self._use_openrouter_first = True
                self.session = None
                self._loop = None
            self.set_speaking(False)
            self.ui.set_state("LISTENING")
            if fatal_hint:
                self.ui.write_log(
                    "ERR: Не удаётся подключиться к серверу Gemini. Это ошибка конфигурации "
                    "хоста/сети (см. /etc/hosts или прокси), а не временный сбой."
                )
                print(
                    "[VOICE ECHO] 🚫 Gemini host unreachable — retrying will not help "
                    "until DNS/hosts/proxy is fixed. See /etc/hosts and proxy settings."
                )
                _startup_log(f"gemini connect unreachable: {e}")
            print("[VOICE ECHO] 🔄 Reconnecting in 5s...")
            await asyncio.sleep(5)

def main():
    _startup_log("main entered")
    try:
        if update_from_github(BASE_DIR):
            _startup_log("updated from GitHub; restarting")
            restart_application(BASE_DIR)
            return
    except Exception as exc:
        _startup_log(f"GitHub update skipped: {exc}")
    _ensure_desktop_shortcut()
    ui = VoiceUI(str(BASE_DIR / "assets" / "Voice_Lite_Logo.png"), show_immediately=True)
    dashboard = None
    dashboard_enabled = DashboardServer is not None and not _is_port_in_use(8000)
    if DashboardServer is not None and not dashboard_enabled:
        _startup_log("dashboard disabled: port 8000 already in use")
        try:
            ui.write_log("SYS: Mobile Connect уже запущен в другом экземпляре Voice Echo.")
        except Exception:
            pass
    if dashboard_enabled:
        dashboard = DashboardServer()

    if dashboard is not None:
        def _start_dashboard_server():
            try:
                _startup_log("dashboard thread started")
                asyncio.run(dashboard.serve())
            except Exception as exc:
                _startup_log(f"dashboard thread error: {exc}")
                try:
                    ui.write_log(f"ERR: Ошибка сервера Mobile Connect: {exc}")
                except Exception:
                    pass

        threading.Thread(target=_start_dashboard_server, daemon=True).start()
        _startup_log("dashboard thread spawned")

    voice_connect = None
    voice_connect_enabled = False
    if get_voice_connect_service is not None:
        try:
            voice_connect = get_voice_connect_service(BASE_DIR)
            voice_connect_enabled = bool(voice_connect.gateway.config.enabled)
        except Exception as exc:
            _startup_log(f"voice connect init failed: {exc}")
            try:
                ui.write_log(f"ERR: Не удалось инициализировать Voice Connect: {exc}")
            except Exception:
                pass
            voice_connect = None
    try:
        if voice_connect is not None and hasattr(ui, "set_voice_connect_service"):
            ui.set_voice_connect_service(voice_connect)
    except Exception:
        pass
    if voice_connect is not None and voice_connect_enabled:
        connect_port = int(getattr(voice_connect.gateway.config, "port", 8765))
        if _is_port_in_use(connect_port):
            _startup_log(f"voice connect disabled: port {connect_port} already in use")
            try:
                ui.write_log(f"SYS: Voice Connect уже запущен на порту {connect_port}.")
            except Exception:
                pass
        else:
            def _start_voice_connect_server():
                try:
                    _startup_log("voice connect thread started")
                    voice_connect.start_background()
                    _startup_log("voice connect thread spawned")
                except Exception as exc:
                    _startup_log(f"voice connect thread error: {exc}")
                    try:
                        ui.write_log(f"ERR: Ошибка сервера Voice Connect: {exc}")
                    except Exception:
                        pass

            threading.Thread(target=_start_voice_connect_server, daemon=True).start()



    ui.show_main()
    _startup_log("ui shown")

    # Initialize plugin manager and load any plugins from ./plugins
    try:
        plugin_manager = PluginManager(BASE_DIR)
        plugin_manager.load_plugins()
    except Exception:
        plugin_manager = None

    def runner():
        _startup_log("runner waiting api key")
        ui.wait_for_api_key()
        _startup_log("runner api key ready")
        voice_echo = VoiceLive(
            ui,
            dashboard=dashboard,
            dashboard_started=dashboard is not None,
            enable_dashboard=dashboard_enabled,
        )
        try:
            if plugin_manager is not None:
                voice_echo.plugin_manager = plugin_manager
                plugin_manager.register_voice(voice_echo)
                # allow plugins to run a startup hook
                try:
                    plugin_manager.dispatch("on_startup", voice_echo)
                except Exception:
                    pass
        except Exception:
            pass

        print(f"DEBUG: start_ig_daemon is {start_ig_daemon}")
        
        if start_ig_daemon:
            from actions.instagram_chat import set_ig_prompt_callback
            def _ig_handler(thread_id, username, text, is_auto):
                if is_auto:
                    return _ig_gemini_reply(username, text)
                else:
                    voice_echo._ig_reply_mode = True
                    voice_echo._ig_pending_thread = {
                        "thread_id": thread_id,
                        "username": username,
                        "message": text
                    }
                    msg = f"Вам новое сообщение в Instagram от {username}. Что ответить, или мне взять переписку на себя?"
                    ui.write_log(f"📱 Insta ({username}): {text}")
                    ui.write_log(f"Voice Echo: {msg}")
                    voice_echo.speak(msg)
                    return None
                
            set_ig_prompt_callback(_ig_handler)
            start_ig_daemon()

        def _clipboard_monitor():
            try:
                last_clip = pyperclip.paste()
            except Exception:
                last_clip = ""
                
            while True:
                time.sleep(1.0)
                try:
                    curr_clip = pyperclip.paste()
                    if curr_clip != last_clip:
                        last_clip = curr_clip
                        text = (curr_clip or "").strip()
                        if text and len(text) > 3:
                            reply = _clipboard_gemini_reply(text[:1000])
                            ui.write_log(f"Voice Echo (Clipboard): {reply}")
                            voice_echo.speak(reply)
                except Exception:
                    pass

        threading.Thread(target=_clipboard_monitor, daemon=True, name="clipboard-monitor").start()

        try:
            asyncio.run(voice_echo.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    def start_runner():
        threading.Thread(target=runner, daemon=True).start()

    start_runner()
    try:
        ui.play_boot_sequence(
            finished_callback=lambda: threading.Thread(
                target=_speak_daily_briefing,
                args=(ui,),
                daemon=True,
                name="daily-briefing",
            ).start()
        )
    except Exception:
        ui.show_main()
        start_runner()
        threading.Thread(
            target=_speak_daily_briefing,
            args=(ui,),
            daemon=True,
            name="daily-briefing",
        ).start()
    ui.root.mainloop()


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception as e:
        with open("FATAL_CRASH.log", "w") as f:
            traceback.print_exc(file=f)
        raise
