"""
Extracts Editor View - Placeholder
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class ExtractsView(QWidget):
    def __init__(self):
        super().__init__()
        
        layout = QVBoxLayout()
        
        label = QLabel("📝 Extracts Editor\n\nComing soon...")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888; font-size: 18px;")
        
        layout.addWidget(label)
        self.setLayout(layout)