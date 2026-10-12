# gui_app/views/library_view.py
"""
Library View - Fast, professional with responsive layout
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QAbstractItemView, QFileDialog,
    QProgressBar, QFrame, QMenu, QMessageBox, QScrollArea, QCheckBox,
    QInputDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
import sqlite3
from pathlib import Path

from services.extract_store import backup_database, restore_database
from services.perf_log import span as perf_span, log_since as perf_log_since

# Removal toolbar (#72): label base for the button; `_sync_removal_ui`
# appends the ticked count when there is one.
_REMOVE_LABEL = "🗑️ Remove Selected"


class PDFItemWidget(QWidget):
    """Custom widget for PDF item with responsive layout.

    Row content (#72): a checkbox that arms the row for removal (its
    toggled state is pushed up through `check_changed`), the name (with
    a ⚠ file missing mark when the file is gone) and the progress.
    Single click anywhere on the row just highlights it — only the
    checkbox ticks — and a double-click still opens the PDF.
    """

    check_changed = pyqtSignal(str, bool)  # path, checked

    def __init__(
        self,
        name,
        path,
        total_pages,
        current_page,
        missing=False,
        parent=None,
    ):
        super().__init__(parent)
        self.path = path
        self.setup_ui(name, total_pages, current_page, missing)

    def setup_ui(self, name, total_pages, current_page, missing):
        layout = QHBoxLayout()
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(14)

        # Left: the removal checkbox (#72)
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(False)
        self.checkbox.setStyleSheet(
            """
            QCheckBox { color: #ecf0f1; font-size: 15px; spacing: 8px; }
            QCheckBox::indicator { width: 18px; height: 18px; }
            QCheckBox::indicator:unchecked {
                border: 1px solid #95a5a6;
                background-color: #2b2b2b;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #2980b9;
                background-color: #3498db;
            }
            """
        )
        self.checkbox.toggled.connect(
            lambda on: self.check_changed.emit(self.path, on)
        )
        layout.addWidget(self.checkbox, 0)

        # Middle: PDF name (takes available space)
        name_label = QLabel(f"{name}  ⚠ file missing" if missing else name)
        name_label.setStyleSheet(
            "color: #e67e22; font-size: 15px; font-weight: bold;"
            if missing
            else "color: #ecf0f1; font-size: 15px; font-weight: bold;"
        )
        name_label.setWordWrap(True)
        self.name_label = name_label
        layout.addWidget(name_label, 1)  # Stretch factor 1

        # Right side - Progress info (fixed width, no truncation)
        progress_frame = QFrame()
        progress_layout = QVBoxLayout()
        progress_layout.setContentsMargins(10, 5, 10, 5)
        progress_layout.setSpacing(5)

        if total_pages > 0:
            progress = (current_page / total_pages) * 100
        else:
            progress = 0

        # Page number
        page_label = QLabel(f"Page {current_page} / {total_pages}")
        page_label.setStyleSheet("color: #3498db; font-size: 14px; font-weight: bold;")
        page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label = page_label  # kept for in-place refresh (#89)
        progress_layout.addWidget(page_label)

        # Progress bar
        progress_bar = QProgressBar()
        progress_bar.setValue(int(progress))
        progress_bar.setFormat(f"{progress:.1f}%")
        progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #2c3e50;
                border: none;
                border-radius: 3px;
                text-align: center;
                color: #ecf0f1;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background-color: #3498db;
                border-radius: 3px;
            }
        """)
        progress_bar.setFixedHeight(25)
        progress_bar.setFixedWidth(150)
        self.progress_bar = progress_bar  # kept for in-place refresh (#89)
        progress_layout.addWidget(progress_bar)

        progress_frame.setLayout(progress_layout)
        layout.addWidget(progress_frame)

        self.setLayout(layout)
        self.setFixedHeight(80)  # Fixed height prevents truncation

    def set_progress(self, current_page, total_pages):
        """Refresh this row's page text and bar in place (#89) — Back from
        the reader must not rebuild every row just to move one number."""
        self.page_label.setText(f"Page {current_page} / {total_pages}")
        pct = (current_page / total_pages) * 100 if total_pages > 0 else 0
        self.progress_bar.setValue(int(pct))
        self.progress_bar.setFormat(f"{pct:.1f}%")


class LibraryView(QWidget):
    """Library view showing all PDFs with progress"""
    
    pdf_selected = pyqtSignal(str)
    
    def __init__(self, db_path=None):
        super().__init__()
        
        # `db_path` is a test seam (#72): the app uses the real DB, the
        # offscreen tests point it at a temp file.
        self.db_path = Path(db_path) if db_path else (
            Path(__file__).parent.parent / "library.db"
        )
        # Backups live next to the DB (#83); *.db is gitignored so the
        # copies never reach the repo.
        self.backups_dir = self.db_path.parent / "backups"
        self.init_database()
        
        self.selected_pdfs = set()  # ticked rows, by path (#72)
        # Rows need (re)building until the first load finishes (#89):
        # Back skips load_library while this stays False.
        self._structural_dirty = True
        
        self.setup_ui()
        self.load_library()
    
    def init_database(self):
        """Initialize SQLite database"""
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS pdfs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                total_pages INTEGER DEFAULT 0,
                current_page INTEGER DEFAULT 1,
                last_opened TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # #114: per-document zoom memory. Older DBs get the columns
        # backfilled with NULL → first open after upgrade stays Fit.
        cols = {r[1] for r in self.cursor.execute("PRAGMA table_info(pdfs)")}
        if "zoom_mode" not in cols:
            self.cursor.execute("ALTER TABLE pdfs ADD COLUMN zoom_mode TEXT")
        if "zoom_factor" not in cols:
            self.cursor.execute("ALTER TABLE pdfs ADD COLUMN zoom_factor REAL")
        self.conn.commit()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Header
        header = QLabel("📚 My Library")
        header.setStyleSheet("font-size: 28px; font-weight: bold; color: #3498db;")
        layout.addWidget(header)
        
        # Buttons row
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        
        self.add_btn = QPushButton("➕ Add PDF")
        self.add_btn.setFixedHeight(45)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.add_btn.clicked.connect(self.add_pdf)
        buttons_layout.addWidget(self.add_btn)
        
        self.select_all_btn = QPushButton("☑ Select all")
        self.select_all_btn.setFixedHeight(45)
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #34495e;
                color: #ecf0f1;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3d566e;
            }
            QPushButton:disabled {
                color: #7f8c8d;
            }
        """)
        self.select_all_btn.clicked.connect(self.toggle_select_all)
        buttons_layout.addWidget(self.select_all_btn)
        
        self.remove_btn = QPushButton(_REMOVE_LABEL)
        self.remove_btn.setFixedHeight(45)
        self.remove_btn.setEnabled(False)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #7f4a44;
                color: #cfcfcf;
            }
        """)
        self.remove_btn.clicked.connect(self.remove_selected_pdfs)
        buttons_layout.addWidget(self.remove_btn)

        # One-click DB backup (#83): safe snapshot of library.db — the
        # user's whole study history — into backups/ next to it.
        self.backup_btn = QPushButton("💾 Backup")
        self.backup_btn.setFixedHeight(45)
        self.backup_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        self.backup_btn.clicked.connect(self._backup_library)
        buttons_layout.addWidget(self.backup_btn)

        # The missing half of Backup (#109): load a snapshot from backups/.
        self.restore_btn = QPushButton("♻️ Restore")
        self.restore_btn.setFixedHeight(45)
        self.restore_btn.setStyleSheet("""
            QPushButton {
                background-color: #8e44ad;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #9b59b6;
            }
        """)
        self.restore_btn.clicked.connect(self._restore_library)
        buttons_layout.addWidget(self.restore_btn)

        layout.addLayout(buttons_layout)
        
        # PDF List with responsive scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.pdf_list = QListWidget()
        # A plain click does NOTHING (#93): no highlight, no state —
        # selection served no purpose (Remove reacts only to checkboxes,
        # Del to ticked rows, double-click to the open signal).
        self.pdf_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.pdf_list.setStyleSheet("""
            QListWidget {
                background-color: #2b2b2b;
                color: #ecf0f1;
                border: none;
                border-radius: 8px;
                padding: 10px;
            }
            QListWidget::item {
                background-color: #34495e;
                border-radius: 6px;
                padding: 5px;
                margin: 5px 0;
            }
            QListWidget::item:hover {
                background-color: #3d566e;
            }
        """)
        self.pdf_list.itemDoubleClicked.connect(self.on_pdf_double_clicked)

        # Del removes the ticked rows (#72), scoped to this view so it
        # works anywhere inside the Library but never while another
        # view has focus.
        self.delete_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Delete), self
        )
        self.delete_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.delete_shortcut.activated.connect(self._delete_key_pressed)
        
        scroll.setWidget(self.pdf_list)
        layout.addWidget(scroll)
        
        # Stats
        self.stats_label = QLabel("0 PDFs")
        self.stats_label.setStyleSheet("color: #95a5a6; font-size: 14px;")
        layout.addWidget(self.stats_label)
        
        self.setLayout(layout)
    
    def load_library(self):
        """Rebuild the whole row list from the database."""
        with perf_span("library.load_library"):
            self._rebuild_library_list()
            self._structural_dirty = False

    def needs_rebuild(self) -> bool:
        """True while the visible rows don't match the DB's PDF set (#89).
        Adds/removes rebuild through load_library and clear this; progress
        never sets it (update_progress lands in place), so Back from the
        reader skips the full rebuild."""
        return self._structural_dirty

    def paintEvent(self, event):
        # Perceived Back latency (follow-up to #89): the mark is stamped
        # at the click in reader.go_back; the first paint after the view
        # switch is what the user actually sees.
        super().paintEvent(event)
        perf_log_since("back", "back: click -> library first paint")

    def _rebuild_library_list(self):
        self.pdf_list.clear()
        self.selected_pdfs.clear()
        
        self.cursor.execute("""
            SELECT id, path, name, total_pages, current_page 
            FROM pdfs 
            ORDER BY last_opened DESC
        """)
        
        pdfs = self.cursor.fetchall()
        
        for pdf_id, path, name, total_pages, current_page in pdfs:
            # Files that moved or were deleted stay listed, marked, so
            # they can be ticked and removed (#72) — before, they simply
            # vanished from the view and could never be cleaned up.
            missing = not Path(path).exists()
            item = QListWidgetItem()
            
            widget = PDFItemWidget(
                name, path, total_pages, current_page, missing=missing
            )
            widget.check_changed.connect(self.on_row_check)
            item.setSizeHint(widget.sizeHint())
            
            item.setData(Qt.ItemDataRole.UserRole, {
                'id': pdf_id,
                'path': path,
                'name': name,
                'total_pages': total_pages,
                'current_page': current_page
            })
            
            self.pdf_list.addItem(item)
            self.pdf_list.setItemWidget(item, widget)
        
        self._sync_removal_ui()

    def _row_widget(self, index: int) -> PDFItemWidget:
        """The custom row widget at `index` (the list stores items and
        widgets separately)."""
        return self.pdf_list.itemWidget(self.pdf_list.item(index))

    def _selected_names(self) -> list:
        """Filenames of the ticked rows, sorted — what the confirm
        dialog lists (#72). Read from the items themselves so the list
        stays the single source of truth for names."""
        ticked = self.selected_pdfs
        names = []
        for i in range(self.pdf_list.count()):
            data = self.pdf_list.item(i).data(Qt.ItemDataRole.UserRole)
            if data and data.get("path") in ticked:
                names.append(data.get("name") or data["path"])
        return sorted(names)

    def on_row_check(self, path: str, checked: bool):
        """A row checkbox was ticked/unticked: keep the removal set and
        the toolbar in step (#72)."""
        if checked:
            self.selected_pdfs.add(path)
        else:
            self.selected_pdfs.discard(path)
        self._sync_removal_ui()

    def toggle_select_all(self):
        """☑ Select all / ☐ Clear, whichever fits the current state."""
        all_rows = self.pdf_list.count()
        check = len(self.selected_pdfs) != all_rows
        for i in range(all_rows):
            self._row_widget(i).checkbox.setChecked(check)
        # each setChecked fires on_row_check, which already synced

    def _sync_removal_ui(self):
        """Remove button, Select all label and the stats line reflect the
        ticked rows (#72): disabled at 0, count in the text."""
        n = len(self.selected_pdfs)
        rows = self.pdf_list.count()
        self.remove_btn.setEnabled(n > 0)
        self.remove_btn.setText(
            f"{_REMOVE_LABEL} ({n})" if n else _REMOVE_LABEL
        )
        if rows and n == rows:
            self.select_all_btn.setText("☐ Clear")
        else:
            self.select_all_btn.setText("☑ Select all")
        self.select_all_btn.setEnabled(rows > 0)
        stats = f"{rows} PDF{'s' if rows != 1 else ''} in library"
        if n:
            stats += f" — {n} selected"
        self.stats_label.setText(stats)

    def on_pdf_double_clicked(self, item: QListWidgetItem):
        """Handle PDF double-click - open immediately"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        if not Path(data['path']).exists():
            QMessageBox.warning(
                self,
                "File Missing",
                "This file was moved or deleted, so it cannot be opened.\n\n"
                "Tick it and use "
                f"{_REMOVE_LABEL} to clean it from the library.",
            )
            return
        self.pdf_selected.emit(data['path'])
    
    def add_pdf(self):
        """Add new PDF to library"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add PDFs",
            "",
            "PDF Files (*.pdf)"
        )
        
        for file_path in file_paths:
            self.add_pdf_to_library(file_path)
        
        self.load_library()
    
    def add_pdf_to_library(self, file_path: str):
        """Add a single PDF to database.

        Re-adding a path already in the library updates name/page count
        only — the row id, read progress and every extract/flashcard
        keyed to it are preserved (#99).
        """
        try:
            import fitz
            doc = fitz.open(file_path)
            total_pages = len(doc)
            doc.close()
            
            name = Path(file_path).name
            
            self.cursor.execute("""
                INSERT INTO pdfs (path, name, total_pages, current_page)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(path) DO UPDATE SET
                    name = excluded.name,
                    total_pages = excluded.total_pages
            """, (file_path, name, total_pages))
            
            self.conn.commit()
            
        except Exception as e:
            print(f"Error adding PDF: {e}")
            self._toast(f"Could not add {Path(file_path).name}: {e}")

    def _toast(self, message: str, timeout: int = 5000):
        """Status-bar message when embedded in MainWindow; no-op standalone."""
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(message, timeout)
    
    def _delete_key_pressed(self):
        """Del-key handler (#72): silent when nothing is ticked."""
        if self.selected_pdfs:
            self.remove_selected_pdfs()

    def remove_selected_pdfs(self):
        """Remove the ticked PDFs from the library — from the library
        only, the files on disk are never touched (#72)."""
        if not self.selected_pdfs:
            return  # button is disabled and Del is guarded: defense only
        
        names = self._selected_names()
        if not self._confirm_removal(names):
            return

        failed = []
        for path in list(self.selected_pdfs):
            try:
                self.cursor.execute("DELETE FROM pdfs WHERE path = ?", (path,))
            except Exception as e:
                print(f"Error removing {path}: {e}")
                failed.append(Path(path).name)
        
        self.conn.commit()
        if failed:
            self._toast(f"Could not remove {', '.join(failed)} — see console")
        self.selected_pdfs.clear()
        self.load_library()

    def _confirm_removal(self, names) -> bool:
        """The Yes/No dialog for a removal (#72): the count up front, the
        ticked names behind "Show details", plus what is NOT happening.
        Split out from `remove_selected_pdfs` so tests can bypass it."""
        count = len(names)
        box = QMessageBox(
            QMessageBox.Icon.Question,
            "Remove PDFs",
            f"Remove {count} selected PDF{'s' if count != 1 else ''} "
            "from the library?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self,
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setInformativeText(
            "The files on disk are NOT deleted.\n"
            "Extracts and flashcards made from these PDFs are kept — they "
            "keep showing the original name."
        )
        box.setDetailedText("\n".join(names))
        return box.exec() == QMessageBox.StandardButton.Yes

    def _do_backup(self):
        """Run the backup seam and return the written path (#83). A
        separate method so tests can monkeypatch it (the
        `_confirm_removal` pattern)."""
        return backup_database(self.conn, self.backups_dir)

    def _backup_library(self):
        """💾 Backup: snapshot library.db into backups/ and tell the
        user where it went (#83)."""
        path = self._do_backup()
        QMessageBox.information(
            self,
            "Backup saved",
            f"A copy of your library was saved to:\n\n{path}\n\n"
            "Keep it somewhere safe — it holds your extracts, flashcards "
            "and study schedule.",
        )

    def _list_backup_files(self):
        """Snapshots in backups/, newest first (#109)."""
        if not self.backups_dir.exists():
            return []
        return sorted(
            self.backups_dir.glob("library-*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def _restore_library(self):
        """♻️ Restore: pick a snapshot from backups/, confirm, and replace
        the live library's content in place (#109)."""
        backups = self._list_backup_files()
        if not backups:
            QMessageBox.information(
                self,
                "Restore backup",
                "No backups found yet.\n\n"
                "Click 💾 Backup first to create one.",
            )
            return
        names = [p.name for p in backups]
        name, ok = QInputDialog.getItem(
            self,
            "Restore backup",
            "Choose a snapshot (newest first):",
            names,
            0,
            False,
        )
        if not ok or not name:
            return
        chosen = self.backups_dir / name
        reply = QMessageBox.question(
            self,
            "Restore backup",
            f"Replace the current library with\n{name}?\n\n"
            "Your current extracts, flashcards and reading progress "
            "will be replaced by the snapshot.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            restore_database(self.conn, chosen)
        except Exception as e:
            print(f"Error restoring backup: {e}")
            QMessageBox.critical(
                self,
                "Restore failed",
                f"Could not restore from {name}:\n{e}",
            )
            return
        self.selected_pdfs.clear()
        self._structural_dirty = True
        self.load_library()
        QMessageBox.information(
            self,
            "Restore backup",
            f"Restored from {name}.\n\n"
            "Open Extracts or Flashcards to see the restored data.",
        )

    def update_progress(self, pdf_path: str, current_page: int):
        """Persist progress and refresh the row in place (#89): one label
        update instead of tearing down every row on the next Back."""
        with perf_span("library.update_progress"):
            try:
                self.cursor.execute("""
                    UPDATE pdfs 
                    SET current_page = ?, last_opened = CURRENT_TIMESTAMP
                    WHERE path = ?
                """, (current_page, pdf_path))
                self.conn.commit()
            except Exception as e:
                print(f"Error updating progress: {e}")
                self._toast("Could not save read progress")
            self._update_row_progress(pdf_path, current_page)

    def update_zoom(self, pdf_path: str, zoom_mode: str, zoom_factor: float):
        """Persist the reader's zoom for one document (#114): 'fit' or
        'custom' plus the factor (ignored for fit). Reopen restores it;
        a first open (NULL columns) stays Fit."""
        try:
            self.cursor.execute("""
                UPDATE pdfs
                SET zoom_mode = ?, zoom_factor = ?
                WHERE path = ?
            """, (zoom_mode, zoom_factor, pdf_path))
            self.conn.commit()
        except Exception as e:
            print(f"Error updating zoom: {e}")

    def _update_row_progress(self, pdf_path: str, current_page: int):
        """Find the row for `pdf_path` and sync its widget + item data —
        no list rebuild, no file re-stat, no selection wipe."""
        for i in range(self.pdf_list.count()):
            item = self.pdf_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("path") == pdf_path:
                data["current_page"] = current_page  # shared dict, in place
                self._row_widget(i).set_progress(
                    current_page, data.get("total_pages") or 0
                )
                return
    
    def closeEvent(self, event):
        self.conn.close()
        event.accept()