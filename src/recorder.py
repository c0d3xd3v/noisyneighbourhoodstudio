import sounddevice as sd
import numpy as np
import time
import sys
import argparse
from collections import deque
import datetime
import wave
import csv
import os
import threading


# === Konfiguration ===
chunk_size = 1024
buffer_size = 6
buffer_seconds    = buffer_size * 0.5
post_roll_seconds = buffer_size * 0.5
scale_factor      = 1.5
db_threshold      = -35.0  # Standardwert, falls keine Kalibrierung/Argument

# === Konfiguration für minutengenaue Zeitfenster ===
# Format: ((Start_Stunde, Start_Minute), (End_Stunde, End_Minute))
# Unterstützt auch Nachtfenster über Mitternacht (z.B. von 22:00 bis 06:00 Uhr)
ZEITFENSTER = [
    ((0, 0),(23,59))
]

# === Globale Variablen (Pfade & Zustände) ===
data_root = "data"
data_dir = ""
log_filename = ""
log_file = None
csv_writer = None

samplerate = 44100  # Standardwert, wird dynamisch angepasst
ringbuffer = None  # Wird nach Samplerate-Bestimmung definiert
recording_post_roll = False
post_roll_samples_needed = 0
post_roll_samples_collected = 0
clip_buffer = []
trigger_sample_index = None
clip_filename = None

measurement_thread = None
service_running = False

# === Hilfsfunktionen ===

def rms_value(data):
    return np.sqrt(np.mean(data**2)) if len(data) > 0 else 0.0

def rms_to_db(rms, floor=1e-10):
    rms = max(rms, floor)
    return 20 * np.log10(rms)

def print_inline(text):
    sys.stdout.write('\r' + text)
    sys.stdout.flush()

def save_clip(data, current_samplerate, filename=None):
    if filename is None:
        now = datetime.datetime.now()
        filename = now.strftime("clip_%Y%m%d_%H%M%S.%f")[:-3] + ".wav"

    full_path = os.path.join(data_dir, filename)

    data = np.array(data)
    # Anwenden des Skalierungsfaktors für die Ausgabedatei
    data = data * scale_factor

    # Clip-Schutz (Verzerrungen verhindern)
    data = np.clip(data, -1.0, 1.0)
    data_int16 = (data * 32767).astype(np.int16)

    with wave.open(full_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(current_samplerate)
        wf.writeframes(data_int16.tobytes())
    print(f"\n💾 Clip gespeichert: {full_path}")

def list_devices(with_exit=False):
    print("\n🎧 Verfügbare Audio-Geräte:")
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        print(f"  {i}: {d['name']}")
    if with_exit:
        sys.exit(0)

def prepare_data_directory():
    os.makedirs(data_dir, exist_ok=True)
    print(f"📁 Arbeitsverzeichnis: '{data_dir}/'")

def initialize_logger():
    global log_file, csv_writer
    log_file = open(log_filename, mode="a", newline="", encoding="utf-8")
    csv_writer = csv.writer(log_file)
    if os.stat(log_filename).st_size == 0:
        csv_writer.writerow(["timestamp", "trigger_db", "rms", "clip_filename"])
        log_file.flush()

def calibrate_noise_floor(duration=5, device_index=None, current_samplerate=44100):
    print(f"\n📏 Starte Kalibrierung ({duration} Sekunden)... Bitte still sein.")
    values = []

    def callback(indata, frames, time_info, status):
        mono = indata[:, 0]
        rms = rms_value(mono)
        values.append(rms)

    with sd.InputStream(device=device_index, channels=1, samplerate=current_samplerate, callback=callback):
        time.sleep(duration)

    if len(values) == 0:
        print("⚠️  Keine RMS-Werte erfasst! Nutze Standard-Threshold.")
        return db_threshold

    median_rms = np.median(values)
    max_rms = np.max(values)
    suggested_rms = median_rms + (max_rms - median_rms) * 0.5
    suggested_db = rms_to_db(suggested_rms)

    print(f"\n📊 Kalibrierung abgeschlossen.")
    print(f"  • Median dB:      {rms_to_db(median_rms):.2f} dB")
    print(f"  • Max dB:         {rms_to_db(max_rms):.2f} dB")
    print(f"  • 🔧 Empfohlener Trigger-Level: {suggested_db:.2f} dB")

    return suggested_db


def select_best_samplerate(device):
    global samplerate
    # Hier ist die korrekte, vollständige Liste hinterlegt:
    for rate in [96000, 48000, 44100]:
        try:
            sd.check_input_settings(device=device, samplerate=rate)
            print(f"✅ Sample-Rate {rate} Hz funktioniert.")
            samplerate = rate
            return
        except Exception:
            continue
    print(f"⚠️ Keine Standard-Samplerate erkannt. Versuche 44100 Hz blind.")
    samplerate = 44100

def is_in_any_time_window():
    """Prüft, ob die aktuelle Uhrzeit in mindestens eines der minutengenauen Fenster fällt."""
    jetzt = datetime.datetime.now().time()

    for start_tup, ende_tup in ZEITFENSTER:
        start_zeit = datetime.time(start_tup[0], start_tup[1], 0)
        ende_zeit = datetime.time(ende_tup[0], ende_tup[1], 0)

        if start_zeit > ende_zeit:
            # Über-Nacht-Logik (z.B. 22:00 bis 06:00)
            if jetzt >= start_zeit or jetzt < ende_zeit:
                return True
        else:
            # Normale Tag-Logik (z.B. 20:32 bis 20:33)
            if start_zeit <= jetzt < ende_zeit:
                return True

    return False

def create_new_session():
    """Erstellt ein neues Session-Verzeichnis und initialisiert den Logger neu."""
    global data_dir, log_filename, log_file, csv_writer, ringbuffer, clip_buffer, recording_post_roll

    # Zustand zurücksetzen
    recording_post_roll = False
    clip_buffer = []
    if ringbuffer is not None:
        ringbuffer.clear()

    # Alten Logger schließen, falls vorhanden
    if log_file and not log_file.closed:
        log_file.close()

    # Neue Pfade generieren
    session_id = datetime.datetime.now().strftime("session_%Y%m%d_%H%M%S")
    data_dir = os.path.join(data_root, session_id)
    log_filename = os.path.join(data_dir, "trigger_log.csv")

    # Struktur anlegen
    prepare_data_directory()
    initialize_logger()
    print(f"🚀 Neue Session gestartet: {data_dir}")

# === Audio Callback ===

def audio_callback(indata, frames, time_info, status):
    global ringbuffer, recording_post_roll, clip_buffer
    global post_roll_samples_collected, trigger_sample_index
    global clip_filename

    if status:
        print(f"\n⚠️ Status-Fehler im Audio-Stream: {status}")

    mono_raw = indata[:, 0]
    ringbuffer.extend(mono_raw)

    # Pegelberechnung auf Basis des Originalsignals
    rms = rms_value(mono_raw)
    db = rms_to_db(rms)

    # Korrekte Peak-Berechnung in dBFS
    peak = np.max(np.abs(mono_raw))
    peak_db = 20 * np.log10(peak) if peak > 1e-10 else -100.0

    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    if db > db_threshold and not recording_post_roll:
        recording_post_roll = True
        clip_buffer = list(ringbuffer)
        post_roll_samples_collected = 0
        trigger_sample_index = len(ringbuffer)

        now = datetime.datetime.now()
        clip_filename = now.strftime("clip_%Y%m%d_%H%M%S.%f")[:-3] + ".wav"

        print(f"\n🔔 Trigger erkannt: {db:.2f} dB > {db_threshold:.2f} dB – starte Aufnahme")
        if csv_writer:
            csv_writer.writerow([timestamp, f"{db:.2f}", f"{rms:.5f}", clip_filename])
            log_file.flush()

    if recording_post_roll:
        clip_buffer.extend(mono_raw)
        post_roll_samples_collected += len(mono_raw)

        if post_roll_samples_collected >= post_roll_samples_needed:
            recording_post_roll = False
            if clip_filename:
                save_clip(clip_buffer, samplerate, filename=clip_filename)
                trigger_time_sec = trigger_sample_index / samplerate
                print(f"📍 Trigger war bei {trigger_time_sec:.3f} s im Clip")
            else:
                print("⚠️ Kein Dateiname gesetzt – Clip wird nicht gespeichert.")
            clip_buffer = []
            trigger_sample_index = None
            clip_filename = None  # Reset

    print_inline(f"{timestamp} | RMS dB: {db:.2f} | Peak dB: {peak_db:.2f}")

def run_measurement_core(device_id, threshold=None):
    global rode_device_index, db_threshold, samplerate, ringbuffer, post_roll_samples_needed, log_file, service_running

    # WICHTIG: service_running wird jetzt von Flask beim Klick auf Start auf True gesetzt!
    rode_device_index = device_id

    select_best_samplerate(rode_device_index)
    ringbuffer = deque(maxlen=int(buffer_seconds * samplerate))
    post_roll_samples_needed = int(post_roll_seconds * samplerate)

    if threshold is None:
        db_threshold = calibrate_noise_floor(
            duration=5, device_index=rode_device_index, current_samplerate=samplerate
        )
    else:
        db_threshold = float(threshold)

    stream = None
    session_active = False

    print("\n💤 System im Standby. Warte auf Start-Befehl via WLAN...")

    try:
        # Die Schleife läuft erst, wenn service_running True ist
        while service_running:
            active_now = is_in_any_time_window()

            if active_now and not session_active:
                print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Überwachungsfenster erreicht. Starte Session...")
                create_new_session()

                stream = sd.InputStream(
                    device=rode_device_index,
                    channels=1,
                    samplerate=samplerate,
                    blocksize=chunk_size,
                    callback=audio_callback
                )
                stream.start()
                session_active = True

            elif not active_now and session_active:
                print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Zeitfenster beendet. Schließe Session...")
                if stream:
                    stream.stop()
                    stream.close()
                    stream = None
                if log_file and not log_file.closed:
                    log_file.close()
                session_active = False

            time.sleep(1.0)

    finally:
        if stream:
            stream.stop()
            stream.close()
        if log_file and not log_file.closed:
            log_file.close()
        print("\n🛑 Audio-Kernschleife sauber beendet und im Standby.")

def start_service(device_id, threshold=None):
    global measurement_thread
    global service_running

    if service_running:
        return False

    service_running = True

    measurement_thread = threading.Thread(
        target=run_measurement_core,
        args=(device_id, threshold),
        daemon=True
    )

    measurement_thread.start()
    return True

def stop_service():
    global service_running

    service_running = False


# === Hauptprogramm ===

if __name__ == "__main__":
    service_running = True

    parser = argparse.ArgumentParser(
        description="Audio Trigger Recorder für Lärm- und Impulsüberwachung in bestimmten Zeitfenstern.",
        add_help=False
    )

    # Argumente definieren
    parser.add_argument('-h', '--help', action='help', help='Zeigt diese Hilfe an und beendet das Programm.')
    parser.add_argument('--deviceid', type=int, help='Index des Audio-Eingabegeräts (z.B. Mikrofon)')
    parser.add_argument('--dbthreshold', type=float, help='Schwellenwert für Trigger in dB (z.B. -35.0). Falls weggelassen, startet die automatische Kalibrierung.')
    parser.add_argument('--timeout', type=float, help='Optionale Wartezeit vor dem allerersten Überwachungsstart (in Minuten).')
    parser.add_argument('--list', action='store_true', help='Listet alle verfügbaren Audiogeräte und deren IDs auf.')

    # Wenn überhaupt keine Parameter übergeben wurden, erzwinge die Hilfe-Ausgabe
    if len(sys.argv) == 1:
        print("\n❌ Fehler: Keine Parameter angegeben!")
        print("Du musst mindestens die `--deviceid` deines Mikrofons angeben.")
        print("-" * 60)
        parser.print_help()
        print("-" * 60)
        print("\n💡 TIPP: Nutze zuerst `python script.py --list`, um die passende ID deines Mikrofons herauszufinden.")
        sys.exit(1)

    args = parser.parse_args()

    # Falls nur die Geräteliste angefordert wurde
    if args.list:
        list_devices(with_exit=True)

    # Validierung: Device ID wird für den normalen Betrieb benötigt
    if args.deviceid is None:
        print("\n❌ Fehler: Für den Überwachungsmodus wird das Argument `--deviceid` zwingend benötigt.")
        list_devices(with_exit=True)

    run_measurement_core(args.deviceid, args.dbthreshold)
