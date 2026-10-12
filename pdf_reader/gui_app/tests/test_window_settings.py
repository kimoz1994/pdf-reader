"""Window geometry + app icon (#117)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication, QFrame, QMainWindow

from services.window_settings import (
    make_app_icon,
    restore_window_state,
    save_window_state,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    s = QSettings(str(tmp_path / "geom.ini"), QSettings.Format.IniFormat)
    yield s
    s.sync()


@pytest.fixture
def window(app):
    w = QMainWindow()
    w.resize(1400, 900)
    yield w
    w.close()


@pytest.fixture
def sidebar(app):
    f = QFrame()
    f.setFixedWidth(250)
    return f


def test_no_settings_keeps_defaults(window, sidebar, settings):
    """(#117) First launch: restore is a no-op, defaults stay."""
    assert restore_window_state(settings, window, sidebar) is False
    assert sidebar.width() == 250


def test_geometry_and_sidebar_roundtrip(window, sidebar, settings, app):
    """(#117 AC) Saved size + sidebar width come back on restore.

    Sizes stay inside the offscreen test screen (800x800) — Qt clamps
    restoreGeometry to the screen, which would mask a real roundtrip.
    """
    window.resize(700, 600)
    sidebar.setFixedWidth(320)
    save_window_state(settings, window, sidebar)

    # Fresh widgets, as on next launch (no oversized minimum here).
    w2 = QMainWindow()
    s2 = QFrame()
    s2.setFixedWidth(250)

    assert restore_window_state(settings, w2, s2) is True
    assert s2.width() == 320
    geom = w2.geometry()
    assert abs(geom.width() - 700) <= 2
    assert abs(geom.height() - 600) <= 2
    w2.close()


def test_restore_false_only_when_both_missing(window, sidebar, tmp_path):
    """(#117) A settings file with unrelated keys still reports False."""
    s = QSettings(str(tmp_path / "other.ini"), QSettings.Format.IniFormat)
    s.setValue("unrelated/key", 1)
    assert restore_window_state(s, window, sidebar) is False


def test_app_icon_is_drawn(window):
    """(#117 AC) An icon exists and has non-zero content."""
    icon = make_app_icon()
    assert not icon.isNull()
    pm = icon.pixmap(64, 64)
    assert not pm.isNull()
    assert pm.width() == 64
