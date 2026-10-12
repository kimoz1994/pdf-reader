"""Offscreen tests for the flashcard list row actions (#60), the
Due-today filter (#61), and the Source-cell jump (#62).

Delete asks for confirmation and removes the row; edit corrects the
question through a small dialog; both refresh the list immediately and
neither disturbs the card's scheduling state. The confirm and the
dialog are monkeypatched seams (`_confirm_delete` / `_prompt_question`),
exactly like the library's `_confirm_removal`.

The 📅 Due today toggle (#61) switches the table between every card and
exactly the Review session's set — same `list_due_cards(conn,
end_of_local_day_utc())` cutoff — and stays usable at zero and many due.

Source jump (#62): a live Source cell carries the jump payload and
emits `source_jump_requested`; a deleted Extract or removed Document
leaves the card listed (no cascade) with the jump hidden.
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
    Capture,
    commit_working_set,
    create_flashcard,
    delete_extract,
    init_schema,
    list_due_cards,
    list_flashcards,
    record_review,
)
from services.fsrs_scheduler import end_of_local_day_utc
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


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def seed_due_spread(conn):
    """One card per due category: overdue, later-today, tomorrow, and
    brand-new (due now). 'Later today' is pinned to the local cutoff so
    the test can't flake near midnight."""
    now = datetime.now(timezone.utc)
    cutoff = end_of_local_day_utc()
    overdue = create_flashcard(
        conn, "Overdue?", "A", due_utc=_iso(now - timedelta(days=2))
    )
    later = create_flashcard(
        conn, "LaterToday?", "B", due_utc=_iso(cutoff - timedelta(hours=1))
    )
    tomorrow = create_flashcard(
        conn, "Tomorrow?", "C", due_utc=_iso(cutoff + timedelta(hours=1))
    )
    fresh = create_flashcard(conn, "New?", "D")
    return overdue, later, tomorrow, fresh


def visible_ids(view):
    return [
        view.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for row in range(view.table.rowCount())
    ]


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


def test_delete_asks_confirm_and_removes_only_that_card(
    app, conn, monkeypatch
):
    """(#60 AC) Delete goes through a confirmation carrying the row's
    question; on confirm the card — and its image blobs and review
    logs — are gone, the sibling card and the list stay."""
    doomed = create_flashcard(conn, "Qbye", "B", image_blobs=[b"\x89PNG-x"])
    record_review(
        conn, doomed, 3, "{}", datetime.now(timezone.utc) + timedelta(days=1)
    )
    create_flashcard(conn, "Qkeep", "A", image_blobs=[b"\x89PNG-keep"])
    view = make_view(conn, monkeypatch)
    view.show()
    view.table.selectRow(row_of(view, "Qbye"))

    asked = {}

    def fake_confirm(question):
        asked["q"] = question
        return True

    monkeypatch.setattr(view, "_confirm_delete", fake_confirm)
    view.delete_btn.click()

    assert asked["q"] == "Qbye"  # the dialog names the card it removes
    assert [c.question for c in list_flashcards(conn)] == ["Qkeep"]
    assert conn.execute(
        "SELECT COUNT(*) FROM flashcard_images WHERE flashcard_id = ?", (doomed,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM review_logs WHERE flashcard_id = ?", (doomed,)
    ).fetchone()[0] == 0
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

    monkeypatch.setattr(view, "_prompt_question", lambda current: "Fixed?")
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

    monkeypatch.setattr(view, "_prompt_question", lambda current: None)
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

    monkeypatch.setattr(view, "_prompt_question", lambda current: "Qa!")
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


# ------------------------------------------------------------
# Due-today filter (#61)
# ------------------------------------------------------------


def test_filter_defaults_off_and_toggles_to_the_review_set(
    app, conn, monkeypatch
):
    """(#61 AC) The toggle starts on All; flipping it shows exactly the
    Review session's set — overdue, later-today and new cards in, the
    tomorrow card out — and flipping back restores every row."""
    overdue, later, tomorrow, fresh = seed_due_spread(conn)
    view = make_view(conn, monkeypatch)
    view.show()

    assert not view.due_toggle.isChecked()
    assert view.table.rowCount() == 4

    view.due_toggle.click()  # -> Due today

    assert view.due_toggle.isChecked()
    assert sorted(visible_ids(view)) == sorted(
        c.id for c in list_due_cards(conn, end_of_local_day_utc())
    )
    assert tomorrow not in visible_ids(view)
    assert {overdue, later, fresh} == set(visible_ids(view))

    view.due_toggle.click()  # -> All

    assert not view.due_toggle.isChecked()
    assert view.table.rowCount() == 4


def test_filter_zero_due_stays_usable(app, conn, monkeypatch):
    """(#61 AC) With nothing due, Due-today shows the existing empty
    state (no blank table) and All brings the card back."""
    tomorrow = create_flashcard(
        conn, "Tomorrow?", "A",
        due_utc=_iso(end_of_local_day_utc() + timedelta(hours=1)),
    )
    view = make_view(conn, monkeypatch)
    view.show()
    view.due_toggle.click()

    assert view.table.rowCount() == 0
    assert not view.table.isVisible()
    assert view.due_hint.isVisible()
    assert view.due_hint.text() == "No cards due today"
    assert not view.review_btn.isEnabled()

    view.due_toggle.click()  # back to All

    assert view.table.isVisible()
    assert visible_ids(view) == [tomorrow]


def test_filter_many_due_matches_review_button_and_keeps_row_actions(
    app, conn, monkeypatch
):
    """(#61 AC) Every due card shows under the filter, the Review
    button's count agrees, and delete still works on a visible row."""
    overdue, later, tomorrow, fresh = seed_due_spread(conn)
    view = make_view(conn, monkeypatch)
    view.show()
    view.due_toggle.click()

    assert view.table.rowCount() == 3
    assert view.review_btn.text() == "▶ Review (3)"
    assert tomorrow not in visible_ids(view)

    view.table.selectRow(row_of(view, "New?"))
    assert view.delete_btn.isEnabled()
    monkeypatch.setattr(view, "_confirm_delete", lambda q: True)
    view.delete_btn.click()

    assert view.table.rowCount() == 2
    assert fresh not in visible_ids(view)
    assert tomorrow not in visible_ids(view)
    remaining = {c.question for c in list_flashcards(conn)}
    assert remaining == {"Overdue?", "LaterToday?", "Tomorrow?"}


def test_filter_with_no_cards_shows_the_empty_state(app, conn, monkeypatch):
    """(#61) An empty library keeps the 'No flashcards yet' state under
    either toggle position."""
    view = make_view(conn, monkeypatch)
    view.show()
    view.due_toggle.click()

    assert not view.table.isVisible()
    assert view.empty_label.isVisible()
    assert "No flashcards yet" in view.empty_label.text()


# ------------------------------------------------------------
# Source jump (#62): click the Source cell -> the Extract Editor
# ------------------------------------------------------------


def seed_sourced_card(conn, question):
    """A live document + Extract + card on it; returns (doc_id, eid)."""
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
        conn, doc_id, [Capture(0, (0, 0, 1, 1), "text", "x")]
    )
    create_flashcard(conn, question, "A", extract_id=eid, doc_id=doc_id)
    return doc_id, eid


def click_source(view, question):
    """Pretend the Source cell of `question`'s row was clicked."""
    view.table.cellClicked.emit(row_of(view, question), 1)


def test_source_cell_click_emits_jump_for_live_source(app, conn, monkeypatch):
    """(#62 AC) Clicking a live Source cell emits the jump payload the
    navigation path needs, and the cell is styled as a link."""
    doc_id, eid = seed_sourced_card(conn, "Sourced?")
    view = make_view(conn, monkeypatch)
    view.show()
    hits = []
    view.source_jump_requested.connect(lambda e, d: hits.append((e, d)))

    click_source(view, "Sourced?")

    assert hits == [(eid, doc_id)]
    cell = view.table.item(row_of(view, "Sourced?"), 1)
    assert cell.data(Qt.ItemDataRole.UserRole) == {
        "extract_id": eid,
        "doc_id": doc_id,
    }
    assert cell.foreground().color().name() == "#3498db"
    assert "Extract" in cell.toolTip()


def test_source_click_dead_for_deleted_extract(app, conn, monkeypatch):
    """(#62 AC) The card survives delete_extract with no cascade, shows
    the 'source gone' marker, and its jump is hidden — clicking does
    nothing."""
    doc_id, eid = seed_sourced_card(conn, "Orphan?")
    delete_extract(conn, eid)
    view = make_view(conn, monkeypatch)
    view.show()
    hits = []
    view.source_jump_requested.connect(lambda e, d: hits.append((e, d)))
    cell = view.table.item(row_of(view, "Orphan?"), 1)

    click_source(view, "Orphan?")

    assert hits == []
    assert cell.text() == "book ⚠ source gone"
    assert cell.data(Qt.ItemDataRole.UserRole) is None
    assert cell.foreground().color().name() != "#3498db"
    assert cell.toolTip() == ""


def test_source_click_dead_for_removed_document(app, conn, monkeypatch):
    """(#62 AC) The Document row deleted = no jump either; #70's
    name-keeping marker stays on the cell."""
    doc_id, _eid = seed_sourced_card(conn, "NoDoc?")
    conn.execute("DELETE FROM pdfs WHERE id = ?", (doc_id,))
    conn.commit()
    view = make_view(conn, monkeypatch)
    view.show()
    hits = []
    view.source_jump_requested.connect(lambda e, d: hits.append((e, d)))

    click_source(view, "NoDoc?")

    assert hits == []
    cell = view.table.item(row_of(view, "NoDoc?"), 1)
    assert cell.text() == "book ⚠ removed source"
    assert cell.data(Qt.ItemDataRole.UserRole) is None
    assert cell.toolTip() == ""


def test_source_click_column_guard(app, conn, monkeypatch):
    """(#62) Only the Source column jumps — clicking Question/Created/
    Next due never emits, even on a live-source row."""
    seed_sourced_card(conn, "Sourced?")
    view = make_view(conn, monkeypatch)
    view.show()
    hits = []
    view.source_jump_requested.connect(lambda e, d: hits.append((e, d)))
    row = row_of(view, "Sourced?")

    for col in (0, 2, 3):
        view.table.cellClicked.emit(row, col)

    assert hits == []


# ------------------------------------------------------------
# Sort + search (#110)
# ------------------------------------------------------------


def test_table_is_sortable(app, conn, monkeypatch):
    """(#110 AC) Header clicks sort the card list."""
    create_flashcard(conn, "B-question", "A")
    create_flashcard(conn, "A-question", "B")
    view = make_view(conn, monkeypatch)
    view.show()

    assert view.table.isSortingEnabled()
    view.table.sortItems(0, Qt.SortOrder.AscendingOrder)
    texts = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert texts == ["A-question", "B-question"]


def test_filter_narrows_to_matching_cards(app, conn, monkeypatch):
    """(#110 AC) Typing in the search box keeps only rows whose question
    or source name contains the text (case-insensitive)."""
    create_flashcard(conn, "What is a buffer?", "A")
    create_flashcard(conn, "Define cache", "B")
    view = make_view(conn, monkeypatch)
    view.show()

    view.filter_input.setText("buffer")

    texts = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert texts == ["What is a buffer?"]


def test_filter_matches_source_name(app, conn, monkeypatch):
    """(#110) The search also covers the source Document name."""
    seed_sourced_card(conn, "From book?")
    create_flashcard(conn, "Untied?", "A")
    view = make_view(conn, monkeypatch)
    view.show()

    view.filter_input.setText("book")

    texts = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert texts == ["From book?"]


def test_filter_empty_shows_no_match_message(app, conn, monkeypatch):
    """(#110) A filter with zero hits hides the table and says so —
    not a silent empty box."""
    create_flashcard(conn, "Visible?", "A")
    view = make_view(conn, monkeypatch)
    view.show()

    view.filter_input.setText("zzz-no-such-card")

    assert not view.table.isVisible()
    assert view.empty_label.isVisible()
    assert "no cards match" in view.empty_label.text().lower()


def test_clearing_filter_restores_the_list(app, conn, monkeypatch):
    """(#110) Emptying the search box brings every card back."""
    create_flashcard(conn, "One", "A")
    create_flashcard(conn, "Two", "B")
    view = make_view(conn, monkeypatch)
    view.show()

    view.filter_input.setText("one")
    assert view.table.rowCount() == 1
    view.filter_input.setText("")

    assert view.table.rowCount() == 2
    assert view.table.isVisible()


def test_filter_composes_with_due_today(app, conn, monkeypatch):
    """(#110) Search applies *on top of* the 📅 Due today filter —
    both must match for a row to show."""
    now = datetime.now(timezone.utc)
    cutoff = end_of_local_day_utc()
    create_flashcard(
        conn, "Due alpha?", "A", due_utc=_iso(now - timedelta(hours=1))
    )
    create_flashcard(conn, "Due beta?", "B", due_utc=_iso(cutoff))
    create_flashcard(
        conn, "Someday alpha?", "C", due_utc=_iso(cutoff + timedelta(days=7))
    )
    view = make_view(conn, monkeypatch)
    view.show()

    view.due_toggle.setChecked(True)  # due-only
    view.filter_input.setText("alpha")  # …and alpha

    texts = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert texts == ["Due alpha?"]


# ------------------------------------------------------------
# Study stats strip (#111)
# ------------------------------------------------------------


def test_stats_strip_shows_counts(app, conn, monkeypatch):
    """(#111 AC) The strip lists total cards, reviews today, due
    tomorrow, due-in-7-days — and a streak once one exists."""
    from datetime import datetime as _dt, timezone as _tz

    now = _dt.now(_tz.utc)
    c1 = create_flashcard(
        conn, "Q1?", "A", due_utc=(now + timedelta(days=1)).isoformat(timespec="seconds")
    )
    create_flashcard(
        conn, "Q2?", "A", due_utc=(now + timedelta(days=3)).isoformat(timespec="seconds")
    )
    record_review(conn, c1, 3, "{}", now + timedelta(hours=1))
    view = make_view(conn, monkeypatch)
    view.show()

    text = view.stats_label.text()
    assert view.stats_label.isVisible()
    assert "2 cards" in text
    assert "1 reviewed today" in text
    assert "streak" in text.lower()


def test_stats_strip_hidden_when_empty(app, conn, monkeypatch):
    """(#111) An empty library hides the strip — no floating zeros."""
    view = make_view(conn, monkeypatch)
    view.show()

    assert not view.stats_label.isVisible()
