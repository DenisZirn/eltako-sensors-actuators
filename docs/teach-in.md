# Aktoren anlernen und steuern

[← Dokumentationsübersicht](README.md)

**Teach-in** und **Schaltbefehl** sind zwei getrennte Vorgänge. Der Aktor muss die für spätere Befehle verwendete **Sender-ID** kennen. Ein `telegram_sent` in der Diagnose bestätigt noch nicht, dass der Aktor den Befehl akzeptiert hat.

## Grundablauf

1. Geräteprofil, EEP und Sender-ID mit [EEDTOY](eedtoy.md) kontrollieren.
2. Einlernvorgang am Aktor entsprechend seiner **originalen ELTAKO-Bedienungsanleitung** starten.
3. Falls die Integration für das Gerät eine Teach-in-Schaltfläche anbietet, diese auslösen; andernfalls die Lernfunktion von PCT14 bzw. des Aktors nutzen.
4. Einlernen durch einen Schaltversuch und nach Möglichkeit durch die echte Statusrückmeldung bestätigen.
5. Bei Nichtfunktion die [Diagnose](diagnostics.md) mit `sender_id` und `effective_sender_ids` kontrollieren.

Die Lernverfahren unterscheiden sich je nach Gerät und EEP. **Keine beliebigen Lerntelegramme für unbekannte Profile senden.**

## F2L14 – zweistufiger Lüfter

Die Integration bildet den F2L14 als Home-Assistant-`fan` ab:

| Home Assistant | Bedeutung |
| --- | --- |
| 0 % | Aus |
| 50 % | Stufe 1 |
| 100 % | Stufe 2 |

`f2l14_mode: exclusive` bedeutet, dass Stufe 2 nur den zweiten Kontakt aktiviert; bei `additive` können beide Kontakte aktiv sein – entsprechend der Aktorprogrammierung.

Der Funk-Sendepfad verwendet RPS/`F6-02-01`: `30` (Stufe 1), `70` (Stufe 2) sowie ein separates Loslass-Telegramm. Der **FAM-USB-Hotfix in v0.1.165** verwendet die konfigurierte `sender.id` statt `stage_1_id` als Absender. `stage_1_id` und `stage_2_id` bleiben Statusrückmeldungen.

## FMS14 – zwei Kanäle

Beide Kanäle werden in EEDTOY als separate Einträge behandelt. Die Steuerung verwendet **A5-38-08**:

- EIN: `01-00-00-09`
- AUS: `01-00-00-08`

Voraussetzung ist die korrekt im Aktor eingelernte Controller-Zuordnung. Aktorstatus wird getrennt von der Controller-Sendeadresse empfangen.

## FHK14 / F4HK14

Bei FHK14 ist für die Controller-Sollwertvorgabe die passende Zuordnung in PCT14 erforderlich: **Funktionsgruppe 3, Funktion 65** (Temperatursollwert vom Controller). Die Raumtemperaturquelle wird anschließend in den [Integrationsoptionen](climate.md) gewählt.

## RGBW

- **FRGBW71L:** Ein/Aus und Farb-/Helligkeitssteuerung werden unterstützt.
- **FRGBW14:** Telegrammverarbeitung ist implementiert; die praktische Steuerung ist **noch im Test** und sollte nicht als freigegeben betrachtet werden.

## Sicherheit

Beim Anlernen von Schalt-, Heizungs- oder Rollladenaktoren können reale Ausgänge aktiviert werden. Nur bei sicherem Anlagenzustand testen und die Verdrahtungs-/Herstelleranweisungen beachten.

[Zur Diagnose →](diagnostics.md)
