import sys
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QFrame,
    QDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)
from PyQt6.QtCore import Qt, QPointF, QTimer, pyqtSignal, QRectF
from PyQt6.QtGui import QKeyEvent, QPainter, QColor, QPen, QBrush
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView

import pymupdf  # instead of fitz


parent_dir = Path(__file__).parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumSize(600, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("📖 Keyboard Shortcuts")
        title.setStyleSheet(
            "font-size:18px;font-weight:bold;color:#3498db;"
        )
        layout.addWidget(title)

        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(
            ["Key", "Action", "Description"]
        )
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )

        shortcuts = [
            ("j / ↓", "Navigation", "Scroll down"),
            ("k / ↑", "Navigation", "Scroll up"),
            ("n", "Search", "Next match"),
            ("N", "Search", "Previous match"),
            ("g g", "Navigation", "Go to top"),
            ("G", "Navigation", "Go to bottom"),
            ("Space", "Navigation", "Page down"),
            ("Backspace", "Navigation", "Page up"),
            ("+ / =", "Zoom", "Zoom in"),
            ("-", "Zoom", "Zoom out"),
            ("/", "Search", "Open search bar"),
            ("Enter", "Search", "Jump to next match"),
            ("Esc", "Search", "Close search"),
            ("h", "Hints", "Enter hint mode"),
            ("?", "Help", "Show this dialog"),
        ]

        table.setRowCount(len(shortcuts))
        for r, row in enumerate(shortcuts):
            for c, value in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(value))

        table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        layout.addWidget(table)

        close_btn = QPushButton("Close (Esc)")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)


class SearchBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        icon = QLabel("🔍")
        layout.addWidget(icon)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search…")
        layout.addWidget(self.search_input)

        self.match_label = QLabel("")
        layout.addWidget(self.match_label)

        self.setStyleSheet(
            """
            QFrame {
                background-color:#2c3e50;
                border-radius:8px;
            }
            QLineEdit {
                background-color:#34495e;
                color:#ecf0f1;
                border:none;
                padding:5px;
            }
            QLabel {
                color:#95a5a6;
                font-size:12px;
            }
            """
        )

    def text(self):
        return self.search_input.text()

    def clear(self):
        self.search_input.clear()
        self.match_label.clear()

    def set_match_count(self, count, current=0):
        if count:
            self.match_label.setText(
                f"{current}/{count} matches"
            )
        else:
            self.match_label.setText("No matches")


class SearchHighlightOverlay(QWidget):
    """Overlay widget to draw search match highlights on top of QPdfView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.current_rect = None  # in widget coordinates (QRectF)

    def set_current_rect(self, rect: QRectF | None):
        self.current_rect = rect
        self.update()

    def paintEvent(self, event):
        if not self.current_rect:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pen = QPen(QColor(255, 255, 0), 3)
        brush = QBrush(QColor(255, 255, 0, 80))
        painter.setPen(pen)
        painter.setBrush(brush)

        painter.drawRect(self.current_rect)


class PDFReaderView(QWidget):
    back_requested = pyqtSignal()
    progress_changed = pyqtSignal(str, int)
    hint_mode_requested = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.current_pdf = None
        self.doc = None  # QPdfDocument
        self.last_visible_page = 0

        self.search_mode = False
        self.current_result_index = -1
        self.search_matches = []  # list of (page_index, rect_pymupdf)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(
            self.update_pdf_search
        )

        self.last_g_time = 0.0

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 5, 10, 5)

        self.back_btn = QPushButton("◀ Back")
        self.back_btn.setFixedHeight(35)
        self.back_btn.clicked.connect(self.go_back)
        toolbar.addWidget(self.back_btn)

        self.zoom_out_btn = QPushButton("🔍 -")
        self.zoom_out_btn.setFixedHeight(35)
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        toolbar.addWidget(self.zoom_out_btn)

        self.zoom_label = QLabel("Zoom: Fit")
        self.zoom_label.setStyleSheet(
            "color:white;font-size:14px;"
        )
        toolbar.addWidget(self.zoom_label)

        self.zoom_in_btn = QPushButton("🔍 +")
        self.zoom_in_btn.setFixedHeight(35)
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        toolbar.addWidget(self.zoom_in_btn)

        self.prev_btn = QPushButton("◀ Prev")
        self.prev_btn.setFixedHeight(35)
        self.prev_btn.clicked.connect(self.prev_page)
        self.prev_btn.setEnabled(False)
        toolbar.addWidget(self.prev_btn)

        self.page_label = QLabel("Page: -")
        self.page_label.setStyleSheet(
            "color:white;font-size:14px;"
        )
        toolbar.addWidget(self.page_label)

        self.next_btn = QPushButton("Next ▶")
        self.next_btn.setFixedHeight(35)
        self.next_btn.clicked.connect(self.next_page)
        self.next_btn.setEnabled(False)
        toolbar.addWidget(self.next_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.search_bar = SearchBar(self)
        self.search_bar.hide()
        self.search_bar.search_input.returnPressed.connect(
            self.on_search_enter
        )
        self.search_bar.search_input.textChanged.connect(
            self.on_search_text_changed
        )
        layout.addWidget(self.search_bar)

        # Stack: pdf_view + overlay
        self.pdf_view = QPdfView(self)
        self.pdf_view.setStyleSheet(
            "background-color:#2b2b2b;border:none;"
        )
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        try:
            self.pdf_view.setPageSpacing(12)
        except Exception:
            pass

        layout.addWidget(self.pdf_view)

        # Overlay for highlights
        self.highlight_overlay = SearchHighlightOverlay(self)
        self.highlight_overlay.setGeometry(self.pdf_view.geometry())
        self.highlight_overlay.show()

        self.setLayout(layout)

        self.pdf_view.pageNavigator().currentPageChanged.connect(
            self.on_page_changed
        )

        self.pdf_view.verticalScrollBar().valueChanged.connect(
            self.on_scroll
        )

        self.pdf_view.installEventFilter(self)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.Resize and obj is self.pdf_view:
            self.highlight_overlay.setGeometry(self.pdf_view.geometry())
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------
    # PDF loading with saved progress
    # ------------------------------------------------------------

    def load_pdf(self, pdf_path: str):
        # Clear existing document
        if self.pdf_view:
            self.pdf_view.setDocument(None)

        if self.doc is not None:
            self.doc.close()
            self.doc = None

        self.current_pdf = pdf_path
        self.last_visible_page = 0
        saved_page = 0
        self.search_matches = []
        self.current_result_index = -1
        self.search_bar.set_match_count(0)
        self.highlight_overlay.set_current_rect(None)

        try:
            main_window = self.window()
            if hasattr(main_window, "library_view"):
                library_view = main_window.library_view
                library_view.cursor.execute(
                    "SELECT current_page FROM pdfs WHERE path = ?",
                    (pdf_path,),
                )
                row = library_view.cursor.fetchone()
                if row and row[0]:
                    saved_page = max(0, int(row[0]) - 1)
        except Exception as e:
            print(f"Error restoring saved page: {e}")
            saved_page = 0

        self.doc = QPdfDocument(self)
        self.doc.load(pdf_path)
        count = self.doc.pageCount()
        if count <= 0:
            print(f"Could not load PDF: {pdf_path}")
            self.doc = None
            return

        saved_page = min(saved_page, count - 1)

        self.pdf_view.setDocument(self.doc)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.zoom_label.setText("Zoom: Fit")

        # Jump to saved page
        self.pdf_view.pageNavigator().jump(
            saved_page, QPointF(0.0, 0.0), 0.0
        )

        self.last_visible_page = saved_page
        self.page_label.setText(
            f"Page: {saved_page + 1}/{count}"
        )
        self.prev_btn.setEnabled(saved_page > 0)
        self.next_btn.setEnabled(saved_page < count - 1)

        if self.current_pdf:
            self.progress_changed.emit(
                self.current_pdf, saved_page + 1
            )

        self.setFocus()

    # ------------------------------------------------------------
    # Scroll / page change
    # ------------------------------------------------------------

    def on_page_changed(self, page_index: int):
        if not self.doc:
            return

        self.last_visible_page = page_index
        count = self.doc.pageCount()
        self.page_label.setText(
            f"Page: {page_index + 1}/{count}"
        )
        self.prev_btn.setEnabled(page_index > 0)
        self.next_btn.setEnabled(page_index < count - 1)

        if self.current_pdf:
            self.progress_changed.emit(
                self.current_pdf, page_index + 1
            )

            try:
                main_window = self.window()
                if hasattr(main_window, "library_view"):
                    library_view = main_window.library_view
                    library_view.cursor.execute(
                        "UPDATE pdfs SET current_page = ?, last_opened = CURRENT_TIMESTAMP WHERE path = ?",
                        (page_index + 1, self.current_pdf),
                    )
                    library_view.conn.commit()
            except Exception as e:
                print(f"Error saving page to DB: {e}")

    def on_scroll(self, value: int):
        pass

    # ------------------------------------------------------------
    # Keyboard navigation
    # ------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        modifiers = event.modifiers()
        now = time.time()

        # Hint mode trigger
        if key == Qt.Key.Key_H and modifiers == Qt.KeyboardModifier.NoModifier:
            self.hint_mode_requested.emit()
            event.accept()
            return

        # Search bar visible: handle search-specific keys, but allow navigation
        if self.search_bar.isVisible():
            if key == Qt.Key.Key_Escape:
                self.close_search()
                event.accept()
                return

            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                # Confirm search and move focus to viewer
                self.confirm_search_and_focus_viewer()
                event.accept()
                return

            if (
                key == Qt.Key.Key_N
                and modifiers
                == Qt.KeyboardModifier.ShiftModifier
            ):
                self.prev_search_result()
                event.accept()
                return

            if (
                key == Qt.Key.Key_N
                and modifiers
                == Qt.KeyboardModifier.NoModifier
            ):
                self.next_search_result()
                event.accept()
                return

            # Allow navigation keys even when search bar is visible
            if key in (Qt.Key.Key_J, Qt.Key.Key_Down):
                bar = self.pdf_view.verticalScrollBar()
                bar.setValue(bar.value() + 120)
                event.accept()
                return

            if key in (Qt.Key.Key_K, Qt.Key.Key_Up):
                bar = self.pdf_view.verticalScrollBar()
                bar.setValue(max(0, bar.value() - 120))
                event.accept()
                return

            if key == Qt.Key.Key_G and modifiers == Qt.KeyboardModifier.NoModifier:
                if now - self.last_g_time < 0.5:
                    # gg → top
                    bar = self.pdf_view.verticalScrollBar()
                    bar.setValue(0)
                    event.accept()
                    self.last_g_time = 0.0
                    return
                else:
                    self.last_g_time = now
                    event.accept()
                    return

            if key == Qt.Key.Key_G and modifiers == Qt.KeyboardModifier.ShiftModifier:
                # Shift+G → bottom
                bar = self.pdf_view.verticalScrollBar()
                bar.setValue(bar.maximum())
                event.accept()
                return

            if key == Qt.Key.Key_Space:
                bar = self.pdf_view.verticalScrollBar()
                bar.setValue(
                    bar.value()
                    + self.pdf_view.viewport().height()
                )
                event.accept()
                return

            if key == Qt.Key.Key_Backspace:
                bar = self.pdf_view.verticalScrollBar()
                bar.setValue(
                    max(
                        0,
                        bar.value()
                        - self.pdf_view.viewport().height(),
                    )
                )
                event.accept()
                return

            if key in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
                self.zoom_in()
                event.accept()
                return

            if key == Qt.Key.Key_Minus:
                self.zoom_out()
                event.accept()
                return

            # For normal typing, let QLineEdit handle it
            super().keyPressEvent(event)
            return

        # Normal viewer mode (search bar not visible)
        if key == Qt.Key.Key_Question:
            HelpDialog(self).exec()
            event.accept()
            return

        if (
            key == Qt.Key.Key_Slash
            and modifiers
            == Qt.KeyboardModifier.NoModifier
        ):
            self.open_search()
            event.accept()
            return

        if key in (Qt.Key.Key_J, Qt.Key.Key_Down):
            bar = self.pdf_view.verticalScrollBar()
            bar.setValue(bar.value() + 120)
            event.accept()
            return

        if key in (Qt.Key.Key_K, Qt.Key.Key_Up):
            bar = self.pdf_view.verticalScrollBar()
            bar.setValue(max(0, bar.value() - 120))
            event.accept()
            return

        if key == Qt.Key.Key_N and modifiers == Qt.KeyboardModifier.NoModifier:
            self.next_page()
            event.accept()
            return

        if key == Qt.Key.Key_N and modifiers == Qt.KeyboardModifier.ShiftModifier:
            self.prev_page()
            event.accept()
            return

        if key == Qt.Key.Key_G and modifiers == Qt.KeyboardModifier.NoModifier:
            if now - self.last_g_time < 0.5:
                # gg → top
                bar = self.pdf_view.verticalScrollBar()
                bar.setValue(0)
                event.accept()
                self.last_g_time = 0.0
                return
            else:
                self.last_g_time = now
                event.accept()
                return

        if key == Qt.Key.Key_G and modifiers == Qt.KeyboardModifier.ShiftModifier:
            # Shift+G → bottom
            bar = self.pdf_view.verticalScrollBar()
            bar.setValue(bar.maximum())
            event.accept()
            return

        if key == Qt.Key.Key_Space:
            bar = self.pdf_view.verticalScrollBar()
            bar.setValue(
                bar.value()
                + self.pdf_view.viewport().height()
            )
            event.accept()
            return

        if key == Qt.Key.Key_Backspace:
            bar = self.pdf_view.verticalScrollBar()
            bar.setValue(
                max(
                    0,
                    bar.value()
                    - self.pdf_view.viewport().height(),
                )
            )
            event.accept()
            return

        if key in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
            self.zoom_in()
            event.accept()
            return

        if key == Qt.Key.Key_Minus:
            self.zoom_out()
            event.accept()
            return

        super().keyPressEvent(event)

    # ------------------------------------------------------------
    # Button navigation
    # ------------------------------------------------------------

    def prev_page(self):
        if self.doc and self.last_visible_page > 0:
            self.pdf_view.pageNavigator().jump(
                self.last_visible_page - 1,
                QPointF(0.0, 0.0),
                0.0,
            )

    def next_page(self):
        if not self.doc:
            return
        last_page = self.doc.pageCount() - 1
        if self.last_visible_page < last_page:
            self.pdf_view.pageNavigator().jump(
                self.last_visible_page + 1,
                QPointF(0.0, 0.0),
                0.0,
            )

    # ------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------

    def zoom_in(self):
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        current = self.pdf_view.zoomFactor()
        new = min(5.0, current + 0.25)
        self.pdf_view.setZoomFactor(new)
        self.zoom_label.setText(
            f"Zoom: {int(new * 100)}%"
        )

    def zoom_out(self):
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        current = self.pdf_view.zoomFactor()
        new = max(0.25, current - 0.25)
        self.pdf_view.setZoomFactor(new)
        self.zoom_label.setText(
            f"Zoom: {int(new * 100)}%"
        )

    # ------------------------------------------------------------
    # Search (PyMuPDF-based) with highlight
    # ------------------------------------------------------------

    def open_search(self):
        self.search_bar.show()
        self.search_bar.search_input.setFocus()
        self.search_bar.search_input.selectAll()

    def close_search(self):
        self.search_timer.stop()
        self.search_bar.hide()
        self.search_bar.clear()
        self.search_matches = []
        self.current_result_index = -1
        self.search_bar.set_match_count(0)
        self.highlight_overlay.set_current_rect(None)
        self.setFocus()

    def confirm_search_and_focus_viewer(self):
        text = self.search_bar.text().strip()
        if not text:
            self.close_search()
            return
        # Ensure search is run
        if not self.search_matches:
            self.update_pdf_search()
        # Move focus to viewer so n/N and navigation keys work
        self.setFocus()

    def on_search_text_changed(self, text: str):
        self.search_timer.stop()
        if not text.strip():
            self.search_matches = []
            self.current_result_index = -1
            self.search_bar.set_match_count(0)
            self.highlight_overlay.set_current_rect(None)
            return
        self.search_timer.start()

    def update_pdf_search(self):
        text = self.search_bar.text().strip()
        if not text or not self.current_pdf:
            self.search_matches = []
            self.current_result_index = -1
            self.search_bar.set_match_count(0)
            self.highlight_overlay.set_current_rect(None)
            return

        # Search using PyMuPDF
        self.search_matches = []
        try:
            mupdf_doc = pymupdf.open(self.current_pdf)
            for page_index in range(len(mupdf_doc)):
                page = mupdf_doc[page_index]
                rects = page.search_for(text)
                for rect in rects:
                    # rect is (x0, y0, x1, y1) in page coordinates
                    self.search_matches.append((page_index, rect))
            mupdf_doc.close()
        except Exception as e:
            print(f"Search error: {e}")
            self.search_matches = []

        self.current_result_index = -1
        if self.search_matches:
            self.current_result_index = 0
            self.search_bar.set_match_count(
                len(self.search_matches), 1
            )
            self.go_to_search_result(0)
        else:
            self.search_bar.set_match_count(0)
            self.highlight_overlay.set_current_rect(None)

    def on_search_enter(self):
        # Handled in keyPressEvent
        pass

    def next_search_result(self):
        if not self.search_matches:
            return
        self.current_result_index = (
            self.current_result_index + 1
        ) % len(self.search_matches)
        self.search_bar.set_match_count(
            len(self.search_matches),
            self.current_result_index + 1,
        )
        self.go_to_search_result(self.current_result_index)

    def prev_search_result(self):
        if not self.search_matches:
            return
        self.current_result_index = (
            self.current_result_index - 1
        ) % len(self.search_matches)
        self.search_bar.set_match_count(
            len(self.search_matches),
            self.current_result_index + 1,
        )
        self.go_to_search_result(self.current_result_index)

    def go_to_search_result(self, index: int):
        if not self.search_matches:
            return
        if not 0 <= index < len(self.search_matches):
            return

        page_index, rect_mupdf = self.search_matches[index]

        # Jump to that page
        self.pdf_view.pageNavigator().jump(
            page_index, QPointF(0.0, 0.0), 0.0
        )

        # Compute and set highlight rectangle in widget coordinates
        self.update_highlight_rect(page_index, rect_mupdf)

    def update_highlight_rect(self, page_index: int, rect_mupdf):
        # Simplified highlight: for now, just clear it to avoid errors.
        # We can re-enable precise highlighting in the hint-system iteration.
        self.highlight_overlay.set_current_rect(None)

    # ------------------------------------------------------------
    # Misc / back
    # ------------------------------------------------------------

    def closeEvent(self, event):
        if self.pdf_view:
            self.pdf_view.setDocument(None)
        if self.doc is not None:
            self.doc.close()
            self.doc = None
        event.accept()

    def go_back(self):
        if self.current_pdf:
            self.progress_changed.emit(
                self.current_pdf,
                self.last_visible_page + 1,
            )
        self.back_requested.emit()