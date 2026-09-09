# Eltako Sensors & Actuators

Home-Assistant-Custom-Integration für untenstehende ELTAKO-Geräte.

[![Home Assistant öffnen und dieses Repository in HACS anzeigen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DenisZirn&repository=eltako-sensors-actuators&category=integration)

Home-Assistant-Custom-Integration für die unten aufgeführten ELTAKO-Geräte.

Wichtiger Hinweis: Dieses Projekt ist eine ausschließlich privat entwickelte, inoffizielle Home-Assistant-Integration. Es besteht keinerlei geschäftliche, organisatorische oder sonstige Verbindung zu ELTAKO. Die Integration wurde weder von ELTAKO entwickelt noch beauftragt, geprüft, unterstützt oder offiziell freigegeben. „ELTAKO“ sowie die genannten Produktbezeichnungen und Marken sind Eigentum ihrer jeweiligen Rechteinhaber.

## Freigegebener Gerätekatalog (v0.1.159)

- F2T55 – Taster 2-Kanal EU
- FT55, F4T55E – Taster 4-Kanal EU
- F4USM61B – Universalsender, Betriebsarten 1 bis 8
- FTS14EM – 10-Kanal-Eingabemodul
- FAE14LPR – Aktor Heizen/Kühlen für 2 Zonen
- FNSN55EB, FNS65EB – Näherungsschalter
- FTK, FTKB, FFKB – Fenster-/Türkontakt
- FTKE, FFTE, FFG7B – Fensterkontakt / Fenstergriff (F6-10-00)
- FFG7B – Fensterkontakt / Fenstergriff (A5-14-09)
- FBH55ESB, FB55EB – Bewegungsmelder
- FBH55ESB / FBHT55ESB – Bewegung + Helligkeit automatisch
- FRWB – Rauchmelder
- FHMB – Rauch-/Hitzemelder
- FSM60B – Betriebsart 1, 2, 3 und 4
- FFT60SB – Temperatur + Feuchte 0…40 °C
- FLGTF – Temperatur + Feuchte −20…60 °C / 0…100 %
- FLGTF – TVOC + Temperatur/Feuchte automatisch
- FCO2TF65 – CO2 + Temperatur + Feuchte
- FUTH65D – Raumregler Temperatur + Feuchte + Sollwert
- FUTH65D – Raumregler Temperatur + Feuchte + Belegung
- FUTH55ED – FHK-Datenübermittlung (A5-10-06)
- FUTH55ED – FKS Kieback & Peter (A5-20-01)
- FUTH55ED – FKS-H Hora (A5-20-04)
- FUTH55ED – 2-Punkt-Regler TF61R / FR62 (A5-38-08)
- FUTH55ED – Hygrostat (A5-10-12)
- FTR65DSB, FTR55DSB, FTR55EHB, FTR55ESB, FTR65HB, FTRF65HB, FTR55HB, FTR65SB, FTRF65SB, FTR55SB – TF61 und FHK
- FKS-SV – Smart Valve / Heizkörper-Stellantrieb (noch im Test)
- FKS-B – Heizkörper-Stellantrieb, A5-20-04 / Modus 02; direktes Einlernen der HA-Sender-ID über reinen FAM-USB mit ESP2 noch nicht unterstützt
- FHK14, F4HK14 – Heizung/Klima  (noch im Test)
- FAE14SSR, FHK61SSR – Heizungs-/Schaltaktoren  (noch im Test)
- FWZ12, FWZ14, DSZ14 – Funk-/Wechselstromzähler kWh
- F3Z14D – 3-Kanal-S0-Drehstromzähler
- FWS61, FWG14MS – Wetterstation Wind + Regen + Temperatur
- FUD14, FUD71, FDG14, FD2G14, FUD61, FUD61NP-230V, FUD61NPN-230V, FD62, FD62NP-230V, FD62NPN-230V, FSUD-230V – Dimmer
- FRGBW71L – RGBW-Aktor
- FRGBW14 – RGBW-Aktor (noch im Test)
- FMS14 – 2-Kanal-Multifunktions-Stromstoßschalter
- FSR14-2x, FSR14-4x, FSR14M-2x, FSR14SSR
- FSR71, FSR71-2x-230V, FSR71NP-2x-230V, FSR71NP-4x-230V
- FMZ14, FSR61-230V, FSR61NP-230V, FSR61/8-24V UC, FSR61G-230V, FSR61LN-230V, FSR62, FLC61NP-230V
- FR62-230V, FR62NP-230V, FL62-230V, FL62NP-230V
- FSB14, FSB14/12-24V DC, FSB61-230V, FSB71-230V, FSB61NP-230V, FSB62, FJ62/12-36V DC, FJ62NP-230V, FJ62NPN

Nicht aufgeführte Produktbezeichnungen gehören nicht zum freigegebenen Katalog. Gemeinsame EEP-Decoder bleiben intern erhalten, soweit sie für die oben genannten Geräte erforderlich sind.

## Installation über HACS

Über den folgenden Button kann das Repository direkt in HACS geöffnet und als benutzerdefiniertes Integrations-Repository hinzugefügt werden:

[![Home Assistant öffnen und dieses Repository in HACS anzeigen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DenisZirn&repository=eltako-sensors-actuators&category=integration)

Danach in HACS **Eltako Sensors & Actuators** herunterladen. Bei einem HACS-Update kann Home Assistant einen Neustart verlangen, damit neuer Integrationscode geladen wird. Änderungen an Gateway oder EEDTOY-YAML werden dagegen durch einen Integrations-Reload übernommen.

## Manuelle Installation

Den Ordner `custom_components/eltako_sensors_actuators` nach Home Assistant kopieren und Home Assistant neu laden beziehungsweise neu starten.

## Änderungen in v0.1.159

- Die FHK14-/F4HK14-Behandlung für Anlagen ohne eingelernten Raumtemperatursensor wurde angepasst.
- Der vom FHK14 verwendete Protokollwert 40,0 °C bleibt sichtbar, solange keine abweichende echte Aktor-Rückmeldung zur Raumtemperatur vorliegt.
- Sollwerttelegramme verwenden weiterhin den etablierten Protokollplatzhalter `DB1=0x00` (40 °C); für die tatsächliche Raumtemperatur bleibt der im Aktor eingelernte Raumtemperatursensor maßgeblich.
- Die Hotfix-Korrekturen aus v0.1.158 für FWZ14-65A, DSZ14DRS sowie F2T55, FT55 und F4T55E bleiben vollständig enthalten.

### Bekannter Prüfpunkt

Die FHK-Unterstützung befindet sich hinsichtlich der korrekten Ermittlung und Darstellung der Ist-Temperatur weiterhin in Prüfung.

## Änderungen in v0.1.157

- FHK14/F4HK14-Steuerung weiter stabilisiert. Die aktuelle Raumtemperatur wird nur noch aus einer echten Aktor-Rückmeldung übernommen; synthetische Controllerwerte werden nicht mehr als Isttemperatur angezeigt.
- FAE14LPR verwendet dieselbe abgesicherte Isttemperatur-Logik. Bis zur ersten gültigen Aktor-Rückmeldung wird 0,0 °C angezeigt.
- Zustände von Sensoren, Binärsensoren, Schaltern, Licht, Cover und Klima werden nach einem Home-Assistant-Neustart wiederhergestellt, ohne dabei Schalttelegramme auszulösen.
- Technische Unique-IDs der YAML-Entitäten wurden stabilisiert. Bestehende Registry-Einträge werden migriert, ohne vorhandene `entity_id` umzubenennen.
- Temperaturmesswerte werden mit einer leichten EMA-Glättung (`alpha=0.25`) beruhigt. Der unveränderte Rohwert bleibt als Attribut `raw_temperature` erhalten. Solltemperaturen werden nicht geglättet.
- F4T55E bereinigt: Die vier echten Tasten bleiben erhalten; ältere generische Hilfsentitäten wie `Gedrückte Taste`, `Tastenposition`, `Signalcode` und `Letztes Telegramm` werden entfernt.
- FKS-B als Klimagerät mit bidirektionalem EEP `A5-20-04` ergänzt.
- FKS-B Modus 02: Solltemperaturen von 10–30 °C werden im Empfangsfenster des Ventils nach dem praktisch ermittelten MiniSafe2-Telegrammmuster beantwortet.
- Der FKS-B-Teach-In-Pfad wurde hinsichtlich Nutzdaten, Status und Antwortzeit an den erfolgreichen MiniSafe2-Mitschnitt angeglichen.
- Das direkte Einlernen einer Home-Assistant-Sender-ID in einen FKS-B über einen reinen FAM-USB mit ESP2 ist weiterhin nicht möglich.
- FRGBW14 bleibt offen; die praktische Ansteuerung ist noch nicht abschließend validiert.

## FMS14

Der FMS14 wird als 2-Kanal-Multifunktions-Stromstoßschalter unterstützt.

Bei einem FMS14 wird jeder Kanal als eigene Home-Assistant-Entität angelegt.

Die Ansteuerung erfolgt über A5-38-08:

- EIN: `01-00-00-09`
- AUS: `01-00-00-08`

Die von EEDTOY erzeugte `sender.id` wird unverändert übernommen.

Statusrückmeldungen werden von der jeweiligen physischen Kanaladresse ausgewertet:

- `70` = EIN
- `50` = AUS

EEDTOY erzeugt für den FMS14 die passenden A5-38-08-Senderdaten.

## F4USM61B

Der F4USM61B wird in den Betriebsarten 1 bis 8 unterstützt.

Je nach Betriebsart werden unter anderem Tasterzustände, Kontakte, Bewegung, Belegung und Batteriestatus ausgewertet.

## FTS14EM

Der FTS14EM wird als 10-Kanal-Eingabemodul unterstützt.

Die Eingänge E1 bis E10 werden als eigene Home-Assistant-Entitäten angelegt.

Technische Zusatzinformationen zu empfangenen Telegrammen werden nicht mehr als separate Geräteentitäten erzeugt. Telegrammdetails stehen ausschließlich über die Funk-/Bus-Diagnose zur Verfügung.

## FSM60B

Der FSM60B wurde hardwareseitig getestet.

Unterstützt werden die Betriebsarten 1, 2, 3 und 4.

Je nach Betriebsart werden unter anderem Kontakt-, Alarm- und Batteriezustände ausgewertet.

## FUTH55ED

Unterstützte Betriebsarten aus EEDTOY:

- FHK-Datenübermittlung A5-10-06, Lerntelegramm `40-30-0D-87`
- FKS Kieback & Peter A5-20-01, Controller-/Antworttelegramme
- FKS-H Hora A5-20-04, Controller-/Antworttelegramme
- 2-Punkt-Regler TF61R / FR62 A5-38-08, Lerntelegramm `E0-40-0D-80`
- Hygrostat A5-10-12, Lerntelegramm `40-90-0D-80`

Der FUTH55ED wird passiv ausgewertet und nicht als FKS-SV-Aktor mit einer virtuellen `sender.id` behandelt.

## FTR55/65-Familie

Unterstützte Modelle: FTR65DSB, FTR55DSB, FTR55EHB, FTR55ESB, FTR65HB, FTRF65HB, FTR55HB, FTR65SB, FTRF65SB und FTR55SB.

- Betriebsart TF61: A5-38-08, Lerntelegramm `E0-40-0D-80`, Heizanforderung AUS `01-00-00-08`, EIN `01-00-00-09`, Hysterese 1 K.
- Betriebsart FHK: A5-10-06, Lerntelegramm `40-30-0D-87`, DB2 Solltemperatur, DB1 invertierte Isttemperatur, DB0 `0F`.
- Sollwertbereich 12–28 °C; 8 °C wird als Frostschutz erkannt.

## FHK14 / F4HK14

Die Integration enthält Decoder und Sendeunterstützung für FHK14 und F4HK14.

Der FHK14 ist mit korrekt programmiertem Controllerplatz funktionsfähig. Für die Controller-Sollwertvorgabe muss die Sender-ID im Aktor in Function Group 3, Function 65 (`temperature setpoint from controller`) eingetragen sein.

Die aktuelle Raumtemperatur wird nur aus einer echten Aktor-Rückmeldung übernommen. Meldet der FHK14 den Protokollwert 40,0 °C, bleibt dieser als Hinweis auf einen möglicherweise nicht eingelernten Raumtemperatursensor sichtbar.

Die korrekte Ermittlung und Darstellung der Ist-Temperatur befindet sich weiterhin in Prüfung.

## FKS-B

Der FKS-B wird als Klimagerät mit dem bidirektionalen EEP `A5-20-04` unterstützt.

Für Modus 02 wird die Solltemperatur im Bereich 10–30 °C im Empfangsfenster des Ventils beantwortet; der FKS-B übernimmt die eigentliche Ventilregelung selbstständig.

Bekannte Einschränkung: Das direkte Einlernen einer Home-Assistant-Sender-ID in einen FKS-B über einen reinen FAM-USB mit ESP2 ist derzeit nicht möglich. Der ESP2-Sendepfad arbeitet als Broadcast, während der erfolgreiche Anlernvorgang mit MiniSafe2 eine gerichtete Kommunikation verwendet.

## FDG14

- A5-38-08 / FUNC=38 / Command 2.
- Direkte Helligkeitsvorgabe 0–100 %.
- Dimmgeschwindigkeit 0–255; Standard `0` nutzt die am FDG14 eingestellte Geschwindigkeit.
- Lerntelegramm `E0-40-0D-80`.
- Statusrückmeldungen liefern Ein/Aus, Dimmwert und Dimmgeschwindigkeit an Home Assistant.

## FRGBW14 / FRGBW71L

Der FRGBW71L unterstützt Ein/Aus, Helligkeit sowie Rot, Grün, Blau und Weiß.

Die Telegrammverarbeitung für den FRGBW14 ist ebenfalls Bestandteil der Integration. Die praktische Ansteuerung des FRGBW14 ist noch nicht abschließend validiert und bleibt offen.

## FFG7B

- A5-14-09 und F6-10-00 werden anhand des tatsächlich empfangenen ORG automatisch unterschieden, auch wenn im YAML das andere FFG7B-Profil gewählt wurde.
- A5-14-09 wertet den Fensterzustand robust in Standard- und umgekehrter Byte-Darstellung aus.
- Unterstützte Zustände: `geschlossen`, `gekippt`, `offen`.
- A5-14-09 liefert zusätzlich die Batteriespannung.
- Die Entity-Auswertung besitzt zusätzliche Decoderpfade aus `data_hex`, `value` und dem rohen ESP2-Frame.
- F6-10-00 unterstützt zusätzlich die Zweizustandswerte von FTKE/FFTE (`70/50` und `30/10`).

## Funk- / Bus-Diagnose

Die Integration enthält eine eigene Diagnose für gesendete und empfangene Funk- und Bustelegramme.

Die Diagnose kann über die Integrationsoptionen aktiviert werden.

Seit v0.1.156 verwendet das Frontend die Datei:

`frontend/diagnostics-panel.js`

Technische Telegrammdetails werden bevorzugt in dieser Diagnose dargestellt und nicht als zusätzliche Geräteentitäten angelegt.

## Übersetzungen

Die Integration enthält deutsche und englische Übersetzungen:

- `translations/de.json`
- `translations/en.json`
