# -*- coding: utf-8 -*-
"""
Diagnose der freq_zero / missing_file - Ausfälle
=================================================
Klärt, WARUM Clips keine auswertbare Dominant-Frequenz liefern, statt sie
nur zu zählen. Für jeden Ausfall werden zusätzliche Diagnosewerte erfasst:

- Cliplänge in Samples/Sekunden
- Sample-Rate (Hardware-/Session-Wechsel erkennbar?)
- Vorhandensein eines DC-Offsets (Mittelwert des Signals != 0)
- RMS-Pegel des Clips (nahe Stille?)
- Verhältnis Energie < 5 Hz vs. Energie 5-250 Hz (DC-/Tiefpass-Artefakt?)

Ergebnis wird getrennt nach Kampagne (2025/2026) und Ausfallgrund
aggregiert ausgegeben, damit sichtbar wird, ob der höhere 2026-Ausfall
technische Gründe hat (kürzere Clips, andere Hardware-Session) oder
tatsächlich mit sehr leisen/strukturschall-typischen Ereignissen
zusammenhängt.
"""

import os
import csv
from datetime import datetime
from collections import defaultdict
import numpy as np
import soundfile as sf

# === KONFIGURATION ===
PATH_2025 = "/home/kaih/Dokumente/ruhestoerung_2025/daten/juli_25"
PATH_2026 = "/home/kaih/Dokumente/ruhestoerung_2025/daten/24_4_26"

DB_MIN_THRESHOLD = -50.0
DAYS = [3, 4, 5, 6]  # Do, Fr, Sa, So
# =====================


def analyse_clip(wav_path):
    """Liefert Diagnosewerte für einen Clip, unabhängig davon ob die
    Dominant-Frequenz später gültig ist oder nicht."""
    info = {
        "exists": False,
        "readable": False,
        "duration_s": None,
        "sample_rate": None,
        "n_samples": None,
        "dc_offset": None,
        "rms": None,
        "peak_freq": None,
        "energy_below_5hz_ratio": None,
    }

    if not os.path.exists(wav_path):
        return info
    info["exists"] = True

    try:
        data, sample_rate = sf.read(wav_path)
        if len(data.shape) > 1:
            data = data[:, 0]

        if len(data) == 0:
            return info

        info["readable"] = True
        info["sample_rate"] = sample_rate
        info["n_samples"] = len(data)
        info["duration_s"] = len(data) / sample_rate
        info["dc_offset"] = float(np.mean(data))
        info["rms"] = float(np.sqrt(np.mean(np.square(data))))

        fft_spectrum = np.fft.rfft(data)
        freqs = np.fft.rfftfreq(len(data), d=1. / sample_rate)
        magnitude = np.abs(fft_spectrum)

        peak_idx = np.argmax(magnitude)
        info["peak_freq"] = float(freqs[peak_idx])

        total_energy = np.sum(magnitude ** 2) + 1e-12
        below_5hz_energy = np.sum(magnitude[freqs < 5.0] ** 2)
        info["energy_below_5hz_ratio"] = float(below_5hz_energy / total_energy)

    except Exception:
        pass

    return info


def load_and_diagnose(data_root, is_2026=False):
    results = []

    if not os.path.exists(data_root):
        print(f"Pfad nicht gefunden: {data_root}")
        return results

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
                        continue

                    if ts.weekday() not in DAYS:
                        continue

                    time_val = ts.hour + ts.minute / 60.0
                    if not (time_val >= 22.0 or time_val < 2.5):
                        continue

                    trigger_db = float(row["trigger_db"])
                    if trigger_db < DB_MIN_THRESHOLD:
                        continue

                    clean_filename = row["clip_filename"].strip()
                    wav_path = os.path.join(session_path, clean_filename)

                    diag = analyse_clip(wav_path)
                    diag["trigger_db"] = trigger_db
                    diag["session"] = session_name

                    # Klassifikation, konsistent zum Hauptscript
                    if not diag["exists"]:
                        diag["status"] = "missing_file"
                    elif not diag["readable"]:
                        diag["status"] = "read_error_or_empty"
                    elif diag["peak_freq"] is None or diag["peak_freq"] <= 0:
                        diag["status"] = "freq_zero"
                    else:
                        diag["status"] = "ok"

                    results.append(diag)
                except Exception:
                    continue

    return results


def print_group_stats(label, results):
    print(f"\n{'='*70}")
    print(f" {label}")
    print(f"{'='*70}")

    by_status = defaultdict(list)
    for r in results:
        by_status[r["status"]].append(r)

    total = len(results)
    for status, items in by_status.items():
        pct = 100 * len(items) / total if total else 0
        print(f"\n--- Status: {status} ({len(items)} / {total} = {pct:.1f}%) ---")

        durations = [r["duration_s"] for r in items if r["duration_s"] is not None]
        rms_vals = [r["rms"] for r in items if r["rms"] is not None]
        dc_vals = [r["dc_offset"] for r in items if r["dc_offset"] is not None]
        below5_vals = [r["energy_below_5hz_ratio"] for r in items if r["energy_below_5hz_ratio"] is not None]
        db_vals = [r["trigger_db"] for r in items]
        sample_rates = set(r["sample_rate"] for r in items if r["sample_rate"] is not None)

        if durations:
            print(f"  Cliplänge [s]:        Median={np.median(durations):.3f}  Mittel={np.mean(durations):.3f}")
        if rms_vals:
            print(f"  RMS-Pegel:            Median={np.median(rms_vals):.5f}  Mittel={np.mean(rms_vals):.5f}")
        if dc_vals:
            print(f"  |DC-Offset|:          Median={np.median(np.abs(dc_vals)):.6f}")
        if below5_vals:
            print(f"  Energieanteil <5Hz:   Median={np.median(below5_vals):.3f}  Mittel={np.mean(below5_vals):.3f}")
        if db_vals:
            print(f"  trigger_db:           Median={np.median(db_vals):.1f}  Mittel={np.mean(db_vals):.1f}")
        if sample_rates:
            print(f"  Sample-Rate(n):       {sample_rates}")


def main():
    print("Lade und diagnostiziere 2025 (Baseline)...")
    results_2025 = load_and_diagnose(PATH_2025, is_2026=False)

    print("Lade und diagnostiziere 2026 (Kurzzeitanalyse)...")
    results_2026 = load_and_diagnose(PATH_2026, is_2026=True)

    print_group_stats("2025 - BASELINE", results_2025)
    print_group_stats("2026 - KURZZEITANALYSE", results_2026)

    print(f"\n{'='*70}")
    print(" DIREKTVERGLEICH: freq_zero-Clips, Cliplänge & Pegel")
    print(f"{'='*70}")
    for label, results in (("2025", results_2025), ("2026", results_2026)):
        fz = [r for r in results if r["status"] == "freq_zero"]
        ok = [r for r in results if r["status"] == "ok"]
        if fz and ok:
            fz_dur = [r["duration_s"] for r in fz if r["duration_s"] is not None]
            ok_dur = [r["duration_s"] for r in ok if r["duration_s"] is not None]
            fz_db = [r["trigger_db"] for r in fz]
            ok_db = [r["trigger_db"] for r in ok]
            print(f"\n{label}:")
            if fz_dur and ok_dur:
                print(f"  Cliplänge freq_zero vs. ok: {np.median(fz_dur):.3f}s vs. {np.median(ok_dur):.3f}s")
            print(f"  trigger_db freq_zero vs. ok: {np.median(fz_db):.1f} dB vs. {np.median(ok_db):.1f} dB")


if __name__ == "__main__":
    main()
