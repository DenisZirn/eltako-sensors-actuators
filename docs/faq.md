# FAQ und bekannte Einschränkungen

[← Dokumentationsübersicht](README.md)

## Wo installiere ich die Integration?

Über den Home Assistant Marketplace, über **Add from link** mit dem GitHub-Repository oder durch manuelles Entpacken der Release-ZIP. Siehe [Installation](installation.md). Die öffentliche Marketplace-Suche setzt die Annahme des [Katalog-Pull-Requests](https://github.com/hacs/default/pull/13465) voraus.

## Brauche ich EEDTOY zwingend?

Nein, aber EEDTOY wird empfohlen, weil es Gerätekennungen, EEPs, Sender-IDs und Exportstruktur handhabbar macht. Die Integration importiert die vollständige Geräte-YAML über die Optionen. [EEDTOY-Anleitung](eedtoy.md).

## Muss ich YAML in `configuration.yaml` schreiben?

**Nein.** Die YAML gehört in **Konfigurieren → EEDTOY YAML importieren oder ersetzen**.

## Muss Home Assistant nach dem YAML-Import neu gestartet werden?

Der aktuelle Import setzt einen **gezielten automatischen Reload** des betroffenen Config Entry. Nach einer **manuellen Dateiinstallation** oder einem Code-Update solltest du Home Assistant vollständig neu starten.


## Warum kann ich senden, aber der Aktor reagiert nicht?

`telegram_sent` bestätigt lediglich, dass der serielle Schreibvorgang durchgeführt wurde. Kontrolliere die im Aktor gelernte Sender-ID, `effective_sender_ids`, EEP, PCT14-Funktion und eine reale Statusrückmeldung. [Diagnose](diagnostics.md).


## Warum erscheinen nicht alle Batterieinformationen sofort?

Manche EnOcean-Geräte senden Batteriestatus nur mit bestimmten Telegrammen oder über eine separate physische ID. Ein aktuelles Kanaltelegramm ist nicht gleichbedeutend mit einer aktuellen Batteriemeldung.

## Wird FRGBW14 unterstützt?

Die Telegrammverarbeitung ist implementiert; die **praktische Steuerung ist noch nicht vollständig freigegeben**. Diese Einschränkung gilt bis zu einem erfolgreichen Hardwaretest.

## Kann ich negative Isttemperaturen verwenden?

Externe Werte von **−15 bis +40 °C** werden eingelesen. Das übertragene A5-10-06-Protokoll kann keine negativen Werte darstellen, der FKS-SV-Pfad akzeptiert für die Ventilantwort nur 0–40 °C. [Heizung](climate.md).

## Ist das ein offizielles ELTAKO-Produkt?

**Nein.** Die Integration ist ein unabhängiges Community-Projekt unter MIT-Lizenz. Zur Fehlermeldung bitte ein [GitHub Issue](https://github.com/DenisZirn/eltako-sensors-actuators/issues) mit anonymisiertem Diagnoselog eröffnen.
