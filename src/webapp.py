import time, os
from flask import jsonify
from flask import Flask, render_template, request, redirect, jsonify
import sounddevice as sd
import recorder

session_start = None

app = Flask(__name__)


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

    return render_template(
        "index.html",
        devices=devices,
        running=recorder.service_running,
        threshold=recorder.db_threshold,
        samplerate=recorder.samplerate
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


@app.route("/upload_local", methods=["POST"])
def upload_local():
    # 1. Prüfen, ob die Datei im Request existiert
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Keine Datei empfangen"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "Leerer Dateiname"}), 400

    # 2. Den Pfad direkt aus der recorder-Bibliothek auslesen
    # Falls noch keine Session gestartet wurde, nutzen wir den aktuellen Ordner als Fallback
    target_dir = getattr(recorder, "data_dir", None)

    if not target_dir:
        return jsonify({"ok": False, "error": "Keine aktive Session in recorderlib gefunden"}), 400

    # 3. Datei im exakten Session-Ordner abspeichern
    file_path = os.path.join(target_dir, file.filename)
    file.save(file_path)

    return jsonify({"ok": True, "path": file_path})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, ssl_context=("/home/defaultuser/certs/cert.pem",
                 "/home/defaultuser/certs/key.pem"))
