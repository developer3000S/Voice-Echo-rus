import base64
import io
import json
import sys
import cv2
import mss
import mss.tools
from pathlib import Path

try:
    import PIL.Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from llm_client import client as llm

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

IMG_MAX_W = 640
IMG_MAX_H = 360
JPEG_Q    = 55

SYSTEM_PROMPT = (
    "Ты — Voice AI - Lite, open-source ассистент. "
    "Анализируй изображения с технической точностью и интеллектом. "
    "Помогай пользователю понятным ему образом — не усложняй. "
    "Будь кратким, умным и полезным, как ИИ-ассистент Тони Старка. "
    "Отвечай максимум 2 короткими предложениями. Скорость — приоритет. "
    "Обращайся к пользователю «сэр» для уважительного тона. "
    "Спрашивай, нужна ли пользователю дальнейшая помощь с его проблемой."
)


def _get_camera_index() -> int:
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "camera_index" in cfg:
            return int(cfg["camera_index"])
    except Exception:
        pass

    print("[Camera] [FIND] No camera index in config. Auto-detecting...")
    best_index = 0

    for idx in range(6):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            continue
        for _ in range(5):
            cap.read()
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None and frame.mean() > 5:
            best_index = idx
            print(f"[Camera] [OK] Camera found at index {idx} — saving to config.")
            break
        else:
            print(f"[Camera] [WARN]  Index {idx}: no valid frame.")

    try:
        cfg = {}
        if API_CONFIG_PATH.exists():
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["camera_index"] = best_index
        with open(API_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        print(f"[Camera] [SAVE] Camera index {best_index} saved to config.")
    except Exception as e:
        print(f"[Camera] [WARN]  Could not save camera index: {e}")

    return best_index


def _to_jpeg(img_bytes: bytes) -> bytes:
    if not _PIL_OK:
        return img_bytes
    img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
    resample = getattr(PIL.Image, "Resampling", PIL.Image).BILINEAR
    img.thumbnail([IMG_MAX_W, IMG_MAX_H], resample)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
    return buf.getvalue()


def _capture_screenshot() -> bytes:
    try:
        if _PIL_OK:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=True).convert("RGB")
            resample = getattr(PIL.Image, "Resampling", PIL.Image).BILINEAR
            img.thumbnail([IMG_MAX_W, IMG_MAX_H], resample)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
            return buf.getvalue()
        else:
            raise RuntimeError("PIL not available")
    except Exception as e:
        print(f"[ScreenProcess] PIL ImageGrab failed ({e}). Falling back to mss.")
        with mss.mss() as sct:
            monitors = getattr(sct, "monitors", []) or []
            if len(monitors) > 1:
                monitor = monitors[1]
            elif monitors:
                monitor = monitors[0]
            else:
                raise RuntimeError("No monitors were detected for screen capture.")
            shot = sct.grab(monitor)
            png_bytes = mss.tools.to_png(shot.rgb, shot.size)
        return _to_jpeg(png_bytes)


def _capture_camera() -> bytes:
    camera_index = _get_camera_index()
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Camera could not be opened: index {camera_index}")
    for _ in range(10):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        raise RuntimeError("Could not capture camera frame.")
    if _PIL_OK:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail([IMG_MAX_W, IMG_MAX_H], PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
        return buf.getvalue()
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    return buf.tobytes()


def screen_process(
    parameters:     dict,
    response:       str | None = None,
    player=None,
    session_memory=None,
    image_bytes:    bytes | None = None,
) -> bool:
    user_text = (parameters or {}).get("text") or (parameters or {}).get("user_text", "")
    user_text = (user_text or "").strip()
    if not user_text:
        print("[ScreenProcess] [WARN] No user_text provided.")
        return False

    angle = (parameters or {}).get("angle", "screen").lower().strip()
    print(f"[ScreenProcess] angle={angle!r}  text={user_text!r}")

    def _screen_failure(message: str) -> bool:
        print(f"[ScreenProcess] [FAIL] {message}")
        if player and hasattr(player, "update_task_workspace"):
            try:
                player.update_task_workspace(
                    status="Screen analysis failed",
                    output=message,
                    percent=0,
                )
            except Exception:
                pass
        if player and hasattr(player, "write_log"):
            player.write_log(f"System Event: {message}")
        if player and hasattr(player, "set_scanning") and angle != "camera":
            player.set_scanning(False, "")
        return False

    if player and hasattr(player, "set_scanning") and angle != "camera":
        player.set_scanning(True, "SCANNING SCREEN")

    try:
        if angle == "camera":
            image_bytes = _capture_camera()
            mime_type   = "image/jpeg"
            print("[ScreenProcess] [CAMERA] Camera captured")
        else:
            if image_bytes:
                mime_type = "image/jpeg"
                print("[ScreenProcess] [SCREEN] Using pre-captured UI screenshot")
            else:
                image_bytes = _capture_screenshot()
                mime_type   = "image/jpeg" if _PIL_OK else "image/png"
                print("[ScreenProcess] [SCREEN] Screen captured")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"[ScreenProcess] [ERR] Capture error: {e}")
        return _screen_failure("Failed to capture the screen. Please ensure the application has permission to capture your display.")

    if not image_bytes:
        print("[ScreenProcess] [ERR] No image bytes available for analysis.")
        return _screen_failure("Screen capture returned empty data. Try again or restart the app.")

    print(f"[ScreenProcess] [PKG] {len(image_bytes)} bytes → sending")
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        text = llm.vision(user_text, b64, mime_type, system=SYSTEM_PROMPT, max_tokens=300)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"[ScreenProcess] [ERR] Vision analysis failed: {e}")
        return _screen_failure("Модуль зрения недоступен: локальной vision-модели нет.")

    if player and hasattr(player, "write_log"):
        player.write_log(f"Voice AI: {text}")
    if player and hasattr(player, "set_scanning") and angle != "camera":
        player.set_scanning(False, "")
    print(f"[ScreenProcess] [MSG] {text}")
    return True


def warmup_session(player=None):
    return None


if __name__ == "__main__":
    print("[TEST] screen_processor.py — local vision")
    print("=" * 50)
    mode    = input("screen / camera (default: screen): ").strip().lower() or "screen"
    request = input("Question (Enter for default): ").strip() or "What do you see? Be brief."

    result = screen_process({"angle": mode, "text": request}, player=None)
    print(f"\n{'[OK]' if result else '[ERR]'}")