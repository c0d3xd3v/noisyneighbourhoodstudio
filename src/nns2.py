# -*- coding: utf-8 -*-
import csv
import json
import os
import shutil
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QPushButton, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QListWidget, QListWidgetItem, QFileDialog
)
from PySide6.QtGui import QPainter, QColor, QPolygon, QGuiApplication
from PySide6.QtCore import QTimer, QTime, QPoint, Qt, QUrl
from PySide6 import QtCore
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices

import pyqtgraph as pg
import numpy as np
import soundfile as sf
from scipy.signal import spectrogram

from PySide6.QtGui import QTransform

QGuiApplication.setAttribute(Qt.AA_UseDesktopOpenGL)

# === Audio-Konfiguration ===
media_player = None
audio_output = None
current_audio_file = ""

# === Verzeichnisstruktur ===
data_root = "/home/kaih/Downloads/data/"
FAVORITES_FILE = os.path.join(data_root, "favorites.json")

# === Favoriten laden/speichern ===
def load_favorites():
    if not os.path.exists(FAVORITES_FILE):
        return []
    try:
        with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_favorites(favs):
    try:
        with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump(favs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern der Favoriten: {e}")

# === GUI aufbauen ===
app = QApplication([])
main_widget = QWidget()
main_layout = QHBoxLayout()
main_widget.setLayout(main_layout)

# --- Linke Seite: Tabs ---
left_tab_widget = QTabWidget()

# Tab 1: Session-Tree
session_tree_tab = QWidget()
session_tree_layout = QVBoxLayout()
session_tree_tab.setLayout(session_tree_layout)

session_tree = QTreeWidget()
session_tree.setHeaderLabels(["Datum", "Session"])
delete_button = QPushButton("🗑 Session löschen")
session_tree_layout.addWidget(session_tree)
session_tree_layout.addWidget(delete_button)

left_tab_widget.addTab(session_tree_tab, "📁 Sessions")

# Tab 2: Favoriten
favorites_tab = QWidget()
favorites_layout = QVBoxLayout()
favorites_tab.setLayout(favorites_layout)

favorites_list = QListWidget()
favorites_list.setToolTip("Klick zum Laden des Favoriten")
remove_fav_button = QPushButton("✖ Favorit entfernen")
favorites_layout.addWidget(QLabel("⭐ Gespeicherte Favoriten"))
favorites_layout.addWidget(favorites_list)
favorites_layout.addWidget(remove_fav_button)

left_tab_widget.addTab(favorites_tab, "⭐ Favoriten")

main_layout.addWidget(left_tab_widget, 1)

# --- Rechte Seite: Content ---
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

spectrogram_plot = pg.PlotWidget()
spectrogram_img = pg.ImageItem()
spectrogram_plot.addItem(spectrogram_img)
spectrogram_plot.setLabel('bottom', 'Zeit (s)')
spectrogram_plot.setLabel('left', 'Frequenz (Hz)')
spectrogram_plot.setTitle("Spektrogramm")
spectrogram_plot.enableAutoRange(x=False, y=False)

info_label = QLabel("Wähle links eine Session")
play_button = QPushButton("▶️ Abspielen")
play_button.setEnabled(False)

fav_button = QPushButton("⭐ Als Favorit speichern")
fav_button.setEnabled(False)

content_layout.addWidget(plot_widget)
content_layout.addWidget(info_label)
content_layout.addWidget(play_button)
content_layout.addWidget(fav_button)

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
current_clip_filename = ""   # NEU: für Favoriten
playback_line = None

# === QMediaPlayer initialisieren ===
media_player = QMediaPlayer()
audio_output = QAudioOutput()
media_player.setAudioOutput(audio_output)
audio_output.setVolume(0.8)

# === Hilfsfunktionen ===
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
    mapping = {}
    if not os.path.exists(filepath):
        return mapping
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            if len(parts) == 2:
                dataset_file = os.path.basename(parts[0]).strip()
                sample_file = os.path.basename(parts[1]).strip()
                mapping[dataset_file] = sample_file
    return mapping

def render_waveform_and_spectrogram(fname):
    """Lädt eine WAV-Datei und zeichnet Waveform + Spektrogramm."""
    global last_audio_data, last_samplerate, current_audio_file
    if not os.path.exists(fname):
        waveform_plot.clear()
        spectrogram_plot.clear()
        play_button.setEnabled(False)
        save_button.setEnabled(False)
        fav_button.setEnabled(False)
        return False

    data, samplerate = sf.read(fname)
    if data.ndim > 1:
        data = data[:, 0]

    waveform_plot.clear()
    waveform_plot.plot(np.arange(len(data)) / samplerate, data, pen='c')

    f, t, Sxx = spectrogram(data, samplerate, nperseg=1024, noverlap=512)
    Sxx_dB = 10 * np.log10(Sxx + 1e-10)

    import matplotlib.pyplot as plt
    lut = (plt.get_cmap("inferno")(np.linspace(0, 1, 256))[:, :3] * 255).astype(np.uint8)
    spectrogram_img.setLookupTable(lut)
    spectrogram_img.setImage(Sxx_dB.T, levels=(Sxx_dB.min(), Sxx_dB.max()))

    dx = t[1] - t[0]
    dy = f[1] - f[0]
    transform = QTransform()
    transform.translate(t[0], f[0])
    transform.scale(dx, dy)
    spectrogram_img.setTransform(transform)

    spectrogram_plot.addItem(spectrogram_img)
    
    # 1. Die Kamera aktiv auf das Zeitfenster und exakt 0 bis 1000 Hz einstellen
    spectrogram_plot.setXRange(t[0], t[-1], padding=0)
    spectrogram_plot.setYRange(0, 1000, padding=0)
    
    # 2. Die harten Grenzen setzen (wohin der Nutzer maximal scrollen/zoomen darf)
    spectrogram_plot.setLimits(
        xMin=t[0], 
        xMax=t[-1], 
        yMin=0, 
        yMax=1000
    )
    
    # 3. AutoRange deaktivieren, damit der manuelle Zoom des Nutzers danach funktioniert
    spectrogram_plot.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=False)

    last_audio_data = data
    last_samplerate = samplerate
    current_audio_file = fname
    play_button.setEnabled(True)
    save_button.setEnabled(True)
    fav_button.setEnabled(True)
    return True

def on_click(plot, points):
    global current_clip_filename
    for p in points:
        ts_index = x_values.index(p.pos().x())
        clip_filename = filenames[ts_index]
        fname = os.path.join(current_waveform_dir, clip_filename)
        if render_waveform_and_spectrogram(fname):
            current_clip_filename = clip_filename
            trigger_time_dt = timestamps[ts_index].time()
            trigger_time_qt = QTime(trigger_time_dt.hour, trigger_time_dt.minute, trigger_time_dt.second)
            clock_widget.set_time(trigger_time_qt)
            ts_str = timestamps[ts_index].strftime("%Y-%m-%d %H:%M:%S")
            db_str = f"{db_values[ts_index]:.1f} dB"
            info_label.setText(f"📍 {ts_str}  |  {db_str}  |  {clip_filename}")

def update_cursor_position(position_ms):
    global playback_line
    if playback_line and playback_line in waveform_plot.items():
        playback_line.setPos(position_ms / 1000.0)

def play_waveform():
    global playback_line
    if last_audio_data is None or not current_audio_file:
        return
    stop_playback()
    waveform_plot.clear()
    time_axis = np.arange(len(last_audio_data)) / last_samplerate
    waveform_plot.plot(time_axis, last_audio_data, pen='c')
    playback_line = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=pg.mkPen('r', width=2))
    waveform_plot.addItem(playback_line)

    current_default_device = QMediaDevices.defaultAudioOutput()
    audio_output.setDevice(current_default_device)
    media_player.setSource(QUrl.fromLocalFile(current_audio_file))
    
    try:
        media_player.positionChanged.disconnect()
    except:
        pass
    media_player.positionChanged.connect(update_cursor_position)
    media_player.play()
    play_button.setEnabled(False)
    info_label.setText("🔊 Wiedergabe läuft...")

def stop_playback():
    global playback_line
    if media_player.playbackState() == QMediaPlayer.PlayingState:
        media_player.stop()
    try:
        media_player.positionChanged.disconnect()
    except:
        pass
    play_button.setEnabled(True)
    if playback_line and playback_line in waveform_plot.items():
        waveform_plot.removeItem(playback_line)
        playback_line = None

def load_session(session_path, highlight_clip=None):
    """Lädt eine Session und normalisiert die Dynamik strikt von 0 bis 1."""
    global timestamps, db_values, filenames, x_values, scatter, current_waveform_dir
    csv_file = os.path.join(session_path, "trigger_log.csv")
    current_waveform_dir = session_path
    timestamps, db_values, filenames = read_csv(csv_file)

    if not timestamps:
        return

    x_values = [ts.timestamp() for ts in timestamps]
    trigger_plot.clear()
    waveform_plot.clear()
    spectrogram_plot.clear()
    stop_playback()
    play_button.setEnabled(False)
    save_button.setEnabled(False)
    fav_button.setEnabled(False)

    # --- NEU: Dynamik auf 0 bis (max - min) verschieben ---
    max_db = max(db_values)
    min_db = min(db_values)
    db_range = max_db - min_db

    # Falls alle Werte exakt gleich sind (keine Dynamik)
    if db_range == 0:
        y_relative = [0.0 for _ in db_values]  # Setze auf 0 als Fallback
    else:
        # Formel: Wert - Minimum (Skala läuft nun von 0 bis db_range)
        y_relative = [db - min_db for db in db_values]
    # -----------------------------------------------------

    # 1. Optische Baseline bei 0 einzeichnen (Der leiseste Punkt der Session)
    baseline_0 = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen('w', width=1.5, style=pg.QtCore.Qt.PenStyle.DashLine))
    trigger_plot.addItem(baseline_0)
    
    # Optische Decke bei max-min einzeichnen (Der lauteste Punkt der Session)
    baseline_max = pg.InfiniteLine(pos=db_range, angle=0, pen=pg.mkPen('r', width=1, style=pg.QtCore.Qt.PenStyle.DashLine))
    trigger_plot.addItem(baseline_max)

    # 2. Plot mit den normalisierten Werten zeichnen
    trigger_plot.plot(x_values, y_relative, pen=pg.mkPen('y', width=2))
    scatter = pg.ScatterPlotItem(x=x_values, y=y_relative, symbol='o', size=10, brush='r')

    assignments = load_assignments(os.path.join(session_path, "zuordnung.txt"))
    for i, (x, y_rel, fname) in enumerate(zip(x_values, y_relative, filenames)):
        sample_name = assignments.get(fname, "")
        if sample_name:
            label = pg.TextItem(sample_name, anchor=(0, 1), color='w', fill=pg.mkBrush(0, 0, 0, 150))
            label.setPos(x, y_rel)
            trigger_plot.addItem(label)

    if highlight_clip:
        for i, fname in enumerate(filenames):
            if fname == highlight_clip:
                highlight = pg.ScatterPlotItem(
                    x=[x_values[i]], y=[y_relative[i]],
                    symbol='star', size=18,
                    brush=pg.mkBrush(255, 215, 0),
                    pen=pg.mkPen('w', width=1)
                )
                highlight.setZValue(1000)
                trigger_plot.addItem(highlight)
                break

    scatter.sigClicked.connect(on_click)
    trigger_plot.addItem(scatter)
    
    # Grenzen des Plots dynamisch festlegen (basierend auf db_range)
    trigger_plot.setXRange(min(x_values), max(x_values))
    trigger_plot.setYRange(-0.05 * db_range if db_range > 0 else -1, db_range * 1.05 if db_range > 0 else 1)
    
    # Achsen-Beschriftung anpassen
    trigger_plot.setLabel('left', 'Dynamik-Verlauf', units='dB (relativ)')
    
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
        ts_list, db_list, _ = read_csv(os.path.join(session_path, "trigger_log.csv"))
        if not ts_list:
            continue
        date_str = ts_list[0].strftime("%Y-%m-%d")
        time_start = ts_list[0].strftime("%H:%M")
        time_end = ts_list[-1].strftime("%H:%M")
        display_name = f"{time_start} – {time_end} ({len(ts_list)} Trigger)"
        sessions_by_date.setdefault(date_str, []).append((display_name, session_path))
    for date, sessions in sorted(sessions_by_date.items()):
        date_item = QTreeWidgetItem([date])
        for label, path in sessions:
            child = QTreeWidgetItem(["", label])
            child.setData(0, Qt.UserRole, path)
            date_item.addChild(child)
        session_tree.addTopLevelItem(date_item)
        date_item.setExpanded(True)

# === Favoriten-Funktionen ===
def populate_favorites_list():
    favorites_list.clear()
    favs = load_favorites()
    for fav in favs:
        label = f"⭐ {fav['timestamp']}  |  {fav['db']:.1f} dB  |  {fav['clip_filename']}"
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, fav)
        favorites_list.addItem(item)

def add_current_as_favorite():
    global current_clip_filename, current_waveform_dir
    if not current_clip_filename or not current_waveform_dir:
        return

    # Metadaten aus aktuellem State holen
    try:
        idx = filenames.index(current_clip_filename)
        ts_str = timestamps[idx].strftime("%Y-%m-%d %H:%M:%S")
        db_val = db_values[idx]
    except (ValueError, IndexError):
        ts_str = "unbekannt"
        db_val = 0.0

    fav = {
        "session_path": current_waveform_dir,
        "clip_filename": current_clip_filename,
        "timestamp": ts_str,
        "db": db_val
    }

    favs = load_favorites()
    # Duplikate vermeiden
    for existing in favs:
        if existing["session_path"] == fav["session_path"] and existing["clip_filename"] == fav["clip_filename"]:
            QMessageBox.information(main_widget, "Bereits vorhanden", "Dieser Clip ist bereits in den Favoriten.")
            return

    favs.append(fav)
    save_favorites(favs)
    populate_favorites_list()
    left_tab_widget.setCurrentIndex(1)  # Zum Favoriten-Tab wechseln
    QMessageBox.information(main_widget, "Favorit gespeichert", f"Clip wurde zu den Favoriten hinzugefügt:\n{ts_str}")

def on_favorite_clicked(item):
    fav = item.data(Qt.UserRole)
    if not fav:
        return
    session_path = fav["session_path"]
    clip_filename = fav["clip_filename"]

    # Session laden mit Highlight des Favoriten-Clips
    load_session(session_path, highlight_clip=clip_filename)

    # Waveform + Spektrogramm direkt laden
    fname = os.path.join(session_path, clip_filename)
    if render_waveform_and_spectrogram(fname):
        global current_clip_filename
        current_clip_filename = clip_filename
        info_label.setText(f"⭐ Favorit: {fav['timestamp']}  |  {fav['db']:.1f} dB  |  {clip_filename}")

        # Uhr setzen
        try:
            dt = datetime.strptime(fav["timestamp"], "%Y-%m-%d %H:%M:%S")
            clock_widget.set_time(QTime(dt.hour, dt.minute, dt.second))
        except Exception:
            pass

def remove_selected_favorite():
    item = favorites_list.currentItem()
    if not item:
        return
    fav = item.data(Qt.UserRole)
    reply = QMessageBox.question(
        main_widget, "Favorit entfernen",
        f"Favorit '{fav.get('timestamp', '')}' wirklich entfernen?",
        QMessageBox.Yes | QMessageBox.No
    )
    if reply == QMessageBox.Yes:
        favs = load_favorites()
        favs = [f for f in favs if not (
            f["session_path"] == fav["session_path"] and
            f["clip_filename"] == fav["clip_filename"]
        )]
        save_favorites(favs)
        populate_favorites_list()

def save_current_clip():
    if last_audio_data is None or last_samplerate is None:
        QMessageBox.warning(main_widget, "Kein Clip", "Kein Audioclip geladen.")
        return
    save_path, _ = QFileDialog.getSaveFileName(
        main_widget, "Clip speichern als...", "clip.wav", "WAV-Dateien (*.wav)"
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
    reply = QMessageBox.question(
        main_widget, "Löschen",
        f"Session '{session_path}' wirklich löschen?",
        QMessageBox.Yes | QMessageBox.No
    )
    if reply == QMessageBox.Yes:
        shutil.rmtree(session_path)
        populate_session_tree()

# === Signalverbindungen ===
session_tree.itemClicked.connect(on_tree_item_clicked)
delete_button.clicked.connect(delete_selected_session)
play_button.clicked.connect(play_waveform)
save_button.clicked.connect(save_current_clip)
fav_button.clicked.connect(add_current_as_favorite)
favorites_list.itemClicked.connect(on_favorite_clicked)
remove_fav_button.clicked.connect(remove_selected_favorite)
app.aboutToQuit.connect(stop_playback)

populate_session_tree()
populate_favorites_list()

main_widget.setWindowTitle("Noisy Neighbourhood Studio")
main_widget.resize(1300, 850)
main_widget.show()
app.exec()
