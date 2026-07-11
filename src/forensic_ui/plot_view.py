# -*- coding: utf-8 -*-
"""
TriggerPlotWidget kennt NICHTS über dB, Crest-Faktor oder sonstige Bedeutung
der y-Werte. Es bekommt x_values (immer Zeitstempel der Events) und ein
MetricResult (aktuelle Metrik-Wahl) und zeichnet. Beim Metrik-Wechsel wird
nur set_metric_result() erneut aufgerufen - x_values bleiben identisch,
daher bleibt auch der Klick-Index -> Event-Zuordnung stabil.
"""

from typing import Callable, List, Optional

import pyqtgraph as pg

from metrics import MetricResult
from models import SessionData


class TriggerPlotWidget:
    def __init__(self):
        self.plot_widget = pg.GraphicsLayoutWidget()
        self.plot_item = self.plot_widget.addPlot(axisItems={'bottom': pg.DateAxisItem()})
        self.plot_item.setLabel('bottom', 'Zeit')
        self.plot_item.showGrid(x=True, y=True)
        self.plot_item.enableAutoRange(x=False, y=False)

        self._x_values: List[float] = []
        self._on_point_clicked: Optional[Callable[[int], None]] = None
        self._scatter: Optional[pg.ScatterPlotItem] = None

    def set_on_point_clicked(self, callback: Callable[[int], None]) -> None:
        """callback bekommt den Event-Index (Index in session.events)."""
        self._on_point_clicked = callback

    def render(self, session: SessionData, metric_result: MetricResult,
               highlight_index: Optional[int] = None) -> None:
        self.plot_item.clear()

        if session.is_empty:
            return

        self._x_values = [e.timestamp.timestamp() for e in session.events]
        y_values = metric_result.y_values

        assert len(y_values) == len(self._x_values), (
            "Metrik muss genau einen y-Wert pro Event liefern"
        )

        if metric_result.baseline_low is not None:
            self.plot_item.addItem(pg.InfiniteLine(
                pos=metric_result.baseline_low, angle=0,
                pen=pg.mkPen('w', width=1.5, style=pg.QtCore.Qt.PenStyle.DashLine)
            ))
        if metric_result.baseline_high is not None:
            self.plot_item.addItem(pg.InfiniteLine(
                pos=metric_result.baseline_high, angle=0,
                pen=pg.mkPen('r', width=1, style=pg.QtCore.Qt.PenStyle.DashLine)
            ))

        self.plot_item.plot(self._x_values, y_values, pen=pg.mkPen('y', width=2))
        self._scatter = pg.ScatterPlotItem(
            x=self._x_values, y=y_values, symbol='o', size=10, brush='r'
        )

        if metric_result.point_labels:
            for x, y, label in zip(self._x_values, y_values, metric_result.point_labels):
                if label:
                    text = pg.TextItem(label, anchor=(0, 1), color='w',
                                        fill=pg.mkBrush(0, 0, 0, 150))
                    text.setPos(x, y)
                    self.plot_item.addItem(text)

        if highlight_index is not None:
            self.plot_item.addItem(pg.ScatterPlotItem(
                x=[self._x_values[highlight_index]], y=[y_values[highlight_index]],
                symbol='star', size=18,
                brush=pg.mkBrush(255, 215, 0), pen=pg.mkPen('w', width=1),
            ))

        self._scatter.sigClicked.connect(self._handle_click)
        self.plot_item.addItem(self._scatter)

        self.plot_item.setXRange(min(self._x_values), max(self._x_values))
        y_min = min(y_values) if y_values else 0
        y_max = max(y_values) if y_values else 1
        pad = 0.05 * (y_max - y_min) if y_max != y_min else 1
        self.plot_item.setYRange(y_min - pad, y_max + pad)

        self.plot_item.setLabel('left', metric_result.y_label, units=metric_result.y_unit)
        self.plot_item.setTitle(metric_result.y_label)

    def _handle_click(self, plot, points):
        if not self._on_point_clicked:
            return
        for p in points:
            index = self._x_values.index(p.pos().x())
            self._on_point_clicked(index)
