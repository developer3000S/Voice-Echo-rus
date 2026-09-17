#flight_finder.py
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from config import is_windows, is_mac, is_linux

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

_MONTH_MAP: dict[str, int] = {

    "january": 1, "february": 2, "march": 3,     "april": 4,
    "may": 5,     "june": 6,     "july": 7,       "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "ocak": 1,  "şubat": 2,  "mart": 3,   "nisan": 4,
    "mayıs": 5, "haziran": 6, "temmuz": 7, "ağustos": 8,
    "eylül": 9, "ekim": 10,  "kasım": 11, "aralık": 12,
}

_RELATIVE_MAP_KEYS = {
    "today", "bugün",
    "tomorrow", "yarın",
}


def _parse_date(raw: str) -> str:

    raw   = raw.strip()
    lower = raw.lower()
    today = datetime.now()

    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    relative = {
        "today": today, "bugün": today,
        "tomorrow": today + timedelta(days=1),
        "yarın":    today + timedelta(days=1),
    }
    for key, val in relative.items():
        if key in lower:
            return val.strftime("%Y-%m-%d")
# replace the try/except genai block with:
    try:
        from llm_client import client
        result = client.chat(
            f"Today is {today.strftime('%Y-%m-%d')}. "
            f"Convert this date expression to YYYY-MM-DD: '{raw}'. "
            f"Return ONLY the date string, nothing else.",
            system="You are a date converter. Return only the YYYY-MM-DD string."
        )
        result = result.strip()
        if re.match(r"\d{4}-\d{2}-\d{2}", result):
            return result
    except Exception as e:
        print(f"[FlightFinder] ⚠️ date parse failed: {e}")
    for month_name, month_num in _MONTH_MAP.items():
        if month_name in lower:
            day_match = re.search(r"\d{1,2}", raw)
            if day_match:
                day  = int(day_match.group())
                year = today.year if month_num >= today.month else today.year + 1
                return f"{year}-{month_num:02d}-{day:02d}"

    # Last resort: today
    print(f"[FlightFinder] ⚠️ Could not parse date '{raw}' — using today.")
    return today.strftime("%Y-%m-%d")

_CABIN_CODE: dict[str, str] = {
    "economy":  "1",
    "premium":  "2",
    "business": "3",
    "first":    "4",
}

def _build_google_flights_url(
    origin:      str,
    destination: str,
    date:        str,
    return_date: str | None = None,
    passengers:  int        = 1,
    cabin:       str        = "economy",
) -> str:
    from urllib.parse import quote_plus

    cabin_code = _CABIN_CODE.get(cabin.lower(), "1")

    origin_enc      = quote_plus(origin)
    destination_enc = quote_plus(destination)

    if return_date:
        trip = f"Flights+from+{origin_enc}+to+{destination_enc}+on+{date}+returning+{return_date}"
    else:
        trip = f"Flights+from+{origin_enc}+to+{destination_enc}+on+{date}"

    return (
        f"https://www.google.com/travel/flights"
        f"?q={trip}"
        f"&curr=USD"
        f"&cabin={cabin_code}"
        f"&adults={passengers}"
    )

def _search_flights_browser(
    origin:      str,
    destination: str,
    date:        str,
    return_date: str | None,
    passengers:  int,
    cabin:       str,
) -> tuple[str, str]:
    import time
    from actions.browser_control import browser_control

    url = _build_google_flights_url(
        origin, destination, date, return_date, passengers, cabin
    )

    print(f"[FlightFinder] 🌐 Opening: {url}")
    browser_control({"action": "go_to", "url": url})
    time.sleep(5)

    raw = browser_control({"action": "get_text"})
    return (raw or ""), url
def _parse_flights_with_gemini(
    raw_text:    str,
    origin:      str,
    destination: str,
    date:        str,
) -> list[dict]:
    from llm_client import client

    prompt = (
        f"Extract flight options from {origin} to {destination} on {date} "
        f"from this Google Flights page text:\n\n{raw_text[:12000]}\n\n"
        f"Return a JSON array of up to 5 flights:\n"
        f'[{{"airline":"...","departure":"HH:MM","arrival":"HH:MM",'
        f'"duration":"Xh Ym","stops":0,"price":"...","currency":"USD"}}]\n'
        f"If no flights found, return: []"
    )

    try:
        result = client.chat_json(prompt, system="Return only valid JSON. No extra text.")
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"[FlightFinder] ⚠️ parse failed: {e}")
        return []

def _format_spoken(
    flights:     list[dict],
    origin:      str,
    destination: str,
    date:        str,
) -> str:
    if not flights:
        return (
            f"Не нашёл рейсов из {origin} в {destination} "
            f"на {date}. Возможно, страница загрузилась некорректно."
        )

    lines = [f"Вот лучшие рейсы из {origin} в {destination} на {date}."]

    for i, f in enumerate(flights[:5], 1):
        airline   = f.get("airline",   "Неизвестная авиакомпания")
        departure = f.get("departure", "--:--")
        arrival   = f.get("arrival",   "--:--")
        duration  = f.get("duration",  "")
        stops     = f.get("stops",     0)
        price     = f.get("price",     "")
        currency  = f.get("currency",  "")

        stop_str  = "без пересадок" if stops == 0 else f"{stops} пересадк{'а' if stops == 1 else 'и' if stops % 10 in (2,3,4) and stops % 100 not in (12,13,14) else 'ок'}"
        price_str = f"{price} {currency}".strip() if price else "цена недоступна"
        dur_str   = f", {duration}" if duration else ""

        lines.append(
            f"Вариант {i}: {airline}, вылет {departure}, "
            f"прилёт {arrival}{dur_str}, {stop_str}, {price_str}."
        )

    # Cheapest — strip non-digits for comparison
    priced = [f for f in flights if f.get("price")]
    if priced:
        cheapest = min(
            priced,
            key=lambda x: int(re.sub(r"[^\d]", "", str(x["price"])) or "999999"),
        )
        lines.append(
            f"Самый дешёвый вариант — {cheapest.get('airline')} "
            f"за {cheapest.get('price')} {cheapest.get('currency', '')}."
        )

    return " ".join(lines)


def _format_text_report(
    flights:     list[dict],
    origin:      str,
    destination: str,
    date:        str,
    return_date: str | None,
    page_url:    str,
) -> str:
    lines = [
        "Voice AI - Результаты поиска рейсов",
        "─" * 50,
        f"Маршрут   : {origin} → {destination}",
        f"Дата      : {date}",
    ]
    if return_date:
        lines.append(f"Обратно   : {return_date}")
    lines += [
        f"Поиск     : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Источник  : {page_url}",
        "─" * 50,
        "",
    ]

    if not flights:
        lines.append("Рейсы не найдены.")
    else:
        for i, f in enumerate(flights, 1):
            stops    = f.get("stops", 0)
            stop_str = "Без пересадок" if stops == 0 else f"{stops} пересадка(и)"
            lines += [
                f"Рейс {i}:",
                f"  Авиакомпания : {f.get('airline',   'N/A')}",
                f"  Вылет        : {f.get('departure', 'N/A')}",
                f"  Прилёт       : {f.get('arrival',   'N/A')}",
                f"  Длительность : {f.get('duration',  'N/A')}",
                f"  Пересадки    : {stop_str}",
                f"  Цена         : {f.get('price', 'N/A')} {f.get('currency', '')}",
                "",
            ]

    return "\n".join(lines)

def _save_to_desktop(content: str, origin: str, destination: str) -> str:
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"flights_{origin}_{destination}_{ts}.txt".replace(" ", "_")
    desktop  = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    filepath = desktop / filename

    filepath.write_text(content, encoding="utf-8")
    print(f"[FlightFinder] 💾 Saved: {filepath}")

    try:
        if is_windows():
            subprocess.Popen(["notepad.exe", str(filepath)])
        elif is_mac():
            subprocess.Popen(["open", "-t", str(filepath)])
        else:
            subprocess.Popen(["xdg-open", str(filepath)])
    except Exception as e:
        print(f"[FlightFinder] ⚠️ Could not open text editor: {e}")

    return str(filepath)


def flight_finder(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}

    origin      = params.get("origin",      "").strip()
    destination = params.get("destination", "").strip()
    date_raw    = params.get("date",        "").strip()
    return_raw  = (params.get("return_date") or "").strip()
    passengers  = max(1, int(params.get("passengers", 1)))
    cabin       = params.get("cabin", "economy").strip().lower()
    save        = bool(params.get("save", False))

    if not origin or not destination:
        return "Пожалуйста, укажите пункт отправления и пункт назначения."
    if not date_raw:
        return "Пожалуйста, укажите дату вылета."

    # Normalise cabin value
    if cabin not in _CABIN_CODE:
        cabin = "economy"

    date        = _parse_date(date_raw)
    return_date = _parse_date(return_raw) if return_raw else None

    if player:
        player.write_log(f"[FlightFinder] {origin} → {destination} on {date}")

    if speak:
        speak(f"Ищу рейсы из {origin} в {destination} на {date}.")

    print(
        f"[FlightFinder] ▶️ {origin} → {destination} | {date}"
        f"{' → ' + return_date if return_date else ''}"
        f" | {cabin} | {passengers} pax"
    )

    try:
        raw_text, page_url = _search_flights_browser(
            origin, destination, date, return_date, passengers, cabin
        )

        if not raw_text:
            return "Не удалось получить данные о рейсах. Возможно, страница не загрузилась."

        if speak:
            speak("Анализирую результаты.")

        flights = _parse_flights_with_gemini(raw_text, origin, destination, date)
        spoken  = _format_spoken(flights, origin, destination, date)

        if speak:
            speak(spoken)

        result = spoken

        if save and flights:
            report     = _format_text_report(flights, origin, destination, date, return_date, page_url)
            saved_path = _save_to_desktop(report, origin, destination)
            result    += f" Результаты сохранены на рабочем столе: {saved_path}"

        return result

    except Exception as e:
        print(f"[FlightFinder] ❌ {e}")
        return f"Не удалось выполнить поиск рейсов: {e}"