import time, os, sys
from flask import jsonify
from flask import Flask, render_template, request, redirect, jsonify, Response
import sounddevice as sd
import threading
import queue 

import recorder

session_start = None
app = Flask(__name__)

# ==============================================================================
# HIER DEN OPTIMIERTEN LOG-OBSERVER EINFÜGEN
# ==============================================================================
class TriggerEventObserver:
    def __init__(self):
        self.terminal = sys.stdout
        self.subscribers = []

    def write(self, message):
        self.terminal.write(message)
        # Filtert gezielt die Zeile aus deinem Backend-Skript
        if "🔔 Trigger erkannt" in message:
            clean_msg = message.strip().replace('\r', '')
            for q in self.subscribers:
                q.put(clean_msg)

    def flush(self):
        self.terminal.flush()

    def subscribe(self):
        q = queue.Queue()
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        if q in self.subscribers:
            self.subscribers.remove(q)

# System-Output global auf unseren neuen Observer umleiten
sys.stdout = TriggerEventObserver()

@app.route("/session/start")
def start_session():
    global session_start

    session_start = time.time()

    return {"ok": True, "start": session_start}

@app.route("/")
def index():
    devices = []

    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            devices.append({"id": i, "name": d["name"]})

    # Liest den echten Geräte-Index aus Ihrer recorderlib aus
    current_device = getattr(recorder, "rode_device_index", 0)

    # Sicherheits-Fallback falls die Variable im Backend auf None steht
    if current_device is None:
        current_device = 0

    return render_template(
        "index.html",
        devices=devices,
        current_device=current_device,
        running=recorder.service_running,
        threshold=recorder.db_threshold,
        samplerate=recorder.samplerate
    )

# 1. WICHTIG: Erlaube Flask, Pfade mit ODER ohne "/" am Ende exakt gleich zu routen
app.url_map.strict_slashes = False

# 2. WICHTIG: CORS-Header setzen, damit die IP-Adresse 192.168.1.4 zugreifen darf
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route('/api/events')
def sse_endpoint():
    event_queue = sys.stdout.subscribe()

    def event_generator():
        try:
            while True:
                log_line = event_queue.get()
                yield f"data: {log_line}\n\n"
        except GeneratorExit:
            sys.stdout.unsubscribe(event_queue)

    # 3. WICHTIG: Richtige Header für SSE erzwingen
    return Response(
        event_generator(), 
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'  # Verhindert Proxy-Buffering (z.B. Nginx)
        }
    )

@app.route("/recording/start", methods=["POST"])
def start():
    device = int(request.form["device"])
    threshold = request.form.get("threshold", "")

    threshold = None if threshold == "" else float(threshold)

    recorder.start_service(device, threshold)
    return redirect("/")

@app.route("/ping")
def ping():
    return jsonify({
        "server_time": time.time()
    })

@app.route("/recording/stop", methods=["POST"])
def stop():
    recorder.stop_service()
    return redirect("/")


@app.route("/status")
def status():
    return jsonify({
        "running": recorder.service_running,
        "threshold": recorder.db_threshold,
        "samplerate": recorder.samplerate
    })


import json
from datetime import datetime

@app.route("/upload_local", methods=["POST"])
def upload_local():
    # 1. Prüfen, ob die Datei im Request existiert
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Keine Datei empfangen"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "Leerer Dateiname"}), 400

    # 2. Den Pfad direkt aus der recorder-Bibliothek auslesen
    target_dir = getattr(recorder, "data_dir", None)
    if not target_dir:
        return jsonify({"ok": False, "error": "Keine aktive Session in recorderlib gefunden"}), 400

    # 3. Dynamischen Namen generieren (Überschreibt das "local.wav" vom Browser)
    sync_timestamp_ms = request.form.get("sync_server_timestamp")
    
    if sync_timestamp_ms:
        try:
            # Millisekunden-Zeitstempel in Sekunden für datetime umrechnen
            timestamp_seconds = float(sync_timestamp_ms) / 1000.0
            dt = datetime.fromtimestamp(timestamp_seconds)
            
            # Erzeugt das Format: 20260705_153020.619
            formatted_time = dt.strftime("%Y%m%d_%H%M%S") + f".{dt.strftime('%f')[:3]}"
            filename = f"remote_clip_{formatted_time}.wav"
        except Exception:
            # Fallback 1: Falls die Umrechnung schiefläuft
            filename = f"remote_clip_fallback_{int(time.time() * 1000)}.wav"
    else:
        # Fallback 2: Falls kein Zeitstempel im Formular ankam
        filename = f"remote_clip_notime_{int(time.time() * 1000)}.wav"

    # 4. Datei im exakten Session-Ordner abspeichern
    file_path = os.path.join(target_dir, filename)
    file.save(file_path)

    # 5. Timing-Metadaten für alle Fälle als JSON mitsichern
    timing_data = {
        "browser_start_time_ms": request.form.get("browser_start_time"),
        "calculated_server_start_time_ms": sync_timestamp_ms,
        "upload_received_server_time_ms": time.time() * 1000,
        "generated_filename": filename
    }
    
    meta_path = os.path.join(target_dir, f"{filename}.json")
    with open(meta_path, "w") as f:
        json.dump(timing_data, f, indent=4)

    return jsonify({"ok": True, "path": file_path, "filename": filename})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False, ssl_context=("/home/defaultuser/certs/cert.pem",
                 "/home/defaultuser/certs/key.pem"))

