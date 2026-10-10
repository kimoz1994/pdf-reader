"""Offscreen smoke test for the FSRS review session loop (#58).

Drives the dialog exactly as a user would: Space reveals, 1-4 grade,
the queue walks to completion and each grade persists through the
store. Fuzzing is off (injected scheduler) for determinism.
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
    """(#58 AC) Space reveals the answer read-only; keys 1-4 grade and
    advance; every grade persists fsrs_json + due_utc + a review_logs
    row; the dialog closes when the queue is exhausted."""
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

    # Grade 1 (Again) -> card 2.
    QTest.keyClick(dialog, Qt.Key.Key_1)
    assert dialog.question_label.text() == "Q2"
    assert not dialog.answer_view.isVisible()  # hidden again for card 2

    # Reveal + grade 3 (Good) -> session done.
    QTest.keyClick(dialog, Qt.Key.Key_Space)
    assert "Answer two" in dialog.answer_view.toPlainText()
    QTest.keyClick(dialog, Qt.Key.Key_3)
    assert not dialog.isVisible()

    # Persistence: both cards have state + a written due; log rows match
    # the grades in session order.
    cards = {c.id: c for c in list_flashcards(conn)}
    for cid in (q1, q2):
        assert cards[cid].fsrs_json
        assert cards[cid].due_utc  # non-empty (Again stays same-day)
    logs = conn.execute(
        "SELECT flashcard_id, rating FROM review_logs ORDER BY id"
    ).fetchall()
    assert logs == [(q1, 1), (q2, 3)]


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
    assert not dialog.isVisible()  # queue exhausted -> session closed


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

    # A card due tomorrow is not counted.
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    create_flashcard(
        conn, "Qtomorrow", "A", due_utc=tomorrow.isoformat(timespec="seconds")
    )
    view.refresh()
    assert "2" in view.review_btn.text()

    # Click starts a session over the two due cards.
    opened = {}

    def fake_exec(self):
        opened["queue"] = [c.question for c in self._queue]
        return 0

    monkeypatch.setattr(ReviewSessionDialog, "exec", fake_exec)
    view.review_btn.click()
    assert set(opened["queue"]) == {"Qa", "Qb"}


def _tiny_png():
    """A minimal valid 1x1 PNG."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
