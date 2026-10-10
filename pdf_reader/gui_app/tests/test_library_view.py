"""Library removal UX (#72): per-row checkboxes drive a count-enabled
Remove button, with select-all and the Del key; rows whose file is gone
stay listed so they can be removed too. Offscreen widget tests over a
temp database."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from views.library_view import LibraryView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(tmp_path, app):
    v = LibraryView(db_path=tmp_path / "library.db")
    yield v
    v.hide()  # tests that showed it must not reach LibraryView.closeEvent
    v.conn.close()


def seed(view, path, name=None, total_pages=3, current_page=1):
    view.cursor.execute(
        "INSERT INTO pdfs (path, name, total_pages, current_page) VALUES (?, ?, ?, ?)",
        (str(path), name or Path(path).name, total_pages, current_page),
    )
    view.conn.commit()


def rows(view):
    return [
        view.pdf_list.itemWidget(view.pdf_list.item(i))
        for i in range(view.pdf_list.count())
    ]


def test_rows_list_with_checkboxes_and_remove_disabled(view, tmp_path):
    seed(view, tmp_path / "a.pdf")
    seed(view, tmp_path / "b.pdf")
    view.load_library()

    assert view.pdf_list.count() == 2
    assert all(hasattr(row, "checkbox") for row in rows(view))
    assert not view.remove_btn.isEnabled()


def test_missing_file_row_still_listed_marked_and_removable(view, tmp_path, monkeypatch):
    """#72: a file that moved/deleted must not vanish from the view —
    it is exactly the row you want to remove."""
    seed(view, tmp_path / "gone.pdf", name="gone.pdf")
    view.load_library()

    (row,) = rows(view)
    assert "file missing" in row.name_label.text()
    row.checkbox.setChecked(True)
    assert view.remove_btn.isEnabled()

    monkeypatch.setattr(view, "_confirm_removal", lambda names: True)
    view.remove_selected_pdfs()
    assert view.pdf_list.count() == 0
    assert view.cursor.execute("SELECT COUNT(*) FROM pdfs").fetchone()[0] == 0


def test_tick_shows_count_and_updates_stats(view, tmp_path):
    seed(view, tmp_path / "a.pdf")
    seed(view, tmp_path / "b.pdf")
    view.load_library()

    rows(view)[0].checkbox.setChecked(True)
    assert view.remove_btn.isEnabled()
    assert "1" in view.remove_btn.text()
    assert "1 selected" in view.stats_label.text()

    rows(view)[0].checkbox.setChecked(False)
    assert not view.remove_btn.isEnabled()
    assert "selected" not in view.stats_label.text()


def test_row_click_highlights_but_does_not_tick(view, tmp_path):
    """Only the checkbox ticks — a stray click never arms a removal
    (double-click to open stays safe); the click still highlights."""
    seed(view, tmp_path / "a.pdf")
    view.load_library()
    row = rows(view)[0]
    row.resize(600, 80)

    QTest.mouseClick(row, Qt.MouseButton.LeftButton, pos=QPoint(row.width() - 8, 40))
    assert view.pdf_list.item(0).isSelected()
    assert not row.checkbox.isChecked()
    assert not view.remove_btn.isEnabled()


def test_select_all_toggles_every_row(view, tmp_path):
    seed(view, tmp_path / "a.pdf")
    seed(view, tmp_path / "b.pdf")
    view.load_library()

    view.select_all_btn.click()
    assert all(r.checkbox.isChecked() for r in rows(view))
    assert "2" in view.remove_btn.text()

    view.select_all_btn.click()
    assert not any(r.checkbox.isChecked() for r in rows(view))
    assert not view.remove_btn.isEnabled()


def test_remove_deletes_only_checked_rows(view, tmp_path, monkeypatch):
    kept, doomed = tmp_path / "keep.pdf", tmp_path / "bye.pdf"
    seed(view, kept)
    seed(view, doomed)
    view.load_library()

    confirmed = {}
    rows(view)[1].checkbox.setChecked(True)

    def fake_confirm(names):
        confirmed["names"] = names
        return True

    monkeypatch.setattr(view, "_confirm_removal", fake_confirm)
    view.remove_selected_pdfs()

    assert confirmed["names"] == ["bye.pdf"]
    paths = {r[0] for r in view.cursor.execute("SELECT path FROM pdfs")}
    assert paths == {str(kept)}


def test_remove_cancelled_keeps_every_row(view, tmp_path, monkeypatch):
    seed(view, tmp_path / "a.pdf")
    seed(view, tmp_path / "b.pdf")
    view.load_library()
    rows(view)[0].checkbox.setChecked(True)

    monkeypatch.setattr(view, "_confirm_removal", lambda names: False)
    view.remove_selected_pdfs()

    assert view.pdf_list.count() == 2
    assert view.cursor.execute("SELECT COUNT(*) FROM pdfs").fetchone()[0] == 2


def test_del_key_removes_checked_rows(view, tmp_path, monkeypatch, app):
    seed(view, tmp_path / "a.pdf")
    seed(view, tmp_path / "b.pdf")
    view.load_library()
    rows(view)[0].checkbox.setChecked(True)
    monkeypatch.setattr(view, "_confirm_removal", lambda names: True)

    # The shortcut has list scope, so the list must be the focused
    # widget — show + process events the way a real session would.
    view.show()
    app.processEvents()
    view.pdf_list.setFocus()
    app.processEvents()
    QTest.keyClick(view.pdf_list, Qt.Key.Key_Delete)

    assert view.pdf_list.count() == 1
    assert view.cursor.execute("SELECT COUNT(*) FROM pdfs").fetchone()[0] == 1
