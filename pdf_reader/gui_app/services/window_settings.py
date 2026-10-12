"""Window geometry persistence (#117): save/restore the main window's
geometry and the sidebar width through QSettings.

Pure QWidget/QSettings interactions, no app-specific state — tests
drive it with an Ini-format QSettings in a temp dir so the real user
config is never touched.
"""
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtCore import Qt


def save_window_state(settings: QSettings, window, sidebar) -> None:
    """Persist the window's geometry and the sidebar's current width."""
    settings.setValue("window/geometry", window.saveGeometry())
    settings.setValue("window/sidebar_width", sidebar.width())
    settings.sync()


def restore_window_state(settings: QSettings, window, sidebar) -> bool:
    """Apply saved geometry + sidebar width; False when nothing is
    stored yet (first launch — caller keeps its defaults)."""
    geom = settings.value("window/geometry")
    width = settings.value("window/sidebar_width")
    if geom is None and width is None:
        return False
    if geom is not None:
        window.restoreGeometry(geom)
    if width is not None:
        try:
            sidebar.setFixedWidth(int(width))
        except (TypeError, ValueError):
            pass
    return True


def make_app_icon(size: int = 64) -> QIcon:
    """A simple app icon drawn at runtime (#117): rounded blue tile
    with bold 'PDF' — no bundled asset needed, works offscreen."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#3498db"))
    margin = max(2, size // 16)
    p.drawRoundedRect(
        margin, margin, size - 2 * margin, size - 2 * margin,
        size // 6, size // 6,
    )
    p.setPen(QColor("white"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(10, size // 3))
    p.setFont(font)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "PDF")
    p.end()
    return QIcon(pm)
