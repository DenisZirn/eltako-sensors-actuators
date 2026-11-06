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

## Funkaktoren der Baureihen 61, 62 und 71 einlernen

Die Integration **ELTAKO Sensors & Actuators** ermöglicht das Einlernen unterstützter Funkaktoren der Baureihen 61, 62 und 71 über einen **FAM-USB**.

Dafür steht bei entsprechend konfigurierten Aktoren in Home Assistant die Schaltfläche **Lerntelegramm senden** zur Verfügung.

Die Integration erzeugt abhängig vom Gerätetyp und EEP das passende Lerntelegramm und sendet dieses mit der für den FAM-USB wirksamen Sender-ID.

### Vorbereitung

1. Den gewünschten Aktor in **EEDTOY** hinzufügen.
2. Das richtige Gerätemodell und EEP auswählen.
3. Die konfigurierte Sender-ID kontrollieren.
4. Die Geräte-YAML für Home Assistant exportieren.
5. Die YAML unter **Einstellungen → Geräte & Dienste → ELTAKO Sensors & Actuators → Konfigurieren → EEDTOY YAML importieren oder ersetzen** importieren.
6. Kontrollieren, ob der Aktor und die Schaltfläche **Lerntelegramm senden** vorhanden sind.
7. Sicherstellen, dass der FAM-USB verbunden ist.

**Wichtig:** Der FAM-USB kann nur Sender-IDs aus seinem eigenen Base-ID-Bereich übertragen. Die Integration berücksichtigt die Base-ID bei der Bildung der tatsächlich verwendeten Sendeadresse.

Die im Aktor eingelernte Sender-ID muss mit der tatsächlichen Sendeadresse übereinstimmen.

### Baureihe 61 – Einlernen über Drehschalter

Beispiele: FSR61, FSR61NP, FSR61G, FUD61NP, FUD61NPN, FSB61 und FLC61NP.

Bei vielen Aktoren der Baureihe 61 wird die Einlernfunktion über einen Funktionsdrehschalter ausgewählt. Ein weiterer Drehschalter aktiviert den Lernmodus.

**Schritt-für-Schritt-Anleitung**

1. Den gewünschten Aktor in Home Assistant öffnen.
2. Am Aktor die Einlernfunktion für die **GFVS-/Software-Steuerung** auswählen, sofern das Gerätemodell eine solche Einstellung benötigt.
3. Den vorgesehenen Lern-Drehschalter auf **LRN** stellen.
4. Die LED am Aktor beginnt normalerweise ruhig zu blinken und signalisiert die Einlernbereitschaft.
5. In Home Assistant die Schaltfläche **Lerntelegramm senden** betätigen.
6. Die Integration sendet das Lerntelegramm mit der konfigurierten Sender-ID.
7. Bei erfolgreichem Einlernen erlischt normalerweise die LED.
8. Die Drehschalter wieder auf die gewünschte Betriebsfunktion stellen.
9. Die Steuerung über Home Assistant testen.

**Gerätespezifische Besonderheiten**

- **FSR61:** Je nach Fertigungsstand unterscheidet sich die Einstellung des unteren Drehschalters. Bei neueren Ausführungen ist für GFVS keine besondere Einlernposition notwendig.
- **FUD61NP / FUD61NPN:** Die vorgesehene Software-/Dimmsteuerfunktion verwenden. Die Einlernstellungen unterscheiden sich zwischen den Modellen.
- **FSB61:** Die passende Steuerfunktion für Rollladen oder Jalousie auswählen.
- **FLC61NP:** Die Software-Steuerung entsprechend der Geräteanleitung einlernen.

Die genaue Drehschalterposition ist von Gerätetyp und Fertigungsdatum abhängig. Es gibt deshalb **keine einheitliche Drehschalterstellung für die gesamte Baureihe 61**.

Weitere Informationen enthält die [ELTAKO-Übersicht zu den Einlernstellungen der Baureihe 61](https://www.eltako.com/fileadmin/downloads/de/Technische_Daten/Einlern-Einstellungen_des_unteren_Drehschalters_bei_den_g%C3%A4ngigsten_Ger%C3%A4ten_der_Baureihe_61_und_Tippsequenzen_f%C3%BCr_Ger%C3%A4te_der_Baureihe_62.pdf).

### Baureihe 62 – Einlernen über Tippsequenzen

Beispiele: FL62, FR62, FR62NP, FD62, FD62NP und FJ62.

Viele Geräte der Baureihe 62 besitzen keine Drehschalter. Die Einlernfunktionen werden über Tippsequenzen an einem örtlichen oder bereits eingelernten Taster aktiviert.

#### Lernmodus aktivieren

Bei einem neuen Aktor kann der Lernmodus bereits aktiv sein. Bei verschiedenen Ausführungen wird er nach dem Einschalten beziehungsweise nach einem Einlernvorgang für eine begrenzte Zeit bereitgestellt.

Ist der Lernmodus gesperrt, muss er zunächst entsperrt werden.

Bei den entsprechenden Ausführungen erfolgt das Entsperren durch:

**4-mal kurz und anschließend 1-mal lang (länger als 2 Sekunden) tippen.**

Die Einlernbereitschaft wird häufig durch ein kurzes Ein- und Ausschalten der angeschlossenen Last signalisiert.

#### Einlernen als GFVS-/Software-Steuerung

Für die GFVS-Steuerung wird bei den in der ELTAKO-Tippsequenzübersicht aufgeführten Geräten **1-mal kurz** als entsprechende Einlernfunktion verwendet.

**Schritt-für-Schritt-Anleitung**

1. Sicherstellen, dass der betreffende Aktor einlernbar ist.
2. Falls erforderlich, den Lernmodus entsperren.
3. Die für das konkrete Gerät vorgesehene **GFVS-Einlernfunktion** auswählen.
4. In Home Assistant den gewünschten Aktor öffnen.
5. Die Schaltfläche **Lerntelegramm senden** betätigen.
6. Der Aktor empfängt das Lerntelegramm mit der Sender-ID des FAM-USB.
7. Die Bestätigung des Aktors abwarten.
8. Anschließend die Steuerung in Home Assistant testen.

**Achtung:** Die einzelne Betätigung zur Auswahl der GFVS-Funktion ist nicht mit den längeren Tippsequenzen zum Sperren, Entsperren oder Löschen zu verwechseln.

#### Übersicht der Tippsequenzen

Die folgende Übersicht gilt für die in der ELTAKO-Tabelle beschriebenen Geräteausführungen der Baureihe 62.

| Funktion | Tippsequenz |
|---|---|
| GFVS-/Software-Steuerung | 1-mal kurz |
| Universaltaster | 3-mal kurz |
| Richtungstaster | 4-mal kurz |
| Zentral EIN / AUF | 5-mal kurz |
| Zentral AUS / AB | 6-mal kurz |
| Lernmodus sperren | 3-mal kurz + 1-mal lang |
| Lernmodus entsperren | 4-mal kurz + 1-mal lang |
| Rückmeldungen aktivieren/deaktivieren | 7-mal kurz + 1-mal lang |
| Speicherinhalt löschen | 8-mal kurz + 1-mal lang |

Beim **FR62** ist eine Besonderheit zu beachten: Für die Universaltasterfunktion unterscheiden sich die Tippsequenzen für **Schließer (3-mal)** und **Öffner (4-mal)**.

Nicht alle Funktionen sind bei jeder Gerätevariante vorhanden. Die aktuelle Bedienungsanleitung des jeweiligen Modells hat Vorrang.

**Wichtig:** Die Sequenz zum Löschen des Speicherinhalts entfernt eingelernte Zuordnungen. Sie darf nicht versehentlich während des normalen Einlernens ausgeführt werden.

Die vollständigen modellabhängigen Angaben stehen in der [ELTAKO-Tippsequenzübersicht der Baureihe 62](https://www.eltako.com/fileadmin/downloads/de/Technische_Daten/Einlern-Einstellungen_des_unteren_Drehschalters_bei_den_g%C3%A4ngigsten_Ger%C3%A4ten_der_Baureihe_61_und_Tippsequenzen_f%C3%BCr_Ger%C3%A4te_der_Baureihe_62.pdf).

### Baureihe 71 – Einlernen über die Gerätebedienung

Beispiele: FSR71, FSR71-2x, FSR71NP-2x, FSB71, FUD71 und FRGBW71L.

Bei den Aktoren der Baureihe 71 unterscheiden sich Lernmodus und Funktionsauswahl je nach Gerätemodell.

**Schritt-für-Schritt-Anleitung**

1. Den gewünschten Aktor in EEDTOY konfigurieren und die YAML nach Home Assistant importieren.
2. Die gewünschte Einlernfunktion für Software- beziehungsweise GFVS-Steuerung am Aktor auswählen.
3. Bei mehrkanaligen Geräten den richtigen Kanal festlegen.
4. Den vorgesehenen Lern-Drehschalter auf **LRN** stellen, sofern das Modell eine entsprechende Stellung besitzt.
5. Die Einlernbereitschaft anhand der LED-Anzeige kontrollieren.
6. In Home Assistant **Lerntelegramm senden** betätigen.
7. Die Einlernbestätigung des Aktors abwarten.
8. Den Aktor wieder in den normalen Betriebsmodus versetzen.
9. Die Steuerung über Home Assistant testen.

**Gerätespezifische Besonderheiten**

- **FSR71-2x:** Der richtige Kanal muss beim Einlernen berücksichtigt werden. Die Kanäle lassen sich abhängig von der Konfiguration getrennt steuern.
- **FSB71-230V:** Bei der entsprechenden Ausführung steht die Position **180** am oberen Drehschalter für Szenentaster und PC-/GFVS-Steuerung. Danach wird der mittlere Drehschalter auf **LRN** gestellt.
- **FUD71:** Die für die Software-Dimmsteuerung vorgesehene Einlernfunktion auswählen.
- **FRGBW71L:** Für die Ansteuerung über Home Assistant wird das entsprechende freie RGBW-Profil eingelernt. Dafür besitzt die Integration eine spezielle Lerntelegramm-Funktion.

Die Drehschalterpositionen dürfen nicht pauschal auf alle Geräte der Baureihe 71 übertragen werden.

### Verwendete Lerntelegramme der Integration

Die Integration verwendet abhängig vom Geräteprofil unterschiedliche Lerntelegramme.

| Gerätefunktion | Telegrammprofil | Daten (DB3–DB0) |
|---|---|---|
| Schaltaktoren, Software-Steuerung | A5-38-08, FUNC 38 / CMD 1 | `E0-40-0D-80` |
| Dimmer, Software-Steuerung | A5-38-08, FUNC 38 / CMD 2 | `E0-40-0D-80` |
| Rollladen-/Jalousieaktoren mit Direktsteuerprofil | FUNC 3F / TYPE 7F | `FF-F8-0D-80` |
| FRGBW71L, freies RGBW-Profil | 07-3F-7F | `FF-F8-0D-87` |

Die Werte beschreiben die aktuell in der Integration implementierten Lerntelegramme.

Je nach Aktor können zusätzliche oder andere Lernverfahren erforderlich sein. Insbesondere das Einlernen als **F6-02-01-Richtungstaster** unterscheidet sich vom Einlernen eines Software-Controllers mit einem **A5-38-08-Lerntelegramm**.

Die gewählte Einlernfunktion muss zum später verwendeten Steuertelegramm passen.

### Erfolgreiches Einlernen überprüfen

Nach dem Einlernen sollte sich der Aktor über Home Assistant bedienen lassen.

Falls keine Reaktion erfolgt:

1. Kontrollieren, ob sich der Aktor tatsächlich im richtigen Lernmodus befand.
2. Das ausgewählte Geräteprofil und EEP überprüfen.
3. Die in EEDTOY konfigurierte Sender-ID kontrollieren.
4. In der **Funk-/Bus-Diagnose** `sender_id` und `effective_sender_ids` vergleichen.
5. Sicherstellen, dass die tatsächlich verwendete Sender-ID im Aktor eingelernt wurde.
6. Bei mehrkanaligen Geräten den richtigen Kanal prüfen.
7. Die Funkreichweite zwischen FAM-USB und Aktor überprüfen.
8. Die Steuerung nach Möglichkeit anhand einer tatsächlichen Statusrückmeldung bestätigen.

Ein erfolgreiches `telegram_sent` oder `send_finished` bestätigt lediglich den Sendevorgang über das Gateway.

Es bedeutet **nicht automatisch, dass der Aktor das Lerntelegramm empfangen und gespeichert hat**.

### Hinweise zum Einlernen

- Bereits eingelernte Sender bleiben beim normalen Hinzufügen eines weiteren Senders erhalten, sofern keine Löschfunktion ausgelöst wird.
- Die Einlernposition **LRN** darf nicht mit **CLR** verwechselt werden.
- Beim Einlernen sollte möglichst kein anderer Funksender betätigt werden, damit nicht versehentlich ein falsches Telegramm gespeichert wird.
- Bei der Baureihe 62 keine unbekannten Tippsequenzen ausprobieren. Einige Kombinationen löschen oder sperren die Einlernfunktion.
- Das im Aktor eingelernte Telegrammprofil muss der späteren Steuerfunktion in Home Assistant entsprechen.

## F2L14 – zweistufiger Lüfter

Die Integration bildet den F2L14 als Home-Assistant-`fan` ab:

| Home Assistant | Bedeutung |
| --- | --- |
| 0 % | Aus |
| 50 % | Stufe 1 |
| 100 % | Stufe 2 |

`f2l14_mode: exclusive` bedeutet, dass Stufe 2 nur den zweiten Kontakt aktiviert; bei `additive` können beide Kontakte aktiv sein – entsprechend der Aktorprogrammierung.

Der Funk-Sendepfad verwendet RPS/`F6-02-01`: `30` (Stufe 1), `70` (Stufe 2) sowie ein separates Loslass-Telegramm.

Der **FAM-USB-Hotfix in v0.1.165** verwendet die konfigurierte `sender.id` statt `stage_1_id` als Absender. `stage_1_id` und `stage_2_id` bleiben Statusrückmeldungen.

## FMS14 – zwei Kanäle

Beide Kanäle werden in EEDTOY als separate Einträge behandelt. Die Steuerung verwendet **A5-38-08**:

- EIN: `01-00-00-09`
- AUS: `01-00-00-08`

Die benötigten Sender-IDs und Kanalzuordnungen werden über EEDTOY eingerichtet und in die Aktoren geschrieben.

Eine zusätzliche manuelle Controller-Konfiguration ist bei korrekt durchgeführter EEDTOY-Programmierung nicht erforderlich.

Die Statusrückmeldungen werden getrennt von der Controller-Sendeadresse empfangen.

## FHK14 / F4HK14

Die Aktoren FHK14 und F4HK14 können über Home Assistant als Climate-Entitäten gesteuert werden.

Die dafür benötigten Sender-IDs und Aktorzuordnungen werden über **EEDTOY** eingerichtet und in die Aktoren geschrieben. Eine zusätzliche manuelle Controller-Konfiguration ist nicht erforderlich.

Für die Sollwertvorgabe muss die passende Controller-Funktion im Aktor programmiert sein. Beim FHK14 entspricht dies der **Funktionsgruppe 3, Funktion 65**.

Die gewünschte Raumtemperaturquelle wird anschließend direkt in Home Assistant über die [Integrationsoptionen](climate.md) ausgewählt.

Dabei kann zwischen der bestehenden beziehungsweise eingelernten Temperaturquelle und einem externen Home-Assistant-Raumtemperatursensor gewechselt werden.

## RGBW

- **FRGBW71L:** Ein/Aus und Farb-/Helligkeitssteuerung werden unterstützt. Für das Einlernen steht eine spezielle Funktion für das freie RGBW-Profil zur Verfügung.
- **FRGBW14:** Telegrammverarbeitung ist implementiert; die praktische Steuerung ist **noch im Test** und sollte nicht als freigegeben betrachtet werden.

Der FRGBW14 ist ein Serie-14-Busaktor. Seine Controller-Zuordnung wird über die Busprogrammierung beziehungsweise EEDTOY vorgenommen und nicht über das Funk-Lerntelegramm des FRGBW71L.

## Sicherheit

Beim Anlernen von Schalt-, Heizungs- oder Rollladenaktoren können reale Ausgänge aktiviert werden. Nur bei sicherem Anlagenzustand testen und die Verdrahtungs- und Herstelleranweisungen beachten.

Arbeiten an der elektrischen Anlage dürfen nur von entsprechend qualifizierten Elektrofachkräften durchgeführt werden.

Vor dem Einlernen sicherstellen, dass durch unbeabsichtigte Schalt-, Dimm- oder Fahrbefehle keine Gefährdung entsteht.

## Weiterführende Informationen

- [ELTAKO – Einlernstellungen Baureihe 61 und Tippsequenzen Baureihe 62](https://www.eltako.com/fileadmin/downloads/de/Technische_Daten/Einlern-Einstellungen_des_unteren_Drehschalters_bei_den_g%C3%A4ngigsten_Ger%C3%A4ten_der_Baureihe_61_und_Tippsequenzen_f%C3%BCr_Ger%C3%A4te_der_Baureihe_62.pdf)
- [ELTAKO – Offizielle Bedienungsanleitungen](https://www.eltako.com/de/service/downloads-zone/)
- [EEDTOY – ELTAKO EnOcean Device to YAML Generator](https://github.com/DenisZirn/eedtoy)
- [ELTAKO Sensors & Actuators – Funk-/Bus-Diagnose](diagnostics.md)

[Zur Diagnose →](diagnostics.md)
