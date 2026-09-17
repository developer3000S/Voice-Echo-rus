"""Download the offline voice models used by Voice Echo's local voice engine.

Fetches:
  - Piper TTS voice      (ru_RU-irina-medium) from HuggingFace
  - sherpa-onnx STT model (streaming zipformer small ru / modern Vosk format)
    from HuggingFace

Run:  .venv/bin/python download_voice_models.py
"""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "config" / "models"
PIPER_DIR = MODELS_DIR / "piper"
STT_DIR = MODELS_DIR / "sherpa-ru"

PIPER_FILES = {
    "ru_RU-irina-medium.onnx": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
        "ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx"
    ),
    "ru_RU-irina-medium.onnx.json": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
        "ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json"
    ),
}

STT_REPO = "csukuangfj/sherpa-onnx-streaming-zipformer-small-ru-vosk-int8-2025-08-16"


def _download(url: str, dest: Path) -> None:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  exists, skip: {dest.name}")
        return
    print(f"  downloading {dest.name} ...")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
        tmp.replace(dest)
    print(f"  saved: {dest.name} ({dest.stat().st_size} bytes)")


def main() -> None:
    print(f"[VoiceEcho] Models -> {MODELS_DIR}")
    if not PIPER_DIR.exists() and PIPER_FILES:
        import sys

        print(f"[VoiceEcho] Downloading Piper Russian voice into {PIPER_DIR} ...")
        for name, url in PIPER_FILES.items():
            _download(url, PIPER_DIR / name)

    print(f"[VoiceEcho] Downloading sherpa-onnx Russian STT model into {STT_DIR} ...")
    try:
        from huggingface_hub import snapshot_download, errors

        snapshot_download(STT_REPO, local_dir=str(STT_DIR))
    except errors.HfHubHTTPError as exc:
        print(f"[VoiceEcho] huggingface_hub failed ({exc}); trying simple HTTP fallback...")
        import sys

        for name in ("encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt", "bpe.model"):
            _download(
                f"https://huggingface.co/{STT_REPO}/resolve/main/{name}",
                STT_DIR / name,
            )

    print("[VoiceEcho] Done. Starting Voice Echo will now use offline voice.")


if __name__ == "__main__":
    main()