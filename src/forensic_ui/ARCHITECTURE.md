# Noisy Neighbourhood Studio – Architektur

## Ziel
x-Achse (Zeitstempel der Trigger-Events) bleibt immer gleich.
y-Achse ("was zeigen wir an?") wird austauschbar: aktuell "Pegel relativ (dB)",
später z.B. "Pegeldynamik" (Crest-Faktor, Anstiegszeit, dB-Spannweite pro Event, ...).

## Module

```
models.py              -> reine Datenklassen (TriggerEvent, SessionData)
session_repository.py  -> I/O: CSV lesen, Sessions scannen, Favoriten laden/speichern
metrics.py              -> Metric-Interface + MetricRegistry + konkrete Metriken
plot_view.py            -> TriggerPlotWidget: kennt nur (x_values, MetricResult)
audio_render.py         -> Waveform + Spektrogramm zeichnen (unverändert aus altem Code)
clock_widget.py         -> AnalogClockWidget (unverändert)
main_window.py          -> baut GUI zusammen, verdrahtet Signale
main.py                 -> Entry point
```

## Datenfluss

1. `session_repository.load_session(path)` -> `SessionData`
   (enthält Liste von `TriggerEvent`, jeder mit timestamp, raw db, clip_filename, Pfad zur wav)

2. Nutzer wählt eine Metrik im UI (Dropdown), z.B. "trigger_level" oder später "pegeldynamik"

3. `MetricRegistry.get(key).compute(session)` -> `MetricResult`
   (enthält y_values, y_label, y_unit, optionale Baselines, optionale Punkt-Labels)

4. `TriggerPlotWidget.set_metric(session, metric_result)`
   - x_values = [e.timestamp for e in session.events]  <- ändert sich NIE beim Metrik-Wechsel
   - y_values = metric_result.y_values                  <- das einzige, was sich ändert
   - Plot wird neu gezeichnet, Klick-Handling (on_click -> Event-Index) bleibt identisch,
     weil der Index in x_values/y_values/session.events immer synchron ist.

## Neue Metrik hinzufügen (später)

```python
@MetricRegistry.register
class PegeldynamikMetric(Metric):
    key = "pegeldynamik"
    display_name = "Pegeldynamik (Crest-Faktor pro Event)"

    def compute(self, session: SessionData) -> MetricResult:
        y = []
        for event in session.events:
            data, sr = load_audio(event.audio_path)   # audio_render.load_audio
            crest = np.max(np.abs(data)) / (np.sqrt(np.mean(data**2)) + 1e-12)
            y.append(crest)
        return MetricResult(y_values=y, y_label="Crest-Faktor", y_unit="")
```

Das ist alles. Kein Eingriff in plot_view.py, main_window.py oder session_repository.py nötig.
Die einzige Regel: `len(y_values) == len(session.events)`, Reihenfolge synchron zu x_values.

## Warum SessionData und nicht nur die CSV-Spalten?

Damit eine Metrik wie Pegeldynamik auch auf die Audiodatei selbst zugreifen kann
(nicht nur auf den einen dB-Wert aus der CSV), hält TriggerEvent den vollen Pfad
zur .wav-Datei. Metriken, die nur CSV-Spalten brauchen (wie die aktuelle),
ignorieren das einfach.
