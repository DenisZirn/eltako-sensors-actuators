# Bestätigter Referenzstand

## Bestätigung und Präzisierung vom 27.11.2026

Der Anwender hat **v0.1.169-beta.2 für seine eingesetzte Konfiguration als funktionsfähig bestätigt**. Zunächst nahm er **FHK61** aus, weil eine Änderung der Solltemperatur dort nicht zum erwarteten Schalten führte.

**Nachfolgende Präzisierung am selben Tag:** FHK61 funktioniert, solange **keine Betriebsart eingelernt ist**. Der Anwender hat deshalb angewiesen, den Funktionsstand von beta.2 einschließlich FHK61 für v0.1.169 zu übernehmen. Beim FHK61 vorerst keine Betriebsart einlernen; die Kombination mit Betriebsarteinlernen bleibt Gegenstand weiterer Tests.

Diese Bestätigung hält den erreichten Gesamtstand fest. Sie ersetzt keine gesonderte Prüfung bisher ungetesteter Gerätevarianten und belegt keine einzeln protokollierte Ausführung aller vorgeschlagenen Testschritte.

| Referenz | Wert |
| --- | --- |
| Integrationsversion | `0.1.169-beta.2` |
| Code-Commit des bestätigten Pakets | `b579017993aa99e6616c9af556a4f40f6a8b2893` |
| Lokaler Git-Tag | `verified/v0.1.169-beta.2-except-fhk61` |
| Installationspaket | `eltako_sensors_actuators_v0.1.169-beta.2.zip` |
| Paketgröße | 451255 Bytes |
| SHA-256 des Pakets | `9cecaed20c26a499e3448ae99cae22f6a8e7200631bdd8fc5b30b3cdf2e9d92b` |

Der Tag bezeichnet genau den ausgelieferten Code-Stand. Sein historischer Name bleibt trotz der späteren Präzisierung unverändert. Die nachträgliche Dokumentation der Anwenderbestätigung verändert dessen Laufzeitdateien und Installationspaket nicht.

## Grundlage für weitere Korrekturen

- Dieser Stand ist die feste Vergleichsbasis für die weitere FHK61-Arbeit.
- Der bestätigte FHK14-Betrieb mit eingelerntem Sensor und zentraler HA-Sollwertvorgabe sowie der externe F64-Temperaturpfad gehören zur Vergleichsbasis.
- FHK61-Korrekturen werden in einem folgenden Teststand getrennt geprüft. Der Referenztag wird dafür nicht verschoben.
- Bei der Erstellung von beta.2 bestanden **197 automatisierte Tests**. Das Paket enthält 61 Dateien unter genau einem Ordner `eltako_sensors_actuators`.

## Offener Punkt: Betriebsarteinlernen beim FHK61

**Ursprüngliche Beobachtung:** Der Aktor reagierte nicht mit dem erwarteten Schalten auf eine Sollwertänderung.

**Präzisierte Bestätigung:** Ohne eingelernte Betriebsart funktioniert der FHK61 nach Rückmeldung des Anwenders. Die frühere pauschale FHK61-Ausnahme ist damit auf die Kombination mit Betriebsarteinlernen eingegrenzt.

**Status:** Das Betriebsarteinlernen beim FHK61 ist weiterhin offen. Die Präzisierung belegt keine bestimmte Protokollursache und keine erfolgreiche Korrektur dieser Kombination. Die Rückmeldung bezeichnet FHK61; daraus wird weder eine Funktionsbestätigung noch ein identischer Fehler aller Varianten FHK61U/FHK61SSR abgeleitet.

Die bestätigte Referenzversion und ihr unverändertes Paket bleiben `0.1.169-beta.2`. Für das reguläre Release v0.1.169 wird dieser Laufzeitstand mit angepasster Versionsnummer übernommen.
