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
# Delete confirm mentions flashcard impact (#108)
# ------------------------------------------------------------


def _extract_row(view):
    """The first Extract row in the tree (child of the first Document)."""
    doc_item = view.tree.topLevelItem(0)
    return doc_item.child(0)


def test_delete_confirm_mentions_flashcard_count(app, conn, monkeypatch):
    """(#108 AC) When N flashcards point at the Extract, the confirm
    text says so — the user learns the cards lose their source link."""
    from PyQt6.QtWidgets import QMessageBox

    from services.extract_store import create_flashcard

    doc_id, eid = seed_extract(conn)
    create_flashcard(conn, "Q1", "A1", extract_id=eid, doc_id=doc_id)
    create_flashcard(conn, "Q2", "A2", extract_id=eid, doc_id=doc_id)
    view = make_view(conn, monkeypatch)
    view.tree.setCurrentItem(_extract_row(view))

    seen = []

    def fake_question(parent, title, text, *a, **k):
        seen.append(text)
        return QMessageBox.StandardButton.No  # cancel: we only inspect the text

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))

    view.delete_selected()

    assert seen, "no confirm dialog"
    assert "2 flashcards" in seen[0]
    assert "lose their source link" in seen[0]


def test_delete_confirm_omits_flashcard_line_when_none(app, conn, monkeypatch):
    """(#108) No cards on the Extract: the confirm text has no flashcard
    warning line."""
    from PyQt6.QtWidgets import QMessageBox

    doc_id, eid = seed_extract(conn)
    view = make_view(conn, monkeypatch)
    view.tree.setCurrentItem(_extract_row(view))

    seen = []

    def fake_question(parent, title, text, *a, **k):
        seen.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))

    view.delete_selected()

    assert seen and "flashcard" not in seen[0]
