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

# === Konfiguration ===
samplerate = 44100
chunk_size = 1024
buffer_size = 6
buffer_seconds    = buffer_size * 0.5
post_roll_seconds = buffer_size * 0.5
scale_factor      = 1.5
db_threshold      = -35.0  # überschrieben bei Kalibrierung

# === Session-Verzeichnis automatisch anlegen ===
data_root = "data"
session_id = datetime.datetime.now().strftime("session_%Y%m%d_%H%M%S")
data_dir = os.path.join(data_root, session_id)
log_filename = os.path.join(data_dir, "trigger_log.csv")

'''
# === Konfiguration ===
samplerate = 44100 #48000
chunk_size = 1024

buffer_size = 6
buffer_seconds    = buffer_size*0.5
post_roll_seconds = buffer_size*0.5
scale_factor      = 1.5
db_threshold      = -35.0  # wird durch Kalibrierung überschrieben
data_dir          = "data"
log_filename      = os.path.join(data_dir, "trigger_log.csv")
'''

# === Zustandsvariablen ===
ringbuffer = deque(maxlen=int(buffer_seconds * samplerate))
recording_post_roll = False
post_roll_samples_needed = int(post_roll_seconds * samplerate)
post_roll_samples_collected = 0
clip_buffer = []
trigger_sample_index = None

# === Hilfsfunktionen ===

def rms_value(data):
    return np.sqrt(np.mean(data**2))

def rms_to_db(rms, floor=1e-10):
    rms = max(rms, floor)
    return 20 * np.log10(rms)

def print_inline(text):
    sys.stdout.write('\r' + text)
    sys.stdout.flush()

def save_clip(data, samplerate, filename=None):
    if filename is None:
        now = datetime.datetime.now()
        filename = now.strftime("clip_%Y%m%d_%H%M%S.%f")[:-3] + ".wav"
    filename = os.path.join(data_dir, filename)

    data = np.array(data)
    max_val = np.max(np.abs(data))
    if max_val > 0:
        data = data / max_val
    data_int16 = (data * 32767).astype(np.int16)

    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(data_int16.tobytes())
    print(f"\n💾 Clip gespeichert: {filename}")


def list_devices(with_exit=False):
    print("\n🎧 Verfügbare Audio-Geräte:")
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        print(f"  {i}: {d['name']}")
    if with_exit:
        print("\n❗Bitte starte das Skript erneut mit der gewünschten Geräte-ID:\n  z. B.  python script.py --deviceid 4")
        sys.exit(1)

def prepare_data_directory():
    if os.path.exists(data_dir):
        for filename in os.listdir(data_dir):
            path = os.path.join(data_dir, filename)
            try:
                os.remove(path)
                print(f"🗑️  Gelöscht: {path}")
            except Exception as e:
                print(f"⚠️  Fehler beim Löschen von {path}: {e}")
    else:
        os.makedirs(data_dir)

    print(f"📁 Arbeitsverzeichnis: '{data_dir}/'")

def initialize_logger():
    global log_file, csv_writer
    log_file = open(log_filename, mode="a", newline="")
    csv_writer = csv.writer(log_file)
    if os.stat(log_filename).st_size == 0:
        csv_writer.writerow(["timestamp", "trigger_db", "rms", "clip_filename"])

def calibrate_noise_floor(duration=10, device_index=None, samplerate=48000, scale_factor=1.0):
    print(f"\n📏 Starte Kalibrierung ({duration} Sekunden)... Bitte still sein.")
    values = []

    def callback(indata, frames, time_info, status):
        mono = indata[:, 0] * scale_factor
        rms = np.sqrt(np.mean(mono**2))
        values.append(rms)

    with sd.InputStream(device=device_index, channels=1, samplerate=samplerate, callback=callback):
        time.sleep(duration)

    if len(values) == 0:
        print("⚠️  Keine RMS-Werte erfasst! War das Mikrofon stumm?")
        return db_threshold

    median_rms = np.median(values)
    max_rms = np.max(values)
    suggested_rms = median_rms + (max_rms - median_rms) * 0.5
    suggested_db = rms_to_db(1.0 * suggested_rms)

    print(f"\n📊 Kalibrierung abgeschlossen.")
    print(f"  • Median RMS:     {median_rms:.5f}")
    print(f"  • Max RMS:        {max_rms:.5f}")
    print(f"  • 🔧 Empfohlener Trigger-Level: {suggested_db:.2f}/{rms_to_db(suggested_rms):.2f} dB")

    return suggested_db

def select_best_samplerate(device):
    global samplerate
    for rate in [96000, 48000, 44100]:
        try:
            sd.check_input_settings(device=device, samplerate=rate)
            print(f"✅ Sample-Rate {rate} Hz funktioniert.")
            samplerate = rate
            return
        except Exception as e:
            print(f"❌ Sample-Rate {rate} Hz funktioniert NICHT: {e}")

# === Callback ===

def audio_callback(indata, frames, time_info, status):
    global ringbuffer, recording_post_roll, clip_buffer
    global post_roll_samples_collected, trigger_sample_index
    global clip_filename  # <-- wichtig!

    db_offset = 20 * np.log10(scale_factor)

    mono_raw = indata[:, 0]
    mono = mono_raw * scale_factor
    ringbuffer.extend(mono_raw)

    rms = rms_value(mono)
    db = rms_to_db(rms) - db_offset
    peak = np.max(np.abs(mono))
    peak_db = rms_to_db(peak) - db_offset
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    if db > db_threshold and not recording_post_roll:
        recording_post_roll = True
        clip_buffer = list(ringbuffer)
        post_roll_samples_collected = 0
        trigger_sample_index = len(ringbuffer)

        now = datetime.datetime.now()
        clip_filename = now.strftime("clip_%Y%m%d_%H%M%S.%f")[:-3] + ".wav"

        print(f"\n🔔 Trigger erkannt: {db:.2f} dB > {db_threshold:.2f} dB – starte Aufnahme")
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
            clip_filename = None  # reset

    print_inline(f"{timestamp} | RMS dB: {db:.2f} | Peak dB: {peak_db:.2f}")

# === Hauptprogramm ===

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audio Trigger Recorder")
    parser.add_argument('--deviceid', type=int, help='Index des Eingabe-Geräts (siehe Geräteliste)')
    parser.add_argument('--dbthreshold', type=float, help='threshold for trigger')
    parser.add_argument('--timeout', type=float, help='time out before start tracking')
    args = parser.parse_args()

    if args.deviceid is None:
        list_devices(with_exit=True)

    rode_device_index = args.deviceid
    
    list_devices(with_exit=False)
    prepare_data_directory()
    initialize_logger()

    select_best_samplerate(rode_device_index)

    if args.timeout is not None:
        print(f"wait {args.timeout} minutes.")
        time.sleep(60*args.timeout)

    if args.dbthreshold is None:
        db_threshold = calibrate_noise_floor(
            duration=10,
            device_index=rode_device_index,
            samplerate=samplerate,
            scale_factor=scale_factor
        )
    else:
        db_threshold = -1.0 * float(args.dbthreshold)
        print("using :", db_threshold)

    print(f"\n🎙️ Monitoring läuft... Pre-Roll: {buffer_seconds}s | Post-Roll: {post_roll_seconds}s")
    print("Drücke STRG+C zum Beenden.")

    try:
        with sd.InputStream(
            device=rode_device_index,
            channels=1,
            samplerate=samplerate,
            blocksize=chunk_size,
            callback=audio_callback
        ):
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n🚪 Aufnahme beendet.")
        log_file.close()
