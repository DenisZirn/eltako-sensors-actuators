# Installation und Updates

[← Dokumentationsübersicht](README.md)

## Voraussetzungen

- Home Assistant **2026.11.0 oder neuer** für v0.1.165.
- Ein kompatibles Gateway, z. B. **FAM-USB** oder **FGW14-USB**; siehe [Gateways](gateways.md).
- Schreibzugriff auf die Home-Assistant-Konfiguration für die manuelle Installation.
- Für die komfortable Geräteeinrichtung empfiehlt sich [EEDTOY](eedtoy.md).

**Vor Installation und Updates ein vollständiges Home-Assistant-Backup erstellen.**

## Installation über den Home Assistant Marketplace

1. In Home Assistant den **Marketplace** öffnen.
2. Nach **ELTAKO Sensors & Actuators** suchen und die Integration installieren.
3. Solange das Repository noch **nicht im öffentlichen Katalog** freigegeben ist, die Funktion **Add from link / Aus Link hinzufügen** mit der URL
   `https://github.com/DenisZirn/eltako-sensors-actuators` verwenden.
4. Nach der Installation **Home Assistant neu starten**.
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen → ELTAKO Sensors & Actuators** öffnen, USB-Port auswählen und die Einrichtung abschließen.

Die [öffentliche Katalogaufnahme](https://github.com/hacs/default/pull/13465) ist unabhängig von der Verfügbarkeit des GitHub-Releases.

## Manuelle Installation

1. Die Datei [`ELTAKO_Sensors_Actuators.zip` aus dem Release](https://github.com/DenisZirn/eltako-sensors-actuators/releases/tag/v0.1.165) herunterladen.
2. Archiv entpacken und die enthaltenen Dateien nach
   `/config/custom_components/eltako_sensors_actuators/` kopieren.
3. Kontrollieren, dass die Dateien direkt an dieser Stelle liegen:

   `
   /config/custom_components/eltako_sensors_actuators/
     __init__.py
     manifest.json
     gateway.py
     bus/
     ...
   `

   **Keinen zusätzlichen verschachtelten Ordner** beim Entpacken erzeugen.
4. Home Assistant vollständig neu starten.
5. Die Integration unter **Geräte & Dienste** hinzufügen.

## Einrichtung nach der Installation

Die Integration zuerst mit dem passenden Gateway verbinden. Danach in den Integrationsoptionen **EEDTOY YAML importieren oder ersetzen** wählen; die YAML wird **nicht** als eigener Block in `configuration.yaml` eingetragen. Mehr dazu unter [EEDTOY/YAML](eedtoy.md).

Eine Config-Entry-Instanz entspricht einem physischen Gateway. Bei mehreren Gateways entsprechende Einträge anlegen und die zugehörigen YAML-Blöcke auswählen.

## Aktualisierungen

- Bei einer **neuen Versionsnummer** kann der Marketplace ein Update anbieten.
- Nach Code-Updates Home Assistant neu starten.
- **Besonderheit v0.1.165:** Die installierbare ZIP wurde nachträglich mit einem getesteten **F2L14-FAM-USB-Fix** ersetzt, **ohne neue Versionsnummer**. Bei schon installiertem v0.1.165 erscheint deswegen in der Regel **kein automatischer Update-Hinweis**. In diesem Fall die aktuelle ZIP erneut manuell installieren.
- YAML-Import und Änderung des seriellen Anschlusses lösen nach erfolgreichem Speichern einen **gezielten Reload** des betroffenen Eintrags aus. Eine Änderung der Raumtemperaturquelle wird dagegen direkt übernommen. Bei Bedarf gibt es den Dienst `eltako_sensors_actuators.reload_config`.

[USB-Gateways einrichten →](gateways.md)
