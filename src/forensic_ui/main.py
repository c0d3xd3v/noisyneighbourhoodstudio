# -*- coding: utf-8 -*-
import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from main_window import MainWindow

# Import sorgt dafür, dass die konkreten Metriken bei MetricRegistry registriert werden,
# auch wenn main_window.py sie nur indirekt über MetricRegistry.all() nutzt.
import metrics  # noqa: F401


def main():
    QGuiApplication.setAttribute(Qt.AA_UseDesktopOpenGL)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
