"""Тесты wake word «Привет, Бро».

Локальный STT (sherpa-onnx ru) доносит «бро» как «бру»/«бра», а старый
предикат был написан под английское «voice echo» и вырезал всю кириллицу
регуляркой [^a-z0-9\\s]+ — wake word вообще никогда не срабатывал.
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import _wakeword_detected  # noqa: E402


def test_wakeword_detects_russian_transcriptions():
    assert _wakeword_detected("привет бро")
    assert _wakeword_detected("привет бру")
    assert _wakeword_detected("привет бра")
    assert _wakeword_detected("привет брат")
    assert _wakeword_detected("хей бро")
    assert _wakeword_detected("хейбру")
    assert _wakeword_detected("эй бро")
    assert _wakeword_detected("эйбру")
    assert _wakeword_detected("бро")
    assert _wakeword_detected("бру")


def test_wakeword_is_case_insensitive_and_punctuated():
    assert _wakeword_detected("ПРИВЕТ БРО")
    assert _wakeword_detected("Привет, Бро!")
    assert _wakeword_detected("Привет, Бро, открой блокнот")


def test_wakeword_ignores_plain_greetings_and_commands():
    assert not _wakeword_detected("привет")
    assert not _wakeword_detected("как дела")
    assert not _wakeword_detected("открой блокнот")
    assert not _wakeword_detected("voice echo")
    assert not _wakeword_detected("")
