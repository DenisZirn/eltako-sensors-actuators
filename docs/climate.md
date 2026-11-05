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

Bei FHK14 muss die Sender-ID als Controller für die Sollwertvorgabe korrekt eingelernt sein (PCT14: **Funktionsgruppe 3, Funktion 65**). Der Climate-Zustand allein beweist nicht, dass der Aktor den Steuerbefehl ausgeführt hat.

## Diagnoseattribute

Je nach Aktor stehen u. a. `temperaturquelle_konfiguriert`, `temperaturquelle_tatsaechlich`, `temperaturquellen_status`, `aktuelle_externe_raumtemperatur`, `protokoll_isttemperatur` und `protokoll_temperatur_begrenzt` zur Verfügung.

Bei Status **Fallback** zuerst in **Entwicklerwerkzeuge → Zustände** den tatsächlich gemeldeten Sensorwert und `unit_of_measurement` prüfen.

[Weitere Fehleranalyse →](diagnostics.md)
