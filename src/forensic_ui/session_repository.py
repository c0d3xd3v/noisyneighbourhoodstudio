# -*- coding: utf-8 -*-
"""Alles, was Dateien anfasst (CSV, JSON, Verzeichnisse). Kein Qt hier."""

import csv
import json
import os
import shutil
from datetime import datetime
from typing import Dict, List

from models import TriggerEvent, SessionData, FavoriteEntry

from causality_tool_interface import session_has_remote_clip


DEFAULT_DATA_ROOT = "/home/kaih/Downloads/data/"
CONFIG_PATH = os.path.expanduser("~/.config/noisy_neighbourhood_studio/config.json")
_MAX_RECENT = 8

_config_cache: Dict = None  # lazy geladen


def _load_config() -> Dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _config_cache = json.load(f)
                return _config_cache
        except Exception:
            pass
    _config_cache = {"data_root": DEFAULT_DATA_ROOT, "recent_roots": [DEFAULT_DATA_ROOT]}
    return _config_cache


def _save_config() -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(_config_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern der Config: {e}")


def get_data_root() -> str:
    """Das aktuell aktive Projekt (Datenordner)."""
    return _load_config()["data_root"]


def set_data_root(path: str) -> None:
    """Wechselt das aktive Projekt und merkt es sich für den nächsten Start."""
    config = _load_config()
    config["data_root"] = path
    recent = [p for p in config.get("recent_roots", []) if p != path]
    recent.insert(0, path)
    config["recent_roots"] = recent[:_MAX_RECENT]
    _save_config()


def get_recent_data_roots() -> List[str]:
    """Zuletzt benutzte Projekte, neuestes zuerst. Enthält immer das aktuelle."""
    config = _load_config()
    recent = config.get("recent_roots", [])
    current = config["data_root"]
    if current not in recent:
        recent = [current] + recent
    return recent[:_MAX_RECENT]


def get_favorites_path(data_root: str = None) -> str:
    """Favoriten liegen im jeweiligen Projekt, nicht global."""
    return os.path.join(data_root or get_data_root(), "favorites.json")


def _read_csv(csv_file: str) -> List[dict]:
    if not os.path.exists(csv_file):
        return []
    rows = []
    with open(csv_file, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append({
                    "timestamp": datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S.%f"),
                    "trigger_db": float(row["trigger_db"]),
                    "clip_filename": row.get("clip_filename", "").strip(),
                })
            except Exception:
                continue
    return rows


def _load_assignments(session_path: str) -> Dict[str, str]:
    filepath = os.path.join(session_path, "zuordnung.txt")
    mapping = {}
    if not os.path.exists(filepath):
        return mapping
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            if len(parts) == 2:
                dataset_file = os.path.basename(parts[0]).strip()
                sample_file = os.path.basename(parts[1]).strip()
                mapping[dataset_file] = sample_file
    return mapping


def load_session(session_path: str) -> SessionData:
    csv_file = os.path.join(session_path, "trigger_log.csv")
    rows = _read_csv(csv_file)
    assignments = _load_assignments(session_path)

    events = [
        TriggerEvent(
            timestamp=row["timestamp"],
            trigger_db=row["trigger_db"],
            clip_filename=row["clip_filename"],
            audio_path=os.path.join(session_path, row["clip_filename"]),
            label=assignments.get(row["clip_filename"]),
        )
        for row in rows
    ]

    has_remote_clip = session_has_remote_clip(session_path)

    return SessionData(
        session_path=session_path,
        session_name=os.path.basename(session_path),
        has_remote_clip=has_remote_clip,
        events=events,
    )


def list_sessions_by_date(data_root: str = None) -> Dict[str, List[tuple]]:
    """Gibt {datum_str: [(anzeige_label, session_path), ...]} zurück,
    genau wie bisher populate_session_tree() gebraucht hat."""
    data_root = data_root or get_data_root()
    sessions_by_date: Dict[str, List[tuple]] = {}
    if not os.path.exists(data_root):
        return sessions_by_date

    for session_name in sorted(os.listdir(data_root)):
        session_path = os.path.join(data_root, session_name)
        if not os.path.isdir(session_path):
            continue
        rows = _read_csv(os.path.join(session_path, "trigger_log.csv"))
        if not rows:
            continue
        date_str = rows[0]["timestamp"].strftime("%Y-%m-%d")
        time_start = rows[0]["timestamp"].strftime("%H:%M")
        time_end = rows[-1]["timestamp"].strftime("%H:%M")
        label = f"{time_start} – {time_end} ({len(rows)} Trigger)"
        sessions_by_date.setdefault(date_str, []).append((label, session_path))

    return sessions_by_date


def is_valid_session_folder(path: str) -> bool:
    """Ein Ordner gilt als Session, wenn er ein trigger_log.csv enthält."""
    return os.path.isfile(os.path.join(path, "trigger_log.csv"))


def import_sessions_from_folder(source_folder: str, data_root: str = None) -> List[str]:
    """
    Kopiert Sessions aus source_folder in das aktuelle Projekt (oder ein
    explizit angegebenes data_root).

    Unterstützt zwei Fälle:
    - source_folder ist selbst eine einzelne Session (enthält trigger_log.csv direkt)
    - source_folder enthält mehrere Session-Unterordner (z.B. Export vom Jetson Nano)

    Bereits vorhandene Sessions (gleicher Ordnername in data_root) werden
    übersprungen, nicht überschrieben. Gibt die Namen der neu importierten
    Sessions zurück.
    """
    data_root = data_root or get_data_root()
    imported: List[str] = []
    if not os.path.isdir(source_folder):
        return imported

    os.makedirs(data_root, exist_ok=True)

    if is_valid_session_folder(source_folder):
        candidates = [source_folder]
    else:
        candidates = [
            os.path.join(source_folder, name)
            for name in sorted(os.listdir(source_folder))
            if os.path.isdir(os.path.join(source_folder, name))
        ]

    for src in candidates:
        if not is_valid_session_folder(src):
            continue
        name = os.path.basename(os.path.normpath(src))
        dst = os.path.join(data_root, name)
        if os.path.exists(dst):
            continue  # nicht überschreiben, Duplikat einfach ignorieren
        shutil.copytree(src, dst)
        imported.append(name)

    return imported


def load_favorites(data_root: str = None) -> List[FavoriteEntry]:
    path = get_favorites_path(data_root)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [FavoriteEntry(**item) for item in raw]
    except Exception:
        return []


def save_favorites(favorites: List[FavoriteEntry], data_root: str = None) -> None:
    path = get_favorites_path(data_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump([fav.__dict__ for fav in favorites], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern der Favoriten: {e}")
