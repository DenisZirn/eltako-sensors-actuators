# ELTAKO Sensors & Actuators v0.1.168

**Veröffentlicht:** 18. November 2026  
**Home Assistant:** 2026.11.0 oder neuer

## Verbesserungen

- **Raumzuordnung bleibt erhalten:** Eine über EEDTOY/YAML vorgeschlagene Raumzuordnung wird beim Anlegen berücksichtigt, überschreibt aber nach einem Home-Assistant-Neustart keine manuell ausgewählte oder entfernte Raumzuordnung mehr.
- **Externe Raumtemperatur:** Änderungen an der Sensorzuordnung werden sofort übernommen, ohne dass die Solltemperatur verändert werden muss. Dies betrifft die Climate-Ansteuerung von FHK14, F4HK14 und kompatiblen FAE14-Aktoren.
- **Laufende Aktualisierung:** Neue Messwerte des zugeordneten externen Temperatursensors werden automatisch in der Climate-Entität nachgeführt. Die Zuordnung bleibt nach einem Neustart erhalten.
- **FKS-SV:** Einheitliche Isttemperatur in der Climate-Entität; eine veraltete doppelte Temperatur-Entity der eigenen Integration wird bereinigt. Die tatsächliche Ventilkommunikation bleibt an das nächste Empfangsfenster gebunden.
- **Raumtemperatursensor zuweisen:** Heizungsaktoren können im Konfigurationsdialog direkt angeklickt werden. Bei vielen Aktoren gibt es eine Seitennavigation.
- **YAML-Sensoren:** Stabilere Initialisierung sowie korrekte Verarbeitung von Messwerten `0` und `false`.

## Kompatibilität und Qualität

- Unterstützung für **FAM-USB** und **FGW14-USB** bleibt erhalten.
- HACS- und Home-Assistant-Validierung aktualisiert; GitHub-Actions-Laufzeit auf Node.js 24 umgestellt.
- Bestehende Geräte-IDs und Sender-IDs bleiben unverändert.
- Automatisierte Regressionstests sowie HACS/hassfest erfolgreich; FHK14, FAE14 und FKS-SV wurden zusätzlich praktisch geprüft.

## Hinweis

Eine zuvor verwendete doppelte FKS-SV-Temperatur-Entity kann aus der Entity-Registry entfernt werden. Falls sie in einem Dashboard verwendet wurde, ist dort die Climate-Entity als Isttemperaturquelle auszuwählen.

**FRGBW14:** Die weitere Optimierung der RGBW-Helligkeit bei Farbwechseln ist nicht Bestandteil dieses Releases und erfolgt getrennt. Der funktionierende FRGBW71L-Pfad bleibt unverändert.

Dieses Projekt ist eine unabhängige Community-Integration und kein offizielles Produkt von ELTAKO.
