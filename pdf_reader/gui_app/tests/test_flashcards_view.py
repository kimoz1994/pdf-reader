"""Offscreen tests for the flashcard list row actions (#60).

Delete asks for confirmation and removes the row; edit corrects the
question through a small dialog; both refresh the list immediately and
neither disturbs the card's scheduling state. The confirm and the
dialog are monkeypatched seams (`_confirm_delete` / `_ask_question`),
exactly like the library's `_confirm_removal`.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from services.extract_store import (
    create_flashcard,
    init_schema,
    list_flashcards,
    record_review,
)
from views.flashcards_view import FlashcardsView, _EditQuestionDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "fc.db")
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
    """Wire a FlashcardsView onto the temp DB (same pattern as the
    review-session tests: skip __init__, patch _db_conn, then
    setup_ui — which refreshes from the DB)."""
    view = FlashcardsView.__new__(FlashcardsView)
    monkeypatch.setattr(FlashcardsView, "_db_conn", lambda self: conn)
    QWidget.__init__(view)
    view.setup_ui()
    return view


def row_of(view, question):
    for row in range(view.table.rowCount()):
        if view.table.item(row, 0).text() == question:
            return row
    raise AssertionError(f"no row for {question!r}")


def test_row_actions_arm_only_with_a_selection(app, conn, monkeypatch):
    """(#60) Edit/Delete (buttons and their context-menu actions) are
    dead without a selected row and come alive with one."""
    create_flashcard(conn, "Qa", "A")
    create_flashcard(conn, "Qb", "B")
    view = make_view(conn, monkeypatch)
    view.show()

    assert not view.edit_btn.isEnabled()
    assert not view.delete_btn.isEnabled()
    assert not view.edit_action.isEnabled()
    assert not view.delete_action.isEnabled()

    view.table.selectRow(row_of(view, "Qa"))
    assert view.edit_btn.isEnabled()
    assert view.delete_btn.isEnabled()
    assert view.edit_action.isEnabled()
    assert view.delete_action.isEnabled()

    view.table.clearSelection()
    assert not view.delete_btn.isEnabled()


def test_delete_asks_confirm_and_refreshes(app, conn, monkeypatch):
    """(#60 AC) Delete goes through a confirmation carrying the row's
    question; on confirm the card is gone and the list reloads."""
    create_flashcard(conn, "Qkeep", "A")
    create_flashcard(conn, "Qbye", "B")
    view = make_view(conn, monkeypatch)
    view.show()
    view.table.selectRow(row_of(view, "Qbye"))

    asked = {}
    monkeypatch.setattr(view, "_confirm_delete", lambda q: asked.setdefault("q", q) or True)
    view.delete_btn.click()

    assert asked["q"] == "Qbye"  # the dialog names the card it removes
    assert [c.question for c in list_flashcards(conn)] == ["Qkeep"]
    assert view.table.rowCount() == 1
    assert view.table.item(0, 0).text() == "Qkeep"


def test_delete_cancelled_keeps_row_and_card(app, conn, monkeypatch):
    """(#60 AC) Saying No to the confirmation removes nothing."""
    create_flashcard(conn, "Qa", "A")
    create_flashcard(conn, "Qb", "B")
    view = make_view(conn, monkeypatch)
    view.show()
    view.table.selectRow(row_of(view, "Qa"))

    monkeypatch.setattr(view, "_confirm_delete", lambda q: False)
    view.delete_btn.click()

    assert view.table.rowCount() == 2
    assert {c.question for c in list_flashcards(conn)} == {"Qa", "Qb"}


def test_delete_with_nothing_selected_is_inert(app, conn, monkeypatch):
    """(#60) The buttons are disabled, but a direct call must guard
    too — no confirmation, no deletion."""
    create_flashcard(conn, "Qa", "A")
    view = make_view(conn, monkeypatch)
    view.show()

    def boom(q):
        raise AssertionError("no confirmation without a selection")

    monkeypatch.setattr(view, "_confirm_delete", boom)
    view._delete_selected()
    assert [c.question for c in list_flashcards(conn)] == ["Qa"]


def test_edit_question_updates_row_and_keeps_schedule(app, conn, monkeypatch):
    """(#60 AC) The edited question shows immediately; fsrs_json and
    due_utc are bit-identical afterwards."""
    graded = create_flashcard(conn, "Typo here?", "A")
    new_due = datetime.now(timezone.utc) + timedelta(days=3)
    record_review(conn, graded, 3, '{"stability": 4.25}', new_due)
    view = make_view(conn, monkeypatch)
    view.show()
    view.table.selectRow(row_of(view, "Typo here?"))

    monkeypatch.setattr(view, "_ask_question", lambda current: "Fixed?")
    view.edit_btn.click()

    assert view.table.rowCount() == 1
    assert view.table.item(0, 0).text() == "Fixed?"
    card = list_flashcards(conn)[0]
    assert card.question == "Fixed?"
    assert card.fsrs_json == '{"stability": 4.25}'
    assert card.due_utc == new_due.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    )


def test_edit_cancelled_changes_nothing(app, conn, monkeypatch):
    """(#60) Backing out of the dialog leaves the question alone."""
    create_flashcard(conn, "Qa", "A")
    view = make_view(conn, monkeypatch)
    view.show()
    view.table.selectRow(0)

    monkeypatch.setattr(view, "_ask_question", lambda current: None)
    view.edit_btn.click()

    assert view.table.item(0, 0).text() == "Qa"
    assert list_flashcards(conn)[0].question == "Qa"


def test_delete_key_removes_the_selected_row(app, conn, monkeypatch):
    """(#60) Del on the table is the same confirmed delete as the
    button (library precedent)."""
    create_flashcard(conn, "Qa", "A")
    create_flashcard(conn, "Qb", "B")
    view = make_view(conn, monkeypatch)
    view.show()
    app.processEvents()
    view.table.selectRow(row_of(view, "Qb"))
    view.table.setFocus()
    app.processEvents()

    monkeypatch.setattr(view, "_confirm_delete", lambda q: True)
    QTest.keyClick(view.table, Qt.Key.Key_Delete)

    assert [c.question for c in list_flashcards(conn)] == ["Qa"]
    assert view.table.rowCount() == 1


def test_edit_key_opens_the_question_dialog(app, conn, monkeypatch):
    """(#60) F2 on the table is the same edit as the button."""
    create_flashcard(conn, "Qa", "A")
    view = make_view(conn, monkeypatch)
    view.show()
    app.processEvents()
    view.table.selectRow(0)
    view.table.setFocus()
    app.processEvents()

    monkeypatch.setattr(view, "_ask_question", lambda current: "Qa!")
    QTest.keyClick(view.table, Qt.Key.Key_F2)

    assert list_flashcards(conn)[0].question == "Qa!"
    assert view.table.item(0, 0).text() == "Qa!"


def test_edit_dialog_prefills_and_gates_save(app):
    """(#60) The dialog opens on the current question, Save dies on an
    empty field, Enter submits when it has one."""
    dialog = _EditQuestionDialog("Old wording?")
    assert dialog.question_edit.text() == "Old wording?"
    assert dialog.save_btn.isEnabled()

    dialog.question_edit.setText("   ")
    assert not dialog.save_btn.isEnabled()

    dialog.question_edit.setText("New wording?")
    assert dialog.save_btn.isEnabled()
    assert dialog.question() == "New wording?"
