# 🎧🔨 noisyneighbourhoodstudio

**DE:** Willkommen im **noisyneighbourhoodstudio** – dem einzigen Ort, an dem der nächtliche Hammerbohrer des Nachbarn die verdiente professionelle Aufbereitung erhält.

**EN:** Welcome to **noisyneighbourhoodstudio** – the only place where your neighbor's 3 AM hammering gets the professional production treatment it truly deserves.

---

**DE:** Dieses Tool verwandelt hilfloses Ärgernis in handfeste Beweise. Es bietet eine interaktive Oberfläche zur **forensischen Analyse von Audio-Samples**, spezialisiert auf die Detektion und Isolierung von **Impulsgeräuschen** (Türknallen, Poltern, Schläge). Schluss mit Vermutungen: Hier wird Lärm nicht nur gehört, sondern seziert, visualisiert und dokumentiert. Weil jeder störende Impuls ein Kunstwerk für sich ist – und jedes Kunstwerk eine akribische Analyse verdient.

**EN:** This tool transforms helpless frustration into concrete evidence. It provides an interactive interface for the **forensic analysis of audio samples**, specializing in the detection and isolation of **impulse noises** (door slamming, thumping, banging). Stop guessing: here, noise isn't just heard; it's dissected, visualized, and documented. Because every disturbing impulse is a masterpiece in its own right – and every masterpiece deserves a meticulous analysis.

---

## Features

- 🎙️ **Aufnahme** – kontinuierliche Überwachung mit automatischer Aufzeichnung bei Überschreitung eines adaptiven Schwellwerts
- 🏷️ **Klassifizierung** – manuelle Beschriftung der erfassten Ereignisse (z. B. Poltern, Tür, Musik)
- 📊 **Visualisierung** – interaktive Baumansicht aller Sessions, Zeitreihen der Störpegel, Waveforms und Spektrogramme pro Ereignis

## So funktioniert die Trigger-Erkennung

Der Kern des Systems: Der Schwellwert wird nicht manuell festgelegt, sondern bei jedem Start automatisch aus der aktuellen Umgebungsstille kalibriert – das System passt sich also an unterschiedliche Räume, Mikrofone und Hintergrundgeräusche an.

1. Beim Start läuft eine kurze Kalibrierungsphase (typischerweise ~10 Sekunden), in der die RMS-Amplitude aller eingehenden Audiosamples erfasst wird:

   $$R = \{R_1, R_2, \dots, R_N\}$$

2. Daraus werden Median und Maximum berechnet:

   $$m = \text{median}(R), \qquad M = \max(R)$$

3. Der Trigger-RMS-Level ergibt sich als Mittelwert zwischen beiden:

   $$R_{trigger} = \frac{m + M}{2}$$

4. Umrechnung in Dezibel:

   $$\text{Trigger-Level (dB)} = 20 \times \log_{10}(R_{trigger})$$

**Effekt:** Alltagsgeräusche (Kühlschrank, Straßenlärm) werden automatisch herausgefiltert – nur echte Ausreißer lösen eine Aufzeichnung aus.

> ⚠️ **Hinweis zur Kalibrierung:** Das System ist *relativ* zur Umgebungslautstärke kalibriert, nicht absolut. Für Vergleiche zwischen Ereignissen ist daher der **Frequenzinhalt (Spektrogramm)** aussagekräftiger als die reine Amplitude.

## Interface

Die Visualisierung gliedert sich in drei Bereiche:

- **Baumansicht (links):** alle aufgezeichneten Sessions, gruppiert nach Tag, mit Anzahl der Trigger pro Zeitfenster
- **Trigger-Pegelverlauf (oben rechts):** Zeitreihe aller Störereignisse der ausgewählten Session in dB
- **Event-Detail (unten rechts):** Klick auf einen Punkt in der Zeitreihe zeigt Waveform und zugehöriges Spektrogramm des jeweiligen Ereignisses

## Hardware-Setup

- **Mikrofon:** Rode NT-USB mini (kalibriertes Kondensatormikrofon, Studioqualität, kein Consumer-Gerät)
- **Positionierung:** ca. 70–80 cm unter der Zimmerdecke

## Installation

```bash
git clone <repo-url>
cd noisyneighbourhoodstudio
pip install -r requirements.txt
```

> 🚧 TODO – `requirements.txt` ergänzen, Python-Version angeben, Startbefehl(e) für Aufnahme/Klassifizierung/Visualisierung dokumentieren

## Tech Stack

- **Python**
- **PySide6** – GUI-Framework
- **pyqtgraph** – Echtzeit-Plots (Trigger-Pegelverlauf, Waveform, Spektrogramm)

> 🚧 TODO – weitere Abhängigkeiten ergänzen (z. B. Audio-I/O, Signalverarbeitung)

## Lizenz

> 🚧 TODO
