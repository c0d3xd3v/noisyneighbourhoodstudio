"""
Audio-I/O und Zeitstempel-Hilfsfunktionen für die Rathenaustraße-38-Kausalanalyse.

Enthält alles, was mit dem Laden von WAV/M4A-Dateien und der Umrechnung
zwischen verschiedenen Zeitstempel-Formaten (JSON, CSV, Dateiname) zu tun hat.
Bewusst UI-frei, damit es unabhängig von Qt getestet/wiederverwendet werden kann.
"""

import os
import re
import json
import wave
import datetime
from dataclasses import dataclass
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
from scipy import signal

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False


BERLIN = ZoneInfo("Europe/Berlin")
TARGET_RATE = 44100

# clip_20260706_032420.152.wav -> Datum + Uhrzeit.Millisekunden
CLIP_FILENAME_RE = re.compile(r"^clip_(\d{8})_(\d{6}\.\d+)\.wav$")


@dataclass
class AudioClip:
    """Eine geladene, normalisierte Audiospur mit ihrer absoluten Startzeit (Epoch)."""
    data: np.ndarray
    sample_rate: int
    start_epoch: float
    file_name: str
    trigger_epoch: Optional[float] = None  # nur bei kurzen Jetson-Clips gesetzt

    @property
    def duration(self) -> float:
        return len(self.data) / self.sample_rate


# ----------------------------------------------------------------------
# Laden & Signalverarbeitung
# ----------------------------------------------------------------------

def load_audio(path, target_rate=TARGET_RATE):
    """Lädt WAV oder M4A, mittelt auf Mono, normalisiert und resampled auf target_rate."""
    ext = os.path.splitext(path)[1].lower()

    if ext == ".wav":
        with wave.open(path, "rb") as wf:
            frames = wf.readframes(-1)
            sr = wf.getframerate()
            sampwidth = wf.getsampwidth()
            nchan = wf.getnchannels()
        dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
        dtype = dtype_map.get(sampwidth, np.int16)
        raw = np.frombuffer(frames, dtype=dtype)
        if nchan > 1:
            raw = raw.reshape(-1, nchan).mean(axis=1)
        data = raw.astype(np.float32)

    elif ext == ".m4a":
        if not PYDUB_AVAILABLE:
            raise RuntimeError(
                "pydub ist nicht installiert. Bitte 'pip install pydub' ausführen "
                "und sicherstellen, dass ffmpeg im PATH liegt."
            )
        seg = AudioSegment.from_file(path, format="m4a")
        if seg.channels > 1:
            seg = seg.set_channels(1)
        sr = seg.frame_rate
        data = np.array(seg.get_array_of_samples()).astype(np.float32)

    else:
        raise ValueError(f"Nicht unterstütztes Dateiformat: {ext}")

    maxval = np.max(np.abs(data))
    data = data / maxval if maxval > 0 else data

    if sr != target_rate:
        n_new = int(len(data) * target_rate / sr)
        data = signal.resample(data, n_new)
        sr = target_rate

    return data, sr


def apply_lowpass(data, sr, cutoff_hz):
    """Zero-Phase-Tiefpass (Butterworth, 4. Ordnung) - filtert unkorreliertes
    Hochfrequenzband heraus, das durch die Wand ohnehin stark gedämpft wird.
    filtfilt vermeidet Phasenverschiebung, die den gefundenen Zeitversatz
    verfälschen würde."""
    if cutoff_hz is None or cutoff_hz <= 0:
        return data
    nyquist = sr / 2.0
    normal_cutoff = min(cutoff_hz / nyquist, 0.99)
    b, a = signal.butter(4, normal_cutoff, btype='low')
    return signal.filtfilt(b, a, data)


# ----------------------------------------------------------------------
# Zeitstempel-Interpretation
# ----------------------------------------------------------------------

def epoch_from_remote_json(json_path):
    """calculated_server_start_time_ms ist bereits UTC-Epoch -> direkt verwendbar."""
    with open(json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    ms = float(meta["calculated_server_start_time_ms"])
    return ms / 1000.0


def parse_local_berlin_to_epoch(ts_str, fmt="%Y-%m-%d %H:%M:%S.%f"):
    """trigger_log.csv-Zeitstempel sind naive Lokalzeit (Europe/Berlin) -> als solche interpretieren."""
    dt = datetime.datetime.strptime(ts_str.strip(), fmt)
    dt = dt.replace(tzinfo=BERLIN)
    return dt.timestamp()


def epoch_from_clip_filename(fname):
    """Fallback, falls trigger_log.csv fehlt oder eine Zeile nicht parsebar ist."""
    m = CLIP_FILENAME_RE.match(fname)
    if not m:
        return None
    raw = m.group(1) + "_" + m.group(2)
    dt = datetime.datetime.strptime(raw, "%Y%m%d_%H%M%S.%f")
    dt = dt.replace(tzinfo=BERLIN)
    return dt.timestamp()


# ----------------------------------------------------------------------
# Convenience: fertige AudioClip-Objekte
# ----------------------------------------------------------------------

def load_remote_as_audioclip(path, start_epoch, file_name, target_rate=TARGET_RATE) -> AudioClip:
    data, sr = load_audio(path, target_rate)
    return AudioClip(data=data, sample_rate=sr, start_epoch=start_epoch, file_name=file_name)


def load_clip_as_audioclip(path, trigger_epoch, file_name, target_rate=TARGET_RATE) -> AudioClip:
    """Lädt einen kurzen Jetson-Clip und berechnet dessen echten Start.

    WICHTIG: Der Trigger-Zeitstempel markiert die MITTE des aufgezeichneten
    6s-Clips (Pre- + Post-Trigger-Puffer), nicht den Anfang. Der tatsächliche
    Datei-Start liegt daher eine halbe Clip-Länge davor.
    """
    data, sr = load_audio(path, target_rate)
    duration = len(data) / sr
    start_epoch = trigger_epoch - duration / 2.0
    return AudioClip(data=data, sample_rate=sr, start_epoch=start_epoch,
                      file_name=file_name, trigger_epoch=trigger_epoch)
