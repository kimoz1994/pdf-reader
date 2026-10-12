"""Offscreen tests for the Flashcards' source-jump landing (#62).

The Flashcards list emits `source_jump_requested(extract_id, doc_id)`;
MainWindow shows the Extracts View (refreshing its tree) and calls
`ExtractsView.open_extract(doc_id, extract_id)`, which reuses the same
activation path as a double-click on the tree row: the full-area
Extract Editor. A missing Extract is a silent no-op — the tree may
have changed since the card list was rendered.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from main_window import MainWindow
from services.extract_store import Capture, commit_working_set, init_schema
from views.extracts_view import ExtractsView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "ex.db")
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS pdfs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            total_pages INTEGER DEFAULT 0,
            current_page INTEGER DEFAULT 1,
            last_opened TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    init_schema(c)
    yield c
    c.close()


def make_view(conn, monkeypatch):
    """Wire an ExtractsView onto the temp DB (the flashcards-view
    pattern: skip __init__, patch _db_conn, then setup_ui — which
    refreshes the tree from the DB)."""
    view = ExtractsView.__new__(ExtractsView)
    monkeypatch.setattr(ExtractsView, "_db_conn", lambda self: conn)
    QWidget.__init__(view)
    view.setup_ui()
    return view


def seed_extract(conn):
    conn.execute(
        "INSERT INTO pdfs (path, name, total_pages, current_page) "
        "VALUES (?, ?, 3, 1)",
        ("C:/tmp/book.pdf", "book.pdf"),
    )
    conn.commit()
    doc_id = conn.execute(
        "SELECT id FROM pdfs WHERE path = ?", ("C:/tmp/book.pdf",)
    ).fetchone()[0]
    eid = commit_working_set(
        conn, doc_id, [Capture(0, (0, 0, 1, 1), "text", "hello")]
    )
    return doc_id, eid


def test_open_extract_shows_the_editor(app, conn, monkeypatch):
    """(#62 AC) The jump lands in the Extract Editor for the exact
    Extract the card pointed at — the tree row's own activation path."""
    doc_id, eid = seed_extract(conn)
    view = make_view(conn, monkeypatch)

    assert view.open_extract(doc_id, eid) is True
    assert view._editor_open
    assert view._editor_extract_id == eid
    assert view._editor_doc_id == doc_id


def test_open_extract_missing_row_is_a_noop(app, conn, monkeypatch):
    """(#62) The tree changed under the card list: no crash, no editor."""
    seed_extract(conn)
    view = make_view(conn, monkeypatch)

    assert view.open_extract(999, 999) is False
    assert not view._editor_open


def test_open_extract_refreshes_when_the_row_is_newer(app, conn, monkeypatch):
    """(#62) The Extract was committed after the view last built its
    tree (e.g. a card created in another session): open_extract finds
    it anyway via a refresh retry."""
    view = make_view(conn, monkeypatch)
    doc_id, eid = seed_extract(conn)

    assert view.open_extract(doc_id, eid) is True
    assert view._editor_open
    assert view._editor_extract_id == eid


def test_open_extract_closes_a_stale_editor_first(app, conn, monkeypatch):
    """(#62) Jumping while another Extract's editor is open replaces it
    instead of stacking — one editor at a time, as the tree path does."""
    doc_id, eid1 = seed_extract(conn)
    eid2 = commit_working_set(
        conn, doc_id, [Capture(1, (0, 0, 1, 1), "text", "second")]
    )
    view = make_view(conn, monkeypatch)
    assert view.open_extract(doc_id, eid1) is True

    assert view.open_extract(doc_id, eid2) is True
    assert view._editor_open
    assert view._editor_extract_id == eid2


def test_source_jump_handler_navigates_via_existing_path(app):
    """(#62 AC) MainWindow's handler shows the Extracts View (the
    app's existing navigation path) and forwards the payload. Built on
    a bare instance — constructing MainWindow would hit the real
    library.db, which tests must never touch."""
    calls = []

    class FakeExtracts:
        def open_extract(self, doc_id, extract_id):
            calls.append(("open", doc_id, extract_id))
            return True

    fake = MainWindow.__new__(MainWindow)
    fake.show_extracts = lambda: calls.append("show_extracts")
    fake.extracts_view = FakeExtracts()

    MainWindow.on_flashcard_source(fake, extract_id=5, doc_id=3)

    assert calls == ["show_extracts", ("open", 3, 5)]


# ------------------------------------------------------------
# Back auto-save failure surfaces instead of silent loss (#101)
# ------------------------------------------------------------


def test_close_editor_failed_save_warns_and_stays(app, conn, monkeypatch):
    """(#101 AC) A failed auto-save on Back must warn and keep the
    editor open — the edit is not silently lost."""
    doc_id, eid = seed_extract(conn)
    view = make_view(conn, monkeypatch)
    assert view.open_extract(doc_id, eid) is True
    view._editor_doc_edit.setPlainText("edited")
    view._editor_dirty = True
    monkeypatch.setattr(view, "_save_editor", lambda: False)
    criticals = []
    monkeypatch.setattr(
        "views.extracts_view.QMessageBox.critical", lambda *a: criticals.append(a)
    )

    view._close_editor()

    assert criticals, "no error dialog shown"
    assert view._editor_open, "editor must stay open on a failed save"


def test_close_editor_successful_save_closes(app, conn, monkeypatch):
    """(#101) A clean (or successful) auto-save still closes the editor."""
    doc_id, eid = seed_extract(conn)
    view = make_view(conn, monkeypatch)
    assert view.open_extract(doc_id, eid) is True
    view._editor_dirty = True
    monkeypatch.setattr(view, "_save_editor", lambda: True)

    view._close_editor()

    assert not view._editor_open
