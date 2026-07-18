# -*- coding: utf-8 -*-
"""
Prüft, ob sich das WAV-Speicherformat (Subtype/Bit-Tiefe) zwischen den
beiden Messkampagnen unterscheidet. Nimmt dazu jeweils eine zufällige,
tatsächlich existierende WAV-Datei aus jedem Kampagnen-Ordner (durchsucht
alle Sessions, sammelt alle vorhandenen Clips, wählt dann zufällig einen).

Falls sich der Subtype unterscheidet (z. B. PCM_16 vs. PCM_24 / FLOAT),
ist das eine plausible Erklärung für den beobachteten Faktor-~40-Unterschied
im absoluten RMS-Pegel zwischen den Kampagnen, unabhängig von Mikrofon-
position oder Gain-Einstellung.
"""

import os
import random
import soundfile as sf

PATH_2025 = "/home/kaih/Dokumente/ruhestoerung_2025/daten/juli_25"
PATH_2026 = "/home/kaih/Dokumente/ruhestoerung_2025/daten/24_4_26"


def find_all_wavs(data_root):
    """Sammelt alle existierenden .wav-Dateien unter allen Session-Ordnern."""
    wav_paths = []

    if not os.path.exists(data_root):
        print(f"Pfad nicht gefunden: {data_root}")
        return wav_paths

    for session_name in sorted(os.listdir(data_root)):
        session_path = os.path.join(data_root, session_name)
        if not os.path.isdir(session_path):
            continue

        for fname in os.listdir(session_path):
            if fname.lower().endswith(".wav"):
                wav_paths.append(os.path.join(session_path, fname))

    return wav_paths


def print_random_wav_info(label, data_root):
    wavs = find_all_wavs(data_root)
    if not wavs:
        print(f"{label}: Keine WAV-Dateien gefunden unter {data_root}")
        return

    chosen = random.choice(wavs)
    info = sf.info(chosen)

    print(f"\n--- {label} ---")
    print(f"Datei:        {chosen}")
    print(f"Subtype:      {info.subtype}")
    print(f"Kanäle:       {info.channels}")
    print(f"Sample-Rate:  {info.samplerate}")
    print(f"Frames:       {info.frames}")
    print(f"Dauer [s]:    {info.frames / info.samplerate:.3f}")
    print(f"Format:       {info.format}")


def main():
    print(f"Gefundene WAV-Dateien werden zufällig ausgewählt (n={random.randint(0,0)} Seed egal)...")
    print_random_wav_info("2025 (Baseline)", PATH_2025)
    print_random_wav_info("2026 (Kurzzeitanalyse)", PATH_2026)


if __name__ == "__main__":
    main()
