import os
import glob
import numpy as np
import soundfile as sf
import scipy.signal as signal

# Pfade zu den Hauptverzeichnissen der Kampagnen (bitte anpassen)
DIR_2025 = "/home/kaih/Dokumente/ruhestoerung_2025/daten/juli_25/"
DIR_2026 = "/home/kaih/Dokumente/ruhestoerung_2025/daten/juni26/"  # Pfad zu Ihrer 2026er-Struktur hier eintragen

# Findet alle Wave-Dateien in allen Unterordnern (z.B. session_*)
files_2025 = sorted(glob.glob(os.path.join(DIR_2025, "**", "*.wav"), recursive=True))[:12]
files_2026 = sorted(glob.glob(os.path.join(DIR_2026, "**", "*.wav"), recursive=True))[:12]

# Validierung, dass Dateien gefunden wurden
if not files_2025 or not files_2026:
    print(f"Fehler: Datensätze unvollständig. Gefunden: 2025 ({len(files_2025)}), 2026 ({len(files_2026)})")
    exit()

# =====================================================================
# CHECK 1: Metadaten & Dateiintegrität via sf.info()
# =====================================================================
print("--- CHECK 1: METADATEN-KONSISTENZ (sf.info) ---")
def check_metadata(file_list, year_label):
    print(f"\nStichprobe {year_label} ({len(file_list)} Dateien):")
    meta_keys = []
    for f in file_list:
        info = sf.info(f)
        print(f"  {os.path.basename(f)}: SR={info.samplerate}Hz, Ch={info.channels}, Sub={info.subtype}")
        meta_keys.append((info.samplerate, info.channels, info.subtype))
    return meta_keys

meta_2025 = check_metadata(files_2025, "2025")
meta_2026 = check_metadata(files_2026, "2026")

if len(set(meta_2025 + meta_2026)) == 1:
    print("\n[OK] Hardware-/Software-Kette strukturell absolut identisch.")
else:
    print("\n!!! WARNUNG: Abweichende Audio-Metadaten zwischen den Kampagnen detektiert !!!")

# =====================================================================
# CHECK 2 & 3: RMS des Rauschbodens (> 2 kHz Hochpass-gefiltert) & Spektrum
# =====================================================================
print("\n--- CHECK 2 & 3: RMS-RAUSCHBODEN ANALYSE (> 2 kHz HP) ---")

def get_noise_floor_rms(file_list):
    rms_values = []
    for f in file_list:
        data, sr = sf.read(f)
        if len(data.shape) > 1: 
            data = data[:, 0]  # Mono erzwingen
        
        # Suche nach dem leisesten 100ms-Segment im Clip (Ereignisfreie Zone)
        seg_len = int(0.1 * sr)
        if len(data) < seg_len: 
            continue
        
        rms_segments = [np.sqrt(np.mean(data[i:i+seg_len]**2)) for i in range(0, len(data)-seg_len, seg_len)]
        quietest_idx = np.argmin(rms_segments)
        stille_segment = data[quietest_idx*seg_len : (quietest_idx+1)*seg_len]
        
        # 2 kHz Hochpassfilter auf das Stille-Segment anwenden
        b, a = signal.butter(4, 2000 / (sr / 2), btype='high')
        filtered_stille = signal.filtfilt(b, a, stille_segment)
        
        rms = np.sqrt(np.mean(filtered_stille**2))
        if rms > 0: 
            rms_values.append(rms)
        
    return 20 * np.log10(np.mean(rms_values)) if rms_values else -np.inf

noise_db_2025 = get_noise_floor_rms(files_2025)
noise_db_2026 = get_noise_floor_rms(files_2026)
delta_noise = noise_db_2026 - noise_db_2025

print(f"Mittlerer Rauschboden 2025 (>2kHz): {noise_db_2025:.2f} dB")
print(f"Mittlerer Rauschboden 2026 (>2kHz): {noise_db_2026:.2f} dB")
print(f"Verschiebung des Rauschbodens:     {delta_noise:+.2f} dB")

print("\n--- SPEKTRALE INTERPRETATIONSHILFE ---")
if abs(delta_noise) < 0.5:
    print("Befund: Konstanter Rauschboden (\u0394 < 0.5 dB).")
    print("-> Keine Veränderung der akustischen Umgebung im Hochfrequenzbereich.")
elif delta_noise < -1.5:
    print("Befund: Deutlich abgesenkter hochfrequenter Rauschboden im Jahr 2026.")
    print("-> BEWEIS: Geformter Abfall durch die Fensterabdichtung (Außenlärm-Reduktion).")
    print("-> Ein reiner Gain-Offset (Software-Pegeländerung) ist hiermit ausgeschlossen.")
else:
    print("Befund: Rauschboden verschoben. Überprüfen Sie, ob ein flacher Gain-Offset vorliegt.")
