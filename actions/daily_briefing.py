# actions/daily_briefing.py
"""
Daily Briefing Action for Voice AI.

Compiles a comprehensive, natural daily briefing including:
- Personalized greeting & current time
- Today's calendar schedule & events
- Top news headlines from Google News RSS
- Weather update
- Summary from previous sessions
"""

import datetime
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

PLUGIN = {
    "name": "daily_briefing",
    "description": (
        "Delivers a comprehensive daily briefing to the user including time, "
        "today's schedule/events, weather, and top world/tech news headlines. "
        "Call this whenever the user asks for their briefing, morning update, or what's happening today."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "category": {
                "type": "STRING",
                "description": "Optional category focus: all (default), tech, world, schedule",
            }
        },
        "required": [],
    },
}


def _get_top_headlines(category: str = "all", limit: int = 3) -> list[str]:
    """Fetches clean top headlines from Russian RSS feeds (Google News RSS is unreachable from this network)."""
    feeds: list[tuple[str, str]] = [
        ("https://tass.ru/rss/v2.xml", "TASS"),
        ("https://ria.ru/export/rss2/index.xml", "РИА Новости"),
        ("https://lenta.ru/rss/news", "Lenta.ru"),
    ]
    if category.lower() == "tech":
        feeds = [("https://tass.ru/rss/v2.xml", "TASS")]

    headlines: list[str] = []
    for feed_url, source in feeds:
        if len(headlines) >= limit:
            break
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                root = ET.fromstring(resp.read())
            for item in root.findall(".//item"):
                if len(headlines) >= limit:
                    break
                title_elem = item.find("title")
                if title_elem is None or not title_elem.text:
                    continue
                title = " ".join(title_elem.text.split())
                if title and title not in headlines:
                    headlines.append(title)
        except Exception as e:
            print(f"[DailyBriefing] News fetch error ({source}): {e}")

    return headlines[:limit]


def _get_today_schedule() -> list[str]:
    """Checks for calendar events scheduled for today."""
    events_path = BASE_DIR / "memory" / "calendar_events.json"
    if not events_path.exists():
        return []

    try:
        with open(events_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            all_events = data
        elif isinstance(data, dict):
            all_events = data.get("events", [])
        else:
            all_events = []

        today_str = datetime.date.today().isoformat()
        today_events = [e for e in all_events if isinstance(e, dict) and e.get("date") == today_str]
        today_events.sort(key=lambda x: x.get("time", "00:00"))
        
        event_descriptions = []
        for e in today_events:
            t = e.get("time", "")
            title = e.get("title", "Event")
            if t:
                event_descriptions.append(f"{title} at {t}")
            else:
                event_descriptions.append(title)
        return event_descriptions
    except Exception as e:
        print(f"[DailyBriefing] Calendar fetch error: {e}")
        return []


def compile_daily_briefing(category: str = "all") -> str:
    """
    Compiles a complete daily briefing.
    """
    now = datetime.datetime.now()
    hour_24 = now.strftime("%H")
    minute = now.strftime("%M")
    time_str = f"{int(hour_24)}:{minute}"
    russian_days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    russian_months = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ]
    date_str = f"{russian_days[now.weekday()]}, {now.day} {russian_months[now.month - 1]}"

    greeting = "Доброе утро"
    if now.hour >= 12 and now.hour < 17:
        greeting = "Добрый день"
    elif now.hour >= 17:
        greeting = "Добрый вечер"

    parts = [f"{greeting}. Сегодня {date_str}, сейчас {time_str}."]

    # 1. Schedule check
    today_events = _get_today_schedule()
    if today_events:
        parts.append(f"На сегодня у вас запланировано: {', '.join(today_events)}.")
    else:
        parts.append("На сегодня у вас нет запланированных событий в календаре.")

    # 2. Previous session context
    try:
        from workspace_store import store
        s = store()
        summary = s._get_state("last_session_summary")
        if summary:
            parts.append(f"Из прошлой сессии: {summary}")
            s._set_state("last_session_summary", "")
    except Exception:
        pass

    # 3. Top News Headlines
    headlines = _get_top_headlines(category=category, limit=3)
    if headlines:
        headline_text = " • " + " • ".join([f"{h}" for h in headlines])
        parts.append(f"Последние новости: {headline_text}")
    else:
        parts.append("Все системы в норме, готов к вашим поручениям.")

    return " ".join(parts)


def daily_briefing(
    parameters: dict | None = None,
    response: str | None = None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    Action entry point for daily briefing.
    """
    p = parameters or {}
    category = p.get("category", "all")
    text = compile_daily_briefing(category=category)

    if player:
        try:
            player.show_daily_briefing(text)
            player.write_log(f"Voice Echo: {text}")
        except Exception:
            pass

    if speak:
        try:
            speak(text)
        except Exception:
            pass

    return text


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Plugin wrapper."""
    return daily_briefing(parameters, player=player, session_memory=session_memory)
