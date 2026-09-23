"""Тесты запуска приложений и подбора текстового редактора.

Проверяют, что при запросе Блокнота, отсутствующего в системе,
Voice Echo не падает с ошибкой, а открывает доступный редактор
(предпочтительно Visual Studio Code).
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from actions import open_app as oa  # noqa: E402


class _FakePlayer:
    def __init__(self):
        self.logs = []

    def write_log(self, text):
        self.logs.append(text)


def test_editor_keys_include_notepad():
    assert "notepad" in oa._EDITOR_KEYS
    assert "блокнот" in oa._EDITOR_KEYS


def test_vscode_is_preferred_fallback(monkeypatch):
    """Среди доступных редакторов первым выбирается Visual Studio Code."""
    available = {"code", "gedit", "nano"}

    def fake_which(name):
        return f"/usr/bin/{name}" if name in available else None

    monkeypatch.setattr(oa.shutil, "which", fake_which)
    assert oa._resolve_editor_fallback("Linux") == "code"


def test_fallback_skips_missing_editors(monkeypatch):
    """Если VS Code не установлен, берём следующий доступный редактор."""
    available = {"gedit"}

    def fake_which(name):
        return f"/usr/bin/{name}" if name in available else None

    monkeypatch.setattr(oa.shutil, "which", fake_which)
    assert oa._resolve_editor_fallback("Linux") == "gedit"


def test_no_fallback_when_nothing_installed(monkeypatch):
    monkeypatch.setattr(oa.shutil, "which", lambda name: None)
    monkeypatch.setattr(oa.os.path, "exists", lambda path: False)
    assert oa._resolve_editor_fallback("Linux") is None


def test_notepad_missing_substitutes_vscode(monkeypatch):
    """Блокнот недоступен → открывается VS Code, без ошибки запуска."""
    monkeypatch.setattr(oa.platform, "system", lambda: "Linux")
    available = {"code"}

    def fake_which(name):
        return f"/usr/bin/{name}" if name in available else None

    monkeypatch.setattr(oa.shutil, "which", fake_which)

    launched = []

    def fake_launcher(name):
        launched.append(name)
        return True

    monkeypatch.setitem(oa._OS_LAUNCHERS, "Linux", fake_launcher)

    result = oa.open_app({"app_name": "notepad"}, player=_FakePlayer())

    assert launched == ["code"]
    assert "notepad is not installed" in result
    assert "code" in result


def test_notepad_present_is_used_as_is(monkeypatch):
    """Если Блокнот установлен, замены не происходит."""
    monkeypatch.setattr(oa.platform, "system", lambda: "Windows")
    available = {"notepad.exe"}

    def fake_which(name):
        return f"C:\\Windows\\System32\\{name}" if name in available else None

    monkeypatch.setattr(oa.shutil, "which", fake_which)

    launched = []

    def fake_launcher(name):
        launched.append(name)
        return True

    monkeypatch.setitem(oa._OS_LAUNCHERS, "Windows", fake_launcher)

    result = oa.open_app({"app_name": "notepad"})

    assert launched == ["notepad.exe"]
    assert result == "Opened notepad successfully, sir."


def test_non_editor_app_is_never_substituted(monkeypatch):
    """Заменять нужно только текстовые редакторы, а не любые приложения."""
    monkeypatch.setattr(oa.platform, "system", lambda: "Linux")
    monkeypatch.setattr(oa.shutil, "which", lambda name: None)

    launched = []

    def fake_launcher(name):
        launched.append(name)
        return True

    monkeypatch.setitem(oa._OS_LAUNCHERS, "Linux", fake_launcher)

    oa.open_app({"app_name": "spotify"})

    assert launched == ["spotify"]


def test_cyrillic_bloknot_triggers_fallback(monkeypatch):
    """Запрос «блокнот» тоже должен получать замену на VS Code."""
    monkeypatch.setattr(oa.platform, "system", lambda: "Linux")
    monkeypatch.setattr(oa.shutil, "which", lambda name: "/usr/bin/code" if name == "code" else None)

    launched = []

    def fake_launcher(name):
        launched.append(name)
        return True

    monkeypatch.setitem(oa._OS_LAUNCHERS, "Linux", fake_launcher)

    result = oa.open_app({"app_name": "блокнот"})

    assert launched == ["code"]
    assert "блокнот is not installed" in result


def test_open_text_file_prefers_available_editor(monkeypatch, tmp_path):
    """open_text_file проверяет редактор и использует фолбэк при необходимости."""
    monkeypatch.setattr(oa.platform, "system", lambda: "Linux")
    monkeypatch.setattr(oa.shutil, "which", lambda name: "/usr/bin/code" if name == "code" else None)

    popped = []
    monkeypatch.setattr(oa.subprocess, "Popen", lambda args, **kw: popped.append(args))

    target = tmp_path / "result.txt"
    ok = oa.open_text_file(target)

    assert ok is True
    assert popped[0][0] == "/usr/bin/code"
    assert str(target) in popped[0][1]
