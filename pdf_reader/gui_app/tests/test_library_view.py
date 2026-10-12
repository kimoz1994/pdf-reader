"""Library removal UX (#72): per-row checkboxes drive a count-enabled
Remove button, with select-all and the Del key; rows whose file is gone
stay listed so they can be removed too. Plus the 💾 Backup button (#83):
one click snapshots library.db into backups/. Plus Back-visit skip (#89):
progress refreshes a row in place and a clean list never rebuilds.
Offscreen widget tests over a temp database."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from main_window import MainWindow
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


def test_row_click_does_nothing(view, tmp_path):
    """(#93) A plain click must be a total no-op: no highlight (the
    NoSelection mode kills it), no tick, no armed removal. Only the
    checkbox changes state; double-click still opens."""
    seed(view, tmp_path / "a.pdf")
    view.load_library()
    row = rows(view)[0]
    row.resize(600, 80)

    QTest.mouseClick(row, Qt.MouseButton.LeftButton, pos=QPoint(row.width() - 8, 40))
    assert not view.pdf_list.item(0).isSelected(), "click must not highlight"
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


# ------------------------------------------------------------
# library.db backup (#83)
# ------------------------------------------------------------


def test_backup_button_calls_seam_and_confirms(view, monkeypatch):
    """(#83 AC) The 💾 Backup button runs the backup seam and shows the
    user where the copy went."""
    fake_path = Path("/backups/library-20261011-120000.db")
    monkeypatch.setattr(view, "_do_backup", lambda: fake_path)
    messages = []
    monkeypatch.setattr(
        "views.library_view.QMessageBox.information",
        lambda *a: messages.append(a),
    )

    view.backup_btn.click()

    assert messages, "no confirmation shown"
    assert str(fake_path) in messages[0][2]


def test_backup_button_writes_a_real_openable_snapshot(view, tmp_path, monkeypatch):
    """(#83) A real click leaves an openable library-*.db copy in the
    backups dir with the same rows as the source."""
    seed(view, tmp_path / "a.pdf")
    seed(view, tmp_path / "b.pdf")
    monkeypatch.setattr(
        "views.library_view.QMessageBox.information", lambda *a: None
    )

    view.backup_btn.click()

    backups = list(view.backups_dir.glob("library-*.db"))
    assert len(backups) == 1
    copy = sqlite3.connect(backups[0])
    try:
        assert copy.execute("SELECT COUNT(*) FROM pdfs").fetchone()[0] == 2
    finally:
        copy.close()


def _row_by_path(view, path):
    for r in rows(view):
        if r.path == str(path):
            return r
    raise AssertionError(f"no row for {path}")


class _StubStack:
    """Pure-Python stand-in for the view stack: no Qt ownership, so the
    temp MainWindow can't delete the fixture's LibraryView on GC."""

    def __init__(self):
        self.shown = None

    def setCurrentWidget(self, widget):
        self.shown = widget


def _bare_main_window(view):
    """Uninitialized MainWindow holding just what show_library touches
    (#89) — constructing a real one would hit the real library.db."""
    win = MainWindow.__new__(MainWindow)
    win.library_view = view
    win.stacked_widget = _StubStack()
    win.library_btn = None
    win._set_active_sidebar = lambda btn: None
    return win


def test_needs_rebuild_false_after_startup(view):
    """(#89) The initial load already built the rows."""
    assert view.needs_rebuild() is False


def test_update_progress_refreshes_row_in_place(view, tmp_path, monkeypatch):
    """(#89) Page changes land on the existing row widget — no rebuild,
    no wiped checkboxes, DB write intact."""
    seed(view, tmp_path / "a.pdf", total_pages=3, current_page=1)
    seed(view, tmp_path / "b.pdf", total_pages=3, current_page=1)
    view.load_library()
    row_widget = _row_by_path(view, tmp_path / "a.pdf")

    rebuilds = []
    monkeypatch.setattr(view, "_rebuild_library_list", lambda: rebuilds.append(1))

    view.update_progress(str(tmp_path / "a.pdf"), 2)

    assert rebuilds == []
    assert _row_by_path(view, tmp_path / "a.pdf") is row_widget  # same widget
    assert row_widget.page_label.text() == "Page 2 / 3"
    assert row_widget.progress_bar.value() == 66
    assert view.needs_rebuild() is False
    got = view.cursor.execute(
        "SELECT current_page FROM pdfs WHERE path = ?", (str(tmp_path / "a.pdf"),)
    ).fetchone()[0]
    assert got == 2, "DB write must still happen"


def test_update_progress_unknown_path_is_a_noop(view, tmp_path):
    """(#89) Progress for a PDF that isn't listed must not crash or dirty
    the list."""
    seed(view, tmp_path / "a.pdf")
    view.load_library()
    view.update_progress(str(tmp_path / "not-listed.pdf"), 7)
    assert view.pdf_list.count() == 1
    assert view.needs_rebuild() is False


def test_show_library_skips_rebuild_when_rows_are_clean(view, tmp_path, monkeypatch):
    """(#89 AC) Back to a clean list does not clear/re-create the rows."""
    seed(view, tmp_path / "a.pdf")
    view.load_library()
    rebuilds = []
    monkeypatch.setattr(view, "_rebuild_library_list", lambda: rebuilds.append(1))

    win = _bare_main_window(view)
    MainWindow.show_library(win)

    assert win.stacked_widget.shown is view
    assert rebuilds == []
    assert view.pdf_list.count() == 1


def test_show_library_rebuilds_when_dirty(view, tmp_path, monkeypatch):
    """(#89) A marked-dirty view still rebuilds through show_library."""
    seed(view, tmp_path / "a.pdf")
    view.load_library()
    view._structural_dirty = True
    rebuilds = []
    monkeypatch.setattr(view, "_rebuild_library_list", lambda: rebuilds.append(1))

    win = _bare_main_window(view)
    MainWindow.show_library(win)

    assert rebuilds == [1]
    assert view.needs_rebuild() is False  # load_library cleared the flag


# ------------------------------------------------------------
# Re-adding an existing PDF preserves history (#99)
# ------------------------------------------------------------


def _make_real_pdf(path, pages=3):
    import fitz

    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()


def test_readd_same_pdf_preserves_id_progress_and_extracts(view, tmp_path):
    """(#99) Re-adding a PDF already in the library must not reset its
    id (which would orphan every extract/flashcard keyed to it) or its
    read progress — name/page count just refresh from disk."""
    from services.extract_store import init_schema

    pdf = tmp_path / "a.pdf"
    _make_real_pdf(pdf, pages=3)

    view.add_pdf_to_library(str(pdf))
    doc_id, page, pages = view.cursor.execute(
        "SELECT id, current_page, total_pages FROM pdfs WHERE path = ?",
        (str(pdf),),
    ).fetchone()
    assert pages == 3
    assert page == 1

    # advance progress + attach an extract to this document
    init_schema(view.conn)
    view.cursor.execute("UPDATE pdfs SET current_page = 2 WHERE id = ?", (doc_id,))
    view.cursor.execute(
        "INSERT INTO extracts (doc_id, created_at, type, text_content) "
        "VALUES (?, datetime('now'), 'text', 'hello')",
        (doc_id,),
    )
    view.conn.commit()

    view.add_pdf_to_library(str(pdf))  # re-add the same file

    new_id, new_page = view.cursor.execute(
        "SELECT id, current_page FROM pdfs WHERE path = ?", (str(pdf),)
    ).fetchone()
    assert new_id == doc_id, "re-add must keep the same row id"
    assert new_page == 2, "re-add must not reset read progress"
    linked = view.cursor.execute(
        "SELECT COUNT(*) FROM extracts WHERE doc_id = ?", (doc_id,)
    ).fetchone()[0]
    assert linked == 1, "extracts must stay linked to the same doc_id"


def test_readd_refreshes_name_and_page_count(view, tmp_path):
    """(#99) A re-add still does its job: page count and name refresh
    from the file on disk."""
    pdf = tmp_path / "a.pdf"
    _make_real_pdf(pdf, pages=3)

    view.add_pdf_to_library(str(pdf))
    # simulate a stale row, then re-add after the file "grew"
    view.cursor.execute("UPDATE pdfs SET name = 'old', total_pages = 1")
    view.conn.commit()
    _make_real_pdf(pdf, pages=5)

    view.add_pdf_to_library(str(pdf))

    name, pages = view.cursor.execute(
        "SELECT name, total_pages FROM pdfs WHERE path = ?", (str(pdf),)
    ).fetchone()
    assert name == "a.pdf"
    assert pages == 5
