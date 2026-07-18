import os
import sys
import subprocess


KAUSALTOOL_MAIN = os.path.expanduser(
    "sound_bridge_causality/main.py"  # <-- ANPASSEN
)

def session_has_remote_clip(session_folder: str) -> bool:
    """True, wenn im Session-Ordner eine lange Handy-Aufnahme samt der für
    die zeitliche Zuordnung nötigen JSON-Metadaten liegt - nur dann ist die
    Kausalanalyse überhaupt sinnvoll startbar."""
    if not session_folder or not os.path.isdir(session_folder):
        return False
    for fname in os.listdir(session_folder):
        if fname.startswith("remote_clip_") and fname.endswith(".wav"):
            return os.path.exists(os.path.join(session_folder, fname + ".json"))
    return False

def launch_kausaltool(session_folder: str) -> None:
    """Startet das Kausalitätstool als eigenen Prozess und übergibt den
    Session-Ordner - der wird dort automatisch geladen (siehe main.py)."""

    script_path = os.path.realpath(__file__)
    script_dir = os.path.dirname(script_path)
    subprocess.Popen(
        [sys.executable, script_dir +"/../"+ KAUSALTOOL_MAIN, session_folder],
        cwd=os.path.dirname(script_dir +"/../"+ KAUSALTOOL_MAIN),
    )
