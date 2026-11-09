# Unterstützte Geräte und Plattformen

[← Dokumentationsübersicht](README.md)

Diese Übersicht beschreibt die unterstützten Gerätetypen der Integration **v0.1.166**. Die verfügbare Home-Assistant-Plattform und die Funktionen hängen vom ausgewählten EEP, der Betriebsart und der Konfiguration des Geräts ab.

| Home-Assistant-Plattform | Typische Geräte und Funktionen |
| --- | --- |
| `binary_sensor` | Taster, Fenster-/Türkontakte, Bewegung, Schaltkontakte, Rauchalarm |
| `sensor` | Temperatur, Luftfeuchte, Helligkeit, Luftqualität, Wetter, Energie, Batterie |
| `switch` / `light` | Schaltaktoren, Dimmer, RGBW |
| `cover` | Rollläden und Jalousien |
| `climate` | FHK14, F4HK14, FKS-SV, FKS-B und weitere kompatible Heizungsgeräte |
| `fan` | F2L14 als zweistufiger Lüfter |

## Wichtige Geräte und Einschränkungen

- **FAH / FHD60SB:** Helligkeitsmessung über `A5-06-01`. Für die korrekte Gerätezuordnung muss `device_type: "FAH"` beziehungsweise `device_type: "FHD60SB"` angegeben sein.
- **FRW / FRW-ws:** Rauchalarm und Batteriewarnung über `F6-02-01`. Trotz des gemeinsamen EEPs wird das Gerät als Rauchmelder und nicht als Taster ausgewertet.
- **FRWB:** eigener Rauchmeldertyp mit `A5-30-03`; nicht mit FRW / FRW-ws gleichsetzen.
- **FFT60SB / FTFSB:** Profile für `A5-04-02` und `A5-04-03`. Das zum Gerät passende EEP auswählen.
- **FLGTF:** Temperatur und Luftfeuchte einzeln oder zusammen mit TVOC über das vollständige Geräteprofil.
- **F2L14:** `fan` mit Aus, Stufe 1 und Stufe 2; Betriebsarten exklusiv und addierend.
- **FMS14:** zwei separate Kanäle; Steuerung über `A5-38-08`.
- **FRGBW71L:** RGBW-Steuerung unterstützt.
- **FRGBW14:** Telegramme implementiert, **Hardwaresteuerung noch im Test**.
- **FHK14 / F4HK14:** Steuerung als Climate-Entität einschließlich externer Raumtemperaturquelle.
- **FKS-SV / FKS-B:** bidirektionale Kommunikation; die Übertragung erfolgt im Empfangsfenster des batteriebetriebenen Stellantriebs.
- **FAE14SSR / FHK61SSR:** **noch im Test**.
- **FWG14MS:** Wetterdaten-Gateway mit eigener Empfangs-ID entsprechend dem eingestellten ID-Bereich. Die PCT14-Busadresse darf nicht als Empfangs-ID der Wettertelegramme verwendet werden.

## Unterstützte Gerätetypen

Die genaue Funktion hängt vom Gerät, EEP, der Betriebsart und der jeweiligen Hardware ab. Als **noch im Test** markierte Geräte sind nicht vollständig freigegeben.

### Taster und Eingabemodule

- F2T55 – Taster 2-Kanal EU
- FT55, F4T55E – Taster 4-Kanal EU
- F4USM61B – Universalsender, Betriebsarten 1 bis 8
- FTS14EM – 10-Kanal-Eingabemodul
- FSM60B – Betriebsarten 1 bis 4

### Kontakte und Bewegungsmelder

- FNSN55EB, FNS65EB – Näherungsschalter
- FTK, FTKB, FFKB – Fenster-/Türkontakte
- FTKE, FFTE, FFG7B – Fensterkontakt / Fenstergriff mit `F6-10-00`
- FFG7B – Fensterkontakt / Fenstergriff mit `A5-14-09`
- FBH55ESB, FB55EB – Bewegungsmelder
- FBH55ESB / FBHT55ESB – Bewegung und Helligkeit

### Rauch- und Hitzemelder

- FRW / FRW-ws – Rauchalarm und Batteriewarnung mit `F6-02-01`
- FRWB – Rauchmelder mit `A5-30-03`
- FHMB – Rauch-/Hitzemelder

### Helligkeit, Temperatur und Luftqualität

- FAH – Helligkeitssensor mit `A5-06-01`
- FHD60SB – Funk-Helligkeitssensor mit `A5-06-01`
- FFT60SB – Temperatur und Luftfeuchte mit `A5-04-02` oder `A5-04-03`
- FTFSB – Temperatur und Luftfeuchte mit `A5-04-02` oder `A5-04-03`
- FLGTF – Temperatur und Luftfeuchte mit `A5-04-02`
- FLGTF – TVOC mit automatischer Temperatur-/Feuchte-Ergänzung über `A5-09-0C` und `A5-04-02`
- FCO2TF65 – CO₂, Temperatur und Luftfeuchte

### Raumregler und Heizungsaktoren

- FUTH65D – Raumregler für Temperatur, Luftfeuchte und Sollwert
- FUTH65D – Raumregler für Temperatur, Luftfeuchte und Belegung
- FUTH55ED – FHK-Datenübermittlung mit `A5-10-06`
- FUTH55ED – FKS Kieback & Peter mit `A5-20-01`
- FUTH55ED – FKS-H Hora mit `A5-20-04`
- FUTH55ED – 2-Punkt-Regler TF61R / FR62 mit `A5-38-08`
- FUTH55ED – Hygrostat mit `A5-10-12`
- FTR65DSB, FTR55DSB, FTR55EHB, FTR55ESB, FTR65HB, FTRF65HB, FTR55HB, FTR65SB, FTRF65SB, FTR55SB – Betriebsarten TF61 und FHK
- FKS-SV – Smart Valve / Heizkörper-Stellantrieb mit `A5-20-01`
- FKS-B – bidirektionaler Heizkörper-Stellantrieb mit `A5-20-04`
- FHK14, F4HK14 – Heizung/Klima
- FAE14LPR – Aktor Heizen/Kühlen für zwei Zonen
- FAE14SSR, FHK61SSR – Heizungs-/Schaltaktoren, **noch im Test**

### Energie und Wetter

- FWZ12, FWZ14, DSZ14 – Funk-/Wechselstromzähler für Energie in kWh
- F3Z14D – 3-Kanal-S0-Drehstromzähler
- FWS61 – Wetterstation für Wind, Regen und Temperatur
- FWG14MS – Wetterdaten-Gateway mit auswählbarem Empfangs-ID-Bereich

### Dimmer und RGBW-Aktoren

- FUD14, FUD71, FDG14, FD2G14
- FUD61, FUD61NP-230V, FUD61NPN-230V
- FD62, FD62NP-230V, FD62NPN-230V
- FSUD-230V
- FRGBW71L – RGBW-Aktor
- FRGBW14 – RGBW-Aktor, **noch im Test**

### Schalt- und Lüfteraktoren

- FMS14 – 2-Kanal-Multifunktions-Stromstoßschalter
- F2L14 – 2-Stufen-Lüfteraktor, exklusiv oder addierend
- FSR14-2x, FSR14-4x, FSR14M-2x, FSR14SSR
- FSR71, FSR71-2x-230V, FSR71NP-2x-230V, FSR71NP-4x-230V
- FMZ14
- FSR61-230V, FSR61NP-230V, FSR61/8-24V UC, FSR61G-230V, FSR61LN-230V
- FSR62, FLC61NP-230V
- FR62-230V, FR62NP-230V, FL62-230V, FL62NP-230V

### Rollladen- und Jalousieaktoren

- FSB14, FSB14/12-24V DC
- FSB61-230V, FSB71-230V, FSB61NP-230V, FSB62
- FJ62/12-36V DC, FJ62NP-230V, FJ62NPN

Ein Eintrag in dieser Liste bedeutet **keine pauschale Funktionsgarantie für alle Gerätegenerationen oder PCT14-Konfigurationen**. Nicht aufgeführte Varianten sind nicht automatisch unterstützt.

## Geräte und Räume zuordnen

Zur zuverlässigen Zuordnung von `device_type`, EEP und Sender-IDs bitte [EEDTOY](eedtoy.md) benutzen. Der technische Gerätetyp ist unabhängig vom frei vergebenen Gerätenamen. Geräte mit demselben EEP können unterschiedliche Gerätetypen und Funktionen haben.

Ab **EEDTOY v1.1.02** wird das Feld **Raum** als `area` in die YAML übernommen. Zum Übertragen der Raumzuordnung die YAML exportieren und in der Integration über **EEDTOY YAML importieren** einlesen.

Bei Problemen eine [Funk-/Bus-Diagnose](diagnostics.md) erstellen.

[← Dokumentationsübersicht](README.md)
