# -*- coding: utf-8 -*-
"""
Filtert ein bereits geladenes Audiosignal für die Wiedergabe-Vorschau
(Tiefpass/Hochpass/Bandpass). Rein für's Anhören gedacht - die im Hauptfenster
angezeigte Waveform/Spektrogramm bleiben immer das unveränderte Original,
damit die dokumentierte Ansicht nicht mit der Hör-Vorschau vermischt wird.
"""

import numpy as np
from scipy.signal import butter, filtfilt

LOWPASS = "lowpass"
HIGHPASS = "highpass"
BANDPASS = "bandpass"


def apply_filter(data: np.ndarray, sr: int, filter_type: str,
                  cutoff_low: float, cutoff_high: float = None, order: int = 4) -> np.ndarray:
    nyquist = sr / 2.0

    if filter_type == LOWPASS:
        b, a = butter(order, cutoff_low / nyquist, btype="low")
    elif filter_type == HIGHPASS:
        b, a = butter(order, cutoff_low / nyquist, btype="high")
    elif filter_type == BANDPASS:
        if cutoff_high is None:
            raise ValueError("Bandpass braucht eine obere Grenzfrequenz.")
        low = cutoff_low / nyquist
        high = cutoff_high / nyquist
        if not (0 < low < high < 1):
            raise ValueError("Ungültiger Frequenzbereich für Bandpass (0 < low < high < Nyquist).")
        b, a = butter(order, [low, high], btype="band")
    else:
        raise ValueError(f"Unbekannter Filtertyp: {filter_type}")

    return filtfilt(b, a, data)