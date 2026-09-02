# Eltako Sensors & Actuators

Home-Assistant-Custom-Integration für untenstehende ELTAKO-Geräte.

[![Home Assistant öffnen und dieses Repository in HACS anzeigen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DenisZirn&repository=eltako-sensors-actuators&category=integration)

Home-Assistant-Custom-Integration für die unten aufgeführten ELTAKO-Geräte.

Wichtiger Hinweis: Dieses Projekt ist eine ausschließlich privat entwickelte, inoffizielle Home-Assistant-Integration. Es besteht keinerlei geschäftliche, organisatorische oder sonstige Verbindung zu ELTAKO. Die Integration wurde weder von ELTAKO entwickelt noch beauftragt, geprüft, unterstützt oder offiziell freigegeben. „ELTAKO“ sowie die genannten Produktbezeichnungen und Marken sind Eigentum ihrer jeweiligen Rechteinhaber.

## Freigegebener Gerätekatalog (v0.1.156)

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
- FHK14, F4HK14 – Heizung/Klima, (noch im Test)
- FAE14SSR, FHK61SSR – Heizungs-/Schaltaktoren
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

## Änderungen in v0.1.156

- FMS14 als eigener 2-Kanal-Multifunktions-Stromstoßschalter ergänzt.
- FMS14-Ansteuerung über A5-38-08 mit `01-00-00-09` für EIN und `01-00-00-08` für AUS.
- Die von EEDTOY vorgegebene `sender.id` wird für den FMS14 unverändert verwendet.
- FMS14-Statusrückmeldungen werden pro physischer Kanaladresse ausgewertet; `70` entspricht EIN und `50` AUS.
- Mehrkanalige Series-14-Aktoren werden kanalbezogen verarbeitet.
- F4USM61B-Unterstützung für Betriebsarten 1 bis 8 erweitert.
- FTS14EM als eigenes Eingabemodul ergänzt.
- Beim FTS14EM werden nur die eigentlichen Eingänge als Home-Assistant-Entitäten angelegt; alte Hilfsentitäten wie „Gedrückte Taste“, „Tastenposition“, „Signalcode“ und „Letztes Telegramm“ wurden entfernt.
- FAE14LPR-Auswertung ergänzt.
- FSM60B-Auswertung für die unterschiedlichen Betriebsarten erweitert und hardwareseitig getestet.
- Series-14-Rückmeldungen weiter vereinheitlicht und stabilisiert.
- Funk-/Bus-Diagnose weiter überarbeitet.
- Deutsche und englische Übersetzungen ergänzt.
- FHK14-/F4HK14-Decoder und Sendewege sind enthalten; die aktive Steuerung wird weiterhin hardwareseitig validiert.
- FRGBW14-Unterstützung ist enthalten, die praktische Ansteuerung wird weiterhin validiert.

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

Die aktive Steuerung wird weiterhin hardwareseitig geprüft und gilt in v0.1.156 noch nicht als abschließend validiert.

## FDG14

- A5-38-08 / FUNC=38 / Command 2.
- Direkte Helligkeitsvorgabe 0–100 %.
- Dimmgeschwindigkeit 0–255; Standard `0` nutzt die am FDG14 eingestellte Geschwindigkeit.
- Lerntelegramm `E0-40-0D-80`.
- Statusrückmeldungen liefern Ein/Aus, Dimmwert und Dimmgeschwindigkeit an Home Assistant.

## FRGBW14 / FRGBW71L

Der FRGBW71L unterstützt Ein/Aus, Helligkeit sowie Rot, Grün, Blau und Weiß.

Die Telegrammverarbeitung für den FRGBW14 ist ebenfalls Bestandteil der Integration. Die praktische Ansteuerung des FRGBW14 wird weiterhin validiert.

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

Ab v0.1.156 verwendet das Frontend die Datei:

`frontend/diagnostics-panel.js`

Technische Telegrammdetails werden bevorzugt in dieser Diagnose dargestellt und nicht als zusätzliche Geräteentitäten angelegt.

## Übersetzungen

v0.1.156 enthält deutsche und englische Übersetzungen:

- `translations/de.json`
- `translations/en.json`
