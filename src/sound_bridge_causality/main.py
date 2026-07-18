"""Einstiegspunkt: `python main.py` startet die Session-Kausalanalyse-App."""

import sys
from PySide6.QtWidgets import QApplication
 
from main_window import WaveformWindow
 
 
def main():
    app = QApplication(sys.argv)
    window = WaveformWindow()
    window.show()
    if len(sys.argv) > 1:
        window.load_session_folder(sys.argv[1])
    sys.exit(app.exec())
 
 
if __name__ == "__main__":
    main()
 
 
