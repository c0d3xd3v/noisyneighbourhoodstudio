# -*- coding: utf-8 -*-
"""Zeigt die Trigger-Uhrzeit als analoge Uhr an. Unverändert aus dem alten Script."""

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPolygon
from PySide6.QtCore import QTime, QPoint, Qt


class AnalogClockWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.display_time = QTime.currentTime()
        self.setMinimumSize(100, 100)

    def set_time(self, time: QTime):
        self.display_time = time
        self.update()

    def paintEvent(self, event):
        side = min(self.width(), self.height())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(side / 200.0, side / 200.0)

        hour_hand = QPolygon([QPoint(7, 8), QPoint(-7, 8), QPoint(0, -40)])
        minute_hand = QPolygon([QPoint(7, 8), QPoint(-7, 8), QPoint(0, -70)])

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(127, 0, 127))
        painter.save()
        painter.rotate(30.0 * ((self.display_time.hour() % 12) + self.display_time.minute() / 60.0))
        painter.drawConvexPolygon(hour_hand)
        painter.restore()

        painter.setBrush(QColor(0, 127, 127))
        painter.save()
        painter.rotate(6.0 * (self.display_time.minute() + self.display_time.second() / 60.0))
        painter.drawConvexPolygon(minute_hand)
        painter.restore()

        painter.setPen(Qt.black)
        for _ in range(12):
            painter.drawLine(88, 0, 96, 0)
            painter.rotate(30.0)
