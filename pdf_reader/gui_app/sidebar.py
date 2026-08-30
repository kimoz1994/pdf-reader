"""Sidebar navigation component for the GUI application."""

try:
    from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
except ImportError:  # pragma: no cover - fallback for environments without PyQt5
    QWidget = object
    QVBoxLayout = object
    QPushButton = object
    QLabel = object


class Sidebar(QWidget):
    """Simple navigation sidebar with buttons for major views."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(QLabel("Navigation"))

        self.reader_button = QPushButton("PDF Reader")
        self.extracts_button = QPushButton("Extracts")
        self.flashcards_button = QPushButton("Flashcards")

        self.layout.addWidget(self.reader_button)
        self.layout.addWidget(self.extracts_button)
        self.layout.addWidget(self.flashcards_button)
