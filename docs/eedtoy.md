# EEDTOY: Geräte-YAML erstellen und importieren

[← Dokumentationsübersicht](README.md)

**[EEDTOY – ELTAKO EnOcean Device to YAML Generator](https://github.com/DenisZirn/eedtoy)** ist ein separates Hilfsprogramm. Es erstellt die Geräte-YAML für diese Integration.

## In EEDTOY vorbereiten

1. Die passende Anwendung aus den [EEDTOY-Releases](https://github.com/DenisZirn/eedtoy/releases) installieren.
2. Das richtige Gateway bzw. den korrekten Gateway-Block wählen.
3. Aktoren und Sensoren hinzufügen; bei unterstützten Businstallationen können vorhandene PCT14-Konfigurationen als Basis dienen.
4. **Geräte-ID**, **EEP**, **`device_type`** und bei Aktoren die **`sender.id`** prüfen.
5. Bei Mehrkanalaktoren (z. B. **FMS14, F2L14**) die Kanal-/Status-IDs und Betriebsart prüfen.
6. Den Export für **Home Assistant / ELTAKO YAML** erstellen.

## In Home Assistant importieren

1. **Einstellungen → Geräte & Dienste → ELTAKO Sensors & Actuators → Konfigurieren**.
2. **EEDTOY YAML importieren oder ersetzen** öffnen.
3. Die YAML **als Text einfügen** oder **eine Datei aus dem Home-Assistant-Konfigurationsordner auswählen**.
4. Enthält die YAML mehrere Gateways, den passenden Gateway-Block auswählen.
5. Speichern; ein erfolgreicher Import erzeugt einen Hinweis und startet den gezielten **Reload** des Gateway-Eintrags.

**Wichtig:** Diese YAML wird über die Integration importiert. Sie gehört **nicht** in `configuration.yaml`.

## Aufbau der YAML

Der Importer erwartet einen Wurzelblock `eltako` mit einer `gateway`-Liste und Geräten nach Plattform. Das folgende Beispiel zeigt die **Struktur**, nicht die vollständige Konfiguration eines konkreten Geräts:

```yaml
eltako:
  gateway:
    - id: 1
      device_type: fam-usb
      base_id: "FF-A6-04-80"
      devices:
        binary_sensor:
          - name: "Taster Schlafzimmer"
            id: "FE-EF-D6-FC"
            eep: "F6-02-01"
            device_type: "F2T55"
```

Bei Aktoren sind weitere Angaben wie `sender: {id: "...", eep: "..."}` erforderlich. Die Werte müssen **zu deiner realen Anlage passen**; keine Beispiel-IDs blind übernehmen. Der von EEDTOY generierte Export ist vorzuziehen.

Der Importer verarbeitet unter anderem die Plattformen `sensor`, `binary_sensor`, `light`, `switch`, `cover`, `climate`, `button` und `fan`.

## Besondere Geräte

- **FMS14:** Die zwei Kanäle werden getrennt abgebildet; Steuertelegramme über **A5-38-08**.
- **F2L14:** `sender.id` ist die **eingelernte Steuer-ID**. `stage_1_id` und `stage_2_id` sind Rückmelde-IDs. `f2l14_mode` kann `exclusive` oder `additive` sein.
- **FHK14 / F4HK14:** Controller-Zuordnung im Aktor kontrollieren; siehe [Heizung](climate.md).
- **F4USM61B:** Kanaltelegramme und Batteriemeldungen können verschiedene physische IDs verwenden; diese nicht vereinheitlichen.
- **FRGBW14:** Telegrammverarbeitung vorhanden, Ansteuerung noch nicht vollständig hardwarevalidiert.

## Nach einem erneuten Import

Der Import ersetzt die gespeicherte Gerätezuordnung für den gewählten Gateway-Block. Vor Änderungen bestehende YAML sichern; bei Problemen das korrekte Gateway und die richtigen `sender.id`-Werte prüfen.

[Unterstützte Geräte →](devices.md)
