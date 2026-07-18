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
import tempfile
from typing import Dict, Optional, Tuple

import soundfile as sf
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QListWidget, QListWidgetItem,
    QFileDialog, QComboBox, QProgressBar, QDoubleSpinBox,
)
from PySide6.QtCore import Qt, QUrl, QTime, QThread
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices

import session_repository
import metric_cache
import audio_filter
from models import SessionData, FavoriteEntry
from metrics import MetricRegistry, MetricResult
from metric_worker import MetricWorker
from plot_view import TriggerPlotWidget
from audio_render import AudioRenderWidget
from clock_widget import AnalogClockWidget

from causality_tool_interface import launch_kausaltool


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Noisy Neighbourhood Studio")
        self.resize(1300, 850)

        self.current_session: Optional[SessionData] = None
        self.current_event_index: Optional[int] = None
        self.current_metric_key: str = MetricRegistry.default_key()

        self._metric_thread: Optional[QThread] = None
        self._metric_worker: Optional[MetricWorker] = None
        self._pending_highlight_index: Optional[int] = None
        self._pending_cache_key: Optional[Tuple[str, str]] = None

        # Metrik-Ergebnisse pro (Session-Pfad, Metrik-Schlüssel) - erspart
        # das Neuberechnen beim Hin- und Herschalten zwischen Metriken.
        # Geht davon aus, dass Sessions nach dem Aufnehmen unverändert bleiben.
        self._metric_cache: Dict[Tuple[str, str], MetricResult] = {}

        self.media_player: Optional[QMediaPlayer] = None
        self.audio_output: Optional[QAudioOutput] = None
        self._filtered_temp_path: Optional[str] = None

        self._build_ui()
        self._wire_signals()
        self._on_filter_type_changed()

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

        toolbar_layout = QHBoxLayout()
        self.btn_kausal = QPushButton("🔗 Kausalanalyse öffnen")
        self.btn_kausal.setEnabled(False)  # ausgegraut, bis eine passende Session geladen ist
        self.btn_kausal.setToolTip(
            "Öffnet das Session-Kausalitätstool für die geladene Session.\n"
            "Nur verfügbar, wenn eine lange Handy-Aufnahme (remote_clip_*.wav\n"
            "mit .json-Metadaten) im Session-Ordner liegt."
        )
        toolbar_layout.addWidget(self.btn_kausal)
        content_layout.addLayout(toolbar_layout)

        # Metrik-Auswahl - hier kommt später einfach ein weiterer Eintrag rein
        metric_row = QHBoxLayout()
        metric_row.addWidget(QLabel("Metrik:"))
        self.metric_combo = QComboBox()
        for metric in MetricRegistry.all():
            self.metric_combo.addItem(metric.display_name, userData=metric.key)
        metric_row.addWidget(self.metric_combo)

        self.metric_progress = QProgressBar()
        self.metric_progress.setVisible(False)
        self.metric_progress.setFixedWidth(200)
        self.metric_progress.setFormat("%v / %m")
        metric_row.addWidget(self.metric_progress)

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

        # Filter-Vorschau für die Wiedergabe - wirkt nur auf's Anhören,
        # Waveform/Spektrogramm oben zeigen weiterhin das unveränderte Original
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))

        self.filter_type_combo = QComboBox()
        self.filter_type_combo.addItem("Tiefpass", userData=audio_filter.LOWPASS)
        self.filter_type_combo.addItem("Hochpass", userData=audio_filter.HIGHPASS)
        self.filter_type_combo.addItem("Bandpass", userData=audio_filter.BANDPASS)
        filter_row.addWidget(self.filter_type_combo)

        self.filter_cutoff_low = QDoubleSpinBox()
        self.filter_cutoff_low.setRange(1.0, 24000.0)
        self.filter_cutoff_low.setValue(300.0)
        self.filter_cutoff_low.setSuffix(" Hz")
        filter_row.addWidget(self.filter_cutoff_low)

        self.filter_cutoff_high_label = QLabel("bis")
        filter_row.addWidget(self.filter_cutoff_high_label)

        self.filter_cutoff_high = QDoubleSpinBox()
        self.filter_cutoff_high.setRange(1.0, 24000.0)
        self.filter_cutoff_high.setValue(3000.0)
        self.filter_cutoff_high.setSuffix(" Hz")
        filter_row.addWidget(self.filter_cutoff_high)

        self.filter_play_button = QPushButton("🎚 Gefiltert abspielen")
        self.filter_play_button.setEnabled(False)
        filter_row.addWidget(self.filter_play_button)

        filter_row.addStretch()
        content_layout.addLayout(filter_row)

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

        self.filter_type_combo.currentIndexChanged.connect(self._on_filter_type_changed)
        self.filter_play_button.clicked.connect(self._play_filtered_clip)

        self.favorites_list.itemClicked.connect(self._on_favorite_clicked)
        self.remove_fav_button.clicked.connect(self._remove_selected_favorite)

        self.btn_kausal.clicked.connect(self._on_open_kausaltool)

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
        self.filter_play_button.setEnabled(False)
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

    # ------------------------------------------------------------- ToolBar

    def _on_open_kausaltool(self):
        launch_kausaltool(self.current_session.session_path)

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

        for metric_key, result in metric_cache.load(self.current_session).items():
            self._metric_cache[(session_path, metric_key)] = result

        self._stop_playback()
        self.play_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.fav_button.setEnabled(False)
        self.filter_play_button.setEnabled(False)

        highlight_index = None
        if highlight_clip:
            for i, event in enumerate(self.current_session.events):
                if event.clip_filename == highlight_clip:
                    highlight_index = i
                    break

        if self.current_session.has_remote_clip is True:
            self.btn_kausal.setEnabled(True)
        else:
            self.btn_kausal.setEnabled(False)

        self._render_plot_async(highlight_index)
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
            self._invalidate_metric_cache(session_path)
            self._populate_session_tree()

    def _invalidate_metric_cache(self, session_path: str):
        keys_to_remove = [key for key in self._metric_cache if key[0] == session_path]
        for key in keys_to_remove:
            del self._metric_cache[key]
        # kein metric_cache.clear() nötig - die Cache-Datei liegt im
        # Session-Ordner und wird durch shutil.rmtree() bereits mit gelöscht

    # -------------------------------------------------------------- Metrik

    def _render_plot_async(self, highlight_index: Optional[int] = None):
        if self.current_session is None or self.current_session.is_empty:
            return
        if self._metric_thread is not None:
            return  # eine Berechnung läuft schon - Anfrage ignorieren statt überlappen

        cache_key = (self.current_session.session_path, self.current_metric_key)
        cached_result = self._metric_cache.get(cache_key)
        if cached_result is not None:
            self.plot_widget.render(self.current_session, cached_result, highlight_index)
            return

        metric = MetricRegistry.get(self.current_metric_key)

        self._set_busy(True)
        self.metric_progress.setVisible(True)
        self.metric_progress.setMinimum(0)
        self.metric_progress.setMaximum(len(self.current_session))
        self.metric_progress.setValue(0)

        self._pending_highlight_index = highlight_index
        self._pending_cache_key = cache_key

        thread = QThread(self)
        worker = MetricWorker(metric, self.current_session)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_metric_progress)
        worker.finished.connect(self._on_metric_finished)
        worker.failed.connect(self._on_metric_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_metric_thread_finished)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._metric_thread = thread
        self._metric_worker = worker
        thread.start()

    def _on_metric_progress(self, done: int, total: int):
        self.metric_progress.setMaximum(total)
        self.metric_progress.setValue(done)

    def _on_metric_finished(self, result):
        if self._pending_cache_key is not None:
            self._metric_cache[self._pending_cache_key] = result
            _session_path, metric_key = self._pending_cache_key
            metric_cache.save_one(self.current_session, metric_key, result)
        self.plot_widget.render(self.current_session, result, self._pending_highlight_index)
        self._pending_highlight_index = None
        self._pending_cache_key = None

    def _on_metric_failed(self, message: str):
        QMessageBox.critical(self, "Fehler bei Metrik-Berechnung", message)

    def _on_metric_thread_finished(self):
        self.metric_progress.setVisible(False)
        self._set_busy(False)
        self._metric_thread = None
        self._metric_worker = None

    def _set_busy(self, busy: bool):
        """Sperrt Navigation, solange eine Metrik-Berechnung im Hintergrund läuft -
        verhindert überlappende Berechnungen und Klicks auf inzwischen veraltete Daten."""
        for widget in (self.metric_combo, self.session_tree, self.favorites_list,
                       self.import_button, self.delete_button,
                       self.project_button, self.project_combo):
            widget.setEnabled(not busy)

    def _on_metric_changed(self, _index: int):
        self.current_metric_key = self.metric_combo.currentData()
        self._render_plot_async(self.current_event_index)

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
        self.filter_play_button.setEnabled(True)

    # ------------------------------------------------------------ Playback

    def _ensure_media_player(self):
        """Erzeugt QMediaPlayer/QAudioOutput erst beim ersten Abspielen, nicht
        beim Programmstart - vermeidet, dass der FFmpeg-Multimedia-Backend
        beim Konstruieren bereits interne Threads/Timer anlegt, bevor das
        Hauptfenster überhaupt sichtbar ist (siehe Crash-Report)."""
        if self.media_player is not None:
            return
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)
        self.media_player.positionChanged.connect(self.audio_render.update_playback_cursor)
        self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)

    def _on_playback_state_changed(self, state):
        """Reagiert sowohl auf natürliches Ende des Clips als auch auf
        explizites Stoppen - ohne das würden die Play-Buttons nach dem
        ersten Durchlauf dauerhaft deaktiviert bleiben."""
        if state != QMediaPlayer.PlayingState:
            self.audio_render.clear_playback_cursor()
            self.play_button.setEnabled(self.current_event_index is not None)
            self.filter_play_button.setEnabled(self.current_event_index is not None)

    def _play_current_clip(self):
        data, _sr = self.audio_render.last_audio
        if data is None or self.current_session is None or self.current_event_index is None:
            return
        self._ensure_media_player()
        self._stop_playback()

        self.audio_render.show_playback_cursor()

        event = self.current_session.events[self.current_event_index]
        self.audio_output.setDevice(QMediaDevices.defaultAudioOutput())
        self.media_player.setSource(QUrl.fromLocalFile(event.audio_path))
        self.media_player.play()

        self.play_button.setEnabled(False)
        self.filter_play_button.setEnabled(False)
        self.info_label.setText("🔊 Wiedergabe läuft...")

    def _stop_playback(self):
        if self.media_player is not None and self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.stop()
        self.audio_render.clear_playback_cursor()
        self.play_button.setEnabled(self.current_event_index is not None)
        self.filter_play_button.setEnabled(self.current_event_index is not None)

    def _on_filter_type_changed(self):
        is_bandpass = self.filter_type_combo.currentData() == audio_filter.BANDPASS
        self.filter_cutoff_high_label.setEnabled(is_bandpass)
        self.filter_cutoff_high.setEnabled(is_bandpass)

    def _play_filtered_clip(self):
        data, sr = self.audio_render.last_audio
        if data is None or self.current_session is None or self.current_event_index is None:
            return

        filter_type = self.filter_type_combo.currentData()
        cutoff_low = self.filter_cutoff_low.value()
        cutoff_high = self.filter_cutoff_high.value() if filter_type == audio_filter.BANDPASS else None

        try:
            filtered = audio_filter.apply_filter(data, sr, filter_type, cutoff_low, cutoff_high)
        except Exception as e:
            QMessageBox.critical(self, "Filterfehler", str(e))
            return

        self._ensure_media_player()
        self._stop_playback()
        self._cleanup_filtered_temp_file()

        fd, temp_path = tempfile.mkstemp(suffix=".wav", prefix="nns_filtered_")
        os.close(fd)
        sf.write(temp_path, filtered, sr)
        self._filtered_temp_path = temp_path

        self.audio_render.show_playback_cursor()

        self.audio_output.setDevice(QMediaDevices.defaultAudioOutput())
        self.media_player.setSource(QUrl.fromLocalFile(temp_path))
        self.media_player.play()

        self.filter_play_button.setEnabled(False)
        self.play_button.setEnabled(False)
        label = self.filter_type_combo.currentText()
        cutoff_text = f"{cutoff_low:.0f} Hz" if cutoff_high is None else f"{cutoff_low:.0f}–{cutoff_high:.0f} Hz"
        self.info_label.setText(f"🎚 Gefilterte Wiedergabe ({label}, {cutoff_text}) — Original bleibt in Waveform/Spektrogramm unverändert")

    def _cleanup_filtered_temp_file(self):
        if self._filtered_temp_path and os.path.exists(self._filtered_temp_path):
            try:
                os.remove(self._filtered_temp_path)
            except OSError:
                pass
        self._filtered_temp_path = None

    # ------------------------------------------------------------ Speichern

    def _save_current_clip(self):
        data, samplerate = self.audio_render.last_audio
        if data is None:
            QMessageBox.warning(self, "Kein Clip", "Kein Audioclip geladen.")
            return
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
        self._cleanup_filtered_temp_file()
        if self._metric_thread is not None:
            self._metric_thread.quit()
            self._metric_thread.wait(3000)
        super().closeEvent(event)