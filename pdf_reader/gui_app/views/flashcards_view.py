"""
Flashcards View — the card list + FSRS review session (#54/#55/#58/#59).

One row per card: question, source document, created, next due — read
from the headless store (`services.extract_store.list_flashcards`). The
Review (n) button starts a session over today's set (new + due at any
point during the local day): a shuffled queue, question first, Space
(or click) reveals the read-only answer, keys 1-4 grade it through the
pinned FSRS scheduler and persist the new due date (#58). Session
completion (#59): the total is fixed at start, Again cards re-queue
within it and come back before the end, finishing shows an end-of-
session summary, and an empty day shows a "No cards due today" hint
instead of a session. Due-today filtering in the list itself lands
with #61.
"""
import random
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QPushButton,
    QTextEdit,
    QDialog,
)
from PyQt6.QtCore import Qt

from services.extract_store import (
    display_title,
    get_flashcard_images,
    list_due_cards,
    list_flashcards,
    record_review,
)
from services.fsrs_scheduler import (
    RATING_AGAIN,
    RATING_EASY,
    RATING_GOOD,
    RATING_HARD,
    end_of_local_day_utc,
    make_scheduler,
    rate_card,
)
from views.flashcard_answer import fill_answer


def _format_created(created_at):
    """`YYYY-MM-DD HH:MM:SS` (UTC, CURRENT_TIMESTAMP) -> local minutes."""
    if not created_at:
        return ""
    try:
        created = datetime.fromisoformat(str(created_at)).replace(
            tzinfo=timezone.utc
        )
        return created.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(created_at)


def _format_due(due_utc):
    """ISO-8601 UTC due time -> local `YYYY-MM-DD HH:MM` (or raw/empty)."""
    if not due_utc:
        return ""
    try:
        return datetime.fromisoformat(due_utc).astimezone().strftime(
            "%Y-%m-%d %H:%M"
        )
    except ValueError:
        return str(due_utc)


def _source_label(card):
    """Same document naming as the Extracts tree: metadata title when
    available, cleaned filename otherwise; a removed source keeps the
    Extract's name snapshot (#70) and is marked the same way the tree
    marks it — `(source removed)` only when no snapshot exists."""
    if not card.source_path and not card.source_name:
        return "(source removed)"
    if not card.source_path:
        return f"{card.source_name} ⚠ removed source"
    return display_title(card.source_path, card.source_name or "")


class ReviewSessionDialog(QDialog):
    """The FSRS review session (#58/#59): question → reveal → grade.

    A shuffled queue fixed at session start (the caller passes today's
    due set); Space or a click reveals the read-only answer (text +
    card-owned images via the shared renderer); keys 1-4 (or the grade
    buttons) advance the card through the scheduler and persist via
    `record_review`. A card graded **Again** re-queues at the end of
    the queue — within the session total fixed at start, so the "n of
    m" denominator never grows — and is shown again before the session
    ends (at most once per card, so the session always terminates).
    Completing the queue shows an end-of-session summary instead of
    closing silently; Escape closes early — graded cards stay graded.
    The scheduler is injected so tests can disable fuzzing (#58 AC).
    """

    def __init__(self, queue, conn, parent=None, scheduler=None, shuffle=True):
        super().__init__(parent)
        self.setWindowTitle("Review Session")
        self.setModal(True)
        self.resize(640, 520)
        self._conn = conn
        self._queue = list(queue)
        if shuffle:
            random.shuffle(self._queue)
        self._total = len(self._queue)  # fixed "m" for the whole session (#59)
        self._index = 0
        self._revealed = False
        self._done = False
        self._tally = {}  # rating -> grade events this session
        self._graded_ids = set()  # distinct cards graded
        self._requeued = set()  # card ids already re-queued once (#59)
        self._scheduler = scheduler if scheduler is not None else make_scheduler()

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #888; font-size: 13px;")
        layout.addWidget(self.progress_label)

        self.question_label = QLabel()
        self.question_label.setWordWrap(True)
        self.question_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.question_label.setStyleSheet(
            "color: #ecf0f1; font-size: 22px; font-weight: bold;"
            " padding: 20px;"
        )
        layout.addWidget(self.question_label, 1)

        self.answer_view = QTextEdit()
        self.answer_view.setReadOnly(True)
        # Explicit color: OS dark-mode would paint white text on the
        # light paper — same fix as the Make-flashcard dialog (#55).
        self.answer_view.setStyleSheet(
            "background-color: #f7f7f5; color: #1a1a1a;"
            " border: 1px solid #d0d0d0;"
            " border-radius: 6px; padding: 8px; font-size: 14px;"
        )
        self.answer_view.hide()
        layout.addWidget(self.answer_view, 1)

        self.reveal_btn = QPushButton("Show answer (Space)")
        self.reveal_btn.clicked.connect(self._reveal)
        layout.addWidget(self.reveal_btn)

        grades = QHBoxLayout()
        self._grade_buttons = []
        for key, name, rating in (
            (Qt.Key.Key_1, "1 Again", RATING_AGAIN),
            (Qt.Key.Key_2, "2 Hard", RATING_HARD),
            (Qt.Key.Key_3, "3 Good", RATING_GOOD),
            (Qt.Key.Key_4, "4 Easy", RATING_EASY),
        ):
            btn = QPushButton(name)
            btn.setEnabled(False)
            btn.clicked.connect(lambda _=False, r=rating: self._grade(r))
            grades.addWidget(btn)
            self._grade_buttons.append((key, btn, rating))
        layout.addLayout(grades)

        # End-of-session summary (#59): hidden until the queue drains.
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_label.setStyleSheet(
            "color: #ecf0f1; font-size: 20px; font-weight: bold;"
            " padding: 30px;"
        )
        self.summary_label.hide()
        layout.addWidget(self.summary_label, 1)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.hide()
        layout.addWidget(self.close_btn)

        self._show_current()

    # ------------------------------------------------------------
    # Session loop
    # ------------------------------------------------------------

    def _show_current(self):
        if self._index >= len(self._queue):
            self._show_summary()
            return
        card = self._queue[self._index]
        self._revealed = False
        # The denominator is fixed at start; a re-queued Again card
        # never pushes the numerator past it (#59).
        shown = min(self._index + 1, self._total)
        self.progress_label.setText(f"{shown} of {self._total}")
        self.question_label.setText(card.question or "(no question)")
        self.answer_view.clear()
        self.answer_view.hide()
        self.reveal_btn.show()
        self.reveal_btn.setEnabled(True)
        for _, btn, _ in self._grade_buttons:
            btn.setEnabled(False)

    def _show_summary(self):
        """End of the queue: hide the study surface and show how the
        session went; the user closes back to the list (#59 AC)."""
        self._done = True
        self._revealed = False
        self.question_label.hide()
        self.answer_view.hide()
        self.reveal_btn.hide()
        for _, btn, _ in self._grade_buttons:
            btn.setEnabled(False)
            btn.hide()
        self.progress_label.setText(f"{self._total} of {self._total}")
        summary = f"Session complete — {len(self._graded_ids)} cards reviewed"
        again = self._tally.get(RATING_AGAIN, 0)
        if again:
            summary += f" ({again} Again)"
        self.summary_label.setText(summary)
        self.summary_label.show()
        self.close_btn.show()
        self.close_btn.setFocus()

    def _reveal(self):
        if self._done or self._revealed or self._index >= len(self._queue):
            return
        card = self._queue[self._index]
        blobs = get_flashcard_images(self._conn, card.id)
        fill_answer(self.answer_view, card.answer_text, blobs)
        self.answer_view.show()
        self.reveal_btn.hide()
        self._revealed = True
        for _, btn, _ in self._grade_buttons:
            btn.setEnabled(True)

    def _grade(self, rating: int):
        if self._done or not self._revealed or self._index >= len(self._queue):
            return
        card = self._queue[self._index]
        fsrs_json, due = rate_card(
            card.fsrs_json, rating, scheduler=self._scheduler
        )
        record_review(self._conn, card.id, rating, fsrs_json, due)
        self._tally[rating] = self._tally.get(rating, 0) + 1
        self._graded_ids.add(card.id)
        if rating == RATING_AGAIN and card.id not in self._requeued:
            # Re-queue within the fixed total: it comes back before the
            # session ends, at most once per card so the queue drains.
            self._requeued.add(card.id)
            self._queue.append(card)
        self._index += 1
        self._show_current()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space and not self._revealed:
            self._reveal()
            event.accept()
            return
        if self._revealed:
            for grade_key, _, rating in self._grade_buttons:
                if key == grade_key:
                    self._grade(rating)
                    event.accept()
                    return
        super().keyPressEvent(event)


class FlashcardsView(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()

    def _db_conn(self):
        """The shared sqlite connection MainWindow keeps open, or None."""
        main_window = self.window()
        if hasattr(main_window, "db_conn"):
            return main_window.db_conn()
        return None

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        header_row = QHBoxLayout()
        header = QLabel("🃏 Flashcards")
        header.setStyleSheet("font-size: 28px; font-weight: bold; color: #3498db;")
        header_row.addWidget(header)
        header_row.addStretch()
        self.review_btn = QPushButton("▶ Review (0)")
        self.review_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white;"
            " font-weight: bold; border: none; border-radius: 6px;"
            " padding: 8px 18px; font-size: 14px; }"
            "QPushButton:hover { background-color: #2ecc71; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        self.review_btn.clicked.connect(self._start_review)
        header_row.addWidget(self.review_btn)
        layout.addLayout(header_row)

        # Visible "nothing to study" state (#59 AC) — a disabled
        # button's tooltip alone is too easy to miss.
        self.due_hint = QLabel()
        self.due_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.due_hint.setStyleSheet("color: #e67e22; font-size: 15px;")
        self.due_hint.hide()
        layout.addWidget(self.due_hint)

        self.empty_label = QLabel(
            "No flashcards yet.\n\n"
            "Select text in the Extract Editor and choose\n"
            "“🃏 Make flashcard…” to create one."
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #888; font-size: 16px;")
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["Question", "Source", "Created", "Next due"]
        )
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setStyleSheet(
            """
            QTableWidget {
                background-color: #2b2b2b;
                color: #ecf0f1;
                border: none;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                gridline-color: #3d566e;
            }
            QHeaderView::section {
                background-color: #34495e;
                color: #ecf0f1;
                border: none;
                padding: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            """
        )
        layout.addWidget(self.table)

        self.setLayout(layout)
        self.refresh()

    def _due_cards(self, conn):
        if conn is None:
            return []
        return list_due_cards(conn, end_of_local_day_utc())

    def _start_review(self):
        conn = self._db_conn()
        queue = self._due_cards(conn)
        if conn is None or not queue:
            # Nothing due: the hint already says so; never open an
            # empty session (#59 AC).
            return
        dialog = ReviewSessionDialog(queue, conn, parent=self)
        dialog.exec()
        # Grades changed next-due — the list must reflect them.
        self.refresh()

    def refresh(self):
        """Reload every card, newest-first (the store's order); update
        the Review button's due-today count (#58 US26) and the empty-
        day hint (#59)."""
        conn = self._db_conn()
        cards = list_flashcards(conn) if conn is not None else []

        due = self._due_cards(conn)
        self.review_btn.setText(f"▶ Review ({len(due)})")
        self.review_btn.setEnabled(bool(due))
        self.review_btn.setToolTip(
            "No cards due today" if not due else ""
        )

        if not cards:
            self.table.setRowCount(0)
            self.table.hide()
            self.empty_label.show()
            self.due_hint.hide()
            return
        self.empty_label.hide()
        self.table.show()
        if due:
            self.due_hint.hide()
        else:
            self.due_hint.setText("No cards due today")
            self.due_hint.show()
        self.table.setRowCount(len(cards))
        for row, card in enumerate(cards):
            items = [
                card.question or "(no question)",
                _source_label(card),
                _format_created(card.created_at),
                _format_due(card.due_utc),
            ]
            for col, value in enumerate(items):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
