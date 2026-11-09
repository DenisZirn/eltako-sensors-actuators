# ELTAKO Sensors & Actuators

<!-- ha-marketplace:exclude-start -->
[![Open in Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=DenisZirn&repository=eltako-sensors-actuators&category=integration)
[![Open Documentation](https://img.shields.io/badge/Documentation-Read%20the%20Guides-1F6FEB?style=for-the-badge&logo=readthedocs&logoColor=white)](docs/README.md)
<!-- ha-marketplace:exclude-end -->

**Unabhängige Home-Assistant-Integration für kompatible ELTAKO-EnOcean-Sensoren und -Aktoren.** Lokale Kommunikation über **FAM-USB** (Funk) und **FGW14-USB / FAM14** (Serie-14-Bus), ohne Cloud-Zwang.

**Version:** v0.1.167 · **Home Assistant:** 2026.11.0+ · **Lizenz:** [MIT](LICENSE) · **Sprachen:** Deutsch und Englisch

> Dieses Community-Projekt ist keine offizielle ELTAKO-Integration und wird nicht von ELTAKO herausgegeben oder unterstützt.

## Schnellstart

1. **Gateway anschließen:** FAM-USB oder FGW14-USB verbinden und möglichst den stabilen `/dev/serial/by-id/`-Port auswählen.
2. **Integration installieren:** Über den [Marketplace-Link](https://my.home-assistant.io/redirect/marketplace_repository/?owner=DenisZirn&repository=eltako-sensors-actuators&category=integration) bzw. **Add from link**, solange die öffentliche Katalogaufnahme aussteht. Alternativ die [Release-ZIP](https://github.com/DenisZirn/eltako-sensors-actuators/releases/tag/v0.1.167) manuell installieren.
3. **Home Assistant neu starten** und unter **Einstellungen → Geräte & Dienste** die Integration hinzufügen.
4. **YAML mit [EEDTOY](https://github.com/DenisZirn/eedtoy)** erstellen und unter **Konfigurieren → EEDTOY YAML importieren oder ersetzen** einlesen. Für aktuelle Geräteprofile wird **EEDTOY 1.1.01 oder neuer** empfohlen.
5. Entitäten und bei Bedarf die **Funk-/Bus-Diagnose** prüfen.

Die Konfiguration wird über den Integrationsdialog importiert und **nicht in `configuration.yaml`** geschrieben.

## Dokumentation

**[📚 Zur vollständigen Dokumentation](docs/README.md)**

| Anleitung | Themen |
| --- | --- |
| [Installation](docs/installation.md) | Voraussetzungen, Marketplace, manuelle Installation, Updates |
| [Gateways](docs/gateways.md) | FAM-USB, FGW14-USB, Ports und Base-ID |
| [EEDTOY / YAML](docs/eedtoy.md) | Geräte hinzufügen, exportieren und importieren |
| [Gerätekatalog](docs/devices.md) | Unterstützte Modelle, Funktionen und Einschränkungen |
| [Aktoren anlernen](docs/teach-in.md) | Sender-ID, Teach-in, F2L14, FMS14, RGBW |
| [Heizung / Climate](docs/climate.md) | FHK14, FKS-SV, externe Raumtemperatur |
| [Funk-/Bus-Diagnose](docs/diagnostics.md) | Telegramme und Fehleranalyse |
| [FAQ](docs/faq.md) | Häufige Fragen und bekannte Einschränkungen |
| [Versionshistorie](docs/changelog.md) | Release-Änderungen |

## Funktionsumfang

- Schalt-, Dimm-, Cover-, RGBW-, Heizungs- und Lüfteraktoren, abhängig von Gerät und EEP.
- Taster, Kontakte, Bewegungs-, Temperatur-, Wetter-, Helligkeits-, Wasser- und Energiesensoren.
- Unterstützung für **FAH, FAH60B, FAH65S, FIH65S und FHD60SB** als Helligkeitssensoren mit Ausgabe in Lux.
- Unterstützung des älteren **FRW-ws Rauchwarnmelders** mit Rauchalarm- und Batteriestatus.
- Unterstützung neuerer **FRWB-Rauchmelder** mit `A5-30-03`.
- Unterstützung des **FWS81 Wassermelders** mit `F6-05-01` als Wasseralarm.
- `serialx` mit gepuffertem ESP2-Empfang einschließlich zuverlässiger FT55-Tast-/Loslass-Telegramme und separater Batterie-IDs.
- EEDTOY-Geräteimport mit technischen Gerätetypen für eine eindeutige Geräteerkennung.
- **Automatische Raumzuordnung:** In EEDTOY hinterlegte Räume werden beim YAML-Import in Home Assistant übernommen.
- Persistente Geräte- und Raumtemperaturzuordnung.
- Externe Raumtemperaturquellen bei kompatiblen Heizungsaktoren.
- Integrierte **Funk-/Bus-Diagnose** zur Analyse empfangener und gesendeter Telegramme.
- Deutsche und englische Oberflächentexte.

## Hinweise zu v0.1.167

- **EEDTOY-Räume:** Das Feld `area` aus dem EEDTOY-Export wird beim Import übernommen. Geräte werden dadurch automatisch dem entsprechenden Home-Assistant-Raum zugeordnet.
- **FRW-ws:** Die doppelte Statusanzeige wurde entfernt. Für den Rauchwarnmelder bleiben die relevanten Entitäten **Rauchalarm** und **Batterie niedrig** erhalten.
- **FWS81:** Der Wassermelder mit EEP `F6-05-01` wird jetzt unterstützt und als Wasseralarm in Home Assistant dargestellt.
- **FAH und FHD60SB:** Helligkeitswerte werden weiterhin korrekt in **Lux** dargestellt.
- Bestehende Entitäten und Konfigurationen werden nach Möglichkeit beibehalten.
- Normale `F6-02-01`-Taster wie FT55 bleiben durch die FRW-Unterstützung unverändert.

**Bekannte Einschränkungen:** Die Unterstützung einzelner Geräte und Funktionen hängt von der verwendeten Hardware, dem EEP und der Gerätekonfiguration ab. Siehe [Gerätekatalog](docs/devices.md).

## Hilfe und Projektlinks

- [EEDTOY – ELTAKO EnOcean Device to YAML Generator](https://github.com/DenisZirn/eedtoy)
- [GitHub Releases](https://github.com/DenisZirn/eltako-sensors-actuators/releases)
- [Fehler melden / Feature vorschlagen](https://github.com/DenisZirn/eltako-sensors-actuators/issues)
- [MIT-Lizenz](LICENSE)

Für Fehlermeldungen bitte Gerätetyp, EEP, Gateway, Softwarestand und **anonymisierte** Diagnose-Telegramme angeben.
