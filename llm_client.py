import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("llm_client")


def _get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = _get_base_dir()
SETTINGS_PATH = BASE_DIR / "config" / "app_settings.json"
MODELS_DIR = BASE_DIR / "models" / "minicpm5-2b"
LOCAL_MODEL = "minicpm5-2b"
LOCAL_GGUF = MODELS_DIR / "MiniCPM5-2B-Q4_K_M.gguf"
LOCAL_MODELFILE = MODELS_DIR / "Modelfile"

TEMPLATE = """<|im_start|>system
{{ .System }}<|im_end|>
<|im_start|>user
{{ .Prompt }}<|im_end|>
<|im_start|>assistant
"""

TIMEOUT = 300

# Язык по умолчанию для всех пользовательских ответов ассистента.
# Берётся из config/app_settings.json (ключ assistant_language), по умолчанию "ru".
DEFAULT_ASSISTANT_LANGUAGE = "ru"
_SETTINGS_LANGUAGE_CACHE: Optional[str] = None


def assistant_language() -> str:
    """Текущий язык общения ассистента ('ru', 'en', ...).

    Значение кэшируется при первом обращении; вызовите ``reset_language_cache()``
    после изменения ``app_settings.json``, чтобы новый язык подхватился."""
    global _SETTINGS_LANGUAGE_CACHE
    if _SETTINGS_LANGUAGE_CACHE is not None:
        return _SETTINGS_LANGUAGE_CACHE
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            lang = json.load(f).get("assistant_language")
    except Exception:
        lang = None
    _SETTINGS_LANGUAGE_CACHE = (lang or DEFAULT_ASSISTANT_LANGUAGE).strip().lower() or DEFAULT_ASSISTANT_LANGUAGE
    return _SETTINGS_LANGUAGE_CACHE


def language_instruction() -> str:
    """Готовая инструкция для системного промпта: отвечать на текущем языке."""
    lang = assistant_language()
    if lang == "ru":
        return "Отвечай на русском языке."
    if lang == "en":
        return "Respond in English."
    return f"Respond in {lang}."


def reset_language_cache() -> None:
    global _SETTINGS_LANGUAGE_CACHE
    _SETTINGS_LANGUAGE_CACHE = None


class UnifiedAIClient:
    """Единый LLM-клиент. Всегда обращается к локальной модели через Ollama."""

    def __init__(self):
        self._local_url = "http://localhost:11434"
        self._local_model = LOCAL_MODEL
        self.reload_settings()

    def reload_settings(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            url = data.get("local_ai_url", "http://localhost:11434/v1").rstrip("/")
            # В настройках исторически хранится OpenAI-совместимый путь (/v1),
            # а нативный API Ollama живёт на корневом пути.
            self._local_url = url[:-3] if url.endswith("/v1") else url
            self._local_model = data.get("local_ai_model", LOCAL_MODEL)
        except Exception as e:
            logger.error(f"[LLM Client] Failed to load settings: {e}")

    # ------------------------------------------------------------------ core

    def _chat(self, messages: list[dict], temperature: float = 0.7,
              response_format: Optional[dict] = None, max_tokens: Optional[int] = None,
              think: bool = False, images: Optional[list[str]] = None,
              model: Optional[str] = None) -> Optional[str]:
        payload = {
            "model": model or self._local_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            "think": think,
        }
        if max_tokens:
            payload["num_predict"] = max_tokens
        if response_format:
            # Нативный API Ollama принимает "json" или объект JSON Schema,
            # но не OpenAI-овское "json_object".
            payload["format"] = "json"
        if images:
            payload["images"] = images

        endpoint = f"{self._local_url}/api/chat"
        try:
            resp = requests.post(endpoint, json=payload, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                message = data.get("message", {})
                content = message.get("content", "")
                return content.strip() if content else None
            logger.error(f"[LLM Client] Local AI Error {resp.status_code}: {resp.text[:300]}")
            return None
        except Exception as e:
            logger.error(f"[LLM Client] Local AI Request Failed: {e}")
            return None

    def chat(self, prompt: str, system: Optional[str] = None,
             history: Optional[list[dict]] = None, model: Optional[str] = None,
             max_tokens: int = 4096, temperature: float = 0.7) -> str:
        if system is None:
            system = f"Ты полезный ассистент. Отвечай кратко. {language_instruction()}"
        self.reload_settings()
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        result = self._chat(messages, temperature, max_tokens=max_tokens)
        if result:
            return result
        raise RuntimeError("Local AI request failed. Please check if Ollama is running.")

    def chat_json(self, prompt: str, system: Optional[str] = None, model: Optional[str] = None,
                  max_tokens: int = 4096) -> dict:
        if system is None:
            system = f"Верни только валидный JSON. {language_instruction()}"
        self.reload_settings()
        messages = [
            {"role": "system", "content": system + " Выводи только валидный JSON, без markdown-форматирования."},
            {"role": "user", "content": prompt},
        ]
        raw = self._chat(messages, temperature=0.2,
                         response_format={"type": "json_object"}, max_tokens=max_tokens)
        if not raw:
            raise RuntimeError("Local AI request failed.")

        clean = raw.strip()
        if clean.startswith("```"):
            parts = clean.split("```")
            clean = parts[1] if len(parts) > 1 else clean
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip().rstrip("`").strip()

        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            raise ValueError(f"Local model returned unparseable JSON: {e}\nRaw output: {raw[:200]}")

    # --------------------------------------------------------------- vision

    def vision(self, prompt: str, image_b64: str, mime: str = "image/png",
               system: str = "Analyze the image.", model: Optional[str] = None,
               max_tokens: int = 1024) -> str:
        """Анализ изображения. MiniCPM5 — текстовая модель, поэтому задача
        поручается мультимодальной модели Ollama (minicpmv), если она доступна."""
        self.reload_settings()
        vision_model = self._pick_vision_model()
        if not vision_model:
            raise RuntimeError("Vision request failed: no multimodal model available in Ollama.")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        result = self._chat(messages, temperature=0.2, max_tokens=max_tokens,
                            images=[image_b64], model=vision_model)
        if result:
            return result
        raise RuntimeError("Local AI vision request failed.")

    def vision_from_file(self, prompt: str, image_path: str, system: str = "Analyze the image.",
                         model: Optional[str] = None, max_tokens: int = 1024) -> str:
        self.reload_settings()
        path = Path(image_path)
        with open(path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        return self.vision(prompt, image_b64, system=system, model=model, max_tokens=max_tokens)

    def _pick_vision_model(self) -> Optional[str]:
        """Мультимодальные модели живут отдельным списком в настройках."""
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            candidate = data.get("local_vision_model", "minicpmv")
            if candidate and self._model_exists(candidate):
                return candidate
        except Exception as e:
            logger.error(f"[LLM Client] vision model lookup failed: {e}")
        return None

    def multi_turn(self, messages: list[dict], model: Optional[str] = None,
                   max_tokens: int = 4096, temperature: float = 0.7) -> str:
        self.reload_settings()
        result = self._chat(messages, temperature, max_tokens=max_tokens)
        if result:
            return result
        raise RuntimeError("Local AI request failed.")

    # ------------------------------------------------- Управление локальной моделью

    def _ollama_base(self) -> str:
        return self._local_url

    def _model_exists(self, model_name: Optional[str] = None) -> bool:
        try:
            resp = requests.get(f"{self._ollama_base()}/api/tags", timeout=10)
            if resp.status_code == 200:
                names = {m.get("name", "") for m in resp.json().get("models", [])}
                target = model_name or self._local_model
                return any(n.split(":")[0] == target for n in names)
        except Exception as e:
            logger.error(f"[LLM Client] ollama tags check failed: {e}")
        return False

    def ensure_local_model(self) -> bool:
        """Импортирует бандл GGUF в Ollama через /api/blobs + /api/create (идемпотентно)."""
        try:
            if self._model_exists():
                return True
            if not LOCAL_GGUF.exists():
                logger.error(f"[LLM Client] GGUF not found: {LOCAL_GGUF}")
                return False

            base = self._ollama_base()
            digest = "sha256:" + _sha256(LOCAL_GGUF)

            resp = requests.head(f"{base}/api/blobs/{digest}", timeout=10)
            if resp.status_code != 200:
                with open(LOCAL_GGUF, "rb") as f:
                    resp = requests.post(
                        f"{base}/api/blobs/{digest}",
                        data=f.read(),
                        headers={"Content-Type": "application/octet-stream"},
                        timeout=600,
                    )
                if resp.status_code not in (200, 201):
                    logger.error(f"[LLM Client] blob upload failed: {resp.status_code} {resp.text[:200]}")
                    return False

            payload = {
                "model": self._local_model,
                "files": {"m.gguf": digest},
                "template": TEMPLATE,
                "parameters": {
                    "stop": ["<|im_start|>", "<|im_end|>"],
                    "num_ctx": 4096,
                    "num_predict": 2048,
                    "temperature": 0.1,
                    "top_p": 0.9,
                },
            }
            with requests.post(f"{base}/api/create", json=payload, stream=True, timeout=1200) as resp:
                if resp.status_code != 200:
                    logger.error(f"[LLM Client] create failed: {resp.status_code}")
                    return False
                for line in resp.iter_lines():
                    if line and '"success"' in line and '"status"' in line:
                        if '"status":"success"' in line or '"status": "success"' in line:
                            return True
            return self._model_exists()
        except Exception as e:
            logger.error(f"[LLM Client] ensure_local_model failed: {e}")
            return False


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


client = UnifiedAIClient()
