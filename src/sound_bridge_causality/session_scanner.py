"""
Liest einen Session-Ordner (Aufnahme-Session) ein: lange Handy-Aufnahme +
kurze Jetson-Clips, verknüpft über trigger_log.csv. Bewusst UI-frei.
"""

import os
import csv
from dataclasses import dataclass, field
from typing import List, Optional

from audio_io import epoch_from_remote_json, parse_local_berlin_to_epoch, epoch_from_clip_filename


@dataclass
class ClipEntry:
    """Referenz auf einen kurzen Jetson-Clip - nur Metadaten, noch nicht geladen."""
    epoch: float           # Trigger-Zeitstempel (Mitte des Clips, siehe audio_io)
    filename: str
    path: str
    trigger_db: str = ""
    rms: str = ""


@dataclass
class SessionScanner:
    """
    Erwartet einen Session-Ordner mit:
      - remote_clip_*.wav          (lange, kontinuierliche Handy-Aufnahme, Senderaum)
      - remote_clip_*.wav.json     (enthält calculated_server_start_time_ms)
      - clip_*.wav                 (kurze 6s-Jetson-Schnipsel, Empfangsraum)
      - trigger_log.csv            (verbindet Zeitstempel mit clip_filename)
    """
    folder: str
    remote_wav_path: Optional[str] = field(default=None, init=False)
    remote_start_epoch: Optional[float] = field(default=None, init=False)
    clips: List[ClipEntry] = field(default_factory=list, init=False)

    def __post_init__(self):
        self._find_remote_recording()
        seen = self._read_trigger_log()
        self._find_orphan_clips(seen)
        self.clips.sort(key=lambda c: c.epoch)

    # ------------------------------------------------------------------
    def _find_remote_recording(self):
        for fname in os.listdir(self.folder):
            if fname.startswith("remote_clip_") and fname.endswith(".wav"):
                self.remote_wav_path = os.path.join(self.folder, fname)
                json_path = self.remote_wav_path + ".json"
                if os.path.exists(json_path):
                    self.remote_start_epoch = epoch_from_remote_json(json_path)
                break

    def _read_trigger_log(self):
        """Liest trigger_log.csv (bevorzugte Quelle für Clip-Zeitstempel)."""
        seen_filenames = set()
        trigger_log_path = os.path.join(self.folder, "trigger_log.csv")
        if not os.path.exists(trigger_log_path):
            return seen_filenames

        with open(trigger_log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fname = (row.get("clip_filename") or "").strip()
                if not fname:
                    continue
                clip_path = os.path.join(self.folder, fname)
                if not os.path.exists(clip_path):
                    continue
                try:
                    epoch = parse_local_berlin_to_epoch(row["timestamp"])
                except Exception:
                    epoch = epoch_from_clip_filename(fname)
                if epoch is None:
                    continue
                self.clips.append(ClipEntry(
                    epoch=epoch, filename=fname, path=clip_path,
                    trigger_db=row.get("trigger_db", ""), rms=row.get("rms", ""),
                ))
                seen_filenames.add(fname)
        return seen_filenames

    def _find_orphan_clips(self, seen_filenames):
        """Fallback: clip_*.wav Dateien, die nicht im CSV stehen, per Dateiname erschließen."""
        for fname in sorted(os.listdir(self.folder)):
            if fname in seen_filenames:
                continue
            if fname.startswith("clip_") and fname.endswith(".wav"):
                epoch = epoch_from_clip_filename(fname)
                if epoch is None:
                    continue
                self.clips.append(ClipEntry(
                    epoch=epoch, filename=fname,
                    path=os.path.join(self.folder, fname),
                ))
