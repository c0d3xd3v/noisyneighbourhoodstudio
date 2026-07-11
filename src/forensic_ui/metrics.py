# -*- coding: utf-8 -*-
"""
Metrik-Abstraktion: eine Metrik nimmt eine SessionData und liefert alles,
was der Plot braucht, um die y-Achse zu zeichnen. Die x-Achse (Zeitstempel)
kommt immer direkt aus session.events und ist hier nicht Teil des Ergebnisses.

Neue Metrik hinzufügen = neue Klasse schreiben + @MetricRegistry.register.
Kein anderer Code muss angefasst werden.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Type

import numpy as np
from scipy.signal import stft

from models import SessionData
from audio_render import load_audio


@dataclass
class MetricResult:
    y_values: List[float]
    y_label: str = "Wert"
    y_unit: str = ""
    # optionale horizontale Referenzlinien, z.B. Baseline min/max wie im alten Code
    baseline_low: Optional[float] = None
    baseline_high: Optional[float] = None
    # optionale Text-Labels pro Punkt (z.B. aus zuordnung.txt), gleiche Länge wie y_values
    point_labels: Optional[List[str]] = None


ProgressCallback = Callable[[int, int], None]  # (erledigt, gesamt)


class Metric(ABC):
    key: str = ""
    display_name: str = ""

    @abstractmethod
    def compute(self, session: SessionData, on_progress: Optional[ProgressCallback] = None) -> MetricResult:
        ...


class MetricRegistry:
    _metrics: Dict[str, Metric] = {}

    @classmethod
    def register(cls, metric_cls: Type[Metric]) -> Type[Metric]:
        instance = metric_cls()
        cls._metrics[instance.key] = instance
        return metric_cls

    @classmethod
    def get(cls, key: str) -> Metric:
        return cls._metrics[key]

    @classmethod
    def all(cls) -> List[Metric]:
        return list(cls._metrics.values())

    @classmethod
    def default_key(cls) -> str:
        # erste registrierte Metrik als Default (aktuell: trigger_level)
        return next(iter(cls._metrics))


@MetricRegistry.register
class TriggerLevelMetric(Metric):
    """Entspricht 1:1 der bisherigen Logik in load_session():
    y = db - min(db), also relative Dynamik ab 0, plus Baselines bei 0 und db_range."""

    key = "trigger_level"
    display_name = "Pegelverlauf (relativ, dB)"

    def compute(self, session: SessionData, on_progress: Optional[ProgressCallback] = None) -> MetricResult:
        if session.is_empty:
            return MetricResult(y_values=[])

        db_values = [e.trigger_db for e in session.events]
        min_db = min(db_values)
        max_db = max(db_values)
        db_range = max_db - min_db

        if db_range == 0:
            y_relative = [0.0 for _ in db_values]
        else:
            y_relative = [db - min_db for db in db_values]

        labels = [e.label or "" for e in session.events]

        return MetricResult(
            y_values=y_relative,
            y_label="Dynamik-Verlauf",
            y_unit="dB (relativ)",
            baseline_low=0.0,
            baseline_high=db_range,
            point_labels=labels,
        )


class _PerClipAudioMetric(Metric):
    """Basisklasse für Metriken, die pro Event die Audiodatei laden und daraus
    einen einzelnen Skalarwert berechnen. Erspart jeder konkreten Metrik das
    Wiederholen von Laden/Fehlerbehandlung/Labels - nur _compute_value()
    muss überschrieben werden."""

    y_label = "Wert"
    y_unit = ""

    def _compute_value(self, data: np.ndarray, sr: int) -> float:
        raise NotImplementedError

    def compute(self, session: SessionData, on_progress: Optional[ProgressCallback] = None) -> MetricResult:
        if session.is_empty:
            return MetricResult(y_values=[])

        total = len(session.events)
        y_values = []
        for i, event in enumerate(session.events):
            try:
                data, sr = load_audio(event.audio_path)
                y_values.append(self._compute_value(data, sr))
            except Exception:
                y_values.append(float("nan"))  # Clip fehlt/kaputt -> Lücke im Plot
            if on_progress:
                on_progress(i + 1, total)

        labels = [e.label or "" for e in session.events]
        return MetricResult(
            y_values=y_values,
            y_label=self.y_label,
            y_unit=self.y_unit,
            point_labels=labels,
        )


def _magnitude_spectrum(data: np.ndarray, sr: int):
    magnitude = np.abs(np.fft.rfft(data))
    freqs = np.fft.rfftfreq(len(data), d=1.0 / sr)
    return freqs, magnitude


@MetricRegistry.register
class CrestFactorMetric(_PerClipAudioMetric):
    """Peak/RMS des gesamten Clips. Hoch bei kurzen, impulsiven Ereignissen
    (Stoß, Poltern), niedrig bei gleichmäßigen Geräuschen (Musik, Rauschen)."""

    key = "crest_factor"
    display_name = "Crest-Faktor (Peak/RMS)"
    y_label = "Crest-Faktor"
    y_unit = ""

    def _compute_value(self, data, sr):
        rms = float(np.sqrt(np.mean(data ** 2)) + 1e-12)
        peak = float(np.max(np.abs(data)))
        return peak / rms


@MetricRegistry.register
class SpectralCentroidMetric(_PerClipAudioMetric):
    """Energiegewichteter Frequenzschwerpunkt des Clips. Hoch = eher hell/
    scharf (Klirren, Klingel), niedrig = eher dumpf (Poltern, Stoß)."""

    key = "spectral_centroid"
    display_name = "Spektraler Schwerpunkt (Hz)"
    y_label = "Spektraler Schwerpunkt"
    y_unit = "Hz"

    def _compute_value(self, data, sr):
        freqs, magnitude = _magnitude_spectrum(data, sr)
        total = magnitude.sum()
        if total <= 0:
            return 0.0
        return float((freqs * magnitude).sum() / total)


@MetricRegistry.register
class DominantFrequencyMetric(_PerClipAudioMetric):
    """Frequenz mit der größten spektralen Energie (DC-Anteil ausgeschlossen)."""

    key = "dominant_frequency"
    display_name = "Dominante Frequenz (Hz)"
    y_label = "Dominante Frequenz"
    y_unit = "Hz"

    def _compute_value(self, data, sr):
        freqs, magnitude = _magnitude_spectrum(data - np.mean(data), sr)
        if len(magnitude) <= 1:
            return 0.0
        idx = int(np.argmax(magnitude[1:])) + 1  # Index 0 = DC, ausschließen
        return float(freqs[idx])


@MetricRegistry.register
class SpectralFluxMetric(_PerClipAudioMetric):
    """Mittlere Änderungsrate des Spektrums zwischen aufeinanderfolgenden
    STFT-Frames innerhalb eines Clips. Hoch bei transienten/perkussiven
    Ereignissen, niedrig bei stationären Geräuschen (Brummen, Verkehr)."""

    key = "spectral_flux"
    display_name = "Spektraler Fluss (Transientheit)"
    y_label = "Spektraler Fluss"
    y_unit = ""

    def _compute_value(self, data, sr):
        _, _, Zxx = stft(data, sr, nperseg=1024, noverlap=512)
        magnitude = np.abs(Zxx)
        if magnitude.shape[1] < 2:
            return 0.0
        diff = np.diff(magnitude, axis=1)
        diff_positive = np.clip(diff, a_min=0, a_max=None)
        flux_per_frame = np.sqrt(np.mean(diff_positive ** 2, axis=0))
        return float(np.mean(flux_per_frame))
