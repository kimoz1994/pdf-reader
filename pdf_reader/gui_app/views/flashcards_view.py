"""
Flashcards View — the card list + FSRS review session (#54/#55/#58/#59/#60/#61/#62).

One row per card: question, source document, created, next due — read
from the headless store (`services.extract_store.list_flashcards`). The
Review (n) button starts a session over today's set (new + due at any
point during the local day): a shuffled queue, question first, Space
(or click) reveals the read-only answer, keys 1-4 grade it through the
pinned FSRS scheduler and persist the new due date (#58). Session
completion (#59): the total is fixed at start, Again cards re-queue
within it and come back before the end, finishing shows an end-of-
session summary, and an empty day shows a "No cards due today" hint
instead of a session. Row actions (#60): a row's question is corrected
in place (F2 / ✏️ Edit question — the schedule is untouched) and a card
is deleted behind a confirmation (Del / 🗑 Delete — its images and
review logs go with it, the source Extract stays). Due-today filter
(#61): the 📅 Due today toggle switches the table between every card and
exactly the Review session's set (the same
`list_due_cards(conn, end_of_local_day_utc())` cutoff — overdue,
later-today and new cards in, tomorrow out), so the rows you see are
always the rows a session would grade. Source jump (#62): a live
Source cell reads as a link and clicking it opens the source Extract
in the Extract Editor (via the Extracts View's navigation path); after
the Extract or the Document is deleted the card survives with a
'⚠ source gone' / '⚠ removed source' marker and the jump is hidden.
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
    QLineEdit,
    QTextEdit,
    QDialog,
    QLineEdit,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QColor, QKeySequence

from services.extract_store import (
    delete_flashcard,
    display_title,
    get_flashcard_images,
    list_due_cards,
    list_flashcards,
    record_review,
    study_stats,
    update_flashcard_question,
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
    marks it — `(source removed)` only when no snapshot exists.

    A deleted source Extract gets its own marker, 'source gone' (#62):
    the document row may still be alive (its title keeps showing), but
    the card's jump target is gone. Removed *documents* keep #70's
    '⚠ removed source' marker."""
    if card.extract_id is not None and not card.extract_exists:
        # Same naming as the live label (cleaned title), marker on top.
        base = (
            display_title(card.source_path, card.source_name or "")
            if card.source_path
            else card.source_name
        )
        if base:
            return f"{base} ⚠ source gone"
        return "(source gone)"
    if not card.source_path and not card.source_name:
        return "(source removed)"
    if not card.source_path:
        return f"{card.source_name} ⚠ removed source"
    return display_title(card.source_path, card.source_name or "")


def _jump_target(card):
    """(#62) The Source cell's click payload for the row: the Extract
    the jump should open, or None when there is nothing to jump to.

    A jump needs a live Extract AND a live Document row — after either
    is deleted the affordance is hidden (the card itself survives,
    no cascade). The dict shape mirrors the Extracts tree's UserRole
    payload so the navigation path is the same."""
    if not card.extract_exists or card.extract_id is None:
        return None
    if not card.source_path or card.doc_id is None:
        return None
    return {"extract_id": card.extract_id, "doc_id": card.doc_id}


class ReviewSessionDialog(QDialog):
    """The FSRS review session (#58/#59): question → reveal → grade.

    A shuffled queue fixed at session start (the caller passes today's
    due set); Space or a click reveals the read-only answer (text +
    card-owned images via the shared renderer); keys 1-4 (or the grade
    buttons) advance the card through the scheduler and persist via
    `record_review`. A card graded **Again** re-queues at the end of
    the queue — within the session total fixed at start, so the "n of
    m" denominator never grows — and is shown again before the session
    ends (at most once per card, so the session always terminates); the
    progress label marks that re-show with "· again" so a frozen
    "m of m" doesn't read as done, and each grade writes its new FSRS
    state back onto the queued card so the re-show is graded from the
    Again-updated state, not the session-start snapshot.
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
        # never pushes the numerator past it (#59). A card coming back
        # is marked, so "m of m" doesn't read as "already done".
        shown = min(self._index + 1, self._total)
        text = f"{shown} of {self._total}"
        if card.id in self._graded_ids:
            text += " · again"
        self.progress_label.setText(text)
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
        # Write the new state back onto the queue entry: the same
        # object is what gets re-queued, so a card shown again is
        # graded from its Again-updated state, not the session-start
        # snapshot (otherwise the first grade's stability update would
        # be silently discarded).
        card.fsrs_json = fsrs_json
        card.due_utc = due
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


class _EditQuestionDialog(QDialog):
    """Modal question-correction dialog (#60): the current question
    prefilled in one line, Save / Cancel; Save dies on an empty field
    and Enter saves when there is one — the same gate and keyboard flow
    as the Make-flashcard dialog (#55). The answer and the schedule are
    not shown or touched here: only the question is ever written."""

    def __init__(self, question, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Question")
        self.setModal(True)
        self.resize(420, 140)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Question:"))
        self.question_edit = QLineEdit(question)
        layout.addWidget(self.question_edit)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.setEnabled(bool(question.strip()))
        self.save_btn.clicked.connect(self.accept)
        self.question_edit.textChanged.connect(
            lambda text: self.save_btn.setEnabled(bool(text.strip()))
        )
        self.question_edit.returnPressed.connect(self._submit_if_ready)
        buttons.addWidget(self.save_btn)
        layout.addLayout(buttons)

    def question(self) -> str:
        return self.question_edit.text()

    def _submit_if_ready(self):
        if self.save_btn.isEnabled():
            self.accept()

    def showEvent(self, event):
        # Prefilled, so select-all lets a typo fix start typing at once.
        super().showEvent(event)
        self.question_edit.selectAll()
        self.question_edit.setFocus()


class FlashcardsView(QWidget):
    # (#62) Clicking a live Source cell: (extract_id, doc_id) — the
    # navigation path opens that Extract in the Extract Editor.
    source_jump_requested = pyqtSignal(int, int)

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
        # Live search (#110): narrows the list by question / source name.
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("🔍 Search cards…")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.setMaximumWidth(240)
        self.filter_input.textChanged.connect(self._on_filter_changed)
        header_row.addWidget(self.filter_input)
        # Due-today filter (#61): unchecked = All, checked = exactly
        # the Review session's set. The button's check state is the
        # single source of truth — refresh() reads it, no shadow flag.
        self.due_toggle = QPushButton("📅 Due today")
        self.due_toggle.setCheckable(True)
        self.due_toggle.setStyleSheet(
            "QPushButton { background-color: #34495e; color: #ecf0f1;"
            " border: none; border-radius: 6px; padding: 8px 14px;"
            " font-size: 14px; }"
            "QPushButton:hover { background-color: #3d566e; }"
            "QPushButton:checked { background-color: #e67e22;"
            " font-weight: bold; }"
        )
        self.due_toggle.setToolTip(
            "Show only the cards a Review session would grade today"
        )
        self.due_toggle.toggled.connect(self._toggle_due_today)
        header_row.addWidget(self.due_toggle)
        # Row actions (#60): armed only while a row is selected.
        self.edit_btn = QPushButton("✏️ Edit question")
        self.edit_btn.setStyleSheet(
            "QPushButton { background-color: #3498db; color: white;"
            " border: none; border-radius: 6px; padding: 8px 14px;"
            " font-size: 14px; }"
            "QPushButton:hover { background-color: #2980b9; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        self.edit_btn.clicked.connect(self._edit_selected)
        header_row.addWidget(self.edit_btn)
        self.delete_btn = QPushButton("🗑 Delete")
        self.delete_btn.setStyleSheet(
            "QPushButton { background-color: #e74c3c; color: white;"
            " border: none; border-radius: 6px; padding: 8px 14px;"
            " font-size: 14px; }"
            "QPushButton:hover { background-color: #c0392b; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        self.delete_btn.clicked.connect(self._delete_selected)
        header_row.addWidget(self.delete_btn)
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

        # Study stats (#111): a quiet strip under the header — reviews
        # today, total cards, due tomorrow / next 7 days, and the
        # consecutive-day streak. Refreshed with the list.
        self.stats_label = QLabel()
        self.stats_label.setStyleSheet("color: #95a5a6; font-size: 13px;")
        self.stats_label.hide()
        layout.addWidget(self.stats_label)

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
        self.table.setSortingEnabled(True)  # #110: click a header to sort
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

        # Row actions (#60): the card id rides on the question cell; the
        # buttons and the context-menu actions share the same handlers.
        # Shortcuts live on the QActions (F2 edit, Del delete — the
        # library's Del precedent) with widget scope, so they fire only
        # while the table (or a child) has focus and the combos print
        # beside the labels in the right-click menu — the app has no
        # menu bar, so that menu is the matching menu (#57's pattern).
        self.table.itemSelectionChanged.connect(self._sync_row_actions)
        # Source jump (#62): the Source cell is a link only when its
        # Extract + Document still exist — see _jump_target.
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.edit_action = QAction("✏️ Edit question…", self)
        self.edit_action.setShortcut(QKeySequence(Qt.Key.Key_F2))
        self.edit_action.setShortcutContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.edit_action.triggered.connect(self._edit_selected)
        self.delete_action = QAction("🗑 Delete", self)
        self.delete_action.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        self.delete_action.setShortcutContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.delete_action.triggered.connect(self._delete_selected)
        self.table.addActions([self.edit_action, self.delete_action])
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)

        self.setLayout(layout)
        self.refresh()

    def _due_cards(self, conn):
        if conn is None:
            return []
        return list_due_cards(conn, end_of_local_day_utc())

    def _refresh_stats(self, conn):
        """(#111) Fill the stats strip from `study_stats`; hide it when
        there's nothing to report (empty library / no conn)."""
        if conn is None:
            self.stats_label.hide()
            return
        s = study_stats(conn)
        if s["total_cards"] == 0 and s["reviews_today"] == 0 and s["streak"] == 0:
            self.stats_label.hide()
            return
        parts = [
            f"📚 {s['total_cards']} cards",
            f"✅ {s['reviews_today']} reviewed today",
            f"📅 {s['due_tomorrow']} due tomorrow",
            f"🗓 {s['due_next_7_days']} due in 7 days",
        ]
        if s["streak"] > 0:
            parts.append(f"🔥 {s['streak']}-day streak")
        self.stats_label.setText("  ·  ".join(parts))
        self.stats_label.show()

    def _toggle_due_today(self, _checked):
        """(#61) The filter button flipped — reload the list. The
        Review button count and the empty-day hint are filter-
        independent and get recomputed by refresh() anyway."""
        self.refresh()

    def _on_filter_changed(self, _text):
        """(#110) Search box changed — re-run refresh so the row set
        tracks the text (and still respects the Due-today toggle)."""
        self.refresh()

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
        """Reload the card list — every card, or just the Review
        session's set when the 📅 Due today filter is on (#61) — and
        update the Review button's due-today count (#58 US26), the
        empty-day hint (#59) and the row-action buttons (#60, dead
        without a selection)."""
        conn = self._db_conn()
        cards = list_flashcards(conn) if conn is not None else []

        due = self._due_cards(conn)
        self.review_btn.setText(f"▶ Review ({len(due)})")
        self.review_btn.setEnabled(bool(due))
        self.review_btn.setToolTip(
            "No cards due today" if not due else ""
        )
        self._refresh_stats(conn)

        if not cards:
            self._hide_table()
            self.empty_label.setText(
                "No flashcards yet.\n\n"
                "Select text in the Extract Editor and choose\n"
                "“🃏 Make flashcard…” to create one."
            )
            self.empty_label.show()
            self.due_hint.hide()
            return
        self.empty_label.hide()
        if due:
            self.due_hint.hide()
        else:
            self.due_hint.setText("No cards due today")
            self.due_hint.show()

        # #61: the filter shows exactly the session's set — the same
        # `_due_cards` list the Review button counts — so a zero-due
        # day hides the table (the hint already says why) instead of
        # showing a blank box.
        visible = due if self.due_toggle.isChecked() else cards
        # #110: the search box narrows further — case-insensitive
        # substring over question + source label (which includes the
        # source document name, so both filters compose).
        needle = self.filter_input.text().strip().lower()
        if needle:
            visible = [
                c
                for c in visible
                if needle in (c.question or "").lower()
                or needle in _source_label(c).lower()
            ]
        if not visible:
            if needle and cards:
                # Search with zero hits: say so, don't show an empty
                # box (and don't claim "no cards" — they exist).
                self._hide_table()
                self.empty_label.setText(f"No cards match “{needle}”")
                self.empty_label.show()
                self.due_hint.hide()
                return
            self._hide_table()
            return
        self.empty_label.hide()
        self.table.show()
        # Sort while filling makes Qt re-sort on every setItem — turn
        # it off for the rebuild, on again after (#110).
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(visible))
        for row, card in enumerate(visible):
            items = [
                card.question or "(no question)",
                _source_label(card),
                _format_created(card.created_at),
                _format_due(card.due_utc),
            ]
            for col, value in enumerate(items):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    # The row actions need the real id, not the text.
                    item.setData(Qt.ItemDataRole.UserRole, card.id)
                elif col == 1:
                    # #62: a live source reads as a link (blue + hint)
                    # and carries its jump payload; an orphaned or
                    # removed source stays a plain cell, no payload.
                    target = _jump_target(card)
                    if target:
                        item.setData(
                            Qt.ItemDataRole.UserRole, target
                        )
                        item.setForeground(QBrush(QColor("#3498db")))
                        item.setToolTip(
                            "Click to open the source Extract"
                        )
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self._sync_row_actions()

    def _on_cell_clicked(self, row, column):
        """(#62) Source cell click -> the jump signal. Any other column
        (and any cell with no payload: deleted Extract / removed
        Document) is a plain cell — selecting the row is all it does."""
        if column != 1:
            return
        item = self.table.item(row, 1)
        target = item.data(Qt.ItemDataRole.UserRole) if item else None
        if target:
            self.source_jump_requested.emit(
                target["extract_id"], target["doc_id"]
            )

    def _hide_table(self):
        """Empty, hidden table with row actions disarmed — the shared
        teardown of refresh()'s two empty states (no cards at all, or
        the Due-today filter on with none due, #61)."""
        self.table.setRowCount(0)
        self.table.hide()
        self._sync_row_actions()

    # ------------------------------------------------------------
    # Row actions (#60): edit question / delete card
    # ------------------------------------------------------------

    def _selected_row(self):
        """The selected row index, or None. Driven by the selection
        model, not the current item — clearSelection() keeps a current
        row, and a row you can't see must not stay armed (#60)."""
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _selected_card_id(self):
        """The id of the selected row's card, or None (nothing
        selected / empty table)."""
        row = self._selected_row()
        if row is None:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _sync_row_actions(self):
        """Arm the edit/delete buttons and context-menu actions only
        while a row is selected."""
        enabled = self._selected_card_id() is not None
        self.edit_btn.setEnabled(enabled)
        self.delete_btn.setEnabled(enabled)
        self.edit_action.setEnabled(enabled)
        self.delete_action.setEnabled(enabled)

    def _selection(self):
        """(conn, card_id, question) for the selected row, or None when
        there is no connection or no selection (#60)."""
        conn = self._db_conn()
        card_id = self._selected_card_id()
        if conn is None or card_id is None:
            return None
        row = self._selected_row()
        return conn, card_id, self.table.item(row, 0).text()

    def _confirm_delete(self, question: str) -> bool:
        """The delete confirmation — its own seam so tests can patch
        it (the library view's `_confirm_removal` pattern)."""
        box = QMessageBox(
            QMessageBox.Icon.Question,
            "Delete Flashcard",
            f"Delete this flashcard?\n\n{question}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self,
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setInformativeText(
            "Only this card is removed — its images and review history "
            "go with it. The source Extract stays."
        )
        return box.exec() == QMessageBox.StandardButton.Yes

    def _prompt_question(self, current: str):
        """Open the edit dialog on `current`; None = cancelled — a
        seam so tests never open a real dialog (#60)."""
        dialog = _EditQuestionDialog(current, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.question()

    def _delete_selected(self, _checked=False):
        """Delete the selected card behind a confirmation, then reload
        the list (#60). Inert with nothing selected — the buttons are
        disabled, but a direct call must guard too."""
        selection = self._selection()
        if selection is None:
            return
        conn, card_id, question = selection
        if not self._confirm_delete(question):
            return
        delete_flashcard(conn, card_id)
        self.refresh()

    def _edit_selected(self, _checked=False):
        """Correct the selected card's question; the schedule is never
        touched (`update_flashcard_question` writes the question alone),
        then the list reloads (#60)."""
        selection = self._selection()
        if selection is None:
            return
        conn, card_id, current = selection
        question = self._prompt_question(current)
        if question is None:
            return
        update_flashcard_question(conn, card_id, question)
        self.refresh()
