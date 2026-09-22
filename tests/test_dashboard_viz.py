"""Тесты визуализации системных метрик для вкладки «Панель».

Проверяют, что выбор варианта визуализации через настройки
(dashboard_viz) действительно применяется к виджету MetricScope,
и что отрисовка не падает на любом из вариантов.
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui import MetricScope  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _fill(scope: MetricScope, points: int = 70) -> None:
    for i in range(points):
        scope.push({
            "cpu": 25 + 40 * abs((i % 30) - 15) / 15,
            "mem": 50 + 25 * (i % 13) / 13,
            "net": 15 + 20 * (i % 7) / 7,
        })


def test_supported_variants(qapp):
    assert MetricScope.VARIANTS == ("line", "bars", "radar")


@pytest.mark.parametrize("variant", ["line", "bars", "radar"])
def test_variant_applied_and_paints(qapp, variant):
    scope = MetricScope(variant=variant)
    scope.resize(560, 190)
    _fill(scope)

    assert scope._variant == variant
    pixmap = scope.grab()

    assert pixmap.width() == 560
    assert pixmap.height() == 190
    assert not pixmap.isNull()


def test_unknown_variant_falls_back_to_line(qapp):
    scope = MetricScope(variant="does-not-exist")
    assert scope._variant == "line"

    scope.set_variant("also-unknown")
    assert scope._variant == "line"


def test_variant_switches_on_the_fly(qapp):
    scope = MetricScope(variant="line")
    _fill(scope)

    for variant in MetricScope.VARIANTS:
        scope.set_variant(variant)
        assert scope._variant == variant
        scope.grab()


def test_push_clamps_and_ignores_bad_values(qapp):
    scope = MetricScope(variant="radar")
    scope.push(None)
    scope.push({"cpu": "not a number", "mem": None})
    scope.push({"cpu": -50})
    assert scope._latest["cpu"] == 0.0

    scope.push({"cpu": 150})
    assert scope._latest["cpu"] == 100.0

    scope.push({"net": 50})
    assert scope._latest["net"] == 100.0
    assert len(scope._history["net"]) <= scope._max_points


def test_history_is_bounded(qapp):
    scope = MetricScope(variant="line")
    scope._max_points = 8
    for i in range(30):
        scope.push({"cpu": float(i)})
    assert len(scope._history["cpu"]) == 8


def test_refresh_syncs_widget_to_persisted_setting(qapp, tmp_path, monkeypatch):
    """refresh() страницы настроек применяет сохранённый вариант к виджету.

    Виджет перестраивается сигналом currentIndexChanged, который
    блокируется на время refresh(), поэтому синхронизацию нужно
    выполнять явно — иначе график останется в старом режиме.
    """
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

    settings_page._set_setting("dashboard_viz", "radar")
    win._app_settings_cache = None
    settings_page.refresh()
    qapp.processEvents()

    assert settings_page._viz_combo.currentData() == "radar"
    assert win._metric_scope._variant == "radar"
