"""
Flashcards View — the card list (#54/#55).

One row per card: question, source document, created, next due — read
from the headless store (`services.extract_store.list_flashcards`). The
review session (start button, due filtering, grading) lands with the
FSRS core (#58/#61).
"""
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
)
from PyQt6.QtCore import Qt

from services.extract_store import display_title, list_flashcards


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
    available, cleaned filename otherwise; removed sources marked."""
    if not card.source_path and not card.source_name:
        return "(source removed)"
    if not card.source_path:
        return card.source_name
    return display_title(card.source_path, card.source_name or "")


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

        header = QLabel("🃏 Flashcards")
        header.setStyleSheet("font-size: 28px; font-weight: bold; color: #3498db;")
        layout.addWidget(header)

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

    def refresh(self):
        """Reload every card, newest-first (the store's order)."""
        conn = self._db_conn()
        cards = list_flashcards(conn) if conn is not None else []

        if not cards:
            self.table.setRowCount(0)
            self.table.hide()
            self.empty_label.show()
            return
        self.empty_label.hide()
        self.table.show()
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
