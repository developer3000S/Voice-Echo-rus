import json
import re
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = Lock()
MAX_VALUE_LENGTH = 380
MEMORY_MAX_CHARS = 2200


def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {}
    }


def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()

    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()


def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


def _trim_to_limit(memory: dict) -> dict:
    serialized = json.dumps(memory, ensure_ascii=False)
    if len(serialized) <= MEMORY_MAX_CHARS:
        return memory

    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))

    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        print(f"[Memory] 🗑️  Trimmed {cat}/{key} (limit: {MEMORY_MAX_CHARS} chars)")

    return memory


def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return

    memory = _trim_to_limit(memory)

    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue

        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            if isinstance(value, dict) and "value" in value:
                new_val = _truncate_value(str(value["value"]))
            else:
                new_val = _truncate_value(str(value))

            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True

    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()

    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory


def should_extract_memory(user_text: str, voice_text: str, api_key: str = "") -> bool:
    try:
        from llm_client import client

        combined = f"User: {user_text[:300]}\nVoice AI: {voice_text[:1000]}"

        result = client.chat(
            f"Содержит ли этот разговор ХОТЯ БЫ ОДНО из перечисленного?\n"
            f"- Личные факты (имя, возраст, город, работа, день рождения, национальность)\n"
            f"- Предпочтения или любимое (еда, цвет, музыка, спорт, игра, фильм, книга и т.д.)\n"
            f"- Активные проекты или цели, над которыми работает пользователь\n"
            f"- Люди из жизни пользователя (друзья, семья, партнёр, коллеги)\n"
            f"- Что пользователь хочет сделать или купить в будущем\n"
            f"- Любой другой факт, достойный долгосрочного запоминания\n\n"
            f"Ответь только YES или NO.\n\nРазговор:\n{combined}",
            system="Ты — проверщик релевантности памяти. Отвечай только YES или NO.",
            max_tokens=5,
            temperature=0.0,
        )
        return "YES" in result.upper()

    except Exception as e:
        print(f"[Memory] ⚠️ Stage1 check failed: {e}")
        return False


def extract_memory(user_text: str, voice_text: str, api_key: str = "") -> dict:
    try:
        from llm_client import client

        combined = f"User: {user_text[:600]}\nVoice AI: {voice_text[:300]}"

        raw = client.chat(
            f"Извлеки ВСЕ запоминающиеся личные факты из этого разговора. Любой язык.\n"
            f"Верни ТОЛЬКО валидный JSON. Используй {{}}, если действительно нечего сохранять.\n\n"
            f"Руководство по категориям:\n"
            f"  identity      → имя, возраст, день рождения, город, страна, работа, школа, национальность, язык\n"
            f"  preferences   → ЛЮБОЕ любимое или предпочитаемое:\n"
            f"                  favorite_food, favorite_color, favorite_music, favorite_film,\n"
            f"                  favorite_game, favorite_sport, favorite_book, favorite_artist,\n"
            f"                  favorite_country, hobbies, interests, dislikes и т.д.\n"
            f"  projects      → строящиеся проекты, текущая работа, цели, идеи в процессе\n"
            f"                  (например, mark_xxv: 'Building a Voice AI - Lite assistant')\n"
            f"  relationships → упомянутые люди: друзья, семья, партнёр, коллеги\n"
            f"                  (например, best_friend_ali: 'Best friend, met in university')\n"
            f"  wishes        → планы на будущее, покупки, путешествия, мечты\n"
            f"  notes         → всё остальное, достойное запоминания (привычки, расписание и т.д.)\n\n"
            f"ВАЖНО:\n"
            f"- Будь ЩЕДРЫМ: если что-то МОЖЕТ быть достойно запоминания, включи это.\n"
            f"- Извлекай из реплик И пользователя, И Voice AI.\n"
            f"- Пропусти: погоду, напоминания, результаты поиска, разовые команды.\n"
            f"- Значения пиши кратко на русском языке независимо от языка разговора.\n\n"
            f"Формат:\n"
            f'{{"identity":{{"name":{{"value":"Али"}}}},\n'
            f' "preferences":{{"favorite_color":{{"value":"синий"}}}},\n'
            f' "projects":{{"mark_xxv":{{"value":"ассистент Voice AI - Lite"}}}},\n'
            f' "relationships":{{"friend_yusuf":{{"value":"близкий друг"}}}},\n'
            f' "wishes":{{"buy_guitar":{{"value":"хочет акустическую гитару"}}}},\n'
            f' "notes":{{"works_at_night":{{"value":"обычно активен поздно ночью"}}}}}}\n\n'
            f"Разговор:\n{combined}\n\nJSON:",
            system="Верни ТОЛЬКО валидный JSON. Без markdown, без пояснений, без лишнего текста.",
            max_tokens=1024,
            temperature=0.2,
        )

        clean = raw.strip()
        clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()

        if not clean or clean == "{}":
            return {}

        return json.loads(clean)

    except json.JSONDecodeError:
        return {}
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ Extract failed: {e}")
        return {}


def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    identity  = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    projects = memory.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for key, entry in list(projects.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for key, entry in list(rels.items())[:10]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for key, entry in list(wishes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    notes = memory.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for key, entry in list(notes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 2000:
        result = result[:1997] + "…"

    return result + "\n"


def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"

forget_memory = forget


CHAT_HISTORY_PATH = BASE_DIR / "memory" / "chat_history.json"
MAX_HISTORY_LENGTH = 40

def load_chat_history() -> list[dict]:
    if not CHAT_HISTORY_PATH.exists():
        return []
    with _lock:
        try:
            data = json.loads(CHAT_HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception as e:
            print(f"[Memory] ⚠️ Chat history load error: {e}")
        return []

def save_chat_history(history: list[dict]) -> None:
    CHAT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        CHAT_HISTORY_PATH.write_text(
            json.dumps(history[-MAX_HISTORY_LENGTH:], indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

def append_to_chat_history(user_msg: str, ai_reply: str) -> None:
    history = load_chat_history()
    if user_msg:
        history.append({"role": "user", "content": user_msg})
    if ai_reply:
        history.append({"role": "assistant", "content": ai_reply})
    save_chat_history(history)