# Heizung, Sollwerte und Raumtemperatursensoren

[← Dokumentationsübersicht](README.md)

Die Integration unterstützt je nach Geräteprofil unter anderem **FHK14**, **F4HK14**, **FKS-SV** und kompatible Heizungsaktoren. v0.1.169 verwendet die Climate-API von Home Assistant 2026.11.

**v0.1.169** übernimmt den bestätigten Funktionsstand aus **v0.1.169-beta.2 einschließlich FHK61**. Der Anwender hat am 27.11.2026 präzisiert: Die Temperatursteuerung des FHK61 funktioniert, solange **keine Betriebsart eingelernt ist**. Beim FHK61 deshalb vorerst keine Betriebsart einlernen; diese Kombination wird separat weiter geprüft. Der bestätigte Beta-Code, das zugehörige Paket und die Präzisierung sind im [Referenzstand](verified-baseline.md) dokumentiert.

## Externe Raumtemperatur zuweisen

1. **Einstellungen → Geräte & Dienste → ELTAKO Sensors & Actuators → Konfigurieren** öffnen.
2. **Raumtemperatursensor zuweisen** wählen.
3. Den gewünschten Heizungsaktor auswählen.
4. Zwischen **Bestehend/eingelernt bzw. intern** und **Externer Home-Assistant-Raumtemperatursensor** wechseln.
5. Beim externen Sensor die gewünschte `sensor.`-Entität auswählen und speichern.

Die Auswahl wird je physischem Aktor gespeichert und hat Vorrang vor einer `room_temperature_entity`-Vorgabe aus der YAML. Die Änderung wird im laufenden Betrieb übernommen; bei Bedarf die Diagnoseattribute prüfen.

Der Sensor muss eine echte **Temperatur-Entität** sein, die einen numerischen Wert in °C oder °F liefert. `unknown`, `unavailable` oder nichtnumerische Werte sind nicht verwendbar.

## Temperaturgrenzen und Protokoll

| Funktion | Bereich/Verhalten |
| --- | --- |
| Externer HA-Sensorwert | **−15 bis +40 °C** gültig |
| FHK14/F4HK14, A5-10-06 | Im Telegramm können nur **0 bis +40 °C** dargestellt werden |
| Negativer Sensorwert beim FHK14 | HA behält den echten Wert; im Telegramm wird **0 °C** als Untergrenze gesendet |
| FKS-SV, A5-20-01 | Negative Istwerte werden **nicht** an das Ventil gesendet; stattdessen Rückfall auf einen gültigen internen Wert |
| Externer Sensor bei Series 14 / F64 nicht verfügbar | Keine Temperaturübertragung bis wieder ein gültiger Istwert vorliegt; keine automatische Änderung der Einlernfunktion |
| Externer Sensor bei FKS-SV nicht verfügbar | Rückfall auf einen gültigen internen Wert |

**Achtung:** Der übertragene Wert von 0 °C ist bei einem realen Messwert unter null **nicht** dessen tatsächliche Temperatur. Für eine Heizungsregelung sollte ein geeigneter **Raum**temperatursensor genutzt werden, kein Außenfühler.

## FKS-SV

Das FKS-SV reagiert auf sein bidirektionales Kommunikationsfenster. Ein neuer Sollwert wird im nächsten Fenster übertragen. Laut bisherigem Hardwaretest liegt das reguläre Intervall ungefähr bei **10 Minuten**; ein kurzer Druck auf die Ventiltaste kann einen zusätzlichen Austausch auslösen.

## FHK14 und PCT14

Bei FHK14 müssen Temperaturquelle und Einlernfunktion zusammenpassen:

| Temperaturquelle | Einlernen am Aktor |
| --- | --- |
| Bestehender/eingelernter Temperatursensor | Physischer Sensor in **FG1**; HA-Sender für die Sollwertvorgabe in **FG3 / Funktion 65** |
| Externer HA-Raumtemperatursensor | HA-Sender für Ist- und Solltemperatur in **FG1 / Funktion 64** |
| Betriebsart Normal, Nacht, Absenken oder Aus | Betriebsart-Sender separat in **FG4 / Funktion 30** |

Die Auswahl eines Sensors in Home Assistant ändert den Gerätespeicher des Aktors nicht. Der Betriebsart-Sender entspricht standardmäßig der HA-Sender-ID; `operating_mode_sender_id` kann einen getrennt eingelernten Sender vorgeben. Das [PCT14-Handbuch](https://www.eltako.com/fileadmin/downloads/de/Software/PCT14_Handbuch.pdf) beschreibt die Funktionen 64 und 65 getrennt.

In **v0.1.169** verändern als Controller-Echo erkannte Telegramme weder den Sollwert noch die Betriebsart der Series-14-Climate. Dadurch wird etwa ein eingestellter Sollwert von 25 °C nicht durch das eigene, mit 24,9 °C zurückdecodierte Sendetelegramm ersetzt. Echte Aktorrückmeldungen werden weiter ausgewertet.

Wird bei einer ausgeschalteten Series-14-Climate ein neuer Sollwert gewählt, sendet die Integration zuerst den Sollwert und anschließend den separaten RPS-Befehl für Normalbetrieb. Scheitert das zweite Senden, bleibt die Anzeige auf Aus und Home Assistant meldet den Teilerfolg ausdrücklich.

Ein erfolgreicher Sendeaufruf bestätigt nur die Übertragung an das Gateway. Der Climate-Zustand allein beweist nicht, dass der Aktor den Steuerbefehl ausgeführt hat.

## Externer HA-Sensor: Telegramm für Funktion 64

Bei externer Temperaturquelle übernimmt HA die Rolle des Raumreglers und überträgt Ist- und Solltemperatur. Die C/A/M/L-Auswahl gehört zum separaten zentralen Sollwertgeber unter Funktion 65 und wird für F64 deshalb nicht angeboten.

In **v0.1.169** verwendet dieser Series-14-Sendepfad ein eigenes FTR-Sensorprofil:

| Feld | Bedeutung |
| --- | --- |
| DB3 = `00` | Unbenutztes Feld im normalen A5-10-06-Sensorprofil |
| DB2 | Solltemperatur, 0–40 °C linear auf 0–255 |
| DB1 | Isttemperatur, 0–40 °C invertiert auf 255–0 |
| DB0 = `0F` | Eltako-FTR-Datentelegramm mit gesetztem Tag-Bit |

Für **25 °C Soll und 21,6 °C Ist** ergibt sich `00-9F-75-0F`. Grundlage sind die FTR55ESB/FTR55EHB-Tabelle in [Inhalte der Eltako-Funktelegramme](https://www.eltako.com/fileadmin/downloads/de/Technische_Daten/Inhalte_der_Eltako-Funktelegramme.pdf), Abschnitt T-13, und [EEP A5-10-06](https://www.enocean-alliance.org/wp-content/uploads/2019/10/EEP268_R3_Feb022018_public.pdf), Seite 52. Das Beispiel ist berechnet, kein aufgezeichneter Hardwaremitschnitt.

### Temperaturauflösung ab 0.1.169-beta.2

Die Temperaturauflösung beträgt **40/255 ≈ 0,157 K**. Bis beta.1 wurde das Sollwertbyte abgeschnitten und damit der Sollwert abgerundet. Das ebenfalls abgeschnittene, invertierte Istwertbyte rundete die Isttemperatur dagegen auf. Dadurch konnte die Übertragung einen realen Temperaturabstand verkleinern oder vollständig aufheben.

Bei **20,3 °C Ist** ergaben sich folgende berechnete Werte:

| Angeforderter Sollwert | beta.1: Ist / Soll auf dem Protokoll | beta.2: Ist / Soll auf dem Protokoll |
| --- | --- | --- |
| 20,5 °C | 20,392 / 20,392 °C | 20,235 / 20,549 °C |
| 21,0 °C | 20,392 / 20,863 °C | 20,235 / 21,020 °C |
| 21,5 °C | 20,392 / 21,490 °C | 20,235 / 21,490 °C |

Für AUTO 3 beschreibt die [FHK14-Anleitung](https://www.eltako.com/fileadmin/downloads/de/_bedienung/FHK14_30014014-2_dt.pdf) das Ausschalten bei Ist ≥ Soll und das Einschalten bei Ist ≤ Soll − Hysterese. Damit erklären die bisherigen Bytes bei 0,5 K Hysterese sowohl das Ausschalten bei angeforderten 20,5 °C als auch das ausbleibende Einschalten bei 21,0 °C. Die Tabelle ist eine Reproduktion mit dem Encoder, kein neuer Funkmitschnitt des Aktors.

Ab beta.2 rundet der externe F64-Pfad beide Temperaturen auf den nächstgelegenen Punkt desselben aufsteigenden Rasters. Erst danach wird das Istwertbyte invertiert: DB2 = q(Soll), DB1 = 255 − q(Ist). So bleiben identische Soll- und Istwerte auch an halben Protokollschritten identisch. Der Rundungsfehler pro Temperatur innerhalb des Protokollbereichs von 0 bis 40 °C beträgt höchstens etwa 0,0784 K. Die Protokollauflösung bleibt bestehen; eine beliebige exakte Schaltschwelle in HA-Dezimalwerten ist damit nicht garantiert.

Die Rundung ist eine Genauigkeitskorrektur der Integration; eine Pflicht zum früheren Abschneiden ist in den genannten Tabellen nicht festgelegt. Die Rundung betrifft ausschließlich F64; native F65-Sender behalten ihre bisherigen Bytes. Bei 20,3 °C Ist und 0,5 K Hysterese lautet ein gezielter Vergleichstest: 20,0 °C Soll → aus; 21,0 °C → ein; zurück auf 20,5 °C → eingeschaltet bleiben; zurück auf 20,0 °C → aus. Bei geänderter Isttemperatur sind diese Testpunkte entsprechend anzupassen.

### Betriebsart, Rückmeldung und Sensoraktualisierung

Im bisherigen externen Sendepfad wurde auch für F64 das F65-Controllerformat verwendet, beispielsweise `70-9F-75-0E`. Die frühere Aussage, F64 benötige zwingend `0E`, war falsch: Bei A5-10-06 bedeutet DB0.0=0 Nacht. Laut PCT14-Handbuch senkt Funktion 64 dann den Sollwert um 4 K. Damit wären bei angeforderten 25 °C nur rund 21 °C wirksam, unterhalb der gemeldeten 21,6 °C. Das ist eine aus Protokoll und Diagnose abgeleitete Erklärung für ausbleibenden Heizbedarf, sofern der Sender tatsächlich als F64 eingetragen ist. Der Anwender hat die Funktion des korrigierten Standes beta.2 am 27.11.2026 bestätigt; dies ist kein zusätzlicher Telegrammmitschnitt zur früheren Ursache.

Das neue F64-Profil sendet neutrale FTR-Temperaturdaten. Normalbetrieb, Nacht, Absenken und Aus bleiben Aufgabe der separat eingelernten RPS-Betriebsartbefehle. Die bisherigen F65-Prioritätsbytes werden dadurch nicht geändert. Der FHK61-Sendepfad bleibt auf dem Stand von beta.2; beim FHK61 vorerst keine Betriebsart einlernen.

Sollwertänderungen und Sensoraktualisierungen werden je Climate serialisiert. Ein während der Sollwertübertragung eintreffender Sensorwert darf keinen alten Sollwert hinterherschicken. Eine physische Rückmeldung mit demselben rohen Sollwertbyte wie der letzte erfolgreiche F64-Sendeauftrag behält den angeforderten HA-Wert bei, wenn dieser Auftrag weiterhin aktuell ist. Dadurch wird 25 °C nicht über 24,9 °C erneut auf einen niedrigeren Telegrammwert gerundet. Tatsächlich abweichende Sollwertrückmeldungen werden weiter verarbeitet.

Nach einer erfolgreichen F64-Temperaturübertragung werden die aktuellen Werte auch bei konstantem externem Istwert alle **15 Minuten** erneut gesendet. Das PCT14-Handbuch beschreibt für F64 einen Störbetrieb nach mehr als einer Stunde ohne Sensortelegramm. Die regelmäßige Übertragung endet beim Entladen der Entität und ist nur für die konfigurierte externe Series-14-Quelle aktiv. Eine neu angelegte Entität ohne wiederhergestellten Zustand erhält dadurch keinen geratenen ersten Sollwert.

Fehlt ein gültiger externer Istwert, pausiert dieser Temperaturpfad und meldet einen Fehler. Eine direkte Sollwertübertragung wird dann mit einer verständlichen Fehlermeldung abgewiesen. Die Integration sendet weder einen erfundenen Istwert von 40 °C noch ein F65-Ersatztelegramm; die physische Einlernfunktion wird durch einen Sensorausfall nicht geändert. Sobald der Sensor wieder gültige Werte liefert, werden die Temperaturdaten erneut übertragen.

## Priorität bei eingelerntem Raumregler

In der Beschreibung der Heizungsprioritäten entspricht die **App** hier **Home Assistant**. Die Priorität bestimmt die Sollwertvorgabe. Ein in FG1 eingelernter Temperatursensor liefert weiterhin die Isttemperatur.

| Auswahl | Sollwertvorgabe |
| --- | --- |
| **Zentral (C)** | Der von HA vorgegebene Sollwert hat Vorrang. |
| **Automatisch (A)** | HA und Raumregler sind gleichberechtigt. |
| **Manuell (M)** | Freigabe an den Raumregler, bis HA erneut einen Sollwert vorgibt. |
| **Begrenzt ±3 K (L)** | HA gibt den Sollwert vor; der Raumregler kann innerhalb von ±3 K verändern. |

Im Hardwaretest vom 26.11.2026 sprang der native FHK14 unter A nach 19,5 / 22,5 / 25 °C Sollvorgabe auf 16,5 / 19,5 / 22 °C zurück. Nach dem Wechsel auf C schaltete derselbe Aktor bei Sollwertänderungen sofort und der Sollwert blieb stabil. Dieser Test bestätigt C für den gewünschten Betrieb mit HA als Sollwertgeber. Die interne Ursache der einzelnen 3-K-Rückmeldungen wird damit nicht für alle Geräte oder Prioritätsmodi verallgemeinert.

Mit **v0.1.169** gilt für Series 14 mit eingelerntem Sensor daher **C als Standard, wenn keine Priorität vorgegeben ist**. Das betrifft auch bestehende Konfigurationen ohne eigene Prioritätsvorgabe. Eine bereits gespeicherte Auswahl sowie explizite YAML-Prioritäten bleiben erhalten. Insbesondere wird ein bewusst gewähltes A oder L nicht durch das Update ersetzt. Für die ausschließliche Sollwertvorgabe durch HA ist C auszuwählen; diese Auswahl bleibt bei Neustarts erhalten.

Ein neuer HA-Sollwert nach M verwendet in diesem Series-14-Steuerweg ebenfalls C. Bei erfolgreichem Versand wird die Auswahl auf C aktualisiert. Scheitert der Versand, bleibt die gespeicherte manuelle Auswahl erhalten. Eine ausdrücklich in HA gewählte Temperaturquelle hat bei Series 14 Vorrang vor einer älteren YAML-Angabe `heating_control_mode`.

Das erfolgreiche C-Ergebnis am nativen FHK14 belegt den Betrieb als zentraler Sollwertgeber. Der externe HA-Sensorpfad über FG1/Funktion 64 wurde in beta.1 korrigiert und in beta.2 um die konsistente Temperaturrundung ergänzt. Der Anwender hat beta.2 am 27.11.2026 als funktionsfähigen Referenzstand bestätigt und die zunächst genannte FHK61-Ausnahme anschließend eingegrenzt: FHK61 funktioniert ohne eingelernte Betriebsart. Die Kombination mit zusätzlichem Betriebsarteinlernen bleibt offen; die Aussage wird nicht pauschal auf FHK61U/FHK61SSR übertragen.

## Diagnoseattribute

Je nach Aktor stehen u. a. `temperaturquelle_konfiguriert`, `temperaturquelle_tatsaechlich`, `temperaturquellen_status`, `aktuelle_externe_raumtemperatur`, `protokoll_isttemperatur` und `protokoll_temperatur_begrenzt` zur Verfügung.

`letzte_controllerantwort` ist ein historischer Attributname: Der Wert wird nach dem erfolgreichen Senden gesetzt und ist **kein Zeitpunkt einer Aktorbestätigung**. Auch `betriebsart_aktor_bestaetigt: false` bei Series 14 ist keine empfangene Ablehnung; die Integration führt hier bisher keine bestätigte Betriebsart nach.

Bei Status **Fehler** im externen F64-Pfad beziehungsweise **Fallback** beim FKS-SV zuerst in **Entwicklerwerkzeuge → Zustände** den tatsächlich gemeldeten Sensorwert und `unit_of_measurement` prüfen.

[Weitere Fehleranalyse →](diagnostics.md)
