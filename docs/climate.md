# Heizung, Sollwerte und Raumtemperatursensoren

[← Dokumentationsübersicht](README.md)

Die Integration unterstützt je nach Geräteprofil unter anderem **FHK14**, **F4HK14**, **FKS-SV** und kompatible Heizungsaktoren. Für Home Assistant 2026.11 verwendet v0.1.165 die aktuelle Climate-API.

## Externe Raumtemperatur zuweisen

1. **Einstellungen → Geräte & Dienste → ELTAKO Sensors & Actuators → Konfigurieren** öffnen.
2. **Raumtemperatursensor zuweisen** wählen.
3. Den gewünschten Heizungsaktor auswählen.
4. Zwischen **Bestehend/eingelernt bzw. intern** und **Externer Home-Assistant-Raumtemperatursensor** wechseln.
5. Beim externen Sensor die gewünschte `sensor.`-Entität auswählen und speichern.

Die Auswahl wird je physischem Aktor gespeichert und hat Vorrang vor einer `room_temperature_entity`-Vorgabe aus der YAML. Die Änderung wird im laufenden Betrieb übernommen; bei Bedarf die Diagnoseattribute prüfen.

Der Sensor muss eine echte **Temperatur-Entität** sein, die einen numerischen Wert in °C oder °F liefert. `unknown`, `unavailable` oder nichtnumerische Werte sind nicht verwendbar.

## Temperaturgrenzen und Protokoll

| Funktion | Bereich/Verhalten |
| --- | --- |
| Externer HA-Sensorwert | **−15 bis +40 °C** gültig |
| FHK14/F4HK14, A5-10-06 | Im Telegramm können nur **0 bis +40 °C** dargestellt werden |
| Negativer Sensorwert beim FHK14 | HA behält den echten Wert; im Telegramm wird **0 °C** als Untergrenze gesendet |
| FKS-SV, A5-20-01 | Negative Istwerte werden **nicht** an das Ventil gesendet; stattdessen Rückfall auf einen gültigen internen Wert |
| Externer Sensor nicht verfügbar | Gerätetypabhängiger Fallback auf die interne/eingelernte Quelle |

**Achtung:** Der übertragene Wert von 0 °C ist bei einem realen Messwert unter null **nicht** dessen tatsächliche Temperatur. Für eine Heizungsregelung sollte ein geeigneter **Raum**temperatursensor genutzt werden, kein Außenfühler.

## FKS-SV

Das FKS-SV reagiert auf sein bidirektionales Kommunikationsfenster. Ein neuer Sollwert wird im nächsten Fenster übertragen. Laut bisherigem Hardwaretest liegt das reguläre Intervall ungefähr bei **10 Minuten**; ein kurzer Druck auf die Ventiltaste kann einen zusätzlichen Austausch auslösen.

## FHK14 und PCT14

Bei FHK14 müssen Temperaturquelle und Einlernfunktion zusammenpassen:

| Temperaturquelle | Einlernen am Aktor |
| --- | --- |
| Bestehender/eingelernter Temperatursensor | Physischer Sensor in **FG1**; HA-Sender für die Sollwertvorgabe in **FG3 / Funktion 65** |
| Externer HA-Raumtemperatursensor | HA-Sender für Ist- und Solltemperatur in **FG1 / Funktion 64** |
| Betriebsart Normal, Nacht, Absenken oder Aus | Betriebsart-Sender separat in **FG4 / Funktion 30** |

Die Auswahl eines Sensors in Home Assistant ändert den Gerätespeicher des Aktors nicht. Der Betriebsart-Sender entspricht standardmäßig der HA-Sender-ID; `operating_mode_sender_id` kann einen getrennt eingelernten Sender vorgeben. Das [PCT14-Handbuch](https://www.eltako.com/fileadmin/downloads/de/Software/PCT14_Handbuch.pdf) beschreibt die Funktionen 64 und 65 getrennt.

Ab Testversion 0.1.175 verändern als Controller-Echo erkannte Telegramme weder den Sollwert noch die Betriebsart der Series-14-Climate. Dadurch wird etwa ein eingestellter Sollwert von 25 °C nicht durch das eigene, mit 24,9 °C zurückdecodierte Sendetelegramm ersetzt. Echte Aktorrückmeldungen werden weiter ausgewertet.

Wird bei einer ausgeschalteten Series-14-Climate ein neuer Sollwert gewählt, sendet die Integration zuerst den Sollwert und anschließend den separaten RPS-Befehl für Normalbetrieb. Scheitert das zweite Senden, bleibt die Anzeige auf Aus und Home Assistant meldet den Teilerfolg ausdrücklich. Die Temperaturkodierung und der reguläre Sollwertpfad bei bereits aktivem Heizbetrieb bleiben gleich.

Ein erfolgreicher Sendeaufruf bestätigt nur die Übertragung an das Gateway. Der Climate-Zustand allein beweist nicht, dass der Aktor den Steuerbefehl ausgeführt hat.

Die Echo-Korrektur erklärt keine größeren Abweichungen echter Rückmeldungen. Im Hardwarevideo vom 26.11.2026 springt der native FHK14 nach 19,5 / 22,5 / 25 °C Sollvorgabe auf 16,5 / 19,5 / 22 °C zurück. Diese wiederholte Differenz von 3 K ist mit der Rundung des eigenen Sendeechos nicht erklärbar. Dafür sind die tatsächlichen Empfangstelegramme und die Prioritätsauswertung am Aktor noch abzugleichen. Testversion 0.1.175 ist deshalb kein hardwarebestätigter Fix dieses 3-K-Verhaltens oder des ausbleibenden Schaltens.

## Diagnoseattribute

Je nach Aktor stehen u. a. `temperaturquelle_konfiguriert`, `temperaturquelle_tatsaechlich`, `temperaturquellen_status`, `aktuelle_externe_raumtemperatur`, `protokoll_isttemperatur` und `protokoll_temperatur_begrenzt` zur Verfügung.

`letzte_controllerantwort` ist ein historischer Attributname: Der Wert wird nach dem erfolgreichen Senden gesetzt und ist **kein Zeitpunkt einer Aktorbestätigung**. Auch `betriebsart_aktor_bestaetigt: false` bei Series 14 ist keine empfangene Ablehnung; die Integration führt hier bisher keine bestätigte Betriebsart nach.

Bei Status **Fallback** zuerst in **Entwicklerwerkzeuge → Zustände** den tatsächlich gemeldeten Sensorwert und `unit_of_measurement` prüfen.

[Weitere Fehleranalyse →](diagnostics.md)
