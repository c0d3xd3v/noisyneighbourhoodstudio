"""
UI: Session-Ordner laden, Clip per Dropdown/Klick auswählen, Kreuzkorrelation
ausführen. Enthält bewusst keine Signalverarbeitungs-Logik - die steckt in
audio_io.py, session_scanner.py und causality_analyzer.py.
"""

import os
import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QFileDialog, QMessageBox, QLabel, QComboBox, QLineEdit,
    QDialog, QCheckBox
)
import pyqtgraph as pg
import numpy as np
from scipy import signal as sp_signal

from audio_io import BERLIN, load_remote_as_audioclip, load_clip_as_audioclip
from session_scanner import SessionScanner
from causality_analyzer import CausalityAnalyzer, sweep_similarity, spectral_similarity_search

from scipy import ndimage as sp_ndimage

# Nominale Länge der Jetson-Clips und Lage des Triggers innerhalb des Clips -
# muss zur tatsächlichen Aufnahmekonfiguration passen (gleiche Annahme wie
# load_clip_as_audioclip in audio_io.py, pre_trigger_fraction=0.5). Wird nur
# für die Timeline-Blöcke NOCH NICHT geladener Clips verwendet; für den aktuell
# geladenen Clip gelten dessen echte Grenzen.
CLIP_NOMINAL_DURATION_S = 6.0
CLIP_PRE_TRIGGER_FRACTION = 0.5


class WaveformWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Noisy Neighbourhood Studio - Session-Kausalanalyse")
        self.resize(1150, 850)

        self.session = None
        self.remote_clip = None    # AudioClip: lange Aufnahme (Senderaum)
        self.selected_clip = None  # AudioClip: aktuell gewählter kurzer Clip (Empfangsraum)
        self._selected_clip_index = None  # Index des gewählten Clips (für Timeline-Highlight)
        self._search_window_initialized = False  # nur beim allerersten Clip auf Standardbreite setzen

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
        main_layout.addLayout(self._build_spectral_row())
        main_layout.addLayout(self._build_result_row())

        self.plot1 = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
        self._setup_plot_style(self.plot1, "Waveform 1: Lange Aufnahme (Senderaum / Handy)")

        self.spec_plot1 = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
        self.spec_plot1.setBackground('k')
        self.spec_plot1.setLabel('left', 'Frequenz (Hz)')
        self.spec_plot1.setLabel('bottom', 'Uhrzeit (Lokalzeit)')
        self.spec_plot1.setTitle("Spektrogramm 1 (Senderaum)")
        self.spec_plot1.setXLink(self.plot1)
        self.spec_plot1.setVisible(False)

        row1 = QHBoxLayout()
        row1.addWidget(self.plot1, 1)
        row1.addWidget(self.spec_plot1, 1)
        main_layout.addLayout(row1, 1)

        self.plot2 = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
        self._setup_plot_style(self.plot2, "Waveform 2: Gewählter Clip (Empfangsraum / Jetson)")

        self.spec_plot2 = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
        self.spec_plot2.setBackground('k')
        self.spec_plot2.setLabel('left', 'Frequenz (Hz)')
        self.spec_plot2.setLabel('bottom', 'Uhrzeit (Lokalzeit)')
        self.spec_plot2.setTitle("Spektrogramm 2 (Empfangsraum)")
        self.spec_plot2.setXLink(self.plot2)
        self.spec_plot2.setVisible(False)

        row2 = QHBoxLayout()
        row2.addWidget(self.plot2, 1)
        row2.addWidget(self.spec_plot2, 1)
        main_layout.addLayout(row2, 1)

        # xLink zurück: beide Waveforms sollen synchron pannen/zoomen, damit
        # man die Position der Regions direkt visuell vergleichen kann. Die
        # vorherige 'murks'-Wirkung kam nicht vom Link selbst, sondern davon,
        # dass select_clip() Plot 2 UND reset_region_to_coarse_window() Plot 1
        # gegenläufig auf unterschiedliche Breiten fixiert haben - das wird
        # jetzt vereinheitlicht (siehe select_clip / _fit_plot1_view_to_region).
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
        self.btn_sweep = QPushButton("📈 Frequenz-Sweep")
        self.btn_sweep.setToolTip(
            "Berechnet die Übereinstimmung über eine ganze Reihe von Tiefpass-"
            "Grenzfrequenzen (8-60 Hz) und zeichnet sie als Kurve. Mehrere Clips "
            "nacheinander sweepen -> liegen die Maxima im selben Band, spricht "
            "das Bild für sich. Optional mit Fehlpaarungs-Referenzkurve."
        )
        self.btn_sweep.clicked.connect(self.run_frequency_sweep)
        self.btn_auto_template = QPushButton("🎯 Template auto")
        self.btn_auto_template.setToolTip(
            "Setzt den Clip-Ausschnitt (Template) nach fester Hüllkurvenregel:\n"
            "Peak der tieffrequenten Hüllkurve, davon -0,3 s bis zum Abklingen\n"
            "auf 10% der Peak-Hüllkurve (min. +0,8 s, max. +2,5 s).\n"
            "Deterministisch und für alle Ereignisse identisch - dieselbe Regel,\n"
            "keine Optimierung auf das Korrelationsergebnis."
        )
        self.btn_auto_template.clicked.connect(self.auto_set_template)
        self.btn_reset_region = QPushButton("↺ Suchfenster zurücksetzen")
        self.btn_reset_region.clicked.connect(self.reset_region_to_coarse_window)
        self.btn_reset_clip_region = QPushButton("↺ Clip-Ausschnitt zurücksetzen (voller Clip)")
        self.btn_reset_clip_region.clicked.connect(self.reset_clip_region_to_full)
        row.addWidget(self.btn_correlate)
        row.addWidget(self.btn_sweep)
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

        row.addWidget(QLabel("Suchfenster-Marge (s):"))
        self.txt_search_margin = QLineEdit("30")
        self.txt_search_margin.setMaximumWidth(60)
        self.txt_search_margin.setToolTip(
            "Beim 'Suchfenster zurücksetzen' wird das Fenster auf Trigger-Zeitpunkt "
            "± diese Marge gesetzt. Der tatsächliche Uhren-Versatz zwischen Handy "
            "und Jetson ist nicht bekannt/gemessen - bei Bedarf hier vergrößern, "
            "falls der echte Impuls in Waveform 1 außerhalb der gelben Region liegt."
        )
        row.addWidget(self.txt_search_margin)
        return row

    def _build_spectral_row(self):
        row = QHBoxLayout()

        self.btn_spectral_similarity = QPushButton("🔊 Spektrale Ähnlichkeit")
        self.btn_spectral_similarity.setToolTip(
            "Alternative zur zeitbasierten Kreuzkorrelation: vergleicht NICHT die "
            "Form der Wellenform, sondern das Betragsspektrum in einem festen "
            "Frequenzband. Robuster gegen dispersionsbedingte Formverzerrung durch "
            "die Wand. WICHTIG: Diese Metrik ist noch nicht kalibriert - mehrere "
            "Fehlpaarungen sammeln, bevor ein Schwellenwert als 'belastbar' gilt."
        )
        self.btn_spectral_similarity.clicked.connect(self.run_spectral_similarity)
        row.addWidget(self.btn_spectral_similarity)

        row.addWidget(QLabel("Frequenzband (Hz):"))
        self.txt_band_fmin = QLineEdit("300")
        self.txt_band_fmin.setMaximumWidth(70)
        row.addWidget(self.txt_band_fmin)
        row.addWidget(QLabel("bis"))
        self.txt_band_fmax = QLineEdit("8000")
        self.txt_band_fmax.setMaximumWidth(70)
        row.addWidget(self.txt_band_fmax)

        row.addSpacing(20)
        self.chk_show_spectrograms = QCheckBox("Spektrogramme anzeigen")
        self.chk_show_spectrograms.stateChanged.connect(self._on_toggle_spectrograms)
        row.addWidget(self.chk_show_spectrograms)

        self.btn_update_spectrograms = QPushButton("🖼 Spektrogramme aktualisieren")
        self.btn_update_spectrograms.clicked.connect(self.update_spectrograms)
        row.addWidget(self.btn_update_spectrograms)

        row.addStretch(1)
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

        # Ergebnis-Markierung auf Plot 1: zeigt NACH einer Kreuzkorrelation, wo
        # genau das Template (region2) am besten gepasst hat - exakt in dessen
        # Breite. Bewusst NICHT interaktiv (movable=False), damit sie nicht mit
        # dem vom Nutzer gesetzten Suchfenster (region1) verwechselt/verschoben
        # werden kann. region1 selbst bleibt dadurch nach einer Korrelation
        # komplett unverändert stehen - kein Springen/Neuzentrieren mehr nötig,
        # der Treffer liegt ja garantiert innerhalb des durchsuchten Bereichs.
        match_brush = pg.mkBrush(0, 255, 0, 90)
        match_pen = pg.mkPen(color=(0, 255, 0), width=2)
        self.match_region = pg.LinearRegionItem(brush=match_brush, pen=match_pen, movable=False)
        self.match_region.setZValue(10)  # über der gelben Suchfenster-Region zeichnen
        self.match_region.hide()
        self.plot1.addItem(self.match_region)

        # Marker für alle kurzen Clips auf Plot 1 - anklickbar zur Auswahl
        self.clip_markers = pg.ScatterPlotItem(
            size=14, symbol='t1', pen=pg.mkPen('w', width=1),
            brush=pg.mkBrush(255, 165, 0, 220)
        )
        self.clip_markers.sigClicked.connect(self.on_marker_clicked)
        self.plot1.addItem(self.clip_markers)

        # Timeline-Blöcke: jeder kurze Clip als halbtransparenter Block in seiner
        # realen zeitlichen Ausdehnung auf Plot 1. Inaktive Clips grau, der
        # aktuell gewählte farbig. Zweck: Auf einen Blick sichtbar machen, dass
        # die Serie der Empfangsereignisse dem dokumentierten Anregungsschema
        # folgt - und dass ALLE Clips der Session im Bild sind (kein Ereignis
        # "herausgepickt"). Die Blockbreite entspricht der realen Clip-Dauer,
        # damit die Proportion Clip vs. Pause visuell stimmt.
        self.clip_blocks_inactive = pg.BarGraphItem(
            x0=[], x1=[], y0=-1.0, height=2.0,
            brush=pg.mkBrush(150, 150, 150, 45),
            pen=pg.mkPen(170, 170, 170, 90),
        )
        self.clip_blocks_inactive.setZValue(-10)  # hinter Waveform und Regionen
        self.plot1.addItem(self.clip_blocks_inactive)

        self.clip_block_selected = pg.BarGraphItem(
            x0=[], x1=[], y0=-1.0, height=2.0,
            brush=pg.mkBrush(0, 200, 255, 55),
            pen=pg.mkPen(0, 220, 255, 160),
        )
        self.clip_block_selected.setZValue(-9)
        self.plot1.addItem(self.clip_block_selected)

        self.clip_time_labels = []  # TextItems (HH:MM:SS) je Block, unten im Plot

        # Doppelklick auf einen Block wählt den zugehörigen Clip aus. Bewusst
        # Doppelklick statt Einfachklick, damit die Auswahl nicht mit dem
        # Verschieben der gelben Suchfenster-Region kollidiert.
        self.plot1.scene().sigMouseClicked.connect(self._on_plot1_double_clicked)

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
        self.load_session_folder(folder)

    def load_session_folder(self, folder) -> bool:
        """Lädt einen Session-Ordner programmatisch (ohne Dateidialog).

        Öffentliche Schnittstelle für die Integration in andere Tools (z.B.
        Start aus dem Noisy Neighbourhood Studio heraus) sowie für den
        Kommandozeilen-Aufruf `python main.py <session_ordner>`.
        Gibt True zurück, wenn die Session vollständig geladen wurde."""
        try:
            self.session = SessionScanner(folder)
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Ordner konnte nicht gelesen werden:\n{e}")
            return False

        if self.session.remote_wav_path is None:
            QMessageBox.warning(self, "Nichts gefunden",
                                 "Keine remote_clip_*.wav in diesem Ordner gefunden.")
            return False
        if self.session.remote_start_epoch is None:
            QMessageBox.warning(self, "JSON fehlt",
                                 "Kein .json mit 'calculated_server_start_time_ms' zur langen "
                                 "Aufnahme gefunden - zeitliche Zuordnung nicht möglich.")
            return False

        try:
            self.remote_clip = load_remote_as_audioclip(
                self.session.remote_wav_path, self.session.remote_start_epoch,
                os.path.basename(self.session.remote_wav_path)
            )
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Fehler beim Laden der langen Aufnahme:\n{e}")
            return False

        n_found = len(self.session.clips)
        self.lbl_folder.setText(f"{os.path.basename(folder)}  —  {n_found} kurze Clip(s) gefunden")

        self._plot_remote()
        self._plot_clip_markers()
        self._populate_clip_dropdown()
        return True

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
        self._update_clip_timeline()

    # ------------------------------------------------------------------
    # Timeline-Darstellung aller Clips auf Plot 1
    # ------------------------------------------------------------------
    def _clip_block_bounds(self, entry):
        """Zeitliche Ausdehnung eines Clips für die Timeline-Darstellung.

        Vor dem Laden ist nur der Trigger-Zeitstempel bekannt - der Block wird
        dann mit der nominalen Clip-Länge um den Trigger gelegt (gleiche
        Annahme wie load_clip_as_audioclip). Für den aktuell geladenen Clip
        werden stattdessen dessen echte Grenzen verwendet."""
        if (self.selected_clip is not None
                and self.selected_clip.file_name == entry.filename):
            c = self.selected_clip
            return c.start_epoch, c.start_epoch + c.duration
        start = entry.epoch - CLIP_NOMINAL_DURATION_S * CLIP_PRE_TRIGGER_FRACTION
        return start, start + CLIP_NOMINAL_DURATION_S

    def _update_clip_timeline(self):
        """Blöcke und Zeitstempel-Labels für alle Clips (neu) zeichnen; der
        aktuell gewählte Clip farbig, alle anderen grau."""
        if self.session is None:
            return

        for lbl in self.clip_time_labels:
            self.plot1.removeItem(lbl)
        self.clip_time_labels = []

        x0_inactive, x1_inactive = [], []
        x0_selected, x1_selected = [], []
        for i, entry in enumerate(self.session.clips):
            b0, b1 = self._clip_block_bounds(entry)
            selected = (i == self._selected_clip_index)
            if selected:
                x0_selected.append(b0)
                x1_selected.append(b1)
            else:
                x0_inactive.append(b0)
                x1_inactive.append(b1)

            dt_local = datetime.datetime.fromtimestamp(entry.epoch, tz=BERLIN)
            color = (0, 220, 255) if selected else (170, 170, 170)
            lbl = pg.TextItem(dt_local.strftime("%H:%M:%S"), color=color, anchor=(0.5, 1.0))
            lbl.setPos((b0 + b1) / 2.0, -0.98)
            lbl.setZValue(-8)
            self.plot1.addItem(lbl)
            self.clip_time_labels.append(lbl)

        self.clip_blocks_inactive.setOpts(x0=x0_inactive, x1=x1_inactive, y0=-1.0, height=2.0)
        self.clip_block_selected.setOpts(x0=x0_selected, x1=x1_selected, y0=-1.0, height=2.0)

    def _on_plot1_double_clicked(self, ev):
        """Doppelklick auf einen Timeline-Block in Waveform 1 wählt den Clip aus."""
        if not ev.double() or self.session is None:
            return
        vb = self.plot1.getPlotItem().vb
        if not vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        x = vb.mapSceneToView(ev.scenePos()).x()
        for i, entry in enumerate(self.session.clips):
            b0, b1 = self._clip_block_bounds(entry)
            if b0 <= x <= b1:
                self.combo_clips.blockSignals(True)
                self.combo_clips.setCurrentIndex(i)
                self.combo_clips.blockSignals(False)
                self.select_clip(i)
                break

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
        self._selected_clip_index = idx
        self._update_clip_timeline()

        t = clip.start_epoch + np.linspace(0, clip.duration, num=len(clip.data))
        if self.curve2 is None:
            self.curve2 = self.plot2.plot(t, clip.data, pen=pg.mkPen('c', width=1))
        else:
            self.curve2.setData(t, clip.data)
        self.plot2.setTitle(f"Waveform 2: {clip.file_name} (Empfangsraum / Jetson)")

        # Clip-Ausschnitt (region2) IMMER auf den neu gewählten Clip ausrichten -
        # ein alter Auswahlstand von einem zeitlich weit entfernten Clip hat sonst
        # keine Bedeutung mehr. Der sichtbare Zoombereich selbst wird NICHT mehr
        # hier separat gesetzt (das kollidierte mit dem xLink) - siehe unten,
        # das läuft jetzt einheitlich über die region1-Fits.
        self.reset_clip_region_to_full()

        # Suchfenster (region1): beim allerersten Clip auf den festen Standard
        # setzen, danach immer nur neu zentrieren und dabei die vom Nutzer
        # zuletzt gewählte Breite beibehalten - dadurch springt/schrumpft die
        # Breite nicht mehr bei jedem Clip-Wechsel. Der Zoom (_fit_plot1_view_to_region)
        # gilt wegen xLink automatisch auch für Waveform 2.
        if not self._search_window_initialized:
            self.reset_region_to_coarse_window()
            self._search_window_initialized = True
        else:
            self._recenter_search_window(clip.trigger_epoch)

        self.lbl_result.setText(f"Clip gewählt: {clip.file_name} — bereit zur Kreuzkorrelation.")

        if getattr(self, "chk_show_spectrograms", None) is not None and self.chk_show_spectrograms.isChecked():
            self._draw_spectrogram(self.spec_plot2, self.selected_clip, "Spektrogramm 2 (Empfangsraum)", fit_view=True)

    def reset_clip_region_to_full(self):
        """Clip-Ausschnitt (Plot 2) auf die volle Länge des geladenen Clips setzen."""
        if self.selected_clip is None:
            return
        c = self.selected_clip
        self.region2.setRegion((c.start_epoch, c.start_epoch + c.duration))
        self.match_region.hide()  # altes Ergebnis bezog sich auf ein anderes Template

    def auto_set_template(self):
        """Setzt den Clip-Ausschnitt (Template, region2) automatisch nach einer
        festen Hüllkurvenregel statt per Hand: Peak der (leicht geglätteten)
        Amplitudenhüllkurve finden, davon 0,3 s vor dem Peak bis zum Abklingen
        auf 10% des Peak-Hüllkurvenwerts danach - Länge auf [0,8 s, 2,5 s]
        begrenzt. Deterministisch, für jedes Ereignis identisch angewendet -
        keine Optimierung auf ein Korrelationsergebnis, nur auf die Signalform
        selbst (Anti-Cherry-Picking: die Regel wählt, nicht das Auge)."""
        if self.selected_clip is None:
            QMessageBox.information(self, "Kein Clip geladen",
                                     "Bitte zuerst einen Clip auswählen.")
            return
        c = self.selected_clip
        sr = c.sample_rate
        data = np.asarray(c.data, dtype=np.float64)

        win = max(1, int(round(sr * 0.005)))  # 5 ms Glättung
        kernel = np.ones(win) / win
        envelope = np.convolve(np.abs(data), kernel, mode='same')

        peak_idx = int(np.argmax(envelope))
        peak_val = envelope[peak_idx]
        if peak_val < 1e-9:
            QMessageBox.warning(self, "Kein Ereignis erkennbar",
                                 "Die Hüllkurve enthält kein erkennbares Maximum.")
            return

        threshold = peak_val * 0.10
        end_idx = len(envelope) - 1
        for i in range(peak_idx, len(envelope)):
            if envelope[i] < threshold:
                end_idx = i
                break

        start_idx = max(0, peak_idx - int(round(sr * 0.3)))

        min_len = int(round(sr * 0.8))
        max_len = int(round(sr * 2.5))
        length = end_idx - start_idx
        if length < min_len:
            end_idx = min(len(data), start_idx + min_len)
        elif length > max_len:
            end_idx = start_idx + max_len

        start_idx = max(0, start_idx)
        end_idx = min(len(data), end_idx)
        if end_idx - start_idx < 10:
            QMessageBox.warning(self, "Template zu schmal",
                                 "Die automatische Erkennung ergab ein zu schmales Fenster.")
            return

        t_start = c.start_epoch + start_idx / sr
        t_end = c.start_epoch + end_idx / sr
        self.region2.setRegion((t_start, t_end))
        self.match_region.hide()

        self.lbl_result.setText(
            f"Template automatisch gesetzt: {end_idx - start_idx} Samples "
            f"({(end_idx - start_idx) / sr:.2f}s), Peak bei {(peak_idx / sr):.3f}s im Clip."
        )

    def reset_region_to_coarse_window(self):
        """Suchfenster auf Plot 1 = Trigger-Zeitpunkt des Clips ± Sicherheitsmarge.
        Expliziter Reset auf die feste Standardbreite - im Unterschied zu
        _recenter_search_window(), das die aktuell gewählte Breite beibehält."""
        if self.selected_clip is None:
            return
        coarse_ts = self.selected_clip.trigger_epoch
        margin = self._get_search_margin_seconds()
        self.region1.setRegion((coarse_ts - margin, coarse_ts + margin))
        self._fit_plot1_view_to_region()
        self.match_region.hide()  # altes Ergebnis bezog sich auf ein anderes Suchfenster

    def _get_search_margin_seconds(self, default=30.0):
        text = self.txt_search_margin.text().strip()
        try:
            value = float(text)
            return value if value > 0 else default
        except ValueError:
            return default

    def _recenter_search_window(self, center_epoch):
        """Verschiebt das Suchfenster (region1) auf eine neue Mitte, behält aber
        die zuletzt gewählte Breite bei. Basis für konsistentes Verhalten sowohl
        beim Clip-Wechsel als auch nach einer Kreuzkorrelation - das Fenster
        springt/schrumpft dadurch nicht mehr unvorhersehbar."""
        current_start, current_end = self.region1.getRegion()
        width = current_end - current_start
        if width <= 1.0:  # unsinnig schmal (z.B. Qt-Default direkt nach Erzeugen)
            width = 2 * self._get_search_margin_seconds()
        self.region1.setRegion((center_epoch - width / 2.0, center_epoch + width / 2.0))
        self._fit_plot1_view_to_region()

    def _fit_plot1_view_to_region(self, padding_factor=0.5):
        """Stellt sicher, dass das komplette Suchfenster (region1) auch wirklich
        im sichtbaren Bereich von Waveform 1 liegt, statt vom aktuellen Zoom
        abgeschnitten zu werden."""
        start, end = self.region1.getRegion()
        pad = (end - start) * padding_factor
        self.plot1.setXRange(start - pad, end + pad, padding=0)

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

    def _extract_current_windows(self, shift_seconds=0.0, quiet=False):
        """Liefert (remote_window, clip_arr) genauso, wie die Kreuzkorrelation
        sie verwenden würde - optional mit zeitlich verschobenem Suchfenster
        (shift_seconds != 0 dient der Fehlpaarungs-Referenz: gleicher Clip,
        aber ein Fensterbereich, in dem der echte Impuls sicher NICHT liegt).
        Gibt None zurück, wenn die Voraussetzungen fehlen; quiet unterdrückt
        dabei die Dialogmeldungen (für automatische Referenzversuche)."""
        if self.remote_clip is None or self.selected_clip is None:
            if not quiet:
                QMessageBox.information(self, "Daten unvollständig",
                                         "Bitte zuerst einen Ordner laden und einen Clip auswählen.")
            return None

        sr = self.remote_clip.sample_rate
        clip_arr = self._get_clip_windowed_data()
        if len(clip_arr) < 10:
            if not quiet:
                QMessageBox.warning(self, "Clip-Ausschnitt zu schmal",
                                     "Der cyanfarbene Ausschnitt in Waveform 2 ist zu schmal.")
            return None

        region_start, region_end = self.region1.getRegion()
        region_start += shift_seconds
        region_end += shift_seconds

        idx_start = int(round((region_start - self.remote_clip.start_epoch) * sr))
        idx_end = int(round((region_end - self.remote_clip.start_epoch) * sr))
        pad_samples = int(round((idx_end - idx_start) * 0.025))
        idx_start = max(0, idx_start - pad_samples)
        idx_end = min(len(self.remote_clip.data), idx_end + pad_samples)

        if idx_end - idx_start < len(clip_arr):
            if not quiet:
                QMessageBox.warning(self, "Suchfenster ungeeignet",
                                     "Das (ggf. verschobene) Suchfenster liegt außerhalb der "
                                     "langen Aufnahme oder ist schmaler als der Clip-Ausschnitt.")
            return None

        return self.remote_clip.data[idx_start:idx_end], clip_arr

    # ------------------------------------------------------------------
    # Frequenz-Sweep: Übereinstimmung über viele Tiefpass-Grenzfrequenzen
    # ------------------------------------------------------------------
    SWEEP_CUTOFFS_HZ = [8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28,
                        30, 32, 34, 36, 38, 40, 45, 50, 55, 60]

    def _ensure_sweep_window(self):
        """Erzeugt das (nicht-modale) Sweep-Fenster beim ersten Bedarf."""
        if getattr(self, "_sweep_dialog", None) is not None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Frequenz-Sweep: Übereinstimmung vs. Tiefpass-Grenzfrequenz")
        dlg.resize(820, 520)
        layout = QVBoxLayout(dlg)

        self._sweep_plot = pg.PlotWidget()
        self._sweep_plot.setBackground('k')
        self._sweep_plot.showGrid(x=True, y=True)
        self._sweep_plot.setLabel('bottom', 'Tiefpass-Grenzfrequenz (Hz)')
        self._sweep_plot.setLabel('left', 'Übereinstimmung (%)')
        self._sweep_plot.setYRange(0, 100)
        self._sweep_legend = self._sweep_plot.addLegend(offset=(10, 10))
        layout.addWidget(self._sweep_plot)

        # Zufallsniveau der Methode als gestrichelte Referenzlinie - Kurven
        # sind erst OBERHALB dieser Linie trennscharf.
        self._sweep_refline = pg.InfiniteLine(
            pos=76.0, angle=0,
            pen=pg.mkPen((200, 200, 200), width=1, style=pg.QtCore.Qt.DashLine),
            label="Zufallsniveau ~76%", labelOpts={"color": (200, 200, 200), "position": 0.05},
        )
        self._sweep_plot.addItem(self._sweep_refline)

        btn_row = QHBoxLayout()
        self._sweep_chk_mismatch = QCheckBox("Fehlpaarungs-Referenz mitzeichnen")
        self._sweep_chk_mismatch.setChecked(True)
        self._sweep_chk_mismatch.setToolTip(
            "Zeichnet zusätzlich denselben Sweep für ein um ±90 s verschobenes "
            "Suchfenster (dort liegt der echte Impuls sicher nicht) - zeigt, wo "
            "das Zufallsniveau für genau diesen Clip liegt."
        )
        btn_clear = QPushButton("Kurven löschen")
        btn_clear.clicked.connect(self._clear_sweep_curves)
        btn_row.addWidget(self._sweep_chk_mismatch)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_clear)
        layout.addLayout(btn_row)

        self._sweep_dialog = dlg
        self._sweep_curve_count = 0

    def _clear_sweep_curves(self):
        self._sweep_plot.clear()
        try:
            self._sweep_legend.clear()
        except Exception:
            pass
        self._sweep_plot.addItem(self._sweep_refline)
        self._sweep_curve_count = 0

    def _pick_mismatch_shift(self):
        """Wählt die Verschiebung für das Fehlpaarungs-Referenzfenster.

        Kandidaten: Anfang der Aufnahme, Ende der Aufnahme, ±90 s. Gültig ist
        ein Kandidat nur, wenn das verschobene Fenster (a) vollständig in der
        Aufnahme liegt, (b) den Trigger-Zeitpunkt des Clips nicht enthält und
        (c) eine Mindestlücke zum Originalfenster hat - ein direkt benachbartes
        Fenster ist KEINE Fehlpaarung (Nachhall, gleiche Hintergrundsituation).
        Unter den gültigen Kandidaten gewinnt der mit der größten Lücke."""
        r_start, r_end = self.region1.getRegion()
        width = r_end - r_start
        rec_start = self.remote_clip.start_epoch
        rec_end = rec_start + self.remote_clip.duration
        min_gap = max(5.0, 1.0 * width)

        # Ein Referenzfenster darf KEINEN bekannten Anregungszeitpunkt enthalten -
        # nicht nur den des gewählten Clips: Enthält es einen anderen Klingeldruck
        # derselben Session, matcht die "Fehlpaarung" zu Recht (gleiche Quelle,
        # gleicher Übertragungsweg) und ist als Zufallsreferenz wertlos.
        # Sicherheitsmarge um jeden Trigger: halbe nominale Clip-Länge + 2 s Nachhall.
        guard = CLIP_NOMINAL_DURATION_S * 0.5 + 2.0
        all_triggers = [c.epoch for c in self.session.clips] if self.session else []

        candidates = []
        for target_start in (rec_start, rec_end - width, r_start - 90.0, r_start + 90.0):
            s, e = target_start, target_start + width
            if s < rec_start - 1e-6 or e > rec_end + 1e-6:
                continue
            gap = max(r_start - e, s - r_end)  # Lücke zwischen den Fenstern
            if gap < min_gap:
                continue
            if any(s - guard <= trig <= e + guard for trig in all_triggers):
                continue
            candidates.append((gap, target_start - r_start))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    def run_frequency_sweep(self):
        """Sweep für den aktuell gewählten Clip rechnen und als Kurve anhängen.
        Mehrfach für verschiedene Clips aufrufen -> Kurven überlagern sich;
        liegen die Maxima im selben Band, ist das direkt sichtbar."""
        pair = self._extract_current_windows()
        if pair is None:
            return
        remote_window, clip_arr = pair
        sr = self.remote_clip.sample_rate

        self._ensure_sweep_window()
        self._sweep_plot.setTitle("")  # evtl. Hinweis vom vorherigen Lauf entfernen
        self.lbl_result.setText("Berechne Frequenz-Sweep (8-60 Hz)... Bitte warten.")
        QApplication.processEvents()

        try:
            cutoffs, sims = sweep_similarity(remote_window, clip_arr, sr, self.SWEEP_CUTOFFS_HZ)
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Frequenz-Sweep fehlgeschlagen:\n{e}")
            return

        entry = self.session.clips[self._selected_clip_index]
        dt_local = datetime.datetime.fromtimestamp(entry.epoch, tz=BERLIN)
        label = dt_local.strftime("%H:%M:%S")

        color = pg.intColor(self._sweep_curve_count, hues=9, values=1)
        self._sweep_plot.plot(
            cutoffs, sims * 100.0,
            pen=pg.mkPen(color, width=2),
            symbol='o', symbolSize=5, symbolBrush=color, symbolPen=None,
            name=label,
        )
        self._sweep_curve_count += 1

        # Fehlpaarungs-Referenz: gleicher Clip, aber Suchfenster an einer
        # maximal entfernten Stelle der Aufnahme, an der der echte Impuls
        # sicher nicht liegt (siehe _pick_mismatch_shift).
        if self._sweep_chk_mismatch.isChecked():
            shift = self._pick_mismatch_shift()
            if shift is None:
                self._sweep_plot.setTitle(
                    f"Hinweis ({label}): keine gültige Fehlpaarungs-Referenz möglich "
                    "(Aufnahme zu kurz oder alle entfernten Fensterlagen enthalten Anregungen)."
                )
            else:
                pair_ref = self._extract_current_windows(shift_seconds=shift, quiet=True)
                if pair_ref is not None:
                    ref_window, _ = pair_ref
                    try:
                        _, sims_ref = sweep_similarity(ref_window, clip_arr, sr, self.SWEEP_CUTOFFS_HZ)
                        self._sweep_plot.plot(
                            cutoffs, sims_ref * 100.0,
                            pen=pg.mkPen((160, 160, 160), width=1, style=pg.QtCore.Qt.DashLine),
                            name=f"{label} Fehlpaarung ({shift:+.0f}s)",
                        )
                    except Exception:
                        pass

        best_idx = int(np.argmax(sims))
        self.lbl_result.setText(
            f"Sweep {label}: Maximum {sims[best_idx]*100:.1f}% bei {cutoffs[best_idx]:.0f} Hz "
            f"| Kurve #{self._sweep_curve_count} im Sweep-Fenster"
        )
        self._sweep_dialog.show()
        self._sweep_dialog.raise_()

    # ------------------------------------------------------------------
    # Spektrogramme (Studio-artige Ansicht, an Waveform 1/2 gekoppelt)
    # ------------------------------------------------------------------
    def _on_toggle_spectrograms(self, _state):
        visible = self.chk_show_spectrograms.isChecked()
        self.spec_plot1.setVisible(visible)
        self.spec_plot2.setVisible(visible)
        if visible:
            self.update_spectrograms()

    @staticmethod
    def _spectrogram_colormap():
        try:
            return pg.colormap.get('inferno', source='matplotlib')
        except Exception:
            # Fallback ohne Matplotlib-Abhaengigkeit: inferno-aehnlicher Verlauf.
            stops = [0.0, 0.3, 0.6, 0.85, 1.0]
            colors = [(0, 0, 4), (87, 16, 110), (188, 55, 84), (249, 142, 9), (252, 255, 164)]
            return pg.ColorMap(stops, colors)

    def _draw_spectrogram(self, plot_widget, audio_clip, title, fit_view=False):
        """Berechnet und zeichnet ein Spektrogramm (dB-Skala, inferno-artige
        Farbgebung wie in der Studio-Ansicht) für einen kompletten AudioClip.
        X-Achse in Epoch-Sekunden - deckt sich mit der Zeitachse der
        zugehörigen Waveform (xLink synchronisiert Pan/Zoom automatisch)."""
        data = np.asarray(audio_clip.data, dtype=np.float64)
        sr = audio_clip.sample_rate
        if len(data) < 32:
            return
        nperseg = int(min(512, max(64, len(data) // 8)))
        noverlap = int(nperseg * 0.75)
        f, t, Sxx = sp_signal.spectrogram(data, fs=sr, nperseg=nperseg, noverlap=noverlap)
        Sxx_db = 10.0 * np.log10(Sxx + 1e-12)

        Sxx_db_display = sp_ndimage.gaussian_filter(Sxx_db, sigma=(1.0, 1.0))

        vmax = float(np.percentile(Sxx_db_display, 99.5))
        vmin = float(np.percentile(Sxx_db_display, 85.0))
        if vmax - vmin < 6.0:
            vmin = vmax - 6.0

        plot_widget.clear()
        img = pg.ImageItem(Sxx_db_display.T)  # ImageItem erwartet Achse0=x(Zeit), Achse1=y(Frequenz)
        img.setLevels((vmin, vmax))
        img.setColorMap(self._spectrogram_colormap())
        t0 = audio_clip.start_epoch + (t[0] if len(t) else 0.0)
        width = (t[-1] - t[0]) if len(t) > 1 else max(len(data) / sr, 0.01)
        height = (f[-1] - f[0]) if len(f) > 1 else sr / 2.0
        img.setRect(pg.QtCore.QRectF(t0, f[0] if len(f) else 0.0, width, height))
        plot_widget.addItem(img)
        plot_widget.setTitle(title)
        if fit_view:
            plot_widget.setXRange(t0, t0 + max(width, 0.01), padding=0.02)

    def update_spectrograms(self):
        """Zeichnet beide Spektrogramme neu - der langen Aufnahme (falls
        geladen) und des aktuell gewählten kurzen Clips (falls gewählt)."""
        if self.remote_clip is not None:
            self._draw_spectrogram(self.spec_plot1, self.remote_clip,
                                   "Spektrogramm 1 (Senderaum)")
        if self.selected_clip is not None:
            self._draw_spectrogram(self.spec_plot2, self.selected_clip,
                                   "Spektrogramm 2 (Empfangsraum)", fit_view=True)

    # ------------------------------------------------------------------
    # Spektrale Ähnlichkeit - Alternative zur zeitbasierten Kreuzkorrelation
    # ------------------------------------------------------------------
    def _get_band_hz(self):
        def _parse(txt, default):
            try:
                v = float(txt.strip())
                return v if v >= 0 else default
            except ValueError:
                return default
        fmin = _parse(self.txt_band_fmin.text(), 300.0)
        fmax = _parse(self.txt_band_fmax.text(), 8000.0)
        if fmax <= fmin:
            fmax = fmin + 100.0
        return fmin, fmax

    def run_spectral_similarity(self):
        """Vergleicht Template und Suchfenster über das Betragsspektrum in
        einem festen Frequenzband statt über die Form der Wellenform im
        Zeitbereich (siehe spectral_similarity_search in causality_analyzer.py) -
        robuster gegen dispersionsbedingte Formverzerrung durch die Wand."""
        pair = self._extract_current_windows()
        if pair is None:
            return
        remote_window, clip_arr = pair
        sr = self.remote_clip.sample_rate
        fmin, fmax = self._get_band_hz()

        self.lbl_result.setText(
            f"Berechne spektrale Ähnlichkeit [{fmin:.0f}-{fmax:.0f} Hz]... Bitte warten."
        )
        QApplication.processEvents()

        try:
            res = spectral_similarity_search(remote_window, clip_arr, sr, fmin=fmin, fmax=fmax)
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Spektrale Ähnlichkeit fehlgeschlagen:\n{e}")
            return

        # Fehlpaarungs-Referenz: dieselbe Methode auf einem Fenster, in dem
        # der echte Impuls sicher nicht liegt (gleiche Logik wie beim Sweep).
        ref_text = ""
        shift = self._pick_mismatch_shift()
        if shift is not None:
            pair_ref = self._extract_current_windows(shift_seconds=shift, quiet=True)
            if pair_ref is not None:
                ref_window, _ = pair_ref
                try:
                    res_ref = spectral_similarity_search(ref_window, clip_arr, sr, fmin=fmin, fmax=fmax)
                    ref_text = f" | Fehlpaarung ({shift:+.0f}s): {res_ref['best_similarity']*100:.1f}%"
                except Exception:
                    pass

        # Absolute Fundstelle: Fensterstart (inkl. desselben 2,5%-Paddings wie
        # in _extract_current_windows) + gefundener Offset innerhalb der Suche.
        region_start, region_end = self.region1.getRegion()
        idx_start = int(round((region_start - self.remote_clip.start_epoch) * sr))
        pad_samples = int(round((region_end - region_start) * sr * 0.025))
        idx_start = max(0, idx_start - pad_samples)
        window_start_epoch = self.remote_clip.start_epoch + idx_start / sr
        match_epoch = window_start_epoch + res["best_offset_samples"] / sr
        clip_duration = res["n_template"] / sr

        dt_match = datetime.datetime.fromtimestamp(match_epoch, tz=BERLIN)
        warn_text = f" | ⚠ {res['warning']}" if res.get("warning") else ""
        self.lbl_result.setText(
            f"[Spektral {fmin:.0f}-{fmax:.0f} Hz] Fein-Start: {dt_match.strftime('%H:%M:%S.%f')[:-3]} | "
            f"Spektrale Übereinstimmung: {res['best_similarity']*100:.1f}%{ref_text} "
            f"(Zufallsniveau dieser Metrik noch nicht kalibriert!){warn_text}"
        )

        self.match_region.setRegion((match_epoch, match_epoch + clip_duration))
        self.match_region.show()

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

        # Interne Sicherheitsmarge: das tatsächlich durchsuchte Fenster ist 5%
        # größer als das markierte, damit ein Treffer nahe am Rand der Markierung
        # nicht abgeschnitten wird. Die sichtbare gelbe Markierung selbst bleibt
        # unverändert - das ist rein ein interner Suchspielraum.
        pad_samples = int(round((idx_end - idx_start) * 0.025))
        idx_start -= pad_samples
        idx_end += pad_samples

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
        # Bewertung am gemessenen Referenzrahmen der Methode orientiert: nicht
        # zusammenhängende Signalpaare erreichen nach Tiefpass-Filterung bereits
        # ~0.76 (Zufallsniveau) - erst deutlich darüber ist ein Treffer
        # trennscharf. Kausal bestätigte Paare lagen bisher bei >= 0.95.
        if result.similarity >= 0.90:
            guete = "belastbar"
        elif result.similarity >= 0.70:
            guete = "nicht trennscharf (Zufallsniveau ~76%)"
        else:
            guete = "kein Zusammenhang erkennbar"

        filt_info = f"Tiefpass {cutoff_hz:.0f} Hz" if cutoff_hz else "ungefiltert"
        result_text = (
            f"[{filt_info}] Fein-Start: {dt_match.strftime('%H:%M:%S.%f')[:-3]} | "
            f"Impuls-Versatz (Peak-zu-Peak): {result.peak_to_peak_delay*1000:+.1f} ms | "
            f"Δ Template-Start: {result.delay_vs_template_start:+.4f} s | "
            f"Übereinstimmung: {result.similarity*100:.1f}% ({guete})"
        )
        self.lbl_result.setText(result_text)

        # Fundstelle als eigene, nicht-interaktive Markierung zeigen - EXAKT so
        # breit wie der unten markierte Clip-Ausschnitt (Template). Das
        # Suchfenster (region1) bleibt dabei komplett unangetastet, dadurch
        # auch kein erzwungener Zoom/Sprung mehr nötig - der Treffer liegt ja
        # garantiert innerhalb des gerade durchsuchten Bereichs.
        self.match_region.setRegion((result.match_start_epoch, result.match_start_epoch + clip_duration))
        self.match_region.show()