# ELTAKO Sensors & Actuators

<!-- ha-marketplace:exclude-start -->
[![Open in Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=DenisZirn&repository=eltako-sensors-actuators&category=integration)
[![Open Documentation](https://img.shields.io/badge/Documentation-Read%20the%20Guides-1F6FEB?style=for-the-badge&logo=readthedocs&logoColor=white)](docs/README.md)
<!-- ha-marketplace:exclude-end -->

**Unabhängige Home-Assistant-Integration für kompatible ELTAKO-EnOcean-Sensoren und -Aktoren.** Lokale Kommunikation über **FAM-USB** (Funk) und **FGW14-USB / FAM14** (Serie-14-Bus), ohne Cloud-Zwang.

**Version:** v0.1.165 · **Home Assistant:** 2026.11.0+ · **Lizenz:** [MIT](LICENSE) · **Sprachen:** Deutsch und Englisch

> Dieses Community-Projekt ist keine offizielle ELTAKO-Integration und wird nicht von ELTAKO herausgegeben oder unterstützt.

## Schnellstart

1. **Gateway anschließen:** FAM-USB oder FGW14-USB und möglichst den stabilen `/dev/serial/by-id/`-Port auswählen.
2. **Integration installieren:** Über den [Marketplace-Link](https://my.home-assistant.io/redirect/marketplace_repository/?owner=DenisZirn&repository=eltako-sensors-actuators&category=integration) bzw. **Add from link**, solange die öffentliche Katalogaufnahme aussteht. Alternativ die [Release-ZIP](https://github.com/DenisZirn/eltako-sensors-actuators/releases/tag/v0.1.165) manuell installieren.
3. **Home Assistant neu starten** und unter **Einstellungen → Geräte & Dienste** die Integration hinzufügen.
4. **YAML mit [EEDTOY](https://github.com/DenisZirn/eedtoy)** erstellen und unter **Konfigurieren → EEDTOY YAML importieren oder ersetzen** einlesen.
5. Entitäten und bei Bedarf die **Funk-/Bus-Diagnose** prüfen.

Die Konfiguration wird über den Integrationsdialog importiert, **nicht in `configuration.yaml`** geschrieben.

## Dokumentation

**[📚 Zur vollständigen Dokumentation](docs/README.md)**

| Anleitung | Themen |
| --- | --- |
| [Installation](docs/installation.md) | Voraussetzungen, Marketplace, manuelle Installation, Updates |
| [Gateways](docs/gateways.md) | FAM-USB, FGW14-USB, Ports und Base-ID |
| [EEDTOY / YAML](docs/eedtoy.md) | Geräte hinzufügen, exportieren und importieren |
| [Gerätekatalog](docs/devices.md) | Unterstützte Modelle, Funktionen, Einschränkungen |
| [Aktoren anlernen](docs/teach-in.md) | Sender-ID, Teach-in, F2L14, FMS14, RGBW |
| [Heizung / Climate](docs/climate.md) | FHK14, FKS-SV, externe Temperatur |
| [Funk-/Bus-Diagnose](docs/diagnostics.md) | Telegramme und Fehleranalyse |
| [FAQ](docs/faq.md) | Häufige Fragen und bekannte Einschränkungen |
| [Versionshistorie](docs/changelog.md) | Release-Änderungen |

## Funktionsumfang

- Schalt-, Dimm-, Cover-, RGBW-, Heizungs- und Lüfteraktoren (abhängig von Gerät/EEP).
- Taster, Kontakte, Bewegungs-, Temperatur-, Wetter- und Energiesensoren.
- `serialx` mit gepuffertem ESP2-Empfang einschließlich FT55-Drücken/Loslassen und separater Batterie-IDs.
- EEDTOY-Geräteimport, persistente Gerätezuordnung und integrierte Funk-/Bus-Diagnose.
- Externe Raumtemperaturquellen bei kompatiblen Heizungsaktoren.
- Deutsche und englische Oberflächentexte.

**Bekannte Einschränkungen:** FRGBW14-Steuerung noch im Test; die Geräte-/EEP-Unterstützung hängt von der tatsächlichen Hardware ab. Siehe [Gerätekatalog](docs/devices.md).

## Wartungshinweis v0.1.165

Die v0.1.165-Release-ZIP wurde nach Veröffentlichung um den **hardwaregetesteten F2L14-FAM-USB-Sender-ID-Fix** ergänzt – **ohne die Versionsnummer zu ändern**. Wer v0.1.165 bereits vorher installiert hatte, erhält hierfür normalerweise keinen automatischen Update-Hinweis und muss die aktuelle ZIP erneut installieren. [Details](docs/installation.md).

## Hilfe und Projektlinks

- [EEDTOY – ELTAKO EnOcean Device to YAML Generator](https://github.com/DenisZirn/eedtoy)
- [GitHub Releases](https://github.com/DenisZirn/eltako-sensors-actuators/releases)
- [Fehler melden / Feature vorschlagen](https://github.com/DenisZirn/eltako-sensors-actuators/issues)
- [MIT-Lizenz](LICENSE)

Für Fehlermeldungen bitte Gerätetyp, EEP, Gateway, Softwarestand und **anonymisierte** Diagnose-Telegramme angeben.
