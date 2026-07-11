# -*- coding: utf-8 -*-
"""
main_window.py verdrahtet alle Bausteine:
- session_repository liefert Daten (I/O)
- metrics.MetricRegistry liefert die y-Achse
- plot_view.TriggerPlotWidget zeichnet x/y
- audio_render.AudioRenderWidget zeichnet Waveform/Spektrogramm + Wiedergabecursor
- clock_widget.AnalogClockWidget zeigt die Uhrzeit des angeklickten Events

Dieses Modul selbst enthält keine Berechnungs- oder I/O-Logik, nur Verdrahtung.
"""

import os
import shutil
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QListWidget, QListWidgetItem,
    QFileDialog, QComboBox,
)
from PySide6.QtCore import Qt, QUrl, QTime
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices

import session_repository
from models import SessionData, FavoriteEntry
from metrics import MetricRegistry
from plot_view import TriggerPlotWidget
from audio_render import AudioRenderWidget
from clock_widget import AnalogClockWidget


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Noisy Neighbourhood Studio")
        self.resize(1300, 850)

        self.current_session: Optional[SessionData] = None
        self.current_event_index: Optional[int] = None
        self.current_metric_key: str = MetricRegistry.default_key()

        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)

        self._build_ui()
        self._wire_signals()

        self._populate_project_combo()
        self._update_window_title()
        self._populate_session_tree()
        self._populate_favorites_list()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        main_layout = QHBoxLayout(self)

        # --- linke Seite: Tabs ---
        self.left_tabs = QTabWidget()

        sessions_tab = QWidget()
        sessions_layout = QVBoxLayout(sessions_tab)

        project_row = QHBoxLayout()
        self.project_combo = QComboBox()
        self.project_combo.setToolTip("Zuletzt benutzte Projekte")
        self.project_button = QPushButton("📂 Projekt wechseln...")
        project_row.addWidget(self.project_combo, 1)
        sessions_layout.addLayout(project_row)
        sessions_layout.addWidget(self.project_button)

        self.session_tree = QTreeWidget()
        self.session_tree.setHeaderLabels(["Datum", "Session"])
        self.import_button = QPushButton("📥 Sessions in Projekt importieren...")
        self.delete_button = QPushButton("🗑 Session löschen")
        sessions_layout.addWidget(self.session_tree)
        sessions_layout.addWidget(self.import_button)
        sessions_layout.addWidget(self.delete_button)
        self.left_tabs.addTab(sessions_tab, "📁 Sessions")

        favorites_tab = QWidget()
        favorites_layout = QVBoxLayout(favorites_tab)
        self.favorites_list = QListWidget()
        self.favorites_list.setToolTip("Klick zum Laden des Favoriten")
        self.remove_fav_button = QPushButton("✖ Favorit entfernen")
        favorites_layout.addWidget(QLabel("⭐ Gespeicherte Favoriten"))
        favorites_layout.addWidget(self.favorites_list)
        favorites_layout.addWidget(self.remove_fav_button)
        self.left_tabs.addTab(favorites_tab, "⭐ Favoriten")

        main_layout.addWidget(self.left_tabs, 1)

        # --- rechte Seite: Content ---
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        main_layout.addWidget(content_widget, 4)

        # Metrik-Auswahl - hier kommt später einfach ein weiterer Eintrag rein
        metric_row = QHBoxLayout()
        metric_row.addWidget(QLabel("Metrik:"))
        self.metric_combo = QComboBox()
        for metric in MetricRegistry.all():
            self.metric_combo.addItem(metric.display_name, userData=metric.key)
        metric_row.addWidget(self.metric_combo)
        metric_row.addStretch()
        content_layout.addLayout(metric_row)

        self.plot_widget = TriggerPlotWidget()
        content_layout.addWidget(self.plot_widget.plot_widget)

        self.info_label = QLabel("Wähle links eine Session")
        self.play_button = QPushButton("▶️ Abspielen")
        self.play_button.setEnabled(False)
        self.fav_button = QPushButton("⭐ Als Favorit speichern")
        self.fav_button.setEnabled(False)
        self.save_button = QPushButton("💾 Clip speichern")
        self.save_button.setEnabled(False)

        content_layout.addWidget(self.info_label)
        content_layout.addWidget(self.play_button)
        content_layout.addWidget(self.fav_button)
        content_layout.addWidget(self.save_button)

        self.audio_render = AudioRenderWidget()
        self.clock_widget = AnalogClockWidget()

        clock_and_waveform = QHBoxLayout()
        waveform_and_spectrogram = QVBoxLayout()
        waveform_and_spectrogram.addWidget(self.audio_render.waveform_plot)
        waveform_and_spectrogram.addWidget(self.audio_render.spectrogram_plot)
        clock_and_waveform.addLayout(waveform_and_spectrogram, 4)
        clock_and_waveform.addWidget(self.clock_widget, 1)
        content_layout.addLayout(clock_and_waveform)

    def _wire_signals(self):
        self.session_tree.itemClicked.connect(self._on_tree_item_clicked)
        self.project_button.clicked.connect(self._switch_project)
        self.project_combo.activated.connect(self._on_project_combo_activated)
        self.import_button.clicked.connect(self._import_session_folder)
        self.delete_button.clicked.connect(self._delete_selected_session)
        self.metric_combo.currentIndexChanged.connect(self._on_metric_changed)

        self.plot_widget.set_on_point_clicked(self._on_point_clicked)

        self.play_button.clicked.connect(self._play_current_clip)
        self.save_button.clicked.connect(self._save_current_clip)
        self.fav_button.clicked.connect(self._add_current_as_favorite)

        self.favorites_list.itemClicked.connect(self._on_favorite_clicked)
        self.remove_fav_button.clicked.connect(self._remove_selected_favorite)

        self.media_player.positionChanged.connect(self.audio_render.update_playback_cursor)

    # -------------------------------------------------------------- Projekt

    def _update_window_title(self):
        self.setWindowTitle(f"Noisy Neighbourhood Studio – {session_repository.get_data_root()}")

    def _populate_project_combo(self):
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        current = session_repository.get_data_root()
        for path in session_repository.get_recent_data_roots():
            self.project_combo.addItem(path, userData=path)
        index = self.project_combo.findData(current)
        if index >= 0:
            self.project_combo.setCurrentIndex(index)
        self.project_combo.blockSignals(False)

    def _reset_state_for_new_project(self):
        self.current_session = None
        self.current_event_index = None
        self._stop_playback()
        self.play_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.fav_button.setEnabled(False)
        self.info_label.setText("Wähle links eine Session")

    def _activate_project(self, path: str):
        session_repository.set_data_root(path)
        self._reset_state_for_new_project()
        self._populate_project_combo()
        self._update_window_title()
        self._populate_session_tree()
        self._populate_favorites_list()

    def _switch_project(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Projekt-Ordner auswählen", session_repository.get_data_root()
        )
        if not folder:
            return
        self._activate_project(folder)

    def _on_project_combo_activated(self, _index: int):
        path = self.project_combo.currentData()
        if path and path != session_repository.get_data_root():
            self._activate_project(path)

    # ------------------------------------------------------------- Sessions

    def _populate_session_tree(self):
        self.session_tree.clear()
        sessions_by_date = session_repository.list_sessions_by_date()
        for date, sessions in sorted(sessions_by_date.items()):
            date_item = QTreeWidgetItem([date])
            for label, path in sessions:
                child = QTreeWidgetItem(["", label])
                child.setData(0, Qt.UserRole, path)
                date_item.addChild(child)
            self.session_tree.addTopLevelItem(date_item)
            date_item.setExpanded(True)

    def _on_tree_item_clicked(self, item, _column):
        path = item.data(0, Qt.UserRole)
        if path:
            self._load_session(path)

    def _load_session(self, session_path: str, highlight_clip: Optional[str] = None):
        self.current_session = session_repository.load_session(session_path)
        self.current_event_index = None

        self._stop_playback()
        self.play_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.fav_button.setEnabled(False)

        highlight_index = None
        if highlight_clip:
            for i, event in enumerate(self.current_session.events):
                if event.clip_filename == highlight_clip:
                    highlight_index = i
                    break

        self._render_plot(highlight_index)
        self.info_label.setText(
            f"📁 Session: {self.current_session.session_name} – {len(self.current_session)} Trigger"
        )

    def _import_session_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Sessions-Ordner auswählen")
        if not folder:
            return

        imported = session_repository.import_sessions_from_folder(folder)
        self._populate_session_tree()

        target = session_repository.get_data_root()
        if imported:
            QMessageBox.information(
                self, "Import erfolgreich",
                f"{len(imported)} Session(s) importiert nach:\n{target}\n\n" + "\n".join(imported)
            )
        else:
            QMessageBox.information(
                self, "Nichts importiert",
                "Keine neuen Sessions gefunden (kein trigger_log.csv, "
                "oder alle bereits im aktuellen Projekt vorhanden)."
            )

    def _delete_selected_session(self):
        item = self.session_tree.currentItem()
        if not item or not item.parent():
            return
        session_path = item.data(0, Qt.UserRole)
        if not session_path:
            return
        reply = QMessageBox.question(
            self, "Löschen", f"Session '{session_path}' wirklich löschen?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            shutil.rmtree(session_path)
            self._populate_session_tree()

    # -------------------------------------------------------------- Metrik

    def _render_plot(self, highlight_index: Optional[int] = None):
        if self.current_session is None or self.current_session.is_empty:
            return
        metric = MetricRegistry.get(self.current_metric_key)
        result = metric.compute(self.current_session)
        self.plot_widget.render(self.current_session, result, highlight_index)

    def _on_metric_changed(self, _index: int):
        self.current_metric_key = self.metric_combo.currentData()
        self._render_plot(self.current_event_index)

    # --------------------------------------------------------------- Klick

    def _on_point_clicked(self, index: int):
        if self.current_session is None:
            return
        event = self.current_session.events[index]
        if not self.audio_render.render(event.audio_path):
            return

        self.current_event_index = index
        trigger_time = event.timestamp.time()
        self.clock_widget.set_time(QTime(trigger_time.hour, trigger_time.minute, trigger_time.second))

        ts_str = event.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        self.info_label.setText(f"📍 {ts_str}  |  {event.trigger_db:.1f} dB  |  {event.clip_filename}")

        self.play_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.fav_button.setEnabled(True)

    # ------------------------------------------------------------ Playback

    def _play_current_clip(self):
        data, _sr = self.audio_render.last_audio
        if data is None or self.current_session is None or self.current_event_index is None:
            return
        self._stop_playback()

        self.audio_render.show_playback_cursor()

        event = self.current_session.events[self.current_event_index]
        self.audio_output.setDevice(QMediaDevices.defaultAudioOutput())
        self.media_player.setSource(QUrl.fromLocalFile(event.audio_path))
        self.media_player.play()

        self.play_button.setEnabled(False)
        self.info_label.setText("🔊 Wiedergabe läuft...")

    def _stop_playback(self):
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.stop()
        self.audio_render.clear_playback_cursor()
        self.play_button.setEnabled(self.current_event_index is not None)

    # ------------------------------------------------------------ Speichern

    def _save_current_clip(self):
        data, samplerate = self.audio_render.last_audio
        if data is None:
            QMessageBox.warning(self, "Kein Clip", "Kein Audioclip geladen.")
            return
        import soundfile as sf
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Clip speichern als...", "clip.wav", "WAV-Dateien (*.wav)"
        )
        if save_path:
            try:
                sf.write(save_path, data, samplerate)
                QMessageBox.information(self, "Erfolg", f"Clip gespeichert:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "Fehler beim Speichern", str(e))

    # ------------------------------------------------------------ Favoriten

    def _populate_favorites_list(self):
        self.favorites_list.clear()
        for fav in session_repository.load_favorites():
            label = f"⭐ {fav.timestamp}  |  {fav.db:.1f} dB  |  {fav.clip_filename}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, fav)
            self.favorites_list.addItem(item)

    def _add_current_as_favorite(self):
        if self.current_session is None or self.current_event_index is None:
            return
        event = self.current_session.events[self.current_event_index]

        favorites = session_repository.load_favorites()
        for existing in favorites:
            if existing.session_path == self.current_session.session_path and \
               existing.clip_filename == event.clip_filename:
                QMessageBox.information(self, "Bereits vorhanden", "Dieser Clip ist bereits in den Favoriten.")
                return

        favorites.append(FavoriteEntry(
            session_path=self.current_session.session_path,
            clip_filename=event.clip_filename,
            timestamp=event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            db=event.trigger_db,
        ))
        session_repository.save_favorites(favorites)
        self._populate_favorites_list()
        self.left_tabs.setCurrentIndex(1)
        QMessageBox.information(self, "Favorit gespeichert", "Clip wurde zu den Favoriten hinzugefügt.")

    def _on_favorite_clicked(self, item: QListWidgetItem):
        fav: FavoriteEntry = item.data(Qt.UserRole)
        if not fav:
            return
        self._load_session(fav.session_path, highlight_clip=fav.clip_filename)

        for i, event in enumerate(self.current_session.events):
            if event.clip_filename == fav.clip_filename:
                self._on_point_clicked(i)
                break

        self.info_label.setText(f"⭐ Favorit: {fav.timestamp}  |  {fav.db:.1f} dB  |  {fav.clip_filename}")

    def _remove_selected_favorite(self):
        item = self.favorites_list.currentItem()
        if not item:
            return
        fav: FavoriteEntry = item.data(Qt.UserRole)
        reply = QMessageBox.question(
            self, "Favorit entfernen", f"Favorit '{fav.timestamp}' wirklich entfernen?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            favorites = session_repository.load_favorites()
            favorites = [
                f for f in favorites
                if not (f.session_path == fav.session_path and f.clip_filename == fav.clip_filename)
            ]
            session_repository.save_favorites(favorites)
            self._populate_favorites_list()

    # -------------------------------------------------------------- Qt-Hook

    def closeEvent(self, event):
        self._stop_playback()
        super().closeEvent(event)
