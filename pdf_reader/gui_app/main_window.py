"""
Main Window - Professional PDF Reader with 4 navigation buttons
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QStackedWidget, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from views.library_view import LibraryView
from views.pdf_reader_view import PDFReaderView
from views.extracts_view import ExtractsView
from services.extract_store import init_schema


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

        # Add to stack
        self.stacked_widget.addWidget(self.library_view)
        self.stacked_widget.addWidget(self.pdf_view)
        self.stacked_widget.addWidget(self.extracts_view)
        
        # Track current PDF
        self.current_pdf_path = None
        
        # Connect signals
        self.library_view.pdf_selected.connect(self.open_pdf)
        self.pdf_view.back_requested.connect(self.go_to_library)
        self.pdf_view.progress_changed.connect(self.on_progress_changed)
        self.pdf_view.progress_changed.connect( self.library_view.update_progress)
        
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
        self.flashcards_btn.clicked.connect(lambda: self.show_coming_soon("Flashcards"))
        layout.addWidget(self.flashcards_btn)
        
        layout.addStretch()
        
        # Footer
        footer = QLabel("v1.0")
        footer.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)
        
        sidebar.setLayout(layout)
        return sidebar
    
    def show_coming_soon(self, feature_name):
        """Show coming soon message"""
        QMessageBox.information(
            self,
            "Coming Soon",
            f"{feature_name} feature is under development.\n\nStay tuned!"
        )
    
    def show_library(self):
        """Show library view"""
        self.stacked_widget.setCurrentWidget(self.library_view)
        self.library_view.load_library()
        self.library_view.setFocus()
        # Update sidebar highlighting
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

    def show_pdf_view(self):
        """Show a PDF view"""
        self.stacked_widget.setCurrentWidget(self.pdf_view)
        self.pdf_view.reload_extract_captures()
        self.pdf_view.setFocus()
        # Update sidebar highlighting
        self.library_btn.setStyleSheet("""
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
    
        self.pdf_reader_btn.setStyleSheet("""
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

    def show_extracts(self):
        """Show the Extracts View and refresh its contents"""
        self.stacked_widget.setCurrentWidget(self.extracts_view)
        self.extracts_view.refresh()
        self.extracts_view.setFocus()
        # Update sidebar highlighting
        self.library_btn.setStyleSheet("""
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

        self.extracts_btn.setStyleSheet("""
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
        self.current_pdf_path = pdf_path
        self.pdf_view.load_pdf(pdf_path)
        self.show_pdf_view()
    
    def go_to_library(self):
        """Go back to library"""
        self.show_library()
    
    def on_progress_changed(self, pdf_path: str, page: int):
        """Update progress in library"""
        self.library_view.update_progress(pdf_path, page)