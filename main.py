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
from ui import VoiceUI
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
from llm_client import client as llm
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
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024


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
    
def _local_text_reply(prompt: str, system: str, temperature: float = 0.6) -> str:
    """Генерация ответа локальной моделью (Ollama)."""
    return llm.chat(prompt, system=system, temperature=temperature)


def _ig_local_reply(username: str, text: str) -> str:
    system_prompt = (
        "Ты — Voice Echo, ИИ-личный ассистент, действующий от имени своего пользователя. "
        "Ты ведёшь их чат в Instagram с разрешения пользователя. "
        "Отвечай естественно, кратко и по-русски, живому собеседнику. "
        "Не звучи как бот. Держи ответы короче двух предложений."
    )
    prompt = f"Instagram DM from {username}: {text}"
    try:
        return _local_text_reply(prompt, system_prompt)
    except Exception as e:
        print(f"[InstagramChat] Reply Error: {e}")
        return "Привет, я сейчас занят. Ответю чуть позже!"


def _clipboard_local_reply(text: str) -> str:
    system_prompt = (
        "Ты — Voice Echo, остроумный и полезный ИИ-ассистент. "
        "Пользователь только что скопировал в буфер обмена следующий текст. "
        "Сделай очень короткий, интересный или полезный комментарий или вопрос об этом (одно предложение). "
        "Не предлагай «помощь» и не спрашивай «чем помочь» — просто дай самостоятельное остроумное наблюдение или краткую суть на русском языке."
    )
    try:
        return _local_text_reply(text, system_prompt, temperature=0.8)
    except Exception:
        return "Интересный текст в буфере обмена!"


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


def _is_network_unreachable(exc: Exception) -> bool:
    """Return True for network errors that won't recover by retrying (DNS/host misconfiguration)."""
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
        if not should_extract_memory(user_text, voice_text):
            return
        data = extract_memory(user_text, voice_text)
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


class VoiceLive:

    def __init__(self, ui: VoiceUI, dashboard=None, dashboard_started: bool = False, enable_dashboard: bool = True):
        self.ui             = ui
        self._smart_home    = SmartHomeService()
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
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
                    self.speak(prompt)
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
                    self.ui._developer_status_lbl.setText("Building website with the local model in the selected workspace")
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
        threading.Thread(target=self._fallback_reply, args=(text, memory_ctx), daemon=True).start()


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
        self.speak(msg)
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
        self.speak(message)
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
            return _local_text_reply(
                prompt,
                system="You are a friendly assistant. Rewrite the reply naturally and humanely.",
                temperature=0.6,
            ) or user_text
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
            data = llm.chat_json(
                f"{system_prompt}\n\nUser Response: {text}",
                system="Return ONLY valid JSON.",
            )
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
                        reply = _ig_local_reply(username, message_text)
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
            request_text = f"{memory_ctx}\n\nCurrent User Request:\n{text}" if memory_ctx else text

            try:
                reply = llm.chat(
                    request_text,
                    system=(
                        "Ты — Voice Echo, краткий и полезный настольный ассистент. "
                        "Отвечай естественно, кратко и всегда на русском языке. "
                        "Не упоминай внутренние детали реализации."
                    ),
                )
            except Exception as e:
                print(f"[VOICE ECHO] ⚠️ Local model reply failed: {e}")
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

        def _speak_thread():
            try:
                self.set_speaking(True)
                from actions.attention_monitor import _speak_edge_native
                _speak_edge_native(text)
            except Exception as e:
                print(f"[VOICE ECHO] TTS failed: {e}")
            finally:
                self.set_speaking(False)
        threading.Thread(target=_speak_thread, daemon=True).start()

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Во время выполнения «{tool_name.replace('_', ' ')}» произошла ошибка. {short}")

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
        try:
            self.ui.boot_set_progress(36, "Инициализация AI-клиента")
        except Exception:
            pass

        if self._local_voice_enabled:
            # Fully offline voice loop: local STT (Vosk/sherpa) + local TTS (Piper).
            # No cloud endpoint is contacted for speech.
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
                    return _ig_local_reply(username, text)
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
                            reply = _clipboard_local_reply(text[:1000])
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
