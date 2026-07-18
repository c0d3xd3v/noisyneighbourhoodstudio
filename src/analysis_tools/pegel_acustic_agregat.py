# -*- coding: utf-8 -*-
"""
Noisy Neighbourhood Studio – Pegeldynamik-Histogramm
=====================================================
Analog zu frequenz_vergleich_histogramm.py -- inklusive identischer
Audio-Validierung, damit beide Histogramme exakt dieselbe Grundgesamtheit
(dieselben Events) beschreiben, nur mit unterschiedlichem Merkmal
(trigger_db statt Dominant-Frequenz).

Ein Event zählt nur, wenn:
- CSV-Filter bestanden (Tag, erweiterte Nachtruhe, trigger_db >= DB_MIN_THRESHOLD)
- die zugehörige WAV-Datei existiert und via soundfile lesbar ist
- die FFT daraus eine Dominant-Frequenz > 0 Hz liefert

Der letzte Punkt ist reiner Gleichlauf mit dem Frequenz-Script (damit exakt
dieselben Events durchfallen bzw. gezählt werden) -- die Frequenz selbst
wird hier nicht weiterverwendet, nur trigger_db.

Zusätzlich werden die Ausfallgründe getrennt gezählt (dropped_missing_file,
dropped_read_error, dropped_freq_zero), um sichtbar zu machen, ob der
Audio-bedingte Ausfall zufällig verteilt ist oder systematisch mit
Kampagne/Pegel korreliert.
"""

import os
import csv
from datetime import datetime
from collections import defaultdict
import numpy as np
import matplotlib.pyplot as plt
import soundfile as sf

# === KONFIGURATION ===
PATH_2025 = "/home/kaih/Dokumente/ruhestoerung_2025/daten/juli_25"
PATH_2026 = "/home/kaih/Dokumente/ruhestoerung_2025/daten/24_4_26"
AUDIO_VALIDATE=True
DB_MIN_THRESHOLD = -35.0
DAYS = [3, 4, 5, 6]  # Do, Fr, Sa, So
# =====================


def get_dominant_frequency_sf(wav_path):
    """Identisch zu frequenz_vergleich_histogramm.py: liest WAV via soundfile,
    berechnet Peak-Frequenz. Gibt None zurück bei jedem Fehler/leerer Datei."""
    try:
        if not os.path.exists(wav_path):
            return None, "missing_file"

        data, sample_rate = sf.read(wav_path)

        if len(data.shape) > 1:
            data = data[:, 0]

        if len(data) == 0:
            return None, "empty_data"

        fft_spectrum = np.fft.rfft(data)
        freqs = np.fft.rfftfreq(len(data), d=1. / sample_rate)

        freq = freqs[np.argmax(np.abs(fft_spectrum))]
        if freq is None or freq <= 0:
            return None, "freq_zero"
        return freq, None
    except Exception as e:
        return None, f"read_error"


def load_levels_from_csv(data_root, is_2026=False):
    """Liest trigger_db-Werte, aber nur für Events, die auch die
    Audio-Validierung des Frequenz-Scripts bestehen würden."""
    levels = []
    dropped = defaultdict(int)

    if not os.path.exists(data_root):
        print(f"Pfad nicht gefunden: {data_root}")
        return levels, dropped

    for session_name in sorted(os.listdir(data_root)):
        session_path = os.path.join(data_root, session_name)
        if not os.path.isdir(session_path):
            continue

        csv_file = os.path.join(session_path, "trigger_log.csv")
        if not os.path.exists(csv_file):
            continue

        with open(csv_file, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = datetime.strptime(row["timestamp"].strip(), "%Y-%m-%d %H:%M:%S.%f")

                    if is_2026 and ts.year == 2026 and ts.month == 6 and ts.day == 24:
                        continue  # Konzert ausblenden

                    if ts.weekday() not in DAYS:
                        continue

                    time_val = ts.hour + ts.minute / 60.0
                    if not (time_val >= 22.0 or time_val < 2.5):
                        continue

                    trigger_db = float(row["trigger_db"])
                    if trigger_db < DB_MIN_THRESHOLD:
                        continue

                    # --- Ab hier identische Audio-Validierung wie im Frequenz-Script ---
                    clean_filename = row["clip_filename"].strip()
                    wav_path = os.path.join(session_path, clean_filename)

                    if AUDIO_VALIDATE:
                        freq, drop_reason = get_dominant_frequency_sf(wav_path)
                        if freq is None:
                            dropped[drop_reason] += 1
                            continue

                    levels.append(trigger_db)
                except Exception:
                    dropped["csv_row_error"] += 1
                    continue

    return levels, dropped


def main():
    print("=" * 75)
    print(" STARTE PEGELDYNAMIK-ANALYSE (TRIGGER-DB, AUDIO-VALIDIERT)")
    print("=" * 75)

    print("Analysiere Pegel für 2025 (Baseline)...")
    levels_2025, dropped_2025 = load_levels_from_csv(PATH_2025, is_2026=False)
    print(f"-> {len(levels_2025)} gültige Events für 2025 erfasst.")
    if dropped_2025:
        print(f"   Ausgefallen: {dict(dropped_2025)}")

    print("\nAnalysiere Pegel für 2026 (Kurzzeitanalyse)...")
    levels_2026, dropped_2026 = load_levels_from_csv(PATH_2026, is_2026=True)
    print(f"-> {len(levels_2026)} gültige Events für 2026 erfasst.")
    if dropped_2026:
        print(f"   Ausgefallen: {dict(dropped_2026)}")

    if len(levels_2025) == 0 and len(levels_2026) == 0:
        print("\nFehler: Keine Events gefunden, die den Filtern entsprechen.")
        return

    # Statistik im Terminal
    for label, levels in (("2025", levels_2025), ("2026", levels_2026)):
        if not levels:
            continue
        arr = np.array(levels)
        print(f"\n--- Pegelstatistik {label} ---")
        print(f"n            = {len(arr)}")
        print(f"Median       = {np.median(arr):.1f} dB (rel.)")
        print(f"Mittelwert   = {np.mean(arr):.1f} dB (rel.)")
        print(f"Min / Max    = {np.min(arr):.1f} / {np.max(arr):.1f} dB")

    # Plot
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.patch.set_facecolor('#ffffff')

    alle_werte = levels_2025 + levels_2026
    lo = np.floor(min(alle_werte) / 2.0) * 2.0
    hi = np.ceil(max(alle_werte) / 2.0) * 2.0 + 2.0
    bins = np.arange(lo, hi, 2.0)

    counts_2025, _ = np.histogram(levels_2025, bins=bins, density=True)
    counts_2026, _ = np.histogram(levels_2026, bins=bins, density=True)

    global_max = max(counts_2025.max(), counts_2026.max())
    counts_2025_norm = counts_2025 / global_max
    counts_2026_norm = counts_2026 / global_max

    bin_width = (bins[1] - bins[0]) * 0.85 / 2

    ax.bar(
        bins[:-1], counts_2025_norm, width=bin_width,
        color='navy', edgecolor='black', linewidth=0.8,
        label=f'Baseline 2025 (n={len(levels_2025)} Events)'
    )
    ax.bar(
        bins[:-1] + bin_width, counts_2026_norm, width=bin_width,
        color='crimson', edgecolor='black', linewidth=0.8,
        label=f'Kurzzeitanalyse 2026 (n={len(levels_2026)} Events)'
    )

    ax.set_ylim(0, 1)

    ax.set_title(
        "Anlage zum Mängelbericht: Pegeldynamik der Kern-Störereignisse\n"
        f"Erweiterte Nachtruhe (Do–So, 22:00 – 02:30 Uhr) | Filter: ≥ {DB_MIN_THRESHOLD}dB, audio-validiert",
        fontsize=14, fontweight='bold', pad=15
    )
    ax.set_xlabel(
        "Relativer Trigger-Pegel [dB, oberhalb kalibrierter Stille]",
        fontsize=12, labelpad=10
    )
    ax.set_ylabel("Normierte relative Häufigkeit (0–1)", fontsize=12, labelpad=10)

    ax.grid(True, linestyle='--', alpha=0.5, zorder=0)
    ax.set_axisbelow(True)

    ax.legend(fontsize=11, loc='upper right', facecolor='#ffffff', edgecolor='#cccccc')

    plt.tight_layout()
    plt.savefig(f"pegeldynamik_histogramm_{AUDIO_VALIDATE}_{abs(DB_MIN_THRESHOLD)}.png", dpi=300)
    print("\nPegeldynamik-Histogramm erfolgreich unter 'pegeldynamik_histogramm.png' gespeichert.")

if __name__ == "__main__":
    main()
