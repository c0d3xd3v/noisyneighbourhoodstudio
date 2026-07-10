"""
Reine Signalverarbeitungs-Logik für die Kausalanalyse - bewusst ohne jede
Qt/UI-Abhängigkeit, damit sie unabhängig testbar/wiederverwendbar ist.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import signal

from audio_io import apply_lowpass


@dataclass
class CorrelationResult:
    match_start_epoch: float          # Position, an der das Template am besten passt
    similarity: float                 # normierte Korrelationsgüte, 0..1
    delay_vs_template_start: float    # match_start_epoch - Start des Clip-Ausschnitts
    peak_to_peak_delay: float         # Versatz Impuls-Peak (Clip) vs. Impuls-Peak (Remote)
    peak_time_remote: float           # absolute Epoch-Zeit des gefundenen Remote-Peaks


class CausalityAnalyzer:
    """Kapselt die normalisierte Kreuzkorrelation (mode='valid') samt optionalem
    Tiefpass-Vorfilter und Peak-zu-Peak-Auswertung.

    Sucht die Position eines kurzen Clip-Ausschnitts (Empfangsraum) innerhalb
    eines längeren Suchfensters (Senderaum). Normalisierung erfolgt lokal
    (rollende Energie des langen Fensters), nicht global - das macht das
    Ergebnis robust gegen die Fensterbreite selbst (eichunabhängige Observable:
    relative Übereinstimmung statt absoluter Pegel).
    """

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate

    def correlate(self, remote_window, clip_arr, window_start_idx: int,
                  remote_start_epoch: float, clip_reference_epoch: float,
                  lowpass_cutoff_hz: Optional[float] = None) -> CorrelationResult:
        sr = self.sample_rate

        remote_filt = apply_lowpass(remote_window, sr, lowpass_cutoff_hz)
        clip_filt = apply_lowpass(clip_arr, sr, lowpass_cutoff_hz)

        d_long = np.asarray(remote_filt, dtype=np.float32)
        d_short = np.asarray(clip_filt, dtype=np.float32)
        d_long = d_long - np.mean(d_long)
        d_short = d_short - np.mean(d_short)

        corr = signal.correlate(d_long, d_short, mode='valid')

        # Rollende Energie von d_long an jeder möglichen Clip-Position (gleiche Länge wie corr)
        rolling_energy = np.convolve(d_long ** 2, np.ones(len(d_short), dtype=np.float64), mode='valid')
        norm_factor = np.sqrt(np.sum(d_short ** 2)) * np.sqrt(rolling_energy)

        # Positionen mit vernachlässigbar kleiner lokaler Energie (Stille, nahe
        # Fließkomma-Rauschen) explizit ausblenden, statt sie durch Division durch
        # eine winzige Zahl künstlich als "perfekten Treffer" erscheinen zu lassen.
        max_energy = float(np.max(rolling_energy)) if len(rolling_energy) else 0.0
        energy_floor = max(max_energy * 1e-6, 1e-12)
        valid_mask = rolling_energy > energy_floor

        with np.errstate(divide='ignore', invalid='ignore'):
            safe_norm = np.where(valid_mask, norm_factor, 1.0)
            corr_normalized = np.where(valid_mask, corr / safe_norm, 0.0)
        # Normierte Kreuzkorrelation ist mathematisch auf [-1, 1] begrenzt - Werte
        # außerhalb entstehen nur durch Restrauschen und werden hier abgeschnitten.
        corr_normalized = np.clip(corr_normalized, -1.0, 1.0)

        best_idx = int(np.argmax(np.abs(corr_normalized)))
        similarity = float(np.abs(corr_normalized[best_idx]))

        match_start_sample_in_remote = window_start_idx + best_idx
        match_start_epoch = remote_start_epoch + match_start_sample_in_remote / sr
        delay_vs_template_start = match_start_epoch - clip_reference_epoch

        # --- Peak-zu-Peak-Versatz (unabhängig von Stille am Anfang des Templates) ---
        peak_idx_short = int(np.argmax(np.abs(d_short)))
        peak_time_short = clip_reference_epoch + peak_idx_short / sr

        aligned_remote_segment = d_long[best_idx: best_idx + len(d_short)]
        peak_idx_long_local = int(np.argmax(np.abs(aligned_remote_segment)))
        peak_time_remote = remote_start_epoch + (window_start_idx + best_idx + peak_idx_long_local) / sr

        # Erwartete Richtung: Handy (Sender) zuerst, Jetson (Empfänger) danach ->
        # positiver Wert = physikalisch plausibel (Empfänger-Peak liegt nach Sender-Peak).
        peak_to_peak_delay = peak_time_short - peak_time_remote

        return CorrelationResult(
            match_start_epoch=match_start_epoch,
            similarity=similarity,
            delay_vs_template_start=delay_vs_template_start,
            peak_to_peak_delay=peak_to_peak_delay,
            peak_time_remote=peak_time_remote,
        )
