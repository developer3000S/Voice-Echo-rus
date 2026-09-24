"""Регрессионный тест переключения типа визуализации голосового сообщения.

Воспроизводит реальный production-путь: страница настроек открывается
(triggers refresh()), после чего пользователь меняет тип анимации в выпадающем
списке. Раньше refresh() оставлял у _voice_viz_combo заблокированные сигналы,
и смена типа не применялась к виджету VoiceVisualizer.
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

import ui as ui_module  # noqa: E402
from ui import VoiceVisualizer  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.mark.parametrize("variant", VoiceVisualizer.VARIANTS)
def test_switch_after_refresh_applies_variant(qapp, tmp_path, monkeypatch, variant):
    monkeypatch.setattr(ui_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ui_module, "APP_SETTINGS_FILE", tmp_path / "app_settings.json")

    ui = ui_module.VoiceUI("/tmp/nonexistent_face.png")
    win = ui._win
    win.show()
    qapp.processEvents()

    page = win._settings_page
    combo = page._voice_viz_combo

    # Открытие страницы настроек вызывает refresh() — после него сигналы
    # комбо должны быть разблокированы.
    page.refresh()
    qapp.processEvents()
    assert not combo.signalsBlocked(), "refresh() left _voice_viz_combo signals blocked"

    idx = combo.findData(variant)
    assert idx >= 0
    combo.setCurrentIndex(idx)
    qapp.processEvents()

    assert win._voice_viz._variant == variant
    assert combo.currentData() == variant
