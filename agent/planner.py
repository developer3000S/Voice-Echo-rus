import json
import re
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()


from llm_client import client as llm


PLANNER_PROMPT = """Ты — модуль планирования Voice Echo, персонального ИИ-ассистента.
Твоя задача: разбить любую цель пользователя на последовательность шагов, используя ТОЛЬКО инструменты из списка ниже.

АБСОЛЮТНЫЕ ПРАВИЛА:
- НИКОГДА не используй generated_code и не пиши Python-скрипты. Такого инструмента не существует.
- НИКОГДА не ссылайся на результаты предыдущих шагов в параметрах. Каждый шаг независим.
- Используй web_search для ЛЮБОГО поиска информации, исследований или актуальных данных.
- Используй file_controller для сохранения контента на диск.
- Используй cmd_control для открытия файлов или выполнения системных команд.
- Максимум 5 шагов. Используй минимально необходимое количество шагов.

ДОСТУПНЫЕ ИНСТРУМЕНТЫ И ИХ ПАРАМЕТРЫ:

open_app
  app_name: string (обязательно)

web_search
  query: string (обязательно) — чёткий, сфокусированный поисковый запрос
  mode: "search" или "compare" (опционально, по умолчанию: search)
  items: list of strings (опционально, для режима compare)
  aspect: string (опционально, для режима compare)

game_updater
  action: "update" | "install" | "list" | "download_status" | "schedule" (обязательно)
  platform: "steam" | "epic" | "both" (опционально, по умолчанию: both)
  game_name: string (опционально)
  app_id: string (опционально)
  shutdown_when_done: boolean (опционально)

browser_control
  action: "go_to" | "search" | "click" | "type" | "scroll" | "get_text" | "press" | "close" (обязательно)
  url: string (для go_to)
  query: string (для search)
  text: string (для click/type)
  direction: "up" | "down" (для scroll)

file_controller
  action: "write" | "create_file" | "read" | "list" | "delete" | "move" | "copy" | "find" | "disk_usage" (обязательно)
  path: string — используй "desktop" для папки рабочего стола
  name: string — имя файла
  content: string — содержимое файла (для write/create_file)

cmd_control
  task: string (обязательно) — описание на естественном языке, что нужно сделать
  visible: boolean (опционально)

office_builder
  Используй, когда пользователь просит ПРЕЗЕНТАЦИЮ, СЛАЙДЫ, ДЕК, ТАБЛИЦУ, EXCEL-ЛИСТ, ТРЕКЕР или БЮДЖЕТ.
  kind: "presentation" | "spreadsheet" (обязательно)
  title: string (обязательно)
  subtitle: string (опционально)
  theme: string (опционально, визуальный стиль)
  Для презентаций: outline: list of strings или slides: list of objects {"title", "bullets"} (максимум 20)
  Для таблиц: worksheets: list of objects {"name", "headers": [string], "rows": [[value]]}

word_document
  Используй, когда пользователь просит WORD-ДОКУМЕНТ, файл .docx, ПИСЬМО, ОТЧЁТ или РЕДАКТИРУЕМЫЙ ДОКУМЕНТ.
  action: "create" | "create_letter" | "create_report" | "summarize" | "read" | "open" (обязательно)
  title: string
  doc_type: "letter" | "report" (опционально)
  file_path: string (для действий read/summarize/open)
  body / content: string (для писем и отчётов)

pdf_document
  Используй, когда пользователь просит СОЗДАТЬ PDF или КОНВЕРТИРОВАТЬ файл DOCX/TXT в PDF.
  action: "create" | "create_letter" | "convert" (обязательно)
  title: string
  file_path: string (для convert — .docx, .txt, .md)
  body / content: string (для create)

file_processor
  Используй, когда пользователь просит ПРОАНАЛИЗИРОВАТЬ, РЕЗЮМИРОВАТЬ или ОБРАБОТАТЬ СУЩЕСТВУЮЩИЙ ФАЙЛ.
  file_path: string (обязательно)
  action: string (опционально — что сделать с файлом)
  instruction: string (опционально)

computer_settings
  action: string (обязательно)
  description: string — описание на естественном языке
  value: string (опционально)

computer_control
  action: "type" | "click" | "hotkey" | "press" | "scroll" | "screenshot" | "screen_find" | "screen_click" (обязательно)
  text: string (для type)
  x, y: int (для click)
  keys: string (для hotkey, например "ctrl+c")
  key: string (для press)
  direction: "up" | "down" (для scroll)
  description: string (для screen_find/screen_click)

screen_process
  text: string (обязательно) — что проанализировать или спросить об экране
  angle: "screen" | "camera" (опционально)

send_message
  receiver: string (обязательно для личных сообщений)
  message_text: string (обязательно для личных сообщений; опциональная подпись для загрузок)
  platform: string (обязательно)
  mode: "dm" | "upload" (опционально; используй upload для медиа-публикаций в Instagram)
  media_path: string (опционально; обязательно для загрузок в Instagram)

reminder
  date: string YYYY-MM-DD (обязательно)
  time: string HH:MM (обязательно)
  message: string (обязательно)

desktop_control
  action: "wallpaper" | "organize" | "clean" | "list" | "task" (обязательно)
  path: string (опционально)
  task: string (опционально)

youtube_video
  action: "play" | "summarize" | "trending" (обязательно)
  query: string (для play)

weather_report
  city: string (обязательно)

flight_finder
  origin: string (обязательно)
  destination: string (обязательно)
  date: string (обязательно)

spotify_controller
  action: "play" | "pause" | "toggle" | "next" | "previous" | "volume_up" | "volume_down" | "search_play" | "open_spotify" (обязательно)
  query: string (для search_play, название песни или исполнителя)

calendar_scheduler
  action: "add_event" | "list_events" | "check_day" | "delete_event" | "get_upcoming" | "export_ics" (обязательно)
  title: string (для add_event)
  date: string (YYYY-MM-DD или "today", "tomorrow")
  time: string (HH:MM)
  duration_minutes: number (опционально, по умолчанию: 30)
  location: string (опционально)

daily_briefing
  category: "all" | "tech" | "world" (опционально)
  Используй, когда пользователь просит утреннюю сводку, дневную сводку или новости.

claude_code
  description: string (обязательно)
  workspace_path: string (опционально)
  Используй для любых запросов по программированию, сайтам, проектам, редактированию файлов и разработке.

ПРИМЕРЫ:

Цель: "изучи машиностроение и сохрани в блокнот"
Шаги:

web_search | query: "машиностроение обзор определение история"
web_search | query: "машиностроение применение и будущие тренды"
file_controller | action: write, path: desktop, name: mechanical_engineering.txt, content: "ИССЛЕДОВАНИЕ МАШИНОСТРОЕНИЯ\n\nЭтот файл будет заполнен результатами веб-исследования."
cmd_control | task: "открой mechanical_engineering.txt на рабочем столе в блокноте"

Цель: "Какая цена у биткоина"
Шаги:

web_search | query: "цена биткоина сегодня USD"

Цель: "Покажи файлы на рабочем столе и найди 5 самых больших"
Шаги:

file_controller | action: list, path: desktop
file_controller | action: largest, path: desktop, count: 5

Цель: "Установи PUBG из Steam"
Шаги:

game_updater | action: install, platform: steam, game_name: "PUBG"

Цель: "Обнови все мои игры в Steam"
Шаги:

game_updater | action: update, platform: steam

Цель: "Напиши Джону в WhatsApp, что завтра встреча"
Шаги:

send_message | receiver: John, message_text: "Tomorrow there is a meeting", platform: WhatsApp

Цель: "Открой часы и поставь напоминание на 30 минут позже"
Шаги:

reminder | date: [today], time: [now+30min], message: "Reminder"

Цель: "Собери премиум-сайт для моего ИИ-ассистента"
Шаги:

Цель: "Включи песню Starboy в Spotify"
Шаги:

spotify_controller | action: search_play, query: "Starboy"

Цель: "Включи расслабляющую музыку"
Шаги:

spotify_controller | action: search_play, query: "relaxing music"

Цель: "Поставь музыку на паузу"
Шаги:

spotify_controller | action: pause

Цель: "Перейди к следующей песне"
Шаги:

spotify_controller | action: next

Цель: "Добавь синхронизацию команды в календарь на завтра в 16:00"
Шаги:

calendar_scheduler | action: add_event, title: "Team sync", date: "tomorrow", time: "16:00", duration_minutes: 30

ВЫВОД — возвращай ТОЛЬКО валидный JSON, без markdown, без пояснений, без блоков кода:
{
  "goal": "...",
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "description": "что делает этот шаг",
      "parameters": {},
      "critical": true
    }
  ]
}
"""


def _looks_like_website_goal(goal: str) -> bool:
    text = (goal or "").lower()
    return any(token in text for token in (
        "website",
        "landing page",
        "landingpage",
        "portfolio",
        "business site",
        "product site",
        "marketing site",
        "homepage",
        "web page",
        "site for",
        "build a site",
        "create a site",
        "create a website",
    ))


def _rewrite_generated_step(step: dict, goal: str) -> None:
    if step.get("tool") != "generated_code":
        return
    desc = step.get("description", goal) or goal
    if _looks_like_website_goal(goal):
        print(f"[Planner] ⚠️ generated_code detected in step {step.get('step')} — replacing with claude_code")
        step["tool"] = "claude_code"
        step["parameters"] = {
          "description": desc[:1200],
        }
        return
    print(f"[Planner] ⚠️ generated_code detected in step {step.get('step')} — replacing with web_search")
    step["tool"] = "web_search"
    step["parameters"] = {"query": desc[:200]}


def create_plan(goal: str, context: str = "") -> dict:
    user_input = f"Goal: {goal}"
    if context:
        user_input += f"\n\nContext: {context}"

    try:
        text = llm.chat(
            user_input,
            system=PLANNER_PROMPT.strip(),
            max_tokens=4096,
            temperature=0.3,
        )
        text     = text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        plan = json.loads(text)

        if "steps" not in plan or not isinstance(plan["steps"], list):
            raise ValueError("Invalid plan structure")

        for step in plan["steps"]:
            _rewrite_generated_step(step, goal)

        print(f"[Planner] ✅ Plan: {len(plan['steps'])} steps")
        for s in plan["steps"]:
            print(f"  Step {s['step']}: [{s['tool']}] {s['description']}")

        return plan

    except json.JSONDecodeError as e:
        print(f"[Planner] ⚠️ JSON parse failed: {e}")
        return _fallback_plan(goal)
    except Exception as e:
        print(f"[Planner] ⚠️ Planning failed: {e}")
        return _fallback_plan(goal)


def _fallback_plan(goal: str) -> dict:
    print("[Planner] 🔄 Fallback plan")
    if _looks_like_website_goal(goal):
        return {
          "goal": goal,
          "steps": [
            {
              "step": 1,
              "tool": "claude_code",
              "description": f"Create the requested website with Claude Code: {goal}",
              "parameters": {"description": goal},
              "critical": True,
            }
          ],
        }
    return {
        "goal": goal,
        "steps": [
            {
                "step": 1,
                "tool": "web_search",
                "description": f"Search for: {goal}",
                "parameters": {"query": goal},
                "critical": True
            }
        ]
    }


def replan(goal: str, completed_steps: list, failed_step: dict, error: str) -> dict:
    completed_summary = "\n".join(
        f"  - Шаг {s['step']} ({s['tool']}): ВЫПОЛНЕН" for s in completed_steps
    )

    prompt = f"""Цель: {goal}

Уже выполнено:
{completed_summary if completed_summary else '  (ничего)'}

Проваленный шаг: [{failed_step.get('tool')}] {failed_step.get('description')}
Ошибка: {error}

Создай ИСПРАВЛЕННЫЙ план только для оставшейся работы. Не повторяй выполненные шаги."""

    try:
        text = llm.chat(
            prompt,
            system=PLANNER_PROMPT.strip(),
            max_tokens=4096,
            temperature=0.3,
        )
        text     = text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        plan     = json.loads(text)

        for step in plan.get("steps", []):
            _rewrite_generated_step(step, goal)

        print(f"[Planner] 🔄 Revised plan: {len(plan['steps'])} steps")
        return plan
    except Exception as e:
        print(f"[Planner] ⚠️ Replan failed: {e}")
        return _fallback_plan(goal)
