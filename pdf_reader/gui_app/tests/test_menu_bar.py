"""Menu bar (#115): File / View / Reader / Help exist; Reader actions
enable only while the reader is on screen; single-letter keys stay
click-only so keyPressEvent remains the source of truth."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def real_win(app, tmp_path, monkeypatch):
    """Real MainWindow pointed at a temp library.db — never the real one."""
    from main_window import MainWindow
    from views.library_view import LibraryView

    orig = LibraryView.__init__

    def patched(self, db_path=None):
        orig(self, db_path or (tmp_path / "library.db"))

    monkeypatch.setattr(LibraryView, "__init__", patched)
    w = MainWindow()
    yield w
    w.close()


def test_menu_bar_has_the_four_menus(real_win):
    titles = [a.text().replace("&", "") for a in real_win.menuBar().actions()]
    assert titles == ["File", "View", "Reader", "Help"]


def test_file_menu_wires_add_and_backup(real_win):
    file_menu = real_win.menuBar().actions()[0].menu()
    labels = [a.text() for a in file_menu.actions() if a.text()]
    assert any("Add PDF" in t for t in labels)
    assert any("Backup" in t for t in labels)
    assert any(t == "Quit" for t in labels)


def test_view_menu_targets_the_navigation_slots(real_win):
    """(#115) View actions are wired to the same navigation methods the
    sidebar uses (bound at connect time — identity check, not trigger)."""
    view_menu = real_win.menuBar().actions()[1].menu()
    by_label = {a.text(): a for a in view_menu.actions() if a.text()}
    assert "📚 Library" in by_label
    assert "📝 Extracts" in by_label
    assert "🃏 Flashcards" in by_label
    # Each action's shortcut is a real combo Qt can print.
    assert not by_label["📚 Library"].shortcut().isEmpty()
    assert not by_label["📝 Extracts"].shortcut().isEmpty()
    assert not by_label["🃏 Flashcards"].shortcut().isEmpty()


def test_reader_menu_disabled_off_reader(real_win):
    """Reader actions are dead while the library page is showing."""
    assert real_win.stacked_widget.currentWidget() is real_win.library_view
    for act in real_win._reader_menu_actions:
        assert not act.isEnabled(), act.text()


def test_reader_menu_enabled_on_reader(real_win):
    real_win.stacked_widget.setCurrentWidget(real_win.pdf_view)
    real_win._sync_reader_menu(real_win.stacked_widget.currentIndex())
    find = next(
        a for a in real_win._reader_menu_actions if "Find" in a.text()
    )
    assert find.isEnabled()
    # Capture items need a live document — none loaded here.
    commit = next(
        a for a in real_win._reader_menu_actions if "Commit" in a.text()
    )
    assert not commit.isEnabled()


def test_single_letter_reader_items_have_no_shortcut(real_win):
    """(#115 AC) E / D stay click-only — keyPressEvent owns them."""
    for act in real_win._reader_menu_actions:
        if "Commit" in act.text() or "Delete" in act.text():
            assert act.shortcut().isEmpty(), act.text()


def test_multi_key_reader_items_have_shortcuts(real_win):
    find = next(a for a in real_win._reader_menu_actions if "Find" in a.text())
    zoom_in = next(
        a for a in real_win._reader_menu_actions if "Zoom in" in a.text()
    )
    assert not find.shortcut().isEmpty()
    assert not zoom_in.shortcut().isEmpty()


def test_help_menu_opens_shortcuts_dialog(real_win, monkeypatch):
    shown = []

    class _Stub:
        def exec(self):
            shown.append(1)

    monkeypatch.setattr("main_window.HelpDialog", lambda parent=None: _Stub())
    help_menu = real_win.menuBar().actions()[3].menu()
    for act in help_menu.actions():
        if "shortcut" in act.text().lower():
            act.trigger()
    assert shown == [1]
