# -*- coding: utf-8 -*-
import csv
import os
import shutil
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QPushButton, QMessageBox, QTreeWidget, QTreeWidgetItem
)
from PySide6.QtGui import QPainter, QColor, QPolygon
from PySide6.QtCore import QTimer, QTime, QPoint, Qt
from PySide6 import QtCore

from PySide6.QtWidgets import QFileDialog

import pyqtgraph as pg
import numpy as np
import soundfile as sf
import sounddevice as sd
from time import perf_counter
from scipy.signal import spectrogram

from PySide6.QtGui import QTransform

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QGuiApplication

QGuiApplication.setAttribute(Qt.AA_UseDesktopOpenGL)

# === Audio-Konfiguration ===
audio_stream = None
playback_start_time = 0
#sd.default.device = 13
#sd.default.device = 'pulse'

# === Verzeichnisstruktur ===
data_root = "data_2026"

# === GUI aufbauen ===
app = QApplication([])
main_widget = QWidget()
main_layout = QHBoxLayout()
main_widget.setLayout(main_layout)

session_tree = QTreeWidget()
session_tree.setHeaderLabels(["Datum", "Session"])
delete_button = QPushButton("Session löschen")

playback_line = None
playback_timer = QTimer()
playback_position = 0

session_button_layout = QVBoxLayout()
session_button_widget = QWidget()
session_button_widget.setLayout(session_button_layout)
session_button_layout.addWidget(session_tree)
session_button_layout.addWidget(delete_button)
main_layout.addWidget(session_button_widget, 1)

content_widget = QWidget()
content_layout = QVBoxLayout()
content_widget.setLayout(content_layout)
main_layout.addWidget(content_widget, 4)

plot_widget = pg.GraphicsLayoutWidget()
trigger_plot = plot_widget.addPlot(axisItems={'bottom': pg.DateAxisItem()})
trigger_plot.setTitle("Trigger-Pegelverlauf (dB)")
trigger_plot.setLabel('left', 'Trigger dB')
trigger_plot.setLabel('bottom', 'Zeit')
trigger_plot.showGrid(x=True, y=True)
trigger_plot.enableAutoRange(x=False, y=False)

waveform_plot = pg.PlotWidget(title="Waveform")
waveform_plot.setLabel('left', 'Amplitude')
waveform_plot.setLabel('bottom', 'Zeit (s)')
waveform_plot.showGrid(x=True, y=True)
waveform_plot.setFixedHeight(160)

#spectrogram_plot = pg.ImageView()
spectrogram_plot = pg.PlotWidget()
spectrogram_img = pg.ImageItem()
spectrogram_plot.addItem(spectrogram_img)
spectrogram_plot.setLabel('bottom', 'Zeit (s)')
spectrogram_plot.setLabel('left', 'Frequenz (Hz)')
spectrogram_plot.setTitle("Spektrogramm")
#spectrogram_plot.ui.roiBtn.hide()
#spectrogram_plot.ui.menuBtn.hide()
spectrogram_plot.enableAutoRange(x=False, y=False)

info_label = QLabel("Wähle links eine Session")
play_button = QPushButton("▶️ Abspielen")
play_button.setEnabled(False)

content_layout.addWidget(plot_widget)
content_layout.addWidget(info_label)
content_layout.addWidget(play_button)

save_button = QPushButton("💾 Clip speichern")
save_button.setEnabled(False)
content_layout.addWidget(save_button)

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

waveform_and_spectrogram = QVBoxLayout()
waveform_and_spectrogram.addWidget(waveform_plot)
waveform_and_spectrogram.addWidget(spectrogram_plot)

clock_widget = AnalogClockWidget()
clock_and_waveform = QHBoxLayout()
clock_and_waveform.addLayout(waveform_and_spectrogram, 4)
clock_and_waveform.addWidget(clock_widget, 1)
content_layout.addLayout(clock_and_waveform)

timestamps = []
db_values = []
filenames = []
x_values = []
scatter = None
current_waveform_dir = ""
last_audio_data = None
last_samplerate = None

def read_csv(csv_file):
    ts, db, fn = [], [], []
    if not os.path.exists(csv_file):
        return ts, db, fn
    with open(csv_file, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts.append(datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S.%f"))
                db.append(float(row["trigger_db"]))
                fn.append(row.get("clip_filename", "").strip())
            except Exception:
                continue
    return ts, db, fn

def load_assignments(filepath="zuordnung.txt"):
    print(filepath)
    mapping = {}
    if not os.path.exists(filepath):
        print("not exist")
        return mapping
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            print(parts)
            if len(parts) == 2:
                dataset_file = os.path.basename(parts[0]).strip()
                sample_file = os.path.basename(parts[1]).strip()
                mapping[dataset_file] = sample_file
    return mapping

def on_click(plot, points):
    global last_audio_data, last_samplerate
    for p in points:
        ts_index = x_values.index(p.pos().x())
        clip_filename = filenames[ts_index]
        fname = os.path.join(current_waveform_dir, clip_filename)
        if not os.path.exists(fname):
            waveform_plot.clear()
            spectrogram_plot.clear()
            play_button.setEnabled(False)
            return
        print(fname)
        data, samplerate = sf.read(fname)
        if data.ndim > 1:
            data = data[:, 0]
        waveform_plot.clear()
        waveform_plot.plot(np.arange(len(data)) / samplerate, data, pen='c')
        f, t, Sxx = spectrogram(data, samplerate, nperseg=1024, noverlap=512)
        Sxx_dB = 10 * np.log10(Sxx + 1e-10)

        # === Optional: inferno Farbpalette ===
        import matplotlib.pyplot as plt
        lut = (plt.get_cmap("inferno")(np.linspace(0, 1, 256))[:, :3] * 255).astype(np.uint8)
        spectrogram_img.setLookupTable(lut)

        # === Spektrogramm-Bild setzen ===
        spectrogram_img.setImage(Sxx_dB.T, levels=(Sxx_dB.min(), Sxx_dB.max()))
        dx = t[1] - t[0]
        dy = f[1] - f[0]
        transform = QTransform()
        transform.translate(t[0], f[0])
        transform.scale(dx, dy)
        spectrogram_img.setTransform(transform)

        # === Ansicht korrekt einstellen ===
        spectrogram_plot.setLimits(xMin=t[0], xMax=t[-1], yMin=f[0], yMax=f[-1])
        #spectrogram_plot.setXRange(t[0], t[-1], padding=0.01)
        #spectrogram_plot.setYRange(f[0], f[-1], padding=0.01)
        spectrogram_plot.enableAutoRange(False)

        spectrogram_plot.addItem(spectrogram_img)

        # Debug
        print("Sxx_dB range:", Sxx_dB.min(), "to", Sxx_dB.max())
        print("t range:", t[0], "to", t[-1])
        print("f range:", f[0], "to", f[-1])
        '''
        spectrogram_plot.setImage(Sxx_dB.T, autoLevels=True, pos=[t[0], f[0]], scale=[t[1] - t[0], f[1] - f[0]])
        spectrogram_plot.setPredefinedGradient("inferno")
        spectrogram_plot.view.setAspectLocked(False)
        #spectrogram_plot.view.enableAutoRange()
        spectrogram_plot.getView().invertY(False)
        '''
        last_audio_data = data
        last_samplerate = samplerate
        play_button.setEnabled(True)
        save_button.setEnabled(True)
        trigger_time_dt = timestamps[ts_index].time()
        trigger_time_qt = QTime(trigger_time_dt.hour, trigger_time_dt.minute, trigger_time_dt.second)
        clock_widget.set_time(trigger_time_qt)

def play_waveform():
    global playback_line, playback_timer, playback_position, playback_start_time, audio_stream

    print("Output device:", sd.default.device)
    print("Samplerate:", last_samplerate)

    if last_audio_data is None or last_samplerate is None:
        return
    play_button.setEnabled(False)
    duration = len(last_audio_data) / last_samplerate
    playback_position = 0
    playback_start_time = perf_counter()
    if playback_line:
        waveform_plot.removeItem(playback_line)
    playback_line = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=pg.mkPen('r', width=2))
    waveform_plot.addItem(playback_line)
    audio_data = last_audio_data.astype(np.float32)

    def callback(outdata, frames, time, status):
        global playback_position
        start = int(playback_position)
        end = start + frames
        if end > len(audio_data):
            outdata[:len(audio_data) - start] = audio_data[start:].reshape(-1, 1)
            outdata[len(audio_data) - start:] = 0
            raise sd.CallbackStop()
        else:
            outdata[:] = audio_data[start:end].reshape(-1, 1)
        playback_position += frames

    try:
        audio_stream = sd.OutputStream(samplerate=last_samplerate, channels=1, dtype='float32', callback=callback)
        audio_stream.start()
    except Exception as e:
        QMessageBox.critical(main_widget, "Audiofehler", str(e))
        return

    def update_line():
        elapsed = perf_counter() - playback_start_time
        if elapsed > duration:
            stop_playback()
            return
        playback_line.setPos(elapsed)

    playback_timer.timeout.connect(update_line)
    playback_timer.start(1)

def stop_playback():
    global playback_timer, playback_line, audio_stream
    if audio_stream:
        audio_stream.stop()
        audio_stream.close()
        audio_stream = None
    playback_timer.stop()
    play_button.setEnabled(True)
    if playback_line:
        waveform_plot.removeItem(playback_line)
        playback_line = None

def load_session(session_path):
    global timestamps, db_values, filenames, x_values, scatter, current_waveform_dir
    csv_file = os.path.join(session_path, "trigger_log.csv")
    current_waveform_dir = session_path
    timestamps, db_values, filenames = read_csv(csv_file)

    print(f"Lade Session: {session_path}")
    print(f"Timestamps geladen: {len(timestamps)}")
    print(f"dB-Werte geladen: {len(db_values)}")
    print(f"Erste 3 Timestamps: {timestamps[:3]}")
    print(f"Erste 3 dB-Werte: {db_values[:3]}")

    if not timestamps:
        return
    x_values = [ts.timestamp() for ts in timestamps]
    trigger_plot.clear()
    waveform_plot.clear()
    spectrogram_plot.clear()
    play_button.setEnabled(False)
    trigger_plot.plot(x_values, db_values, pen=pg.mkPen('y', width=2))
    scatter = pg.ScatterPlotItem(x=x_values, y=db_values, symbol='o', size=10, brush='r')

    # === Labels neben den Punkten anzeigen ===
    assignments = load_assignments(os.path.join(session_path, "zuordnung.txt"))
    print(assignments)
    for i, (x, db, fname) in enumerate(zip(x_values, db_values, filenames)):
        sample_name = assignments.get(fname, "")
        
        if sample_name:
            label = pg.TextItem(sample_name, anchor=(0, 1), color='w', fill=pg.mkBrush(0, 0, 0, 150))
            label.setPos(x, db)
            trigger_plot.addItem(label)

    scatter.sigClicked.connect(on_click)
    trigger_plot.addItem(scatter)
    #trigger_plot.enableAutoRange('x', True)
    #trigger_plot.enableAutoRange('y', True)
    trigger_plot.setXRange(min(x_values), max(x_values))
    trigger_plot.setYRange(min(db_values), max(db_values))
    print(min(x_values), max(x_values))
    info_label.setText(f"📁 Session: {os.path.basename(session_path)} – {len(x_values)} Trigger")

def populate_session_tree():
    session_tree.clear()
    if not os.path.exists(data_root):
        return
    sessions_by_date = {}
    for session_name in sorted(os.listdir(data_root)):
        session_path = os.path.join(data_root, session_name)
        if not os.path.isdir(session_path):
            continue
        timestamps, db_values, _ = read_csv(os.path.join(session_path, "trigger_log.csv"))
        if not timestamps:
            continue
        date_str = timestamps[0].strftime("%Y-%m-%d")
        time_start = timestamps[0].strftime("%H:%M")
        time_end = timestamps[-1].strftime("%H:%M")
        display_name = f"{time_start} – {time_end} ({len(timestamps)} Trigger)"
        sessions_by_date.setdefault(date_str, []).append((display_name, session_path))
    for date, sessions in sorted(sessions_by_date.items()):
        date_item = QTreeWidgetItem([date])
        for label, path in sessions:
            child = QTreeWidgetItem(["", label])
            child.setData(0, Qt.UserRole, path)
            date_item.addChild(child)
        session_tree.addTopLevelItem(date_item)
        date_item.setExpanded(True)

def save_current_clip():
    if last_audio_data is None or last_samplerate is None:
        QMessageBox.warning(main_widget, "Kein Clip", "Kein Audioclip geladen.")
        return
    save_path, _ = QFileDialog.getSaveFileName(
        main_widget,
        "Clip speichern als...",
        "clip.wav",
        "WAV-Dateien (*.wav)"
    )
    if save_path:
        try:
            sf.write(save_path, last_audio_data, last_samplerate)
            QMessageBox.information(main_widget, "Erfolg", f"Clip gespeichert:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(main_widget, "Fehler beim Speichern", str(e))

def on_tree_item_clicked(item, _):
    session_path = item.data(0, Qt.UserRole)
    if session_path:
        load_session(session_path)

def delete_selected_session():
    item = session_tree.currentItem()
    if not item or not item.parent():
        return
    session_path = item.data(0, Qt.UserRole)
    if not session_path:
        return
    reply = QMessageBox.question(main_widget, "Löschen", f"Session '{session_path}' wirklich löschen?", QMessageBox.Yes | QMessageBox.No)
    if reply == QMessageBox.Yes:
        shutil.rmtree(session_path)
        populate_session_tree()

session_tree.itemClicked.connect(on_tree_item_clicked)
delete_button.clicked.connect(delete_selected_session)
play_button.clicked.connect(play_waveform)
save_button.clicked.connect(save_current_clip)

populate_session_tree()
main_widget.setWindowTitle("Noisy Neighbourhood Studio")
main_widget.resize(1300, 850)
main_widget.show()
app.exec()
