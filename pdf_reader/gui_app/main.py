# gui_app/main.py
"""
GUI Application Entry Point
"""
import sys
from PyQt6.QtWidgets import QApplication
from services.perf_log import ENABLED as PERF_ENABLED  # noqa: F401
from main_window import MainWindow  # Changed from gui_app.main_window


def main():
    if PERF_ENABLED:
        print("[perf] logging enabled -> console + pdf_reader/gui_app/perf.log", flush=True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()