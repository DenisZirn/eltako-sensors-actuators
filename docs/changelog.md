# Versionshistorie

[← Dokumentationsübersicht](README.md)

## Wartungsstand von v0.1.165

Das ursprüngliche Release wurde **ohne Versionssprung** um einen hardwaregetesteten **F2L14-FAM-USB-Sender-ID-Fix** ergänzt. Das vorhandene Release-ZIP wurde ersetzt; `manifest.json` bleibt auf `0.1.165`. Bereits installierte Systeme bekommen dafür normalerweise keinen neuen Marketplace-Updatehinweis. Außerdem bleibt der ursprüngliche Git-Tag auf seinem Erstveröffentlichungs-Commit.

Die detaillierten technischen Release-Notes sind unter [GitHub v0.1.165](https://github.com/DenisZirn/eltako-sensors-actuators/releases/tag/v0.1.165) hinterlegt.

## Änderungen in v0.1.165

- Neue native Home-Assistant-Climate-Eigenschaften für Temperaturwerte.
- Externe Temperaturquelle: −15 bis +40 °C mit protokollgerechter Begrenzung bei FHK14/FKS-SV.
- Serielle USB-Kommunikation über `serialx`; FAM-USB und FGW14-USB im Praxistest geprüft.

## Änderungen in v0.1.164

- Externe Raumtemperaturquelle für FKS-SV, FHK14, F4HK14 und kompatible FAE14-Aktoren.
- Persistente Sensorzuordnung, verständliche Auswahldialoge und Temperatursensorfilter.
- Verbesserte FAM-USB-Portzuordnung (`if01`) und robuste Diagnose.

## Versionshistorie

### Änderungen in v0.1.163

### Geräteerkennung über `device_type`

- Der YAML-Import übernimmt die technische Gerätekennung getrennt vom frei änderbaren Namen.
- Geräte mit demselben EEP lassen sich zuverlässiger unterscheiden; insbesondere werden nicht alle `F6-02-01`-Geräte automatisch als Vierfachtaster behandelt.
- Die bestehenden Betriebsarten- und Kanalparameter bleiben erhalten. Die statischen Zuordnungen für F4USM61B wurden für die Betriebsarten 1–8 überprüft.
- Ältere YAML-Konfigurationen ohne `device_type` werden weiterhin unterstützt.

### F2T55, FT55 und F4T55E

- **F2T55:** `Taste oben`, `Taste unten` und `Taster gedrückt`.
- **FT55/F4T55E:** vier einzelne Tastenpositionen und `Taster gedrückt`.
- Der jeweilige Tastenzustand bleibt während des Drückens auf `Ein` und wird erst beim echten Loslass-Telegramm zurückgesetzt; der bisherige automatische Zeitreset entfällt.
- Deutsche und englische Entity-Bezeichnungen wurden ergänzt.

### Diagnose „Letztes Telegramm“

- Die Diagnose-Entity `Letztes Telegramm` ist wieder bei Tastern vorhanden und wird für andere importierte Geräte ergänzt, sofern noch kein passender Zeitstempel-Sensor besteht.
- **FLGTF:** ein gemeinsamer Diagnose-Zeitstempel für die zusammengehörigen Telegrammprofile.
- **FTS14EM:** ein gemeinsamer Diagnose-Zeitstempel für die Eingänge des physischen Moduls.
- Veraltete Taster-Hilfsentitäten `Gedrückte Taste`, `Tastenposition` und `Signalcode` werden entfernt; `Letztes Telegramm` bleibt als Diagnose-Entity erhalten.


## Änderungen in v0.1.162

### F2L14

- F2L14 als Home-Assistant-`fan`-Entity integriert.
- Zwei Lüfterstufen werden als 50 % / 100 % abgebildet, 0 % entspricht Aus.
- Unterstützung für beide PCT14-Schaltfolgen:
  - `exclusive`: Stufe 1 schaltet nur Kontakt 1, Stufe 2 nur Kontakt 2.
  - `additive`: Stufe 1 schaltet Kontakt 1, Stufe 2 beide Kontakte.
- Native F6-02-01-Tastertelegramme werden verwendet:
  - `0x30` = Stufe 1
  - `0x70` = Stufe 2
  - untere Taste = Aus
- Die F2L14-Betriebsart wird über `f2l14_mode` aus der EEDTOY-YAML übernommen.
- `stage_1_id` und `stage_2_id` werden für die Rückmeldung der beiden Relais verwendet.
- FAM-USB- und FGW14-USB-/FAM14-Konfigurationen werden unterstützt.
- Für zuverlässige F2L14-Tastersequenzen wurde ein definiertes Telegramm-Timing ergänzt.
- Die F2L14-Ansteuerung wurde praktisch mit PCT14 und realem Aktor getestet.

### Deutsche / englische Oberfläche

- Sichtbare Entity-Namen werden schrittweise über Home Assistants Übersetzungssystem bereitgestellt.
- Deutsche und englische Bezeichnungen für zahlreiche Sensoren, Binärsensoren und Diagnose-Entities ergänzt.
- FNSN55EB/FNS65EB: `Näherung` / `Proximity` inklusive übersetzter Zustände.
- F6-02-01-Taster: Tastenpositionen und Diagnosewerte deutsch/englisch.
- Redundante generische F6-02-01-`Unknown`-Entity entfernt.
- EnOcean-ID, Letztes Telegramm, Batterie-/Fenster-/Bewegungs- und weitere Entity-Namen lokalisiert.
- F4USM61B: Eingänge E1 bis E4 werden korrekt als `Input E1` bis `Input E4` bzw. `Eingang E1` bis `Eingang E4` angezeigt.
- Spannungs-Sensoren verwenden `Voltage` / `Spannung` statt gemischter Sprachbezeichnungen.
- FBH55/FBH55ESB erzeugt keine Temperatur-Entity mehr, da diese Gerätevariante keine Temperatur überträgt.
- FBHT55/FBHT55ESB behält die Temperatur-Entity.

### Kompatibilität

- Bestehende Unique-IDs und Entity-IDs bleiben erhalten.
- Die Änderungen betreffen die Darstellung und die neue F2L14-Funktion; bestehende EnOcean-Gerätepfade bleiben unverändert.

## Änderungen in v0.1.161

### FKS-SV

- Die Climate-Entity des FKS-SV ist zuverlässig verfügbar.
- Die A5-20-01-Kommunikation Controller → FKS-SV wurde korrigiert.
- DB2 wird nun EEP-konform als aktuelle Raumtemperatur übertragen.
- Ohne externen Home-Assistant-Raumtemperatursensor wird die zuletzt vom FKS-SV gemeldete Isttemperatur verwendet.
- Neue Solltemperaturen werden in Home Assistant gespeichert und beim nächsten Empfangsfenster des FKS-SV übertragen.
- Das normale Kommunikationsintervall des FKS-SV von etwa 10 Minuten wird unterstützt.
- Durch kurzes Drücken der Taste am FKS-SV kann eine sofortige Kommunikation ausgelöst werden.
- Die Ventilregelung mit Soll- und Isttemperatur wurde praktisch getestet.

### FHK14 / F4HK14

- Die Erkennung echter Aktor-Antworttelegramme wurde korrigiert.
- Die Isttemperatur wird nun auch dann korrekt übernommen, wenn das Antworttelegramm über die konfigurierte Sender-ID empfangen wird.
- Der Fehler, bei dem die Climate-Entity auf 40,0 °C stehen bleiben konnte, wurde behoben.
- Der Protokollwert 40,0 °C wird nur noch dann angezeigt, wenn er tatsächlich vom FHK14 als gültige Rückmeldung vorliegt.

### Home-Assistant-Kompatibilität

- Funk-/Bus-Diagnose verwendet nun die lokale Home-Assistant-Zeitzone statt UTC.
- `ppm` und `ppb` verwenden die aktuellen `UnitOfRatio`-Konstanten von Home Assistant.
- FLGTF TVOC in `ppb` verwendet nun die passende Device Class `VOLATILE_ORGANIC_COMPOUNDS_PARTS`.
- `via_device` wurde auf `via_device_id` umgestellt und korrekt auf den zugehörigen Config Entry eingeschränkt.

### Gateway / ESP2

- Einzelne fehlerhafte ESP2-Telegramme mit Checksum-Fehler führen nicht mehr zu einem vollständigen Neustart der seriellen Verbindung.
- Ungültige ESP2-Frames werden verworfen, während die FAM-USB-Verbindung geöffnet bleibt.
- Echte USB-/Serial-Verbindungsfehler lösen weiterhin einen Reconnect aus.

### Weitere Korrekturen

- Die Wiederherstellung von Climate-Zuständen nach einem Home-Assistant-Neustart wurde stabilisiert.
- Gerätezuordnung und Diagnose wurden weiter bereinigt.
- Die Hotfix-Korrekturen aus den vorherigen Versionen bleiben vollständig enthalten.

## Änderungen in v0.1.157

- FHK14/F4HK14-Steuerung weiter stabilisiert. Die aktuelle Raumtemperatur wird nur noch aus einer echten Aktor-Rückmeldung übernommen; synthetische Controllerwerte werden nicht mehr als Isttemperatur angezeigt.
- FAE14LPR verwendet dieselbe abgesicherte Isttemperatur-Logik. Bis zur ersten gültigen Aktor-Rückmeldung wird 0,0 °C angezeigt.
- Zustände von Sensoren, Binärsensoren, Schaltern, Licht, Cover und Klima werden nach einem Home-Assistant-Neustart wiederhergestellt, ohne dabei Schalttelegramme auszulösen.
- Technische Unique-IDs der YAML-Entitäten wurden stabilisiert. Bestehende Registry-Einträge werden migriert, ohne vorhandene `entity_id` umzubenennen.
- Temperaturmesswerte werden mit einer leichten EMA-Glättung (`alpha=0.25`) beruhigt. Der unveränderte Rohwert bleibt als Attribut `raw_temperature` erhalten. Solltemperaturen werden nicht geglättet.
- F4T55E bereinigt: Die vier echten Tasten bleiben erhalten; ältere generische Hilfsentitäten wie `Gedrückte Taste`, `Tastenposition` und `Signalcode` werden entfernt. Der Diagnose-Zeitstempel `Letztes Telegramm`, der in dieser älteren Version ebenfalls entfiel, wurde mit v0.1.163 wiederhergestellt.
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

Die Eingänge E1 bis E10 bleiben eigenständige Binärsensoren. Ab v0.1.163 wird der Zeitstempel `Letztes Telegramm` für das physische FTS14EM gemeinsam im Bereich **Diagnose** angezeigt. Weitergehende Telegrammdetails stehen in der Funk-/Bus-Diagnose zur Verfügung.

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

Die aktuelle Raumtemperatur wird ausschließlich aus einer echten Aktor-Rückmeldung übernommen. Antworttelegramme werden sowohl über die Geräte-ID als auch über die konfigurierte Sender-ID korrekt zugeordnet.

Der zuvor mögliche Fehler, bei dem die Climate-Entity auf 40,0 °C stehen blieb, obwohl eine gültige Isttemperatur empfangen wurde, ist seit v0.1.161 behoben.

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

Ausführliche Telegrammdetails werden in der Funk-/Bus-Diagnose dargestellt. Zusätzlich besitzt jedes unterstützte importierte Gerät den Diagnose-Zeitstempel **Letztes Telegramm**, der beim Empfang eines passenden Telegramms aktualisiert wird. Bei zusammengehörigen FLGTF-Profilen sowie beim FTS14EM wird er pro physischem Gerät zusammengefasst.

Seit v0.1.161 werden Zeitstempel in der lokalen Home-Assistant-Zeitzone dargestellt.

Einzelne ungültige ESP2-Telegramme mit Checksum-Fehler werden verworfen, ohne die serielle FAM-USB-Verbindung vollständig neu zu öffnen.

## Übersetzungen

Die Integration enthält deutsche und englische Übersetzungen:

- `translations/de.json`
- `translations/en.json`

[← Dokumentationsübersicht](README.md)
