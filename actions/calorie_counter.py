"""
JARVIS plugin — Calorie Counter (webcam vision).

Hold food up to the camera and ask "how many calories is this?" —
JARVIS switches the HUD to the live camera with an animated scan bar,
photographs the food, analyzes it with the local model, speaks a short summary
in your language and shows the full nutrition breakdown in the
content panel.

Visuals rely on MainWindow's camera signals (_cam_stream_sig /
_cam_frame_sig, present since Mark LI). If they're ever missing the
plugin still works — just without the camera view.
"""

import base64
import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent

PLUGIN = {
    "name": "calorie_counter",
    "description": (
        "Analyzes FOOD through the WEBCAM and reports calories and nutrition "
        "(carbs, sugar, fiber, protein, fat). Use whenever the user asks about "
        "the calories or nutritional value of food they are physically holding "
        "or showing right now — e.g. 'bu elimdeki tabak kaç kalori', 'how many "
        "calories is this', 'şunun besin değeri ne'. This tool takes its OWN "
        "camera photo — NEVER use screen_process for food-calorie questions. "
        "Pass the user's exact spoken words in 'query'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "The user's exact request, verbatim, in their own language.",
            }
        },
        "required": ["query"],
    },
}

_LIVE_SCAN_SECONDS = 1.8     # live preview before the photo is taken
_FPS               = 25
_ANIM_MAX_SECONDS  = 25      # animator safety stop
_SCAN_COLOR        = (255, 190, 40)    # JARVIS cyan-blue (BGR)
_SCAN_CORE         = (255, 235, 130)   # bright core line (BGR)


# ── config helpers (same pattern as actions/web_search.py) ──────────────────

def _config() -> dict:
    try:
        return json.loads(
            (BASE_DIR / "config" / "api_keys.json").read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def _open_camera():
    import platform
    try:
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
    except AttributeError:
        backend = 0
    cap = cv2.VideoCapture(int(_config().get("camera_index", 0)), backend)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return None
    for _ in range(6):  # warm-up frames
        cap.read()
    return cap


# ── scan-bar rendering ───────────────────────────────────────────────────────

def _draw_scan_bar(frame: np.ndarray, phase: float) -> np.ndarray:
    """Return a copy of the BGR frame with an animated scan bar sweeping
    bottom → top → bottom (triangle wave on `phase`)."""
    h, w = frame.shape[:2]
    pos = phase % 2.0
    pos = pos if pos <= 1.0 else 2.0 - pos
    y    = int((1.0 - pos) * (h - 1))
    band = max(6, h // 14)

    out = frame.copy()
    y0, y1 = max(0, y - band), min(h, y + band)
    if y1 > y0:
        region = out[y0:y1].astype(np.float32)
        falloff = 1.0 - (np.abs(np.arange(y0, y1) - y).astype(np.float32) / band)
        alpha = falloff[:, None, None] * 0.55
        glow = np.empty_like(region)
        glow[:] = _SCAN_COLOR
        out[y0:y1] = np.clip(region * (1 - alpha) + glow * alpha, 0, 255).astype(np.uint8)
    cv2.line(out, (0, y), (w, y), _SCAN_CORE, 2)
    return out


def _emit_frame(frame_sig, frame: np.ndarray) -> None:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if ok:
        frame_sig.emit(buf.tobytes())


# ── Nutrition analysis ────────────────────────────────────────────────────────

def _analyze(photo: np.ndarray, query: str, api_key: str) -> dict:
    from llm_client import client as llm

    # match screen_processor's upload size: max 1280 wide
    h, w = photo.shape[:2]
    if w > 1280:
        photo = cv2.resize(photo, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("could not encode photo")

    prompt = (
        "Ты — анализатор питания. Посмотри на еду на этом фото.\n"
        f'Запрос пользователя (отвечай на ТОМ ЖЕ языке, что и запрос): "{query}"\n'
        "Верни ТОЛЬКО минифицированный JSON — без markdown-блоков, без лишнего текста — со следующими ключами:\n"
        ' "food": краткое название блюда/продуктов (null, если еды НЕ видно),\n'
        ' "portion": предполагаемый размер порции коротким текстом,\n'
        ' "calories_kcal": число (общая оценка),\n'
        ' "carbs_g", "sugar_g", "fiber_g", "protein_g", "fat_g": числа,\n'
        ' "panel_text": многострочное текстовое описание пищевой ценности на языке'
        " пользователя — название еды, порция, общее количество калорий, затем"
        " по одной строке на каждый макронутриент (углеводы, сахар, клетчатка,"
        " белки, жиры) с единицами измерения; если видно несколько блюд, добавь"
        " краткий список калорий по каждому пункту; максимум 25 строк,\n"
        ' "spoken_summary": 1-2 разговорных предложения на языке пользователя,'
        " называющие еду и общее количество калорий, с упоминанием, что это"
        " приблизительная оценка. Если еды не видно, вежливо сообщи об этом."
    )

    jpg_b64 = base64.b64encode(jpg.tobytes()).decode("utf-8")
    text = llm.vision(
        prompt,
        jpg_b64,
        "image/jpeg",
        system="Ты — анализатор питания. Верни ТОЛЬКО валидный JSON.",
        max_tokens=2048,
    )
    text = (text or "").strip()

    # tolerate accidental fences / prose around the JSON
    if "{" in text and "}" in text:
        text = text[text.find("{"): text.rfind("}") + 1]
    return json.loads(text)


# ── entry point ──────────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    query = (parameters.get("query") or "").strip() or "How many calories is this food?"

    def _log(msg: str) -> None:
        if player:
            try:
                player.write_log(msg)
            except Exception:
                pass

    # HUD camera signals (graceful if unavailable)
    win        = getattr(player, "_win", None) if player else None
    frame_sig  = getattr(win, "_cam_frame_sig", None)
    stream_sig = getattr(win, "_cam_stream_sig", None)

    cap = _open_camera()
    if cap is None:
        return ("I couldn't access the camera — it may be in use by another "
                "feature or application.")

    photo = None
    stop_anim = threading.Event()
    animator = None
    view_open = False
    try:
        if stream_sig:
            stream_sig.emit(True)   # HUD logo → live camera view
            view_open = True
        _log("JARVIS: Nutrition scan started.")

        # Phase 1 — live preview with scan bar (user positions the food)
        t0 = time.time()
        last = None
        while time.time() - t0 < _LIVE_SCAN_SECONDS:
            ok, frm = cap.read()
            if ok and frm is not None:
                last = frm
                if frame_sig:
                    _emit_frame(frame_sig, _draw_scan_bar(frm, (time.time() - t0) * 1.2))
            time.sleep(1.0 / _FPS)
        ok, frm = cap.read()
        photo = frm if ok and frm is not None else last
    finally:
        try:
            cap.release()   # release BEFORE anything else — avoid device conflicts
        except Exception:
            pass

    if photo is None:
        if view_open:
            stream_sig.emit(False)
        return "I couldn't capture a picture of the food, sorry."

    # Phase 2 — freeze frame, keep the scan bar sweeping while the model analyzes
    if frame_sig:
        def _animate():
            a0 = time.time()
            while (not stop_anim.wait(1.0 / _FPS)
                   and time.time() - a0 < _ANIM_MAX_SECONDS):
                _emit_frame(frame_sig, _draw_scan_bar(photo, (time.time() - a0) * 1.2))
        animator = threading.Thread(target=_animate, daemon=True,
                                    name="calorie-scan-anim")
        animator.start()

    try:
        data = _analyze(photo, query, "")
    except Exception as e:
        return f"The nutrition analysis failed: {e}"
    finally:
        stop_anim.set()
        if animator:
            animator.join(timeout=1)
        if view_open:
            stream_sig.emit(False)  # back to the JARVIS HUD

    spoken = (data.get("spoken_summary") or "").strip()

    if data.get("food"):
        panel = (data.get("panel_text") or "").strip()
        if player and panel:
            try:
                player.show_content("🍽 NUTRITION SCAN", panel)
            except Exception:
                pass
        _log(f"JARVIS: Nutrition scan complete — {data.get('food')}"
             f" ≈ {data.get('calories_kcal')} kcal.")

    return spoken or "The scan finished, but I couldn't read the result."
