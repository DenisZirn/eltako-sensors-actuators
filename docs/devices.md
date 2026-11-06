# Unterstützte Geräte und Plattformen

[← Dokumentationsübersicht](README.md)

Die folgende Übersicht basiert auf dem Gerätekatalog der Integration **v0.1.165**. Die verfügbare Home-Assistant-Plattform und Funktion hängen zusätzlich vom tatsächlich ausgewählten EEP, der Betriebsart und der Konfiguration des Aktors ab.

| Home-Assistant-Plattform | Typische Geräte/Funktionen |
| --- | --- |
| `binary_sensor` | Taster, Fenster-/Türkontakte, Bewegung, Schaltkontakte |
| `sensor` | Temperatur, Luftfeuchte, Wetter, Energie, Batterie |
| `switch` / `light` | Schaltaktoren, Dimmer, RGBW |
| `cover` | Rollläden und Jalousien |
| `climate` | FHK14, F4HK14, FKS-SV und weitere kompatible Heizungsgeräte |
| `fan` | F2L14 als zweistufiger Lüfter |

## Wichtige Geräte und Einschränkungen

- **F2L14:** `fan` mit Aus/Stufe 1/Stufe 2.
- **FMS14:** zwei separate Kanäle; A5-38-08-Steuerung.
- **FRGBW71L:** RGBW-Steuerung unterstützt.
- **FRGBW14:** Telegramme implementiert, **Hardwaresteuerung noch im Test**.
- **FHK14/F4HK14:** Steuerung über Home Assistant als Climate-Entität einschließlich externer Raumtemperaturquelle.
- **FKS-SV:** bidirektionale Kommunikation im Ventil-Empfangsfenster.
- **FAE14SSR / FHK61SSR:** laut Katalog **noch im Test**.

## Gerätekatalog aus der bisherigen README

Die folgende Liste dokumentiert die bereits integrierten Gerätetypen; die genaue Funktion hängt vom Gerät, EEP, der Betriebsart und der jeweiligen Hardware ab. Als „noch im Test“ markierte Geräte sind nicht vollständig freigegeben.

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
- FKS-SV – Smart Valve / Heizkörper-Stellantrieb
- FHK14, F4HK14 – Heizung/Klima
- FAE14SSR, FHK61SSR – Heizungs-/Schaltaktoren  (noch im Test)
- FWZ12, FWZ14, DSZ14 – Funk-/Wechselstromzähler kWh
- F3Z14D – 3-Kanal-S0-Drehstromzähler
- FWS61, FWG14MS – Wetterstation Wind + Regen + Temperatur
- FUD14, FUD71, FDG14, FD2G14, FUD61, FUD61NP-230V, FUD61NPN-230V, FD62, FD62NP-230V, FD62NPN-230V, FSUD-230V – Dimmer
- FRGBW71L – RGBW-Aktor
- FRGBW14 – RGBW-Aktor (noch im Test)
- FMS14 – 2-Kanal-Multifunktions-Stromstoßschalter
- F2L14 – 2-Stufen-Lüfteraktor (exclusive / addierend)
- FSR14-2x, FSR14-4x, FSR14M-2x, FSR14SSR
- FSR71, FSR71-2x-230V, FSR71NP-2x-230V, FSR71NP-4x-230V
- FMZ14, FSR61-230V, FSR61NP-230V, FSR61/8-24V UC, FSR61G-230V, FSR61LN-230V, FSR62, FLC61NP-230V
- FR62-230V, FR62NP-230V, FL62-230V, FL62NP-230V
- FSB14, FSB14/12-24V DC, FSB61-230V, FSB71-230V, FSB61NP-230V, FSB62, FJ62/12-36V DC, FJ62NP-230V, FJ62NPN


Ein Eintrag in dieser Liste bedeutet **keine pauschale Funktionsgarantie für alle Gerätegenerationen oder PCT14-Konfigurationen**. Nicht aufgeführte Varianten sind nicht automatisch unterstützt.

## Geräte zuordnen

Zur zuverlässigen Zuordnung der technischen `device_type`-Kennung sowie EEP und Sender-IDs bitte [EEDTOY](eedtoy.md) benutzen. Bei Problemen eine [Funk-/Bus-Diagnose](diagnostics.md) erstellen.

[← Dokumentationsübersicht](README.md)
