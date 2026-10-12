"""
Main Window - Professional PDF Reader with 4 navigation buttons
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QStackedWidget, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QKeySequence
from pathlib import Path

from views.library_view import LibraryView
from views.pdf_reader_view import PDFReaderView, HelpDialog
from views.extracts_view import ExtractsView
from views.flashcards_view import FlashcardsView
from services.extract_store import init_schema, resolve_doc_id
from services.perf_log import span as perf_span, discard as perf_discard


# Sidebar button states (#55): one active (blue), the rest idle.
_SIDEBAR_ACTIVE = """
    QPushButton {
        background-color: #3498db;
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 15px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #2980b9;
    }
"""
_SIDEBAR_IDLE = """
    QPushButton {
        background-color: #34495e;
        color: #ecf0f1;
        border: none;
        border-radius: 8px;
        font-size: 15px;
    }
    QPushButton:hover {
        background-color: #3d566e;
    }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("PDF Reader")
        self.setMinimumSize(1400, 900)
        
        # Central widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.main_layout = QHBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.central_widget.setLayout(self.main_layout)
        
        # Sidebar
        self.sidebar = self.create_sidebar()
        self.main_layout.addWidget(self.sidebar)
        
        # Content area with stacked widget
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_widget.setLayout(self.content_layout)
        
        self.stacked_widget = QStackedWidget()
        self.content_layout.addWidget(self.stacked_widget)
        
        self.main_layout.addWidget(self.content_widget, 1)

        # Create views
        self.library_view = LibraryView()
        self.pdf_view = PDFReaderView()
        self.extracts_view = ExtractsView()
        self.flashcards_view = FlashcardsView()

        # Add to stack
        self.stacked_widget.addWidget(self.library_view)
        self.stacked_widget.addWidget(self.pdf_view)
        self.stacked_widget.addWidget(self.extracts_view)
        self.stacked_widget.addWidget(self.flashcards_view)
        
        # Track current PDF
        self.current_pdf_path = None
        # View the reader was last entered from (for the Back button)
        self._reader_return_view = None
        
        # Connect signals
        self.library_view.pdf_selected.connect(self.open_pdf)
        self.pdf_view.back_requested.connect(self.go_back_from_reader)
        # Exactly one persistence path for progress (#87): this handler
        # forwards to library_view.update_progress. A second direct connect
        # to update_progress used to run every write twice (the reader also
        # wrote directly before #87 — three writes per page change).
        self.pdf_view.progress_changed.connect(self.on_progress_changed)
        self.extracts_view.jump_requested.connect(self.on_extract_jump)
        self.flashcards_view.source_jump_requested.connect(
            self.on_flashcard_source
        )

        # Menu bar (#115) — after the views exist so File/Reader can
        # call into them; Reader actions enable/disable with the stack.
        self._build_menus()

        # Show library by default
        self.show_library()
    
    def create_sidebar(self):
        """Create sidebar with 4 navigation buttons"""
        sidebar = QFrame()
        sidebar.setFixedWidth(250)
        sidebar.setStyleSheet("""
            QFrame {
                background-color: #1e272e;
                border-right: 1px solid #34495e;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 30, 15, 30)
        layout.setSpacing(12)
        
        # App title
        title = QLabel("📚 PDF Reader")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #3498db;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        layout.addSpacing(25)
        
        # Button 1: Library
        self.library_btn = QPushButton("📖 Library")
        self.library_btn.setFixedHeight(45)
        self.library_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.library_btn.clicked.connect(self.show_library)
        layout.addWidget(self.library_btn)
        
        # Button 2: PDF Reader
        self.pdf_reader_btn = QPushButton("📄 PDF Reader")
        self.pdf_reader_btn.setFixedHeight(45)
        self.pdf_reader_btn.setStyleSheet("""
            QPushButton {
                background-color: #34495e;
                color: #ecf0f1;
                border: none;
                border-radius: 8px;
                font-size: 15px;
            }
            QPushButton:hover {
                background-color: #3d566e;
            }
        """)
        self.pdf_reader_btn.clicked.connect(self.open_current_pdf)
        layout.addWidget(self.pdf_reader_btn)
        
        # Button 3: Extracts
        self.extracts_btn = QPushButton("📝 Extracts")
        self.extracts_btn.setFixedHeight(45)
        self.extracts_btn.setStyleSheet("""
            QPushButton {
                background-color: #34495e;
                color: #ecf0f1;
                border: none;
                border-radius: 8px;
                font-size: 15px;
            }
            QPushButton:hover {
                background-color: #3d566e;
            }
        """)
        self.extracts_btn.clicked.connect(self.show_extracts)
        layout.addWidget(self.extracts_btn)
        
        # Button 4: Flashcards
        self.flashcards_btn = QPushButton("🃏 Flashcards")
        self.flashcards_btn.setFixedHeight(45)
        self.flashcards_btn.setStyleSheet("""
            QPushButton {
                background-color: #34495e;
                color: #ecf0f1;
                border: none;
                border-radius: 8px;
                font-size: 15px;
            }
            QPushButton:hover {
                background-color: #3d566e;
            }
        """)
        self.flashcards_btn.clicked.connect(self.show_flashcards)
        layout.addWidget(self.flashcards_btn)
        
        layout.addStretch()
        
        # Footer
        footer = QLabel("v1.0")
        footer.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)
        
        sidebar.setLayout(layout)
        return sidebar
    
    def _set_active_sidebar(self, active_btn):
        """Highlight one sidebar button and idle the other three (#55)."""
        for btn in (
            self.library_btn,
            self.pdf_reader_btn,
            self.extracts_btn,
            self.flashcards_btn,
        ):
            btn.setStyleSheet(
                _SIDEBAR_ACTIVE if btn is active_btn else _SIDEBAR_IDLE
            )

    def show_library(self):
        """Show library view — rebuild rows only when the PDF set changed
        (#89): Back from the reader used to clear and re-create every row
        (widget construction + a Path().exists() per file) on each
        navigation; progress itself is refreshed in place by
        update_progress, so a clean list needs no rebuild."""
        with perf_span("main.show_library"):
            self.stacked_widget.setCurrentWidget(self.library_view)
            if self.library_view.needs_rebuild():
                self.library_view.load_library()
            self.library_view.setFocus()
            self._set_active_sidebar(self.library_btn)

    def show_pdf_view(self):
        """Show a PDF view"""
        with perf_span("main.show_pdf_view"):
            # Arm the Back target: remember which view we are leaving, but
            # never overwrite an existing arm with the reader itself
            # (re-showing the reader keeps the original origin).
            if self.stacked_widget.currentWidget() is not self.pdf_view:
                self._reader_return_view = self.stacked_widget.currentWidget()
            self.stacked_widget.setCurrentWidget(self.pdf_view)
            self.pdf_view.reload_extract_captures()
            self.pdf_view.setFocus()
            self._set_active_sidebar(self.pdf_reader_btn)

    def show_extracts(self):
        """Show the Extracts View and refresh its contents"""
        self.stacked_widget.setCurrentWidget(self.extracts_view)
        self.extracts_view.refresh()
        self.extracts_view.setFocus()
        self._set_active_sidebar(self.extracts_btn)

    def show_flashcards(self):
        """Show the Flashcards View and refresh its contents"""
        self.stacked_widget.setCurrentWidget(self.flashcards_view)
        self.flashcards_view.refresh()
        self.flashcards_view.setFocus()
        self._set_active_sidebar(self.flashcards_btn)
    
    def db_conn(self):
        """The library view's sqlite connection, extracts schema ensured."""
        conn = getattr(self.library_view, "conn", None)
        if conn is not None:
            init_schema(conn)
        return conn

    def open_current_pdf(self):
        """Open or show current PDF"""
        if self.current_pdf_path:
            self.show_pdf_view()
        else:
            QMessageBox.information(
                self,
                "No PDF Selected",
                "Please select a PDF from the library first."
            )
    
    def open_pdf(self, pdf_path: str):
        """Open PDF in reader"""
        with perf_span("main.open_pdf"):
            self.current_pdf_path = pdf_path
            self.pdf_view.load_pdf(pdf_path)
            self.show_pdf_view()

    def on_flashcard_source(self, extract_id: int, doc_id: int):
        """(#62) Flashcards' Source click → the source Extract in the
        Extract Editor, via the same navigation the sidebar uses
        (show the Extracts View, which refreshes its tree first)."""
        self.show_extracts()
        self.extracts_view.open_extract(doc_id, extract_id)

    def on_extract_jump(self, target: dict):
        """Jump from the Extracts View to a Capture's original region."""
        path = target.get("path")
        conn = self.db_conn()
        if not path or conn is None or resolve_doc_id(conn, path) is None:
            where = f"\n\n{path}" if path else ""
            QMessageBox.warning(
                self,
                "PDF Removed from Library",
                "This Extract's PDF is no longer in the library:"
                f"{where}\n\nRe-add it to the library to jump to the "
                "original location.",
            )
            return
        if not Path(path).exists():
            QMessageBox.warning(
                self,
                "PDF Not Found",
                "The PDF file for this Extract is missing from disk:\n\n"
                f"{path}\n\nRestore the file to jump to the original "
                "location.",
            )
            return
        self.open_pdf(path)
        page = target.get("page")
        rect = target.get("rect")
        if page is not None and rect:
            self.pdf_view.focus_region(page, tuple(rect))
    
    def go_back_from_reader(self):
        """Back from the reader: to the Extracts View when the reader was
        entered via a jump from there, to the Library otherwise."""
        with perf_span("main.go_back_from_reader"):
            if self._reader_return_view is self.extracts_view:
                # Back landed somewhere other than the library: drop the
                # click->paint mark so a later library paint can't pair
                # with it and report a bogus latency.
                perf_discard("back")
                self.show_extracts()
            else:
                self.show_library()
    
    def on_progress_changed(self, pdf_path: str, page: int):
        """Update progress in library"""
        self.library_view.update_progress(pdf_path, page)

    # ------------------------------------------------------------
    # Menu bar (#115)
    # ------------------------------------------------------------

    def _build_menus(self):
        """Minimal menu bar. Single-letter reader keys stay in
        keyPressEvent as the source of truth — menu items for them are
        click-only (letter shown in the label, no setShortcut), so a
        shortcut can never double-fire. Multi-key combos that
        keyPressEvent does not handle get real QActions with shortcuts
        so Qt prints them beside the label."""
        bar = self.menuBar()

        # --- File ---
        file_menu = bar.addMenu("&File")
        add_act = QAction("➕ Add PDF…", self)
        add_act.setShortcut(QKeySequence("Ctrl+O"))
        add_act.triggered.connect(self.library_view.add_pdf)
        file_menu.addAction(add_act)

        backup_act = QAction("💾 Backup library…", self)
        backup_act.setShortcut(QKeySequence("Ctrl+B"))
        backup_act.triggered.connect(self.library_view._backup_library)
        file_menu.addAction(backup_act)

        # Restore exists only once #109 lands; wire it when present.
        if hasattr(self.library_view, "_restore_library"):
            restore_act = QAction("♻️ Restore library…", self)
            restore_act.triggered.connect(self.library_view._restore_library)
            file_menu.addAction(restore_act)

        file_menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        # --- View ---
        view_menu = bar.addMenu("&View")
        lib_act = QAction("📚 Library", self)
        lib_act.setShortcut(QKeySequence("Ctrl+1"))
        lib_act.triggered.connect(self.show_library)
        view_menu.addAction(lib_act)
        ext_act = QAction("📝 Extracts", self)
        ext_act.setShortcut(QKeySequence("Ctrl+2"))
        ext_act.triggered.connect(self.show_extracts)
        view_menu.addAction(ext_act)
        fc_act = QAction("🃏 Flashcards", self)
        fc_act.setShortcut(QKeySequence("Ctrl+3"))
        fc_act.triggered.connect(self.show_flashcards)
        view_menu.addAction(fc_act)

        # --- Reader (enabled only while the reader is on screen) ---
        self.reader_menu = bar.addMenu("&Reader")
        self._reader_menu_actions = []

        def _reader_act(text, slot, shortcut=None):
            act = QAction(text, self)
            if shortcut is not None:
                act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(slot)
            self.reader_menu.addAction(act)
            self._reader_menu_actions.append(act)
            return act

        # Multi-key combos keyPressEvent does not handle → real shortcuts.
        _reader_act("Find…", self.pdf_view.open_search, "Ctrl+F")
        _reader_act("Zoom in", self.pdf_view.zoom_in, "Ctrl++")
        _reader_act("Zoom out", self.pdf_view.zoom_out, "Ctrl+-")
        _reader_act("Next page", self.pdf_view.next_page, "PgDown")
        _reader_act("Previous page", self.pdf_view.prev_page, "PgUp")

        # Zoom Fit (#105) / go-to-page (#106) land on other branches —
        # wire when present so this menu grows with them.
        if hasattr(self.pdf_view, "zoom_fit"):
            _reader_act("Zoom: Fit", self.pdf_view.zoom_fit)
        if hasattr(self.pdf_view, "page_input"):
            go_act = _reader_act(
                "Go to page…", self.pdf_view.page_input.setFocus
            )
            go_act.setShortcut(QKeySequence("Ctrl+G"))

        self.reader_menu.addSeparator()
        # Single-letter keys: click-only (no setShortcut — keyPressEvent
        # owns them, including the search-bar / extract-mode branches).
        _reader_act("Commit extract  (E)", self.pdf_view.commit_working_set)
        _reader_act(
            "Delete newest extract on page  (D, D)",
            self.pdf_view._delete_key,
        )

        # --- Help ---
        help_menu = bar.addMenu("&Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)
        shortcuts_act = QAction("Keyboard shortcuts…", self)
        shortcuts_act.setShortcut(QKeySequence("Ctrl+/"))
        shortcuts_act.triggered.connect(self._show_shortcuts)
        help_menu.addAction(shortcuts_act)

        # Reader menu lives or dies with the stack page.
        self.stacked_widget.currentChanged.connect(self._sync_reader_menu)
        self._sync_reader_menu(self.stacked_widget.currentIndex())

    def _sync_reader_menu(self, index: int):
        """(#115) Enable Reader actions only while the reader is the
        current page; capture actions additionally need a live doc."""
        on_reader = self.stacked_widget.widget(index) is self.pdf_view
        has_doc = bool(getattr(self.pdf_view, "doc", None))
        for act in getattr(self, "_reader_menu_actions", []):
            text = act.text()
            if "Commit extract" in text or "Delete newest" in text:
                act.setEnabled(on_reader and has_doc)
            else:
                act.setEnabled(on_reader)

    def _show_about(self):
        QMessageBox.about(
            self,
            "About PDF Reader",
            "PDF Reader\n\n"
            "A local-first PDF study tool: capture passages, "
            "review them as flashcards (FSRS), keep everything in "
            "one library.db.",
        )

    def _show_shortcuts(self):
        HelpDialog(self).exec()