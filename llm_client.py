import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from proxy_manager import get_httpx_client

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


class UnifiedAIClient:
    """Единый LLM-клиент, который всегда обращается к локальной модели (Ollama)."""

    def __init__(self):
        self._local_url = "http://localhost:11434/v1"
        self._local_model = LOCAL_MODEL
        self.reload_settings()

    def reload_settings(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._local_url = data.get("local_ai_url", "http://localhost:11434/v1").rstrip("/")
            self._local_model = data.get("local_ai_model", LOCAL_MODEL)
        except Exception as e:
            logger.error(f"[LLM Client] Failed to load settings: {e}")

    def _local_chat_completion(self, messages: list[dict], temperature: float = 0.7, response_format: Optional[dict] = None, max_tokens: Optional[int] = None) -> Optional[str]:
        payload = {
            "model": self._local_model,
            "messages": messages,
            "temperature": temperature
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if response_format:
            payload["response_format"] = response_format

        endpoint = f"{self._local_url}/chat/completions"
        try:
            resp = get_httpx_client().post(
                endpoint,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return content.strip() if content else None
            else:
                logger.error(f"[LLM Client] Local AI Error {resp.status_code}: {resp.text}")
                return None
        except Exception as e:
            logger.error(f"[LLM Client] Local AI Request Failed: {e}")
            return None

    def chat(self, prompt: str, system: str = "Ты полезный ассистент. Отвечай кратко и на русском языке.", history: Optional[list[dict]] = None, model: Optional[str] = None, max_tokens: int = 4096, temperature: float = 0.7) -> str:
        self.reload_settings()
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        result = self._local_chat_completion(messages, temperature, max_tokens=max_tokens)
        if result:
            return result
        raise RuntimeError("Local AI request failed. Please check if Ollama is running.")

    def chat_json(self, prompt: str, system: str = "Return ONLY valid JSON.", model: Optional[str] = None, max_tokens: int = 4096) -> dict:
        self.reload_settings()
        messages = [
            {"role": "system", "content": system + " Output valid JSON only, without any markdown formatting."},
            {"role": "user", "content": prompt}
        ]
        raw = self._local_chat_completion(messages, temperature=0.2, response_format={"type": "json_object"}, max_tokens=max_tokens)
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

    def vision(self, prompt: str, image_b64: str, mime: str = "image/png", system: str = "Analyze the image.", model: Optional[str] = None, max_tokens: int = 1024) -> str:
        self.reload_settings()
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                    {"type": "text", "text": prompt}
                ]
            }
        ]
        result = self._local_chat_completion(messages, temperature=0.2, max_tokens=max_tokens)
        if result:
            return result
        raise RuntimeError("Local AI vision request failed.")

    def vision_from_file(self, prompt: str, image_path: str, system: str = "Analyze the image.", model: Optional[str] = None, max_tokens: int = 1024) -> str:
        self.reload_settings()
        path = Path(image_path)
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
        mime = mime_map.get(path.suffix.lower(), "image/png")
        with open(path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        return self.vision(prompt, image_b64, mime, system, model, max_tokens)

    def multi_turn(self, messages: list[dict], model: Optional[str] = None, max_tokens: int = 4096, temperature: float = 0.7) -> str:
        self.reload_settings()
        result = self._local_chat_completion(messages, temperature, max_tokens=max_tokens)
        if result:
            return result
        raise RuntimeError("Local AI request failed.")

    # --- Управление локальной моделью ---

    def _ollama_base(self) -> str:
        return self._local_url.rsplit("/v1", 1)[0]

    def _model_exists(self) -> bool:
        try:
            resp = get_httpx_client().get(f"{self._ollama_base()}/api/tags", timeout=5)
            if resp.status_code == 200:
                names = {m.get("name", "") for m in resp.json().get("models", [])}
                return any(n.split(":")[0] == self._local_model for n in names)
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

            resp = get_httpx_client().head(f"{base}/api/blobs/{digest}", timeout=10)
            if resp.status_code != 200:
                with open(LOCAL_GGUF, "rb") as f:
                    resp = get_httpx_client().post(
                        f"{base}/api/blobs/{digest}",
                        content=f.read(),
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
            with get_httpx_client().stream(
                "POST", f"{base}/api/create",
                json=payload, timeout=1200,
            ) as resp:
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