# -*- coding: utf-8 -*-
"""
QObject-Worker, der eine Metrik-Berechnung in einem eigenen QThread laufen
lässt und dabei Fortschritt sowie das fertige Ergebnis per Qt-Signal meldet -
damit die GUI während der Berechnung (z.B. FFT über hunderte Clips) nicht
einfriert.

Verwendung (siehe main_window.py):
    thread = QThread()
    worker = MetricWorker(metric, session)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress.connect(...)
    worker.finished.connect(...)
    ...
    thread.start()
"""

from PySide6.QtCore import QObject, Signal

from metrics import Metric
from models import SessionData


class MetricWorker(QObject):
    progress = Signal(int, int)  # (erledigt, gesamt)
    finished = Signal(object)    # MetricResult
    failed = Signal(str)

    def __init__(self, metric: Metric, session: SessionData):
        super().__init__()
        self._metric = metric
        self._session = session

    def run(self):
        try:
            result = self._metric.compute(self._session, on_progress=self._emit_progress)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

    def _emit_progress(self, done: int, total: int):
        self.progress.emit(done, total)
