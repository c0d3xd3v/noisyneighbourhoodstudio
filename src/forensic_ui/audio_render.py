# -*- coding: utf-8 -*-
"""
Zeichnet Waveform + Spektrogramm für eine einzelne Audiodatei.
Kennt nichts von Sessions, Metriken oder Favoriten - nur "hier ist ein Pfad,
zeichne die beiden Plots". Verwaltet zusätzlich die rote Wiedergabe-Cursorlinie
auf der Waveform, weil die eng mit dem Waveform-Plot gekoppelt ist.
"""

from typing import Optional, Tuple

import numpy as np
import pyqtgraph as pg
import soundfile as sf
from scipy.signal import spectrogram
from PySide6.QtGui import QTransform


def load_audio(path: str) -> Tuple[np.ndarray, int]:
    data, samplerate = sf.read(path)
    if data.ndim > 1:
        data = data[:, 0]
    return data, samplerate


class AudioRenderWidget:
    def __init__(self):
        self.waveform_plot = pg.PlotWidget(title="Waveform")
        self.waveform_plot.setLabel('left', 'Amplitude')
        self.waveform_plot.setLabel('bottom', 'Zeit (s)')
        self.waveform_plot.showGrid(x=True, y=True)
        self.waveform_plot.setFixedHeight(160)

        self.spectrogram_plot = pg.PlotWidget()
        self.spectrogram_img = pg.ImageItem()
        self.spectrogram_plot.addItem(self.spectrogram_img)
        self.spectrogram_plot.setLabel('bottom', 'Zeit (s)')
        self.spectrogram_plot.setLabel('left', 'Frequenz (Hz)')
        self.spectrogram_plot.setTitle("Spektrogramm")
        self.spectrogram_plot.enableAutoRange(x=False, y=False)

        self._last_data: Optional[np.ndarray] = None
        self._last_samplerate: Optional[int] = None
        self._playback_line: Optional[pg.InfiniteLine] = None

    @property
    def last_audio(self) -> Tuple[Optional[np.ndarray], Optional[int]]:
        return self._last_data, self._last_samplerate

    def render(self, fname: str) -> bool:
        import os
        if not os.path.exists(fname):
            self.waveform_plot.clear()
            self.spectrogram_plot.clear()
            self._playback_line = None
            return False

        data, samplerate = load_audio(fname)

        self.waveform_plot.clear()
        self.waveform_plot.plot(np.arange(len(data)) / samplerate, data, pen='c')
        self._playback_line = None

        f, t, Sxx = spectrogram(data, samplerate, nperseg=1024, noverlap=512)
        Sxx_dB = 10 * np.log10(Sxx + 1e-10)

        import matplotlib.pyplot as plt
        lut = (plt.get_cmap("inferno")(np.linspace(0, 1, 256))[:, :3] * 255).astype(np.uint8)
        self.spectrogram_img.setLookupTable(lut)
        self.spectrogram_img.setImage(Sxx_dB.T, levels=(Sxx_dB.min(), Sxx_dB.max()))

        dx = t[1] - t[0]
        dy = f[1] - f[0]
        transform = QTransform()
        transform.translate(t[0], f[0])
        transform.scale(dx, dy)
        self.spectrogram_img.setTransform(transform)

        self.spectrogram_plot.addItem(self.spectrogram_img)
        self.spectrogram_plot.setXRange(t[0], t[-1], padding=0)
        self.spectrogram_plot.setYRange(0, 1000, padding=0)
        self.spectrogram_plot.setLimits(xMin=t[0], xMax=t[-1], yMin=0, yMax=1000)
        self.spectrogram_plot.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=False)

        self._last_data = data
        self._last_samplerate = samplerate
        return True

    def redraw_static_waveform(self) -> None:
        """Zeichnet die Waveform ohne Cursor neu (z.B. nach Stop)."""
        if self._last_data is None:
            return
        self.waveform_plot.clear()
        time_axis = np.arange(len(self._last_data)) / self._last_samplerate
        self.waveform_plot.plot(time_axis, self._last_data, pen='c')
        self._playback_line = None

    def show_playback_cursor(self) -> None:
        """Zeichnet Waveform neu + setzt Cursorlinie bei 0, für den Start der Wiedergabe."""
        self.redraw_static_waveform()
        self._playback_line = pg.InfiniteLine(
            pos=0, angle=90, movable=False, pen=pg.mkPen('r', width=2)
        )
        self.waveform_plot.addItem(self._playback_line)

    def update_playback_cursor(self, position_ms: int) -> None:
        if self._playback_line and self._playback_line in self.waveform_plot.items():
            self._playback_line.setPos(position_ms / 1000.0)

    def clear_playback_cursor(self) -> None:
        if self._playback_line and self._playback_line in self.waveform_plot.items():
            self.waveform_plot.removeItem(self._playback_line)
        self._playback_line = None
