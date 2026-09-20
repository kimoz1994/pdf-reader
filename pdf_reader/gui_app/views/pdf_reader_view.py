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
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QKeyEvent,
    QPainter,
    QColor,
    QPen,
    QBrush,
    QGuiApplication,
)
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView

import pymupdf  # instead of fitz

from services.extract_store import (
    Capture,
    commit_working_set as store_commit_working_set,
    init_schema,
    list_extracts_for_doc,
    resolve_doc_id,
)
from services.pdf_geometry import (
    CUSTOM,
    FIT_TO_WIDTH,
    PageLayout,
    clip_widget_rect_to_page,
)


parent_dir = Path(__file__).parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))


def rect_to_qrectf(rect: tuple[float, float, float, float]) -> QRectF:
    """Build a QRectF from an (x0, y0, x1, y1) tuple (QRectF wants w/h)."""
    x0, y0, x1, y1 = rect
    return QRectF(x0, y0, x1 - x0, y1 - y0)


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
            ("e", "Extract", "Commit the Working Set as one Extract"),
            ("Esc", "Extract", "Clear the Working Set (yellow highlights)"),
            ("Drag mouse", "Extract", "Select text into the Working Set"),
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
    """Overlay widget to draw highlights on top of QPdfView.

    Draws any of:
      - yellow working-set rectangles (transient pre-extract selection)
      - blue extract rectangles (persisted from the DB)
      - the current search result rect (yellow)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.current_rect = None  # in widget coordinates (QRectF)
        self.working_rects = []  # in widget coordinates (QRectF)
        self.extract_rects = []  # in widget coordinates (QRectF)

    def set_current_rect(self, rect: QRectF | None):
        self.current_rect = rect
        self.update()

    def set_working_rects(self, rects: list[QRectF]):
        self.working_rects = rects
        self.update()

    def set_extract_rects(self, rects: list[QRectF]):
        self.extract_rects = rects
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Persisted extracts: blue, underneath
        if self.extract_rects:
            pen = QPen(QColor(52, 152, 219), 3)
            brush = QBrush(QColor(52, 152, 219, 80))
            painter.setPen(pen)
            painter.setBrush(brush)
            for rect in self.extract_rects:
                painter.drawRect(rect)

        # Working set: yellow, on top of the blue extracts
        if self.working_rects:
            pen = QPen(QColor(255, 255, 0), 3)
            brush = QBrush(QColor(255, 255, 0, 80))
            painter.setPen(pen)
            painter.setBrush(brush)
            for rect in self.working_rects:
                painter.drawRect(rect)

        if self.current_rect:
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
        self._schema_initialized = False

        # Extract workflow state
        self.working_set = []  # list[Capture], the in-memory yellow set
        self.extract_captures = []  # list[Capture], blue re-draws from DB
        self.drag_start = None  # QPointF widget coords while selecting
        self.drag_current = None

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

        self.working_label = QLabel("")
        self.working_label.setStyleSheet(
            "color:#f1c40f;font-size:13px;font-weight:bold;"
        )
        toolbar.addWidget(self.working_label)

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
        self.pdf_view.horizontalScrollBar().valueChanged.connect(
            self.on_scroll
        )

        self.pdf_view.installEventFilter(self)
        self.pdf_view.viewport().installEventFilter(self)
        # Text-selection cursor over the pages, matching the drag-to-select
        # behaviour wired up in eventFilter.
        self.pdf_view.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.Resize and obj is self.pdf_view:
            self.highlight_overlay.setGeometry(self.pdf_view.geometry())
            self._refresh_highlights()

        if obj is self.pdf_view.viewport():
            offset = QPointF(self.pdf_view.viewport().pos())
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.drag_start = event.position() + offset
                    self.drag_current = event.position() + offset
                return False
            if event.type() == QEvent.Type.MouseMove and self.drag_start is not None:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    self.drag_current = event.position() + offset
                    self.update_selection_preview()
                return False
            if event.type() == QEvent.Type.MouseButtonRelease and self.drag_start is not None:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.drag_current = event.position() + offset
                    self.add_drag_selection()
                return False

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

        # Reset extraction workflow state for the new document
        self._reset_extract_state()

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

        # Re-draw persisted extracts (blue) for this document
        self._load_extracts_from_db()
        self._refresh_highlights()

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
        self._refresh_highlights()

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
            key == Qt.Key.Key_E
            and modifiers == Qt.KeyboardModifier.NoModifier
        ):
            self.commit_working_set()
            event.accept()
            return

        if (
            key == Qt.Key.Key_Escape
            and modifiers == Qt.KeyboardModifier.NoModifier
        ):
            if self.working_set:
                self.clear_working_set()
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
        self._refresh_highlights()

    def zoom_out(self):
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        current = self.pdf_view.zoomFactor()
        new = max(0.25, current - 0.25)
        self.pdf_view.setZoomFactor(new)
        self.zoom_label.setText(
            f"Zoom: {int(new * 100)}%"
        )
        self._refresh_highlights()

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
    # Extraction workflow (Working Set -> Extract)
    # ------------------------------------------------------------

    def _reset_extract_state(self):
        """Drop transient extraction state (working set, drag, label, overlay)."""
        self.working_set = []
        self.extract_captures = []
        self.drag_start = None
        self.drag_current = None
        self.working_label.setText("")
        self.highlight_overlay.set_working_rects([])
        self.highlight_overlay.set_extract_rects([])

    def _db_conn(self):
        """The sqlite3 connection the library view keeps open, or None."""
        main_window = self.window()
        if hasattr(main_window, "library_view"):
            conn = main_window.library_view.conn
            if not self._schema_initialized:
                init_schema(conn)
                self._schema_initialized = True
            return conn
        return None

    def _current_doc_id(self):
        conn = self._db_conn()
        if conn is None or not self.current_pdf:
            return None
        return resolve_doc_id(conn, self.current_pdf)

    def _current_layout(self):
        """Build a PageLayout describing the current view state, or None."""
        if self.doc is None:
            return None
        count = self.doc.pageCount()
        if count <= 0:
            return None
        try:
            sizes = [
                (
                    self.doc.pagePointSize(i).width(),
                    self.doc.pagePointSize(i).height(),
                )
                for i in range(count)
            ]
        except Exception:
            return None
        margins = self.pdf_view.documentMargins()
        vp = self.pdf_view.viewport()
        scroll = self.pdf_view.verticalScrollBar().value()
        h_scroll = self.pdf_view.horizontalScrollBar().value()
        zoom_mode = (
            FIT_TO_WIDTH
            if self.pdf_view.zoomMode() == QPdfView.ZoomMode.FitToWidth
            else CUSTOM
        )
        return PageLayout(
            page_sizes_pts=sizes,
            zoom=self.pdf_view.zoomFactor(),
            dpi=float(QGuiApplication.primaryScreen().logicalDotsPerInch()),
            margins=(margins.left(), margins.top(), margins.right(), margins.bottom()),
            spacing=self.pdf_view.pageSpacing(),
            h_scroll=h_scroll,
            v_scroll=scroll,
            viewport_width=vp.width(),
            viewport_height=vp.height(),
            zoom_mode=zoom_mode,
            viewport_offset=(vp.x(), vp.y()),
        )

    def _refresh_highlights(self, preview_widget_rect=None):
        """Recompute widget rects for working set + extracts and repaint."""
        layout = self._current_layout()
        if layout is None:
            self.highlight_overlay.set_working_rects([])
            self.highlight_overlay.set_extract_rects([])
            return
        try:
            working = [
                rect_to_qrectf(layout.pdf_to_widget(c.page, c.rect))
                for c in self.working_set
            ]
            extracts = [
                rect_to_qrectf(layout.pdf_to_widget(c.page, c.rect))
                for c in self.extract_captures
            ]
        except Exception:
            return
        if preview_widget_rect is not None:
            working.append(rect_to_qrectf(preview_widget_rect))
        self.highlight_overlay.set_working_rects(working)
        self.highlight_overlay.set_extract_rects(extracts)

        if self.working_set:
            self.working_label.setText(
                f"Working Set: {len(self.working_set)} (e to commit, Esc to clear)"
            )
        else:
            self.working_label.setText("")

    def _load_extracts_from_db(self):
        """Reload blue extract rects for the current document from the DB."""
        self.extract_captures = []
        doc_id = self._current_doc_id()
        if doc_id is None:
            return
        conn = self._db_conn()
        if conn is None:
            return
        captures = []
        for extract in list_extracts_for_doc(conn, doc_id):
            captures.extend(extract.captures)
        self.extract_captures = captures

    def commit_working_set(self):
        """Persist the Working Set as one Extract and refresh blue re-draws."""
        if not self.working_set:
            return
        conn = self._db_conn()
        doc_id = self._current_doc_id()
        if conn is None or doc_id is None:
            return
        store_commit_working_set(conn, doc_id, self.working_set)
        self.working_set = []
        self._load_extracts_from_db()
        self._refresh_highlights()

    def clear_working_set(self):
        """Drop the pending Working Set without persisting anything."""
        self.working_set = []
        self._refresh_highlights()

    def update_selection_preview(self):
        """While dragging, show a live yellow rect in widget coordinates."""
        if self.drag_start is None or self.drag_current is None:
            return
        layout = self._current_layout()
        if layout is None:
            return
        page_index = layout.widget_point_page_index(
            (self.drag_start.x(), self.drag_start.y())
        )
        if page_index is None:
            self._refresh_highlights()
            return
        drag_widget_rect = (
            min(self.drag_start.x(), self.drag_current.x()),
            min(self.drag_start.y(), self.drag_current.y()),
            max(self.drag_start.x(), self.drag_current.x()),
            max(self.drag_start.y(), self.drag_current.y()),
        )
        clipped = clip_widget_rect_to_page(
            drag_widget_rect, layout.page_rect_widget(page_index)
        )
        if clipped[0] == 0 and clipped[1] == 0 and clipped[2] == 0 and clipped[3] == 0:
            self._refresh_highlights()
            return
        self._refresh_highlights(preview_widget_rect=clipped)

    def _capture_overlaps_extract(self, page_index: int, rect):
        """True if a new capture rect would re-highlight an existing extract."""
        x0, y0, x1, y1 = rect
        for cap in self.extract_captures:
            if cap.page != page_index:
                continue
            cx0, cy0, cx1, cy1 = cap.rect
            if x0 < cx1 and cx0 < x1 and y0 < cy1 and cy0 < y1:
                return True
        return False

    def add_drag_selection(self):
        """Turn the finished drag into a text Capture added to the Working Set."""
        if self.drag_start is None or self.drag_current is None:
            self._refresh_highlights()
            return
        s = self.drag_start
        e = self.drag_current
        self.drag_start = None
        self.drag_current = None
        layout = self._current_layout()
        if layout is None or self.doc is None:
            self._refresh_highlights()
            return
        page_index = layout.widget_point_page_index((s.x(), s.y()))
        if page_index is None:
            self._refresh_highlights()
            return
        drag_widget_rect = (
            min(s.x(), e.x()),
            min(s.y(), e.y()),
            max(s.x(), e.x()),
            max(s.y(), e.y()),
        )
        clipped = clip_widget_rect_to_page(
            drag_widget_rect, layout.page_rect_widget(page_index)
        )
        if clipped[0] == 0 and clipped[1] == 0 and clipped[2] == 0 and clipped[3] == 0:
            self._refresh_highlights()
            return
        start_pdf = layout.widget_to_pdf(page_index, (clipped[0], clipped[1]))
        end_pdf = layout.widget_to_pdf(page_index, (clipped[2], clipped[3]))
        seq = self.doc.getSelection(
            page_index,
            QPointF(min(start_pdf[0], end_pdf[0]), min(start_pdf[1], end_pdf[1])),
            QPointF(max(start_pdf[0], end_pdf[0]), max(start_pdf[1], end_pdf[1])),
        )
        if not seq.isValid() or not seq.text().strip():
            self._refresh_highlights()
            return
        bb = seq.boundingRectangle()
        rect = (bb.x(), bb.y(), bb.x() + bb.width(), bb.y() + bb.height())
        if self._capture_overlaps_extract(page_index, rect):
            self._refresh_highlights()
            self.working_label.setText(
                "Already extracted — cannot re-highlight (yellow)"
            )
            return
        capture = Capture(
            page=page_index,
            rect=rect,
            kind="text",
            text_content=seq.text(),
        )
        self.working_set.append(capture)
        self._refresh_highlights()

    # ------------------------------------------------------------
    # Misc / back
    # ------------------------------------------------------------

    def closeEvent(self, event):
        self._reset_extract_state()
        if self.pdf_view:
            self.pdf_view.setDocument(None)
        if self.doc is not None:
            self.doc.close()
            self.doc = None
        event.accept()

    def go_back(self):
        self._reset_extract_state()
        if self.current_pdf:
            self.progress_changed.emit(
                self.current_pdf,
                self.last_visible_page + 1,
            )
        self.back_requested.emit()