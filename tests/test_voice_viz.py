"""Тесты визуализации голосового сообщения для вкладки «Панель».

Проверяют, что:
  * выбор варианта визуализации через настройки (voice_viz) применяется
    к виджету VoiceVisualizer;
  * отрисовка не падает на любом из вариантов (wave/bars/orb);
  * виджет оживает на состоянии SPEAKING и затихает на остальных;
  * индикатор-эквалайзер появляется в бабблах ассистента и активируется
    на последнее сообщение;
  * карточки «Панели» больше не усекают текст сообщений.
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui import ChatBubble, VoiceVisualizer, VoiceWaveIndicator  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# -- виджет-визуализатор ------------------------------------------------


def test_supported_variants(qapp):
    assert VoiceVisualizer.VARIANTS == ("wave", "bars", "orb")


@pytest.mark.parametrize("variant", ["wave", "bars", "orb"])
def test_variant_applied_and_paints(qapp, variant):
    viz = VoiceVisualizer(variant=variant)
    viz.resize(560, 110)
    viz.set_speaking(True)

    assert viz._variant == variant
    assert viz._speaking is True

    pixmap = viz.grab()
    assert pixmap.width() == 560
    assert pixmap.height() == 110
    assert not pixmap.isNull()


def test_unknown_variant_falls_back_to_wave(qapp):
    viz = VoiceVisualizer(variant="does-not-exist")
    assert viz._variant == "wave"

    viz.set_variant("also-unknown")
    assert viz._variant == "wave"


def test_variant_switches_on_the_fly(qapp):
    viz = VoiceVisualizer(variant="wave")
    viz.resize(560, 110)
    viz.set_speaking(True)

    for variant in VoiceVisualizer.VARIANTS:
        viz.set_variant(variant)
        assert viz._variant == variant
        viz.grab()


def test_speaking_starts_and_stops_timer(qapp):
    viz = VoiceVisualizer(variant="wave")

    assert viz._speaking is False
    assert not viz._timer.isActive()

    viz.set_speaking(True)
    assert viz._speaking is True
    assert viz._timer.isActive()

    viz.set_speaking(False)
    assert viz._speaking is False
    assert not viz._timer.isActive()
    assert viz._phase == 0.0


def test_speaking_paints_idle_and_active(qapp):
    viz = VoiceVisualizer(variant="orb")
    viz.resize(320, 110)
    viz.grab()  # тихое состояние не должно падать

    viz.set_speaking(True)
    qapp.processEvents()
    viz.grab()  # активное состояние тоже


# -- индикатор внутри бабблов -------------------------------------------


def test_assistant_bubble_has_voice_indicator(qapp):
    bubble = ChatBubble("assistant", "Voice Echo", "Привет, чем могу помочь?", "12:00")
    assert isinstance(bubble._voice_indicator, VoiceWaveIndicator)
    assert bubble._voice_indicator.isVisible() is False


def test_user_bubble_has_no_voice_indicator(qapp):
    bubble = ChatBubble("user", "You", "Привет", "12:00")
    assert bubble._voice_indicator is None


def test_voice_indicator_activates(qapp):
    bubble = ChatBubble("assistant", "Voice Echo", "Ответ", "12:00")
    indicator = bubble._voice_indicator

    bubble.set_voice_active(True)
    assert indicator._active is True
    assert indicator._timer.isActive()

    bubble.set_voice_active(False)
    assert indicator._active is False
    assert not indicator._timer.isActive()


# -- лента чата: активен последний ответ ассистента ---------------------


def test_feed_activates_last_assistant_bubble(qapp):
    from ui import ConversationFeed

    feed = ConversationFeed()
    feed.resize(320, 480)
    feed.add_message("assistant", "Voice Echo", "Первый ответ", "12:00")
    feed.add_message("user", "You", "А второй?", "12:01")
    feed.add_message("assistant", "Voice Echo", "Второй ответ", "12:02")
    qapp.processEvents()

    bubbles = [
        feed._layout.itemAt(i).widget()
        for i in range(feed._layout.count())
        if feed._layout.itemAt(i) is not None
        and feed._layout.itemAt(i).widget() is not None
        and feed._layout.itemAt(i).widget().__class__.__name__ == "ChatBubble"
    ]
    assistants = [b for b in bubbles if b._role == "assistant"]
    assert len(assistants) >= 2

    feed.set_voice_active(True)
    qapp.processEvents()
    assert assistants[-1]._voice_indicator._active is True
    assert assistants[0]._voice_indicator._active is False

    feed.set_voice_active(False)
    qapp.processEvents()
    assert assistants[-1]._voice_indicator._active is False


# -- настройки: синхронизация виджета со страницей ----------------------


def test_refresh_syncs_widget_to_persisted_setting(qapp, tmp_path, monkeypatch):
    """refresh() страницы настроек применяет сохранённый вариант к виджету."""
    ui_module = pytest.importorskip("ui", reason="требует полного импорта UI")

    class FakeController:
        def __init__(self, win):
            self._win = win

        def write_log(self, text):
            pass

    monkeypatch.setattr(ui_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ui_module, "APP_SETTINGS_FILE", tmp_path / "app_settings.json")

    ui = ui_module.VoiceUI("/tmp/nonexistent_face.png")
    win = ui._win
    win.show()
    qapp.processEvents()

    settings_page = win._settings_page
    settings_page.set_controller(FakeController(win))

    settings_page._set_setting("voice_viz", "orb")
    win._app_settings_cache = None
    settings_page.refresh()
    qapp.processEvents()

    assert settings_page._voice_viz_combo.currentData() == "orb"
    assert win._voice_viz._variant == "orb"


def test_voice_viz_default_in_settings(qapp):
    """В настройках по умолчанию присутствует voice_viz."""
    ui_module = pytest.importorskip("ui", reason="требует полного импорта UI")
    defaults = ui_module._default_app_settings()
    assert defaults["voice_viz"] in VoiceVisualizer.VARIANTS


# -- карточки панели больше не усекают текст ---------------------------


def test_panel_widgets_hold_full_text(qapp):
    """SmallPanelCard и ChatBubble показывают текст целиком."""
    from ui import SmallPanelCard

    long_text = ("Очень длинное сообщение, которое раньше усекалось "
                 "на шестидесяти или восьмидесяти символах и обрезалось "
                 "многоточием в конце карточки панели.")

    card = SmallPanelCard("РЕЗУЛЬТАТ ДЕЙСТВИЯ", long_text)
    assert card._body_lbl.text() == long_text

    bubble = ChatBubble("assistant", "Voice Echo", long_text, "12:00")
    assert bubble._full_text == long_text
    assert Qt.TextFormat.RichText == bubble._browser.textFormat()
    # Внутри HTML текст сохранён целиком (без многоточия-усечения).
    assert "многоточием в конце карточки панели." in bubble._browser.text()
