# -*- coding: utf-8 -*-
"""Reine Datenklassen. Kein Qt, kein I/O, keine Business-Logik hier."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class TriggerEvent:
    timestamp: datetime
    trigger_db: float          # roher Wert aus der CSV (Rtrigger in dB)
    clip_filename: str         # z.B. "gutzeit_071225.wav"
    audio_path: str            # voller Pfad zur wav-Datei (session_path/clip_filename)
    label: Optional[str] = None  # aus zuordnung.txt, falls vorhanden


@dataclass
class SessionData:
    session_path: str
    session_name: str
    has_remote_clip: bool
    events: List[TriggerEvent] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.events)

    @property
    def is_empty(self) -> bool:
        return len(self.events) == 0


@dataclass
class FavoriteEntry:
    session_path: str
    clip_filename: str
    timestamp: str
    db: float
