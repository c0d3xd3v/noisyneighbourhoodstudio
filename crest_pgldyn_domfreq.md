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

