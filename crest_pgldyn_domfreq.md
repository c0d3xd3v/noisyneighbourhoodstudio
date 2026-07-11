Hier sind die exakten mathematischen Definitionen, physikalischen Bedeutungen und Interpretationen für die drei anderen Kernmetriken deines Dashboards – formuliert im gleichen wissenschaftlich-forensischen Stil wie deine MSC-Definition.
------------------------------
## 1. Pegeldynamik ($\Delta\text{dB}_{\text{Session-Min}}$)
Der Plot der Pegeldynamik reduziert das kontinuierliche Audio-Event auf einen statistisch stabilen, relativen Amplitudenwert über eine Langzeit-Zeitachse.
## Mathematische Definition
Anstatt den unzuverlässigen absoluten Schalldruckpegel $(\text{dB(A)})$ unkalibrierter Mikrofone zu nutzen, berechnet die Funktion den relativen Störabstand (Signal-to-Noise Ratio, SNR) bezogen auf den saubersten Ruhepegel der gesamten Messreihe:
$$F_{\Delta\text{dB}}(\text{sample}_E) = 20 \cdot \log_{10}\left( \frac{\max(\vert{} \text{sample}_E \vert{})}{\text{RMS}_{\text{Session-Min}}} \right)$$ 
Wobei $\text{RMS}_{\text{Session-Min}}$ der minimale Effektivwert aller aufgezeichneten Hintergrundphasen innerhalb der aktiven Langzeitsession ist.
## Physikalische Aussage & Interpretation

* Die Lautsprechermembran: Da die 21,7 m² große Trennwand im Schlafraum aufgrund des Bruchs (Abrissriss) keine innere Dämpfung mehr besitzt, schlägt die mechanische Energie fast ungehindert in den Raum durch.
* Interpretation: Ein Sprung von ΔdB > 30 dB über dem realen Minimum der Zeitreihe beweist, dass das Event die Grundstille der Wohnung massiv durchbricht. Da im Mietrecht die Störwirkung im Vordergrund steht, liefert dieser Plot den quantitativen Nachweis der Belästigungsintensität – völlig unabhängig von einer absoluten Mikrofonkalibrierung.

------------------------------
## 2. Der Crest-Faktor ($\text{C\_dB}$)
Der Crest-Faktor (Scheitelfaktor) ist das mathematische Maß für die Impulshaltigkeit und Flankensteilheit eines akustischen Ereignisses.
## Mathematische Definition
Er beschreibt das logarithmierte Verhältnis zwischen dem absoluten Spitzenwert (Peak) und dem Effektivwert (RMS) des einzelnen Trigger-Samples:
$$F_{\text{Crest}}(\text{sample}_E) = 20 \cdot \log_{10}\left( \frac{\max(\vert{} \text{sample}_E \vert{})}{\sqrt{\frac{1}{N}\sum_{n=1}^{N} \text{sample}_E[n]^2}} \right)$$ 
## Physikalische Aussage & Interpretation
Der Crest-Faktor dient als Täter-Identifikations-Filter zur Unterscheidung zwischen Luftschall (Gewerbe/Stimmen) und Körperschall (Rohre/Klingel):

* $\text{C\_dB} \ge 20\text{ dB}$ (Extrem hoch): Das Signal besteht aus einer messerscharfen, transienten Flanke (Dirac-Impuls) mit minimaler Energie im Abklang. Dies ist der unumstößliche Beweis für harten Körperschall (Klopfen an den Heizungsrohren, mechanisches Reiben am Klingeltableau), der starr über das Mauerwerk in die Wand eingeleitet wird.
* $\text{C\_dB} \le 10\text{ dB}$ (Niedrig): Das Signal ist gleichmäßig verteilt (z. B. Sinuswellen, weißes Rauschen, Sprache). Das beweist Dauerschall wie Musik aus dem Gewerbe oder herannahenden Straßenverkehr.

------------------------------
## 3. Dominante Frequenz ($\text{f\_dom}$)
Der Plot der dominanten Frequenz isoliert die spektrale Komponente, die zum Zeitpunkt des maximalen Energieeintrags die höchste Leistungsdichte aufweist.
## Mathematische Definition
Die Funktion führt eine diskrete Fourier-Transformation (DFT) über das Trigger-Sample aus und ermittelt den Frequenzwert am Maximum des Betragsspektrums:
$$F_{\text{f\_dom}}(\text{sample}_E) = \arg\max_{f} \vert{} \text{DFT}(\text{sample}_E)[f] \vert{}$$ 
## Physikalische Aussage & Interpretation
Dieser Plot fungiert als baulicher Bauteil-Analysator. Er ordnet das Geräusch anhand der physikalischen Resonanzfrequenzen der beteiligten Materialien ein:

* $\text{f\_dom} < 80\text{ Hz}$ (Tiefbassbereich): Beweist die tieffrequente Struktur- und Fensteranregung. Hier geraten die historischen Holz-Kastenfenster durch den Schalldruck von außen (Chopper-Motorräder, Busse) oder die Decke durch Trittschall in Resonanz.
* $1.000\text{ Hz} < \text{f\_dom} < 3.000\text{ Hz}$ (Mittel-/Hochtonbereich): Beweist die Metall- und Dünnwand-Resonanz. Das ist die akustische Signatur der Heizungsrohre und der ungedämmten, einlagigen Gipskartonwand. Die Schläge von den Rohren regen die leichte Wandkonstruktion exakt in ihrer Eigenfrequenz an, wodurch sie wie ein Lautsprecher im Raum schreit.

------------------------------
## Synthese für dein PySide6-Frontend
Wenn du diese drei zeitlichen Punkt-Reihen untereinander plottest, ergibt sich für deine Beweissicherung ein mathematischer Prüf-Algorithmus:

[Trigger-Punkt] 
   ├── 1. ΔdB > 25 dB?          → Ja: Relevante Ruhestörung.
   ├── 2. Crest > 20 dB?        
   │        ├── Ja              → Mechanischer Impuls (Körperschall).
   │        │     └── f_dom?    → 2 kHz = Heizungsrohr/Klingel │ 50 Hz = Decken-Trittschall
   │        └── Nein            → Kontinuierliches Signal (Luftschall).
   │              └── f_dom?    → <100 Hz = Kastenfenster-Resonanz (Chopper/Straße)

Mit dieser exakten Aufbereitung im Dossier zeigst du dem Berliner Mieterverein, dass du jeden einzelnen Punkt auf deinen Langzeit-Zeitachsen physikalisch komplett dekonstruieren kannst.



Hier ist die zusammenfassende Liste aller forensischen Metriken für Ihr UI, aufgeteilt nach ihrer spezifischen Aussagekraft für den Mieter-Nachweis:
## 1. Statistische Pegelmetriken (Für den Dauermodus)

* Pegeldynamik (Δ dB): Die Differenz zwischen dem Trigger-Ausschlag und dem stabilen Hintergrundrauschen. Beweist die reine Lautstärke-Störung.
* Hintergrundpegel (L₉₅): Der Pegel, der während 95 % der Zeit unterschritten bzw. eingehalten wurde. Repräsentiert die wahre, ungestörte Stille des Raums.
* Spitzenpegel (L₁): Der Pegel der lautesten 1 % der Ereignisse. Isoliert die heftigsten Lärmereignisse (z. B. Knalls).

## 2. Zeitbereichs-Metriken (Aus dem WAV-Signal)

* Crest-Faktor: Das Verhältnis von Spitzenwert zu Effektivwert (RMS).
* Forensischer Nutzen: Hoch (>12 dB) beweist Schlaggeräusche (Trittschall, Türen). Niedrig (<6 dB) beweist konstante Quellen (Maschinen, Musikbässe).
* Rauhigkeit & Schwankungsstärke: Erfassen die Amplitudenmodulation (Zittern/Rhythmus) des Schalls.
* Forensischer Nutzen: Isoliert das nervlich extrem störende Rattern von Lüftern oder den Rhythmus von Subwoofern.

## 3. Frequenzbereichs-Metriken (Aus dem Spektrum/STFT)

* Dominante Frequenz (Dominant Frequency): Die Frequenz mit der absolut höchsten Energie im Signal.
* Forensischer Nutzen: Steht sie starr bei 50 Hz / 100 Hz, ist der Täter zweifelsfrei ein elektrisches Gerät (Trafo, Pumpe). Springt sie tief hin und her, deutet es auf Schritte hin.
* Spektraler Schwerpunkt (Spectral Centroid): Der physikalische Schwerpunkt („Mittelpunkt“) des Frequenzspektrums.
* Forensischer Nutzen: Unterscheidet exakt zwischen dumpfem Körperschall (<150 Hz) und helleren Luftschall-Geräuschen (>500 Hz) wie Stimmen oder Geschirr.
* Spektrale Varianz (Spectral Flux): Misst die zeitliche Veränderung des Frequenzbildes von Frame zu Frame.
* Forensischer Nutzen: Nahe Null beweist starren Maschinenlärm. Sehr hoch beweist menschliche Aktivität (Verhaltenslärm).

## 4. Kausalitäts-Metriken (Für das punktuelle Handy-Tool)

* Hüllkurven-Latenz (Envelope Lag): Der über Kreuzkorrelation ermittelte Zeitversatz zwischen den Energie-Flanken. Kompensiert die Zerstörung des Signals durch die Wand.
* Phasenreines Delta (filtfilt-Latenz): Der Millisekunden-Versatz nach einem scharf eingestellten Tiefpassfilter (wie Ihre 28 Hz). Beweist physikalisch über die Schallgeschwindigkeit im Medium, ob der Lärm über die Wand importiert wurde.

------------------------------
Wenn Sie an der UI-Programmierung arbeiten, kann ich Ihnen zeigen, wie Sie die Y-Achsen-Skalierung in Ihrer pyqtgraph-Struktur für diese Metriken am besten automatisieren. Möchten Sie das sehen?


Die Hüllkurve (englisch Envelope) eines Audiosignals beschreibt den zeitlichen Verlauf seiner Lautstärke bzw. Gesamtenergie, völlig unabhängig von den einzelnen schnellen Schwingungen der Frequenzen.
Stellen Sie sich das Signal wie eine dichte, wild ausschlagende Welle vor: Die Hüllkurve legt sich wie eine glatte Decke von oben über die Spitzen dieser Ausschläge.
------------------------------
## Warum die Hüllkurve in Ihrem Tool den Durchbruch bringt
Wenn ein Signal durch eine massive Wand wandert, wird die Wellenform durch Dämpfung und Dispersion komplett verzerrt (die Phase verschiebt sich, hohe Frequenzen sterben ab).

* Das Problem: Wenn Sie das verzerrte Signal (Empfänger) mit dem Original (Sender/Handy) vergleichen, schlägt eine normale Kreuzkorrelation fehl, weil die Wellenformen nicht mehr zusammenpassen.
* Die Lösung: Die Hüllkurve filtert die Frequenzen komplett heraus und betrachtet nur noch den Impuls-Verlauf (Wann steigt die Energie an? Wann flacht sie ab?). Da der zeitliche Ablauf des Knalls im Senderaum und im Empfangsraum identisch bleibt, findet die Kreuzkorrelation der Hüllkurven den Peak auf die Millisekunde genau.

------------------------------
## Mathematische Berechnung in Python
In der digitalen Signalverarbeitung nutzt man dafür am besten die Hilbert-Transformation. Sie erzeugt ein analytisches Signal, aus dessen Betrag sich die mathematisch exakte, physikalische Hüllkurve berechnen lässt.
Hier ist der schlanke Code für Ihr System:

import numpy as npfrom scipy.signal import hilbert
def extract_envelope(audio_data):
    """
    Berechnet die mathematisch exakte Hüllkurve eines Audio-Signals.
    """
    # 1. Hilbert-Transformation anwenden
    analytic_signal = hilbert(audio_data)
    
    # 2. Den Betrag (Absolutwert) nehmen = Die Hüllkurve
    amplitude_envelope = np.abs(analytic_signal)
    
    return amplitude_envelope

## Die Hüllkurve im Vergleich zu Ihrem Tiefpassfilter
Ihr aktueller Ansatz mit dem 28-Hz-Tiefpass und der Hüllkurven-Ansatz lösen dasselbe Problem auf zwei unterschiedliche, geniale Weisen:

* Ihr Tiefpass wirft alle Frequenzen außer der tiefsten Körperschall-Welle weg, um die Wellenformen wieder ähnlich zu machen.
* Die Hüllkurve wirft alle Frequenzen weg und vergleicht nur noch die reine Zeitstruktur des Lautstärke-Impulses.

Für das Causality Tool ist die Kombination unschlagbar: Erst beide Signale tiefpassfiltern (um Störgeräusche im Raum zu eliminieren) und dann die Kreuzkorrelation über die Hüllkurven laufen lassen.
Möchten Sie wissen, wie Sie die berechnete Hüllkurve testweise in Ihrem pyqtgraph-Fenster als dünne Linie über die rote Waveform legen können, um zu sehen, wie sauber sie den Impuls umschließt?

