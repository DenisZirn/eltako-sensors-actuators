# Dokumentation – ELTAKO Sensors & Actuators

**Home Assistant 2026.11+ · Integration v0.1.166 · Deutsch**

Diese Dokumentation behandelt die unabhängige Home-Assistant-Custom-Integration **ELTAKO Sensors & Actuators** für lokale ELTAKO-EnOcean- und Serie-14-Systeme.

Die Integration unterstützt unter anderem **FAM-USB**, **FGW14-USB / FAM14**, den Import von EEDTOY-Konfigurationen sowie zahlreiche Sensoren und Aktoren.

> Dieses Community-Projekt ist keine offizielle ELTAKO-Produktdokumentation und wird nicht von ELTAKO herausgegeben oder unterstützt.

## Einstieg

| Thema | Was du dort findest |
| --- | --- |
| [Installation und Updates](installation.md) | Voraussetzungen, Marketplace, manuelle Installation und Updates |
| [USB-Gateways und Verbindungen](gateways.md) | FAM-USB, FGW14-USB/FAM14, Ports, Baudraten und Base-ID |
| [EEDTOY und YAML-Import](eedtoy.md) | Geräte-YAML erstellen, importieren und Gateway-Blöcke auswählen |
| [Unterstützte Geräte](devices.md) | Gerätekatalog, Plattformen, unterstützte Funktionen und Einschränkungen |
| [Aktoren anlernen und steuern](teach-in.md) | Sender-IDs, Teach-in, F2L14, FMS14, FHK14 und RGBW |
| [Heizung und Raumtemperatur](climate.md) | FKS-SV, FHK14/F4HK14, externe Temperaturquellen und Grenzwerte |
| [Funk-/Bus-Diagnose](diagnostics.md) | Telegramme, Batterie-IDs und Fehleranalyse |
| [FAQ und bekannte Einschränkungen](faq.md) | Häufige Fragen, Updates und Problemlösungen |
| [Versionshistorie](changelog.md) | Änderungen der bisherigen Releases |

## Schnellstart

1. [Integration installieren](installation.md) und ein unterstütztes Gateway anschließen.
2. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** das Gateway konfigurieren.
3. Mit [EEDTOY](https://github.com/DenisZirn/eedtoy) die Geräte und EEPs als YAML exportieren. Für aktuelle Geräteprofile wird **EEDTOY 1.1.01 oder neuer** empfohlen.
4. In **Konfigurieren → EEDTOY YAML importieren oder ersetzen** den gewünschten Gateway-Block importieren.
5. Die erzeugten Entitäten prüfen und bei Bedarf die [Funk-/Bus-Diagnose](diagnostics.md) verwenden.

Die EEDTOY-Konfiguration wird über den Integrationsdialog importiert und **nicht in `configuration.yaml` eingetragen**.

## Neu in v0.1.166

- Verbesserte Kompatibilität mit Home Assistant 2026.11.
- Verbesserte Stabilität der Funk-/Bus-Diagnose.
- Unterstützung für **FAH, FAH60B, FAH65S, FIH65S und FHD60SB** als Helligkeitssensoren mit Ausgabe in Lux.
- Unterstützung des älteren **FRW-ws Rauchwarnmelders** inklusive Rauchalarm- und Batteriestatus.
- Verbesserte Geräteerkennung anhand der von EEDTOY exportierten Gerätetypen.
- Bestehende Geräte- und Entitätszuordnungen werden nach Möglichkeit beibehalten.
- Normale `F6-02-01`-Taster wie FT55 bleiben durch die FRW-Unterstützung unverändert.

## Versions- und Sicherheitsinformationen

- Aktuelles GitHub-Release: [v0.1.166](https://github.com/DenisZirn/eltako-sensors-actuators/releases/tag/v0.1.166)
- Quellcode: [GitHub Repository](https://github.com/DenisZirn/eltako-sensors-actuators)
- Fehler und Funktionswünsche: [GitHub Issues](https://github.com/DenisZirn/eltako-sensors-actuators/issues)
- Lizenz: [MIT](../LICENSE)
- Vor größeren Änderungen oder Updates sollte ein Home-Assistant-Backup erstellt werden.
- Bei Änderungen an Sender-IDs, Aktoren oder Teach-in-Konfigurationen zusätzlich die jeweilige Geräteanleitung beachten.

[Zurück zur Repository-Startseite](../README.md)
