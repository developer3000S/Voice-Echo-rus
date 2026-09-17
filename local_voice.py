"""Fully offline speech engine for Voice Echo.

Text-to-speech : Piper (``ru_RU-irina-medium``)
Speech-to-text : sherpa-onnx streaming Zipformer, the engine behind the modern
                 Vosk streaming models (``sherpa-onnx-streaming-zipformer-small-ru-vosk``).

Everything runs on-device; no Google (or any cloud) endpoint is contacted for
voice synthesis or recognition. Models live under ``config/models/``:

    config/models/piper/ru_RU-irina-medium.onnx
    config/models/piper/ru_RU-irina-medium.onnx.json
    config/models/sherpa-ru/{encoder,decoder,joiner}.onnx
    config/models/sherpa-ru/{tokens.txt,bpe.model}

Both engines degrade gracefully: if a package or model file is missing the
feature simply reports :data:`available` as ``False`` and the app falls back to
its previous online behaviour.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "config" / "models"

PIPER_DIR = MODELS_DIR / "piper"
PIPER_MODEL = PIPER_DIR / "ru_RU-irina-medium.onnx"
PIPER_CONFIG = PIPER_DIR / "ru_RU-irina-medium.onnx.json"

STT_DIR = MODELS_DIR / "sherpa-ru"
STT_TOKENS = STT_DIR / "tokens.txt"
STT_BPE = STT_DIR / "bpe.model"
STT_ENCODER = STT_DIR / "encoder.int8.onnx"
STT_DECODER = STT_DIR / "decoder.onnx"
STT_JOINER = STT_DIR / "joiner.int8.onnx"

STT_SAMPLE_RATE = 16000
TTS_SAMPLE_RATE = 22050

# VAD thresholds (RMS of float32 audio in [-1, 1]).
VAD_ONSET_RMS = 0.011       # frame is speech when RMS exceeds this
VAD_TAIL_RMS = 0.008        # frame is silence when RMS drops below this
VAD_END_SILENCE_SEC = 0.75   # trailing silence that ends a phrase
VAD_MAX_PHRASE_SEC = 12.0    # hard cap for a single phrase
STT_CHUNK_SEC = 0.08         # audio fed to the recognizer per decode step


def voice_setting_enabled() -> bool:
    """Read the ``local_voice_engine`` toggle from ``app_settings.json``."""
    try:
        with open(BASE_DIR / "config" / "app_settings.json", "r", encoding="utf-8") as f:
            return bool(json.load(f).get("local_voice_engine", True))
    except Exception:
        return True


class LocalTTS:
    """Offline neural text-to-speech powered by Piper."""

    def __init__(self) -> None:
        self._voice = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return PIPER_MODEL.exists() and PIPER_CONFIG.exists()

    @property
    def ready(self) -> bool:
        """True when the voice was loaded and is usable."""
        return self._voice is not None

    def _load(self) -> bool:
        if self._voice is not None:
            return True
        if not self.available:
            return False
        try:
            from piper import PiperVoice
        except Exception:
            return False
        try:
            self._voice = PiperVoice.load(str(PIPER_MODEL), config_path=str(PIPER_CONFIG))
            return True
        except Exception as exc:
            print(f"[LocalVoice] Piper load failed: {exc}")
            self._voice = None
            return False

    def synthesize(self, text: str) -> np.ndarray | None:
        """Convert ``text`` to int16 mono samples at 22050 Hz (or None)."""
        text = (text or "").strip()
        if not text:
            return None
        if not self._load():
            return None
        try:
            chunks: list[np.ndarray] = []
            for chunk in self._voice.synthesize(text):
                chunks.append(np.asarray(chunk.audio_int16_array))
            if not chunks:
                return None
            return np.concatenate(chunks)
        except Exception as exc:
            print(f"[LocalVoice] Piper synth failed: {exc}")
            return None

    def speak(self, text: str, stop_event: threading.Event | None = None) -> bool:
        """Synthesize and play ``text`` (blocking). Returns True when played."""
        text = (text or "").strip()
        if not text:
            return False
        audio = self.synthesize(text)
        if audio is None or audio.size == 0:
            return False
        try:
            import sounddevice as sd
        except Exception:
            return False
        try:
            with self._lock:
                sd.stop()  # interrupt any previous speech
                data = audio.astype(np.float32, copy=False) / 32768.0
                stream = sd.OutputStream(samplerate=TTS_SAMPLE_RATE, channels=1, dtype="float32")
                stream.start()
                written = 0
                step = 8000
                while written < data.size:
                    if stop_event is not None and stop_event.is_set():
                        break
                    if not stream.active:
                        break
                    stream.write(data[written: written + step])
                    written += step
                stream.stop()
                stream.close()
            return True
        except Exception as exc:
            print(f"[LocalVoice] Piper playback failed: {exc}")
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass
            return False


class LocalSTT:
    """Offline streaming speech-to-text via sherpa-onnx streaming Zipformer

    (the engine underneath the modern ``vosk-model-streaming-*`` family).
    """

    def __init__(self) -> None:
        self._recognizer = None
        self._stream = None

    @property
    def available(self) -> bool:
        return all(
            p.exists()
            for p in (STT_TOKENS, STT_BPE, STT_ENCODER, STT_DECODER, STT_JOINER)
        )

    def _load(self) -> bool:
        if self._recognizer is not None:
            return True
        if not self.available:
            return False
        try:
            import sherpa_onnx
        except Exception:
            return False
        try:
            self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(STT_TOKENS),
                bpe_vocab=str(STT_BPE),
                modeling_unit="bpe",
                encoder=str(STT_ENCODER),
                decoder=str(STT_DECODER),
                joiner=str(STT_JOINER),
                num_threads=2,
                sample_rate=STT_SAMPLE_RATE,
                feature_dim=80,
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=1.2,
                rule2_min_trailing_silence=0.6,
                rule3_min_utterance_length=20.0,
            )
            self._stream = self._recognizer.create_stream()
            return True
        except Exception as exc:
            print(f"[LocalVoice] STT load failed: {exc}")
            self._recognizer = None
            return False

    def _reset_utterance(self) -> None:
        if self._recognizer is not None:
            self._stream = self._recognizer.create_stream()

    def _decode(self) -> None:
        rec = self._recognizer
        if rec is None:
            return
        for _ in range(2):
            if not rec.is_ready(self._stream):
                break
            rec.decode_stream(self._stream)

    def current_text(self) -> str:
        if self._recognizer is None:
            return ""
        return self._recognizer.get_result(self._stream)

    def feed(self, samples_f32: np.ndarray) -> None:
        """Feed one mono float32 chunk ([-1, 1]) at 16 kHz into the recognizer."""
        if self._recognizer is None:
            return
        self._stream.accept_waveform(STT_SAMPLE_RATE, samples_f32.astype(np.float32))
        self._decode()

    def recognizer_ready(self) -> bool:
        return self._recognizer is not None and self._stream is not None

    @property
    def endpoint_reached(self) -> bool:
        try:
            return bool(self._recognizer is not None and self._stream.is_endpoint())
        except Exception:
            return False

    def finalize(self) -> str:
        """Finish the current utterance and return the recognizable text."""
        if self._recognizer is None:
            return ""
        try:
            self._stream.input_finished()
            for _ in range(10):
                if not self._recognizer.is_ready(self._stream):
                    break
                self._recognizer.decode_stream(self._stream)
            text = (self._recognizer.get_result(self._stream) or "").strip()
        finally:
            self._recognizer.reset(self._stream)
        return text


class LocalVoiceEngine:
    """Coordinator: microphone -> local STT -> on_command callback.

    Commands are dispatched through ``submit`` (provided by the caller, e.g.
    ``ui.submit_external_command``) so the whole pipeline stays thread-safe.
    While muted only wake-words are acted on (the caller decides via
    callbacks).
    """

    def __init__(
        self,
        *,
        submit: Callable[[str], None],
        muted: Callable[[], bool],
        wakeword: Callable[[str], bool],
        on_wakeword: Callable[[], None],
        speaking: Callable[[], bool],
    ) -> None:
        self._submit = submit
        self._muted = muted
        self._wakeword = wakeword
        self._on_wakeword = on_wakeword
        self._speaking = speaking
        self._stt = LocalSTT()
        self._running = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def stt_available(self) -> bool:
        return self._stt.available

    def _loop(self) -> None:
        # Load the recognizer up-front so the first phrase is fast.
        if not self._stt._load():
            print("[LocalVoice] STT unavailable; local voice engine disabled.")
            return
        try:
            import sounddevice as sd
        except Exception:
            print("[LocalVoice] sounddevice missing; local voice engine disabled.")
            return

        print("[LocalVoice] 🎤 Local STT listening (sherpa-onnx / vosk ru)")
        self._stt._reset_utterance()
        in_speech = False
        phrase_start = 0.0
        silence_start = 0.0
        try:
            with sd.InputStream(
                samplerate=STT_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=int(STT_SAMPLE_RATE * STT_CHUNK_SEC),
            ) as stream:
                while not self._stop.is_set():
                    try:
                        indata, _overflowed = stream.read(int(STT_SAMPLE_RATE * STT_CHUNK_SEC))
                    except Exception:
                        if self._stop.is_set():
                            break
                        continue
                    if indata.size == 0:
                        continue
                    chunk = np.asarray(indata, dtype=np.int16).reshape(-1)
                    rms = float(np.sqrt(np.mean((chunk.astype(np.float32) / 32768.0) ** 2)))
                    now = time.monotonic()

                    if self._stt.recognizer_ready():
                        self._stt.feed(chunk.astype(np.float32) / 32768.0)

                    if not in_speech:
                        if rms >= VAD_ONSET_RMS:
                            in_speech = True
                            phrase_start = now
                            silence_start = now
                        continue

                    if rms < VAD_TAIL_RMS:
                        if now - silence_start >= VAD_END_SILENCE_SEC:
                            self._emit_phrase()
                            self._stt._reset_utterance()
                            in_speech = False
                            continue
                    else:
                        silence_start = now

                    if now - phrase_start >= VAD_MAX_PHRASE_SEC:
                        self._emit_phrase()
                        self._stt._reset_utterance()
                        in_speech = False
                        continue

                    if self._stt.endpoint_reached:
                        self._emit_phrase()
                        self._stt._reset_utterance()
                        in_speech = False
        finally:
            self._running = False
            print("[LocalVoice] Local STT stopped.")

    def _emit_phrase(self) -> None:
        text = self._stt.finalize()
        if not text:
            return
        # Skip anything picked up while local TTS is still talking (echo guard).
        if self._speaking():
            return
        try:
            if self._muted():
                if self._wakeword(text):
                    try:
                        self._on_wakeword()
                    except Exception:
                        pass
                return
        except Exception:
            pass
        try:
            self._submit(text)
        except Exception as exc:
            print(f"[LocalVoice] submit failed: {exc}")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="local-stt")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)