# -*- coding: utf-8 -*-
"""
Persistiert berechnete Metrik-Ergebnisse pro Session auf die Platte, damit sie
nach einem Neustart nicht erneut berechnet werden müssen. Geht davon aus, dass
die Clips einer Session sich nach der Aufnahme nicht mehr ändern - als Schutz
davor wird die Event-Anzahl mit abgespeichert und beim Laden verglichen; bei
Abweichung gilt der gesamte Cache-Eintrag der Session als ungültig und wird
verworfen statt veraltete Werte zurückzugeben.

Ablage: eine JSON-Datei direkt im Session-Ordner (<session>/metrics_cache.json)
- wandert also mit, wenn die Session kopiert oder importiert wird.
"""

import json
import os
from typing import Dict

from metrics import MetricResult
from models import SessionData

CACHE_FILENAME = "metrics_cache.json"


def _cache_path(session_path: str) -> str:
    return os.path.join(session_path, CACHE_FILENAME)


def _result_to_dict(result: MetricResult) -> dict:
    return {
        "y_values": result.y_values,
        "y_label": result.y_label,
        "y_unit": result.y_unit,
        "baseline_low": result.baseline_low,
        "baseline_high": result.baseline_high,
        "point_labels": result.point_labels,
    }


def _result_from_dict(data: dict) -> MetricResult:
    return MetricResult(
        y_values=data["y_values"],
        y_label=data.get("y_label", "Wert"),
        y_unit=data.get("y_unit", ""),
        baseline_low=data.get("baseline_low"),
        baseline_high=data.get("baseline_high"),
        point_labels=data.get("point_labels"),
    )


def load(session: SessionData) -> Dict[str, MetricResult]:
    """Lädt alle gecachten Metrik-Ergebnisse für eine Session - aber nur, wenn
    die gespeicherte Event-Anzahl noch zur aktuellen Session passt. Bei
    fehlender/kaputter/veralteter Cache-Datei: leeres Dict, kein Fehler."""
    path = _cache_path(session.session_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}

    if raw.get("n_events") != len(session):
        return {}  # Session hat sich seit dem Cachen verändert - verwerfen

    results: Dict[str, MetricResult] = {}
    for metric_key, result_dict in raw.get("metrics", {}).items():
        try:
            results[metric_key] = _result_from_dict(result_dict)
        except Exception:
            continue  # einzelner kaputter Eintrag soll nicht den Rest blockieren
    return results


def save_one(session: SessionData, metric_key: str, result: MetricResult) -> None:
    """Ergänzt/ersetzt ein einzelnes Metrik-Ergebnis im Cache der Session,
    ohne bereits vorhandene andere Metriken zu verlieren."""
    path = _cache_path(session.session_path)
    raw = {"n_events": len(session), "metrics": {}}

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("n_events") == len(session):
                raw = existing
        except Exception:
            pass

    raw["n_events"] = len(session)
    raw.setdefault("metrics", {})
    raw["metrics"][metric_key] = _result_to_dict(result)

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw, f)
    except Exception as e:
        print(f"Fehler beim Speichern des Metrik-Caches: {e}")


def clear(session_path: str) -> None:
    """Entfernt die Cache-Datei einer Session vollständig (z.B. beim Löschen
    der Session oder wenn manuell ein Neuberechnen erzwungen werden soll)."""
    path = _cache_path(session_path)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass