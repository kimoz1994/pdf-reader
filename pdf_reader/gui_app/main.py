# gui_app/main.py
"""
GUI Application Entry Point
"""
import sys
from PyQt6.QtWidgets import QApplication
from main_window import MainWindow  # Changed from gui_app.main_window


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()