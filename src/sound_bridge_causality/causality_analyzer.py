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


def sweep_similarity(remote_window, clip_arr, sample_rate, cutoffs_hz, work_rate=1000):
    """Übereinstimmung als Funktion der Tiefpass-Grenzfrequenz ("Frequenz-Sweep").

    Beide Signale werden zunächst einmalig auf work_rate dezimiert (mit
    Anti-Aliasing via resample_poly). Das hat zwei Effekte:
      1. Tempo: die Korrelation läuft auf ~1/44 der Samples.
      2. Numerik: bei work_rate=1000 Hz liegt z.B. ein 28-Hz-Cutoff bei
         fc/Nyquist = 0.056 statt 0.0013 - der Butterworth-Filter arbeitet
         dort auch in ba-Form stabil (das bekannte Problem extrem kleiner
         normierter Grenzfrequenzen stellt sich gar nicht erst).

    Gibt (cutoffs, similarities) als np.ndarrays zurück; similarities in 0..1.
    """
    from math import gcd

    max_cutoff = max(cutoffs_hz)
    if max_cutoff >= work_rate / 2 * 0.9:
        raise ValueError(f"work_rate={work_rate} Hz zu niedrig für Cutoff {max_cutoff} Hz.")

    if work_rate < sample_rate:
        g = gcd(int(work_rate), int(sample_rate))
        up, down = int(work_rate) // g, int(sample_rate) // g
        remote_ds = signal.resample_poly(np.asarray(remote_window, dtype=np.float64), up, down)
        clip_ds = signal.resample_poly(np.asarray(clip_arr, dtype=np.float64), up, down)
        sr = work_rate
    else:
        remote_ds, clip_ds, sr = remote_window, clip_arr, sample_rate

    analyzer = CausalityAnalyzer(sample_rate=sr)
    sims = []
    for cutoff in cutoffs_hz:
        # Epoch-Parameter sind für die reine Ähnlichkeit irrelevant -> 0.0
        res = analyzer.correlate(remote_ds, clip_ds, 0, 0.0, 0.0,
                                 lowpass_cutoff_hz=float(cutoff))
        sims.append(res.similarity)

    return np.asarray(cutoffs_hz, dtype=float), np.asarray(sims, dtype=float)


def spectral_similarity_search(remote_window, clip_arr, sample_rate,
                                fmin=300.0, fmax=8000.0, hop_ms=2.0):
    """Sucht die beste Übereinstimmung zwischen einem kurzen Template (clip_arr)
    und einem längeren Suchfenster (remote_window) NICHT über die Form der
    Wellenform im Zeitbereich, sondern über das Betragsspektrum in einem
    festen Frequenzband [fmin, fmax] Hz.

    Motivation: Die Wand wirkt als dispersives Übertragungssystem (Biegewellen
    unterschiedlicher Frequenz laufen unterschiedlich schnell durch die
    Struktur) - dadurch kann sich die ZEITLICHE Form eines Impulses beim
    Durchqueren der Wand verzerren, auch wenn es sich um dasselbe Ereignis
    handelt. Das Betragsspektrum (welche Frequenzanteile enthalten sind, in
    welcher relativen Stärke) ist gegenüber genau dieser Verzerrung robuster,
    weil es die Phaseninformation - und damit die zeitliche Form - ignoriert.

    Für jede Kandidatenposition im Suchfenster wird ein gleich langes Segment
    wie das Template ausgeschnitten, mit einem Hann-Fenster gewichtet, per FFT
    in ein Betragsspektrum umgewandelt, auf das Band [fmin, fmax] beschränkt
    und per Kosinus-Ähnlichkeit mit dem Template-Spektrum verglichen.

    WICHTIG: Diese Metrik ist NICHT auf dieselbe Skala kalibriert wie die
    zeitbereichsbasierte Kreuzkorrelation (dort: ~76% Zufallsniveau aus
    empirischen Fehlpaarungen). Für die spektrale Ähnlichkeit muss ein
    eigenes Zufallsniveau aus mehreren Fehlpaarungen gesammelt werden, bevor
    ein Schwellenwert für "belastbar" sinnvoll festgelegt werden kann.

    Rückgabe: dict mit best_offset_samples, best_similarity (0..1),
    offsets_sec und similarities (komplette Suchkurve, für optionale
    Visualisierung analog zum Korrelationsverlauf), sowie n_template.
    """
    sr = float(sample_rate)
    remote = np.asarray(remote_window, dtype=np.float64)
    templ = np.asarray(clip_arr, dtype=np.float64)
    n_template = len(templ)

    if n_template < 16:
        raise ValueError("Template zu kurz (< 16 Samples).")
    if len(remote) < n_template:
        raise ValueError("Suchfenster kürzer als das Template.")

    window = np.hanning(n_template)
    freqs = np.fft.rfftfreq(n_template, d=1.0 / sr)
    band_mask = (freqs >= fmin) & (freqs <= fmax)
    if not np.any(band_mask):
        raise ValueError(
            f"Kein Frequenzbin im Band [{fmin:.0f},{fmax:.0f}] Hz bei "
            f"Templatelänge {n_template} Samples ({sr:.0f} Hz)."
        )

    templ_spec = np.abs(np.fft.rfft(templ * window))[band_mask]
    templ_norm = np.linalg.norm(templ_spec)
    if templ_norm < 1e-12:
        raise ValueError("Template enthält im gewählten Band keine messbare Energie.")

    hop = max(1, int(round(sr * hop_ms / 1000.0)))
    n_positions = (len(remote) - n_template) // hop + 1
    if n_positions < 1:
        raise ValueError("Suchfenster zu kurz für den gewählten Hop.")

    # Rechenzeit-Deckel: Der Aufwand skaliert mit n_positions * n_template
    # (jede Position braucht eine FFT über die volle Templatelänge). Bei
    # langen Templates (z.B. mehrere Sekunden) würde ein feiner Hop über ein
    # breites Suchfenster sonst Minuten dauern. MAX_SAMPLE_SLOTS ist grob auf
    # ~3-4s Laufzeit kalibriert; wird die Grenze überschritten, wird der Hop
    # automatisch vergrößert (zeitliche Auflösung der Fundstelle sinkt, der
    # Ähnlichkeitswert selbst ist davon unberührt) und eine Warnung zurückgegeben.
    MAX_SAMPLE_SLOTS = 2.5e8
    warning = None
    if n_positions * n_template > MAX_SAMPLE_SLOTS:
        needed_positions = max(10, int(MAX_SAMPLE_SLOTS // n_template))
        new_hop = max(hop, int(np.ceil((len(remote) - n_template) / max(1, needed_positions - 1))))
        if new_hop > hop:
            warning = (
                f"Hop automatisch von {hop_ms:.1f} ms auf {new_hop * 1000.0 / sr:.1f} ms "
                f"vergrößert, um die Rechenzeit bei einem Template von "
                f"{n_template / sr * 1000:.0f} ms Länge zu begrenzen. Für feinere zeitliche "
                f"Auflösung ein kürzeres Template verwenden (der Ähnlichkeitswert selbst "
                f"bleibt davon unberührt)."
            )
            hop = new_hop
            n_positions = (len(remote) - n_template) // hop + 1

    starts = np.arange(n_positions) * hop
    sims = np.empty(n_positions, dtype=np.float64)

    # In Chunks verarbeiten, damit der Speicherbedarf unabhängig von
    # Templatelänge und Suchfensterbreite begrenzt bleibt (statt ein
    # n_positions x n_template großes Array auf einmal zu bauen).
    chunk_size = max(1, int(2_000_000 // max(n_template, 1)))
    for chunk_start in range(0, n_positions, chunk_size):
        chunk_end = min(chunk_start + chunk_size, n_positions)
        starts_chunk = starts[chunk_start:chunk_end]
        idx = starts_chunk[:, None] + np.arange(n_template)[None, :]
        segments = remote[idx] * window[None, :]
        specs = np.abs(np.fft.rfft(segments, axis=1))[:, band_mask]
        norms = np.linalg.norm(specs, axis=1)
        with np.errstate(divide='ignore', invalid='ignore'):
            s = np.where(norms > 1e-12,
                        (specs @ templ_spec) / (norms * templ_norm),
                        0.0)
        sims[chunk_start:chunk_end] = np.clip(s, 0.0, 1.0)

    best_idx = int(np.argmax(sims))
    offsets_sec = starts / sr

    return {
        "best_offset_samples": int(starts[best_idx]),
        "best_similarity": float(sims[best_idx]),
        "offsets_sec": offsets_sec,
        "similarities": sims,
        "hop_samples": hop,
        "n_template": n_template,
        "fmin": fmin,
        "fmax": fmax,
        "warning": warning,
    }