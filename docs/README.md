# Dokumentation – ELTAKO Sensors & Actuators

**Home Assistant 2026.11+ · Integration v0.1.165 · Deutsch**

Diese Dokumentation behandelt die unabhängige Home-Assistant-Custom-Integration **ELTAKO Sensors & Actuators** mit lokalen EnOcean- und Serie-14-Gateways. Sie ist keine offizielle ELTAKO-Produktdokumentation.

## Einstieg

| Thema | Was du dort findest |
| --- | --- |
| [Installation und Updates](installation.md) | Voraussetzungen, Marketplace, manuelle Installation, Updateverhalten |
| [USB-Gateways und Verbindungen](gateways.md) | FAM-USB, FGW14-USB/FAM14, Ports, Baudraten und Base-ID |
| [EEDTOY und YAML-Import](eedtoy.md) | Geräte-YAML erstellen, importieren, Gateway-Blöcke auswählen |
| [Unterstützte Geräte](devices.md) | Gerätekatalog, Plattformen, getestete und noch offene Funktionen |
| [Aktoren anlernen und steuern](teach-in.md) | Sender-IDs, Teach-in, F2L14, FMS14, FHK14 und RGBW |
| [Heizung und Raumtemperatur](climate.md) | FKS-SV, FHK14/F4HK14, Temperaturquelle, Fallback und Grenzwerte |
| [Funk-/Bus-Diagnose](diagnostics.md) | Diagnoseoberfläche, Telegramme, Batterie-IDs und Fehleranalyse |
| [FAQ und bekannte Einschränkungen](faq.md) | Häufige Fehler, Updates, Netzwerk und Support |
| [Versionshistorie](changelog.md) | Bisherige Änderungen und bekannte Einschränkungen |

## Schnellstart

1. [Integration installieren](installation.md) und ein unterstütztes USB-Gateway anschließen.
2. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** den Gateway konfigurieren.
3. Mit [EEDTOY](https://github.com/DenisZirn/eedtoy) die passenden Geräte-IDs und EEPs als YAML exportieren.
4. In **Konfigurieren → EEDTOY YAML importieren oder ersetzen** den Gateway-Block übernehmen.
5. Die erzeugten Entitäten in Home Assistant und ggf. die [Funk-/Bus-Diagnose](diagnostics.md) prüfen.

## Versions- und Sicherheitsinformationen

- Aktuelles GitHub-Release: [v0.1.165](https://github.com/DenisZirn/eltako-sensors-actuators/releases/tag/v0.1.165).
- Quellcode und Meldungen: [Repository](https://github.com/DenisZirn/eltako-sensors-actuators) · [Issues](https://github.com/DenisZirn/eltako-sensors-actuators/issues).
- Lizenz: [MIT](../LICENSE). Das Projekt ist unabhängig von der ELTAKO GmbH.
- Bei Änderungen an Geräten oder Sender-IDs zuerst die aktuelle Konfiguration sichern und die Herstelleranleitung beachten.

[Zurück zur Repository-Startseite](../README.md)
