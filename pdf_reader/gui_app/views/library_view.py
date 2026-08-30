# gui_app/views/library_view.py
"""
Library View - Fast, professional with responsive layout
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFileDialog, QProgressBar,
    QFrame, QMenu, QMessageBox, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
import sqlite3
from pathlib import Path


class PDFItemWidget(QWidget):
    """Custom widget for PDF item with responsive layout"""
    
    def __init__(self, name, path, total_pages, current_page, parent=None):
        super().__init__(parent)
        self.path = path
        self.setup_ui(name, total_pages, current_page)
    
    def setup_ui(self, name, total_pages, current_page):
        layout = QHBoxLayout()
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(20)
        
        # Left side - PDF name (takes available space)
        name_label = QLabel(name)
        name_label.setStyleSheet("color: #ecf0f1; font-size: 15px; font-weight: bold;")
        name_label.setWordWrap(True)
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
        progress_layout.addWidget(progress_bar)
        
        progress_frame.setLayout(progress_layout)
        layout.addWidget(progress_frame)
        
        self.setLayout(layout)
        self.setFixedHeight(80)  # Fixed height prevents truncation


class LibraryView(QWidget):
    """Library view showing all PDFs with progress"""
    
    pdf_selected = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        
        self.db_path = Path(__file__).parent.parent / "library.db"
        self.init_database()
        
        self.selected_pdfs = set()
        
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
        
        self.remove_btn = QPushButton("🗑️ Remove Selected")
        self.remove_btn.setFixedHeight(45)
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
        """)
        self.remove_btn.clicked.connect(self.remove_selected_pdfs)
        buttons_layout.addWidget(self.remove_btn)
        
        layout.addLayout(buttons_layout)
        
        # PDF List with responsive scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.pdf_list = QListWidget()
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
            QListWidget::item:selected {
                background-color: #3498db;
                border: 2px solid #2980b9;
            }
            QListWidget::item:hover {
                background-color: #3d566e;
            }
        """)
        self.pdf_list.itemClicked.connect(self.on_pdf_clicked)
        self.pdf_list.itemDoubleClicked.connect(self.on_pdf_double_clicked)
        
        scroll.setWidget(self.pdf_list)
        layout.addWidget(scroll)
        
        # Stats
        self.stats_label = QLabel("0 PDFs")
        self.stats_label.setStyleSheet("color: #95a5a6; font-size: 14px;")
        layout.addWidget(self.stats_label)
        
        self.setLayout(layout)
    
    def load_library(self):
        """Load PDFs from database"""
        self.pdf_list.clear()
        self.selected_pdfs.clear()
        
        self.cursor.execute("""
            SELECT id, path, name, total_pages, current_page 
            FROM pdfs 
            ORDER BY last_opened DESC
        """)
        
        pdfs = self.cursor.fetchall()
        
        for pdf_id, path, name, total_pages, current_page in pdfs:
            if not Path(path).exists():
                continue
            
            item = QListWidgetItem()
            
            widget = PDFItemWidget(name, path, total_pages, current_page)
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
        
        count = self.pdf_list.count()
        self.stats_label.setText(f"{count} PDF{'s' if count != 1 else ''} in library")
    
    def on_pdf_clicked(self, item: QListWidgetItem):
        """Handle PDF click - toggle selection"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            if item.isSelected():
                self.selected_pdfs.add(data['path'])
            else:
                self.selected_pdfs.discard(data['path'])
    
    def on_pdf_double_clicked(self, item: QListWidgetItem):
        """Handle PDF double-click - open immediately"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
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
        """Add a single PDF to database"""
        try:
            import fitz
            doc = fitz.open(file_path)
            total_pages = len(doc)
            doc.close()
            
            name = Path(file_path).name
            
            self.cursor.execute("""
                INSERT OR REPLACE INTO pdfs (path, name, total_pages, current_page)
                VALUES (?, ?, ?, 1)
            """, (file_path, name, total_pages))
            
            self.conn.commit()
            
        except Exception as e:
            print(f"Error adding PDF: {e}")
    
    def remove_selected_pdfs(self):
        """Remove selected PDFs from library"""
        if not self.selected_pdfs:
            QMessageBox.warning(
                self, 
                "No Selection", 
                "Please select PDFs to remove.\n\nClick on PDFs in the list to select them."
            )
            return
        
        count = len(self.selected_pdfs)
        reply = QMessageBox.question(
            self,
            "Remove PDFs",
            f"Remove {count} selected PDF{'s' if count > 1 else ''} from library?\n\nThis will not delete the files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for path in self.selected_pdfs:
                try:
                    self.cursor.execute("DELETE FROM pdfs WHERE path = ?", (path,))
                except Exception as e:
                    print(f"Error removing {path}: {e}")
            
            self.conn.commit()
            self.selected_pdfs.clear()
            self.load_library()
    
    def update_progress(self, pdf_path: str, current_page: int):
        """Update progress for a PDF"""
        try:
            self.cursor.execute("""
                UPDATE pdfs 
                SET current_page = ?, last_opened = CURRENT_TIMESTAMP
                WHERE path = ?
            """, (current_page, pdf_path))
            self.conn.commit()
        except Exception as e:
            print(f"Error updating progress: {e}")
    
    def closeEvent(self, event):
        self.conn.close()
        event.accept()