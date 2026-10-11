"""Offscreen smoke test for the FSRS review session loop (#58/#59).

Drives the dialog exactly as a user would: Space reveals, 1-4 grade,
the queue walks to completion and each grade persists through the
store. Fuzzing is off (injected scheduler) for determinism. Session
completion (#59): Again cards re-queue within the fixed session total
and come back before the end, finishing shows an end-of-session
summary, and an empty day shows a hint instead of a session.
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
    get_flashcard_images,
    init_schema,
    list_due_cards,
    list_flashcards,
)
from services.fsrs_scheduler import end_of_local_day_utc, make_scheduler
from views.flashcards_view import FlashcardsView, ReviewSessionDialog


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


def _due_today(conn):
    """Build the session queue the way the view does."""
    return list_due_cards(conn, end_of_local_day_utc())


def test_session_loop_reveal_grade_persist(app, conn):
    """(#58/#59 AC) Space reveals the answer read-only; keys 1-4 grade
    and advance; an Again card re-queues and comes back before the
    session ends; every grade persists fsrs_json + due_utc + a
    review_logs row; completion shows the summary, which closes back."""
    q1 = create_flashcard(conn, "Q1", "Answer one")
    q2 = create_flashcard(conn, "Q2", "Answer two")
    queue = _due_today(conn)
    assert {c.id for c in queue} == {q1, q2}

    dialog = ReviewSessionDialog(
        queue, conn, scheduler=make_scheduler(fuzz=False), shuffle=False
    )
    dialog.show()
    assert dialog.isVisible()

    # Card 1: question shown, answer hidden.
    assert dialog.question_label.text() == "Q1"
    assert not dialog.answer_view.isVisible()

    # Space reveals.
    QTest.keyClick(dialog, Qt.Key.Key_Space)
    assert dialog.answer_view.isVisible()
    assert "Answer one" in dialog.answer_view.toPlainText()

    # Grade 1 (Again) -> card 2 (card 1 re-queues behind it).
    QTest.keyClick(dialog, Qt.Key.Key_1)
    assert dialog.question_label.text() == "Q2"
    assert not dialog.answer_view.isVisible()  # hidden again for card 2

    # Reveal + grade 3 (Good) -> the Again card comes back.
    QTest.keyClick(dialog, Qt.Key.Key_Space)
    assert "Answer two" in dialog.answer_view.toPlainText()
    QTest.keyClick(dialog, Qt.Key.Key_3)
    assert dialog.isVisible()
    assert dialog.question_label.text() == "Q1"  # re-queued, not done

    # Finish the re-queued card -> the summary, not a silent close.
    QTest.keyClick(dialog, Qt.Key.Key_Space)
    QTest.keyClick(dialog, Qt.Key.Key_3)
    assert dialog.isVisible()
    assert dialog.summary_label.isVisible()
    assert "Session complete" in dialog.summary_label.text()
    dialog.close_btn.click()
    assert not dialog.isVisible()

    # Persistence: both cards have state + a written due; log rows match
    # the grades in session order (Q1 graded twice: Again then Good).
    cards = {c.id: c for c in list_flashcards(conn)}
    for cid in (q1, q2):
        assert cards[cid].fsrs_json
        assert cards[cid].due_utc  # non-empty (Again stays same-day)
    logs = conn.execute(
        "SELECT flashcard_id, rating FROM review_logs ORDER BY id"
    ).fetchall()
    assert logs == [(q1, 1), (q2, 3), (q1, 3)]


def test_again_requeues_within_fixed_total(app, conn):
    """(#59 AC) The "m" is fixed when the session starts: an Again
    grade re-queues the card at the end without growing the total, the
    card is shown again before the session ends, and the "n of m"
    indicator never exceeds the fixed total."""
    create_flashcard(conn, "QA", "Aa")
    create_flashcard(conn, "QB", "Ab")
    dialog = ReviewSessionDialog(
        _due_today(conn), conn, scheduler=make_scheduler(fuzz=False), shuffle=False
    )
    dialog.show()
    assert dialog._total == 2
    assert dialog.progress_label.text() == "1 of 2"

    # Again on card 1 -> card 2; denominator still 2.
    QTest.keyClick(dialog, Qt.Key.Key_Space)
    QTest.keyClick(dialog, Qt.Key.Key_1)
    assert dialog.isVisible()
    assert dialog.question_label.text() == "QB"
    assert dialog.progress_label.text() == "2 of 2"

    # Good on card 2 -> the Again card returns; still "of 2".
    QTest.keyClick(dialog, Qt.Key.Key_Space)
    QTest.keyClick(dialog, Qt.Key.Key_3)
    assert dialog.question_label.text() == "QA"  # shown again before the end
    assert dialog.progress_label.text() == "2 of 2"  # never "3 of 2"
    assert len(dialog._queue) == 3  # re-queued within the fixed total

    # Finishing shows the summary with both cards reviewed.
    QTest.keyClick(dialog, Qt.Key.Key_Space)
    QTest.keyClick(dialog, Qt.Key.Key_3)
    assert dialog.isVisible()
    assert dialog.summary_label.isVisible()
    assert "2 cards reviewed" in dialog.summary_label.text()
    assert "(1 Again)" in dialog.summary_label.text()


def test_again_card_remains_due_today(app, conn):
    """(#59 AC) A card graded Again is shown again in the same session
    and stays due for the rest of the local day afterwards."""
    q1 = create_flashcard(conn, "Qagain", "A")
    dialog = ReviewSessionDialog(
        _due_today(conn), conn, scheduler=make_scheduler(fuzz=False), shuffle=False
    )
    dialog.show()

    # Again -> re-queued -> shown again in the same session.
    QTest.keyClick(dialog, Qt.Key.Key_Space)
    QTest.keyClick(dialog, Qt.Key.Key_1)
    assert dialog.question_label.text() == "Qagain"

    # Again a second time ends the queue (a card re-queues at most
    # once per session, so the session always terminates).
    QTest.keyClick(dialog, Qt.Key.Key_Space)
    QTest.keyClick(dialog, Qt.Key.Key_1)
    assert dialog.summary_label.isVisible()
    dialog.close_btn.click()
    assert not dialog.isVisible()

    due_ids = {c.id for c in list_due_cards(conn, end_of_local_day_utc())}
    assert q1 in due_ids  # still due today
    logs = conn.execute(
        "SELECT rating FROM review_logs ORDER BY id"
    ).fetchall()
    assert logs == [(1,), (1,)]


def test_session_answer_renders_images_read_only(app, conn):
    """(#58) Mixed-content answers render their card-owned blobs inline
    and cannot be edited."""
    png = _tiny_png()
    fc_id = create_flashcard(
        conn, "Qimg", f"See {chr(0xFFFC)} here", image_blobs=[png]
    )
    dialog = ReviewSessionDialog(
        _due_today(conn), conn, scheduler=make_scheduler(fuzz=False), shuffle=False
    )
    dialog.show()
    assert dialog.question_label.text() == "Qimg"
    assert get_flashcard_images(conn, fc_id) == [png]

    QTest.keyClick(dialog, Qt.Key.Key_Space)
    assert dialog.answer_view.isReadOnly()
    # The image is in the document as a resource, not a placeholder box.
    resources = dialog.answer_view.document().toHtml()
    assert "fcpreview://" in resources


def test_review_session_shuffles_and_reports_progress(app, conn):
    """(#58) The queue is shuffled (not id order) and the progress
    label counts through the fixed session size."""
    ids = [create_flashcard(conn, f"Q{i}", f"A{i}") for i in range(4)]
    queue = _due_today(conn)
    dialog = ReviewSessionDialog(
        queue, conn, scheduler=make_scheduler(fuzz=False), shuffle=True
    )
    dialog.show()
    assert dialog.progress_label.text() == "1 of 4"
    seen = []
    for i in range(4):
        seen.append(dialog.question_label.text())
        QTest.keyClick(dialog, Qt.Key.Key_Space)
        QTest.keyClick(dialog, Qt.Key.Key_3)  # Good
        if dialog.isVisible() and i < 3:
            assert dialog.progress_label.text() == f"{i + 2} of 4"
    assert len(seen) == 4
    assert set(seen) == {f"Q{i}" for i in range(4)}
    # Completion shows the summary and waits for the user (#59),
    # instead of closing silently.
    assert dialog.isVisible()
    assert dialog.summary_label.isVisible()
    assert "4 cards reviewed" in dialog.summary_label.text()
    dialog.close_btn.click()
    assert not dialog.isVisible()  # queue exhausted -> back to the list


def test_review_button_counts_due_and_starts_session(app, conn, monkeypatch):
    """(#58 AC) The Review button shows today's count; clicking it opens
    the session over exactly those cards."""
    create_flashcard(conn, "Qa", "A")
    create_flashcard(conn, "Qb", "A")

    view = FlashcardsView.__new__(FlashcardsView)  # skip __init__; wire manually
    monkeypatch.setattr(FlashcardsView, "_db_conn", lambda self: conn)
    QWidget.__init__(view)
    view.setup_ui()

    assert "2" in view.review_btn.text()  # two due cards
    assert view.due_hint.isHidden()  # something IS due -> no hint

    # A card due tomorrow is not counted.
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    create_flashcard(
        conn, "Qtomorrow", "A", due_utc=tomorrow.isoformat(timespec="seconds")
    )
    view.refresh()
    assert "2" in view.review_btn.text()

    # Click starts a session over the two due cards, and the list
    # reloads cleanly once the session closes (#59).
    opened = {}

    def fake_exec(self):
        opened["queue"] = [c.question for c in self._queue]
        return 0

    monkeypatch.setattr(ReviewSessionDialog, "exec", fake_exec)
    refreshed = []
    monkeypatch.setattr(view, "refresh", lambda: refreshed.append(True))
    view.review_btn.click()
    assert set(opened["queue"]) == {"Qa", "Qb"}
    assert refreshed  # the list returned to cleanly after the session


def test_no_due_cards_shows_hint_not_session(app, conn, monkeypatch):
    """(#59 AC) With no new or due cards, the view shows a visible
    "No cards due today" hint and never starts a session."""
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    create_flashcard(
        conn, "Qlater", "A", due_utc=tomorrow.isoformat(timespec="seconds")
    )

    view = FlashcardsView.__new__(FlashcardsView)  # skip __init__; wire manually
    monkeypatch.setattr(FlashcardsView, "_db_conn", lambda self: conn)
    QWidget.__init__(view)
    view.setup_ui()
    view.show()

    assert view.review_btn.text().endswith("(0)")
    assert not view.review_btn.isEnabled()
    assert view.due_hint.isVisible()
    assert view.due_hint.text() == "No cards due today"

    def boom(self):
        raise AssertionError("session must not start with nothing due")

    monkeypatch.setattr(ReviewSessionDialog, "exec", boom)
    view.review_btn.click()  # disabled + guarded: no session
    view._start_review()  # a direct call must guard too


def _tiny_png():
    """A minimal valid 1x1 PNG."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
