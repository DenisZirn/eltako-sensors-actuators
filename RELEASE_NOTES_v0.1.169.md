# ELTAKO Sensors & Actuators v0.1.169

*Stabile Farben, zuverlässigere Heizungssteuerung und übersichtlichere Raumregler.*

Diese Version enthält die erfolgreich getesteten Verbesserungen aus **v0.1.169-beta.2**.

## Verbessert

- **FRGBW14:** Beim Farbwechsel bleibt die eingestellte Helligkeit erhalten. Unerwartete Helligkeitssprünge und falsche Aus-Anzeigen wurden behoben.
- **Heizungssteuerung der Serie 14:** Die eingestellte Wunschtemperatur springt nicht mehr zurück. Nach „Aus“ nimmt eine neue Temperaturvorgabe den normalen Betrieb wieder auf.
- **Externe Temperatursensoren:** Die Raumtemperatur wird automatisch und regelmäßig an den Heizungsaktor übermittelt – auch wenn sich der Messwert nicht ändert. Raum- und Wunschtemperatur werden genauer übertragen. Ein vorübergehender Sensorausfall wird verständlich angezeigt.
- **Steuerung über Home Assistant:** Bei Heizungsaktoren der Serie 14 mit eingelerntem Raumregler ist „Zentral“ jetzt die Voreinstellung, sofern bisher keine andere Priorität festgelegt wurde. Damit gibt Home Assistant die Wunschtemperatur vor.
- **FTR-Raumregler:** Verbesserte Temperaturanzeige. Nicht übermittelte Betriebsart- und Frostschutzwerte werden nicht mehr als Gerätestatus angezeigt.
- **Diagnose:** Gesendete Befehle und Rückmeldungen des Geräts werden zuverlässiger unterschieden.

## Hinweis zum FHK61

**FHK61 bleibt enthalten.** In der getesteten Konfiguration funktioniert die Temperatursteuerung, solange **keine Betriebsart eingelernt ist**. Bitte die Schaltfläche **„Betriebsart einlernen“ beim FHK61 vorerst nicht verwenden**. Diese Funktion wird separat weiter geprüft.

## Update

Home Assistant **2026.11.0 oder neuer** ist erforderlich. Nach dem Update Home Assistant vollständig neu starten.

- **Marketplace/HACS:** reguläres Update verwenden.
- **Manuelle Installation:** `eltako_sensors_actuators_v0.1.169.zip` herunterladen und den enthaltenen Ordner `eltako_sensors_actuators` nach `/config/custom_components/` kopieren.

Dieses Projekt ist eine unabhängige Community-Integration und kein offizielles Produkt von ELTAKO.
