"""
UI: Session-Ordner laden, Clip per Dropdown/Klick auswählen, Kreuzkorrelation
ausführen. Enthält bewusst keine Signalverarbeitungs-Logik - die steckt in
audio_io.py, session_scanner.py und causality_analyzer.py.
"""

import os
import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QFileDialog, QMessageBox, QLabel, QComboBox, QLineEdit
)
import pyqtgraph as pg
import numpy as np

from audio_io import BERLIN, load_remote_as_audioclip, load_clip_as_audioclip
from session_scanner import SessionScanner
from causality_analyzer import CausalityAnalyzer


class WaveformWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rathenaustraße 38 - Session-Kausalanalyse")
        self.resize(1150, 850)

        self.session = None
        self.remote_clip = None    # AudioClip: lange Aufnahme (Senderaum)
        self.selected_clip = None  # AudioClip: aktuell gewählter kurzer Clip (Empfangsraum)
        self._regions_ever_positioned = False  # nur beim allerersten Clip automatisch positionieren

        self.curve1 = None
        self.curve2 = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        main_layout.addLayout(self._build_folder_row())
        main_layout.addLayout(self._build_clip_selector_row())
        main_layout.addLayout(self._build_analysis_row())
        main_layout.addLayout(self._build_result_row())

        self.plot1 = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
        self._setup_plot_style(self.plot1, "Waveform 1: Lange Aufnahme (Senderaum / Handy)")
        main_layout.addWidget(self.plot1)

        self.plot2 = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
        self._setup_plot_style(self.plot2, "Waveform 2: Gewählter Clip (Empfangsraum / Jetson)")
        main_layout.addWidget(self.plot2)

        self.plot1.setXLink(self.plot2)
        self._build_regions()

    def _build_folder_row(self):
        row = QHBoxLayout()
        self.btn_open_folder = QPushButton("📁 Session-Ordner öffnen")
        self.btn_open_folder.clicked.connect(self.open_session_folder)
        self.lbl_folder = QLabel("Kein Ordner geladen.")
        self.lbl_folder.setStyleSheet("color:#888;")
        row.addWidget(self.btn_open_folder)
        row.addWidget(self.lbl_folder, 1)
        return row

    def _build_clip_selector_row(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("Kurzer Jetson-Clip:"))
        self.combo_clips = QComboBox()
        self.combo_clips.setMinimumWidth(420)
        self.combo_clips.currentIndexChanged.connect(self.on_combo_selected)
        row.addWidget(self.combo_clips, 1)
        return row

    def _build_analysis_row(self):
        row = QHBoxLayout()
        self.btn_correlate = QPushButton("⚡ Kreuzkorrelation (nur gewählter Clip)")
        self.btn_correlate.clicked.connect(self.run_kausal_analysis)
        self.btn_reset_region = QPushButton("↺ Suchfenster zurücksetzen")
        self.btn_reset_region.clicked.connect(self.reset_region_to_coarse_window)
        self.btn_reset_clip_region = QPushButton("↺ Clip-Ausschnitt zurücksetzen (voller Clip)")
        self.btn_reset_clip_region.clicked.connect(self.reset_clip_region_to_full)
        row.addWidget(self.btn_correlate)
        row.addWidget(self.btn_reset_region)
        row.addWidget(self.btn_reset_clip_region)

        row.addWidget(QLabel("Tiefpass (Hz):"))
        self.txt_lowpass_hz = QLineEdit("500")
        self.txt_lowpass_hz.setMaximumWidth(70)
        self.txt_lowpass_hz.setToolTip(
            "Nur Frequenzen unterhalb dieser Grenze fließen in die Korrelation ein "
            "(strukturell übertragene tiefe Frequenzen statt verrauschtem Hochfrequenzband). "
            "Leer lassen für unfiltrierte Korrelation."
        )
        row.addWidget(self.txt_lowpass_hz)
        return row

    def _build_result_row(self):
        row = QHBoxLayout()
        self.lbl_result = QLabel("Kausalanalyse: Kein Clip ausgewählt.")
        self.lbl_result.setStyleSheet("font-weight:bold; color:#007bff; font-family: monospace;")
        row.addWidget(self.lbl_result, 1)
        return row

    def _build_regions(self):
        # Suchfenster (ROI) auf Plot 1 - hier wird die Kreuzkorrelation eingeschränkt.
        region_brush = pg.mkBrush(255, 255, 0, 40)
        region_pen = pg.mkPen(color=(255, 255, 0), width=1)
        self.region1 = pg.LinearRegionItem(brush=region_brush, pen=region_pen)
        self.plot1.addItem(self.region1)

        # Zweite Region auf Plot 2: isoliert einen einzelnen Impuls im kurzen Clip.
        region2_brush = pg.mkBrush(0, 255, 255, 40)
        region2_pen = pg.mkPen(color=(0, 255, 255), width=1)
        self.region2 = pg.LinearRegionItem(brush=region2_brush, pen=region2_pen)
        self.plot2.addItem(self.region2)

        # Marker für alle kurzen Clips auf Plot 1 - anklickbar zur Auswahl
        self.clip_markers = pg.ScatterPlotItem(
            size=14, symbol='t1', pen=pg.mkPen('w', width=1),
            brush=pg.mkBrush(255, 165, 0, 220)
        )
        self.clip_markers.sigClicked.connect(self.on_marker_clicked)
        self.plot1.addItem(self.clip_markers)

    def _setup_plot_style(self, plot_widget, title):
        plot_widget.setBackground('k')
        plot_widget.showGrid(x=True, y=True)
        plot_widget.setLabel('left', 'Amplitude (Normalisiert)')
        plot_widget.setLabel('bottom', 'Uhrzeit (Lokalzeit)')
        plot_widget.setTitle(title)
        plot_widget.setYRange(-1.0, 1.0)

    # ------------------------------------------------------------------
    # Ordner laden
    # ------------------------------------------------------------------
    def open_session_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Session-Ordner auswählen")
        if not folder:
            return
        try:
            self.session = SessionScanner(folder)
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Ordner konnte nicht gelesen werden:\n{e}")
            return

        if self.session.remote_wav_path is None:
            QMessageBox.warning(self, "Nichts gefunden",
                                 "Keine remote_clip_*.wav in diesem Ordner gefunden.")
            return
        if self.session.remote_start_epoch is None:
            QMessageBox.warning(self, "JSON fehlt",
                                 "Kein .json mit 'calculated_server_start_time_ms' zur langen "
                                 "Aufnahme gefunden - zeitliche Zuordnung nicht möglich.")
            return

        try:
            self.remote_clip = load_remote_as_audioclip(
                self.session.remote_wav_path, self.session.remote_start_epoch,
                os.path.basename(self.session.remote_wav_path)
            )
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Fehler beim Laden der langen Aufnahme:\n{e}")
            return

        n_found = len(self.session.clips)
        self.lbl_folder.setText(f"{os.path.basename(folder)}  —  {n_found} kurze Clip(s) gefunden")

        self._plot_remote()
        self._plot_clip_markers()
        self._populate_clip_dropdown()

    def _plot_remote(self):
        info = self.remote_clip
        t = info.start_epoch + np.linspace(0, info.duration, num=len(info.data))
        if self.curve1 is None:
            self.curve1 = self.plot1.plot(t, info.data, pen=pg.mkPen('r', width=1))
        else:
            self.curve1.setData(t, info.data)
        self.plot1.setTitle(f"Waveform 1: {info.file_name} (Senderaum / Handy)")
        self.plot1.setXRange(t[0], t[-1], padding=0.02)

    def _plot_clip_markers(self):
        pts = [{"pos": (c.epoch, 0.0), "data": i}
               for i, c in enumerate(self.session.clips)]
        self.clip_markers.setData(pts)

    def _populate_clip_dropdown(self):
        self.combo_clips.blockSignals(True)
        self.combo_clips.clear()
        for c in self.session.clips:
            dt_local = datetime.datetime.fromtimestamp(c.epoch, tz=BERLIN)
            label = f"{dt_local.strftime('%H:%M:%S.%f')[:-3]}  |  {c.filename}"
            if c.trigger_db:
                label += f"  ({c.trigger_db} dB)"
            self.combo_clips.addItem(label)
        self.combo_clips.blockSignals(False)
        if self.session.clips:
            self.combo_clips.setCurrentIndex(0)
            self.select_clip(0)

    # ------------------------------------------------------------------
    # Clip-Auswahl (Dropdown oder Klick auf Marker im Plot)
    # ------------------------------------------------------------------
    def on_combo_selected(self, idx):
        if idx < 0:
            return
        self.select_clip(idx)

    def on_marker_clicked(self, plot, points, *_):
        if not points:
            return
        idx = points[0].data()
        self.combo_clips.blockSignals(True)
        self.combo_clips.setCurrentIndex(idx)
        self.combo_clips.blockSignals(False)
        self.select_clip(idx)

    def select_clip(self, idx):
        if self.session is None or idx >= len(self.session.clips):
            return
        entry = self.session.clips[idx]

        try:
            clip = load_clip_as_audioclip(entry.path, entry.epoch, entry.filename)
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Fehler beim Laden von {entry.filename}:\n{e}")
            return

        self.selected_clip = clip

        t = clip.start_epoch + np.linspace(0, clip.duration, num=len(clip.data))
        if self.curve2 is None:
            self.curve2 = self.plot2.plot(t, clip.data, pen=pg.mkPen('c', width=1))
        else:
            self.curve2.setData(t, clip.data)
        self.plot2.setTitle(f"Waveform 2: {clip.file_name} (Empfangsraum / Jetson)")

        # Kein automatischer View-Zoom/Reset mehr bei jeder Clip-Auswahl - nur beim
        # allerersten geladenen Clip einmalig sinnvoll positionieren. Danach bleibt
        # alles genau da, wo der Nutzer es zuletzt hingezogen hat.
        if not self._regions_ever_positioned:
            self.plot2.setXRange(t[0], t[-1], padding=0.1)
            self.reset_region_to_coarse_window()
            self.reset_clip_region_to_full()
            self._regions_ever_positioned = True

        self.lbl_result.setText(f"Clip gewählt: {clip.file_name} — bereit zur Kreuzkorrelation.")

    def reset_clip_region_to_full(self):
        """Clip-Ausschnitt (Plot 2) auf die volle Länge des geladenen Clips setzen."""
        if self.selected_clip is None:
            return
        c = self.selected_clip
        self.region2.setRegion((c.start_epoch, c.start_epoch + c.duration))

    def reset_region_to_coarse_window(self):
        """Suchfenster auf Plot 1 = Trigger-Zeitpunkt des Clips ± Sicherheitsmarge."""
        if self.selected_clip is None:
            return
        coarse_ts = self.selected_clip.trigger_epoch
        margin = 8.0
        self.region1.setRegion((coarse_ts - margin, coarse_ts + margin))

    def _get_clip_windowed_data(self):
        """Schneidet den Clip auf den durch region2 markierten Ausschnitt zu."""
        c = self.selected_clip
        region_start, region_end = self.region2.getRegion()
        idx_start = int(round((region_start - c.start_epoch) * c.sample_rate))
        idx_end = int(round((region_end - c.start_epoch) * c.sample_rate))
        idx_start = max(0, idx_start)
        idx_end = min(len(c.data), idx_end)
        if idx_end - idx_start < 10:
            return c.data
        return c.data[idx_start:idx_end]

    # ------------------------------------------------------------------
    # Kreuzkorrelation - eingeschränkt auf das Suchfenster des gewählten Clips
    # ------------------------------------------------------------------
    def run_kausal_analysis(self):
        if self.remote_clip is None or self.selected_clip is None:
            QMessageBox.information(self, "Daten unvollständig",
                                     "Bitte zuerst einen Ordner laden und einen Clip auswählen.")
            return

        if self.remote_clip.sample_rate != self.selected_clip.sample_rate:
            QMessageBox.warning(self, "Samplerate-Konflikt",
                                 f"Unterschiedliche Sampleraten "
                                 f"({self.remote_clip.sample_rate} Hz vs {self.selected_clip.sample_rate} Hz).")
            return
        sr = self.remote_clip.sample_rate

        clip_arr = self._get_clip_windowed_data()
        clip_duration = len(clip_arr) / sr
        if len(clip_arr) < 10:
            QMessageBox.warning(self, "Clip-Ausschnitt zu schmal",
                                 "Der cyanfarbene Ausschnitt in Waveform 2 ist zu schmal. "
                                 "Bitte vergrößern oder 'Clip-Ausschnitt zurücksetzen' klicken.")
            return

        region_start, region_end = self.region1.getRegion()

        # Keine automatische Änderung des Suchfensters - nur prüfen und im
        # Fehlerfall warnen, damit der Bereich ausschließlich manuell bewegt wird.
        current_width = region_end - region_start
        if current_width < clip_duration:
            QMessageBox.warning(
                self, "Suchfenster zu schmal",
                f"Das Suchfenster ({current_width:.2f}s) ist schmaler als der gewählte "
                f"Clip-Ausschnitt ({clip_duration:.2f}s). Bitte in Waveform 1 manuell vergrößern."
            )
            return

        idx_start = int(round((region_start - self.remote_clip.start_epoch) * sr))
        idx_end = int(round((region_end - self.remote_clip.start_epoch) * sr))
        idx_start = max(0, idx_start)
        idx_end = min(len(self.remote_clip.data), idx_end)

        if idx_end - idx_start < len(clip_arr):
            available_sec = (idx_end - idx_start) / sr
            QMessageBox.warning(
                self, "Suchfenster am Rand der Aufnahme",
                f"Nur {available_sec:.2f}s Aufnahme verfügbar, Clip braucht {clip_duration:.2f}s. "
                "Das gewählte Suchfenster reicht über den Anfang/das Ende der langen "
                "Aufnahme hinaus. Bitte Fenster manuell in Richtung Aufnahmemitte ziehen."
            )
            return

        remote_window = self.remote_clip.data[idx_start:idx_end]

        cutoff_text = self.txt_lowpass_hz.text().strip()
        cutoff_hz = None
        if cutoff_text:
            try:
                cutoff_hz = float(cutoff_text)
            except ValueError:
                QMessageBox.warning(self, "Ungültiger Wert",
                                     "Tiefpass-Grenzfrequenz muss eine Zahl (Hz) sein oder leer bleiben.")
                return

        self.lbl_result.setText("Berechne Kreuzkorrelation (mode='valid')... Bitte warten.")
        QApplication.processEvents()

        clip_region_start_epoch, _ = self.region2.getRegion()

        analyzer = CausalityAnalyzer(sample_rate=sr)
        try:
            result = analyzer.correlate(
                remote_window, clip_arr, idx_start, self.remote_clip.start_epoch,
                clip_region_start_epoch, lowpass_cutoff_hz=cutoff_hz
            )
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Kreuzkorrelation fehlgeschlagen:\n{e}")
            return

        self._show_result(result, cutoff_hz, clip_duration)

    def _show_result(self, result, cutoff_hz, clip_duration):
        dt_match = datetime.datetime.fromtimestamp(result.match_start_epoch, tz=BERLIN)
        guete = "belastbar" if result.similarity > 0.6 else (
            "schwach" if result.similarity > 0.3 else "sehr schwach")

        filt_info = f"Tiefpass {cutoff_hz:.0f} Hz" if cutoff_hz else "ungefiltert"
        result_text = (
            f"[{filt_info}] Fein-Start: {dt_match.strftime('%H:%M:%S.%f')[:-3]} | "
            f"Impuls-Versatz (Peak-zu-Peak): {result.peak_to_peak_delay*1000:+.1f} ms | "
            f"Δ Template-Start: {result.delay_vs_template_start:+.4f} s | "
            f"Übereinstimmung: {result.similarity*100:.1f}% ({guete})"
        )
        self.lbl_result.setText(result_text)

        # Markierung der gefundenen Stelle NACH erfolgreicher Berechnung: zentriert
        # auf den tatsächlich gefundenen Impuls-Peak (nicht auf den Template-Start).
        mark_half_width = max(clip_duration / 2.0, 0.5)
        self.region1.setRegion(
            (result.peak_time_remote - mark_half_width, result.peak_time_remote + mark_half_width)
        )
