# Funk-/Bus-Diagnose und Fehlerbehebung

[← Dokumentationsübersicht](README.md)

Die Integration besitzt eine eigene Funk-/Bus-Diagnose für **gesendete und empfangene ESP2-Telegramme**. Sie ist über die Integrationsoptionen erreichbar.

## Diagnose aktivieren

1. **Einstellungen → Geräte & Dienste → ELTAKO Sensors & Actuators → Konfigurieren**.
2. **Funk / Bus Diagnose** öffnen.
3. Falls deaktiviert, aktivieren.
4. In der Diagnose nach Gerät, Gateway oder Ereignisstufe filtern und den benötigten Ausschnitt kopieren.

Bei einem Supportbericht **Zeitstempel, Geräte-ID, EEP, Gateway-Typ, Sender-ID und Rohtelegramm** angeben. Persönliche Netzwerkadressen oder Seriennummern bei öffentlicher Veröffentlichung gegebenenfalls anonymisieren.

## Wichtige Sendeereignisse

| Ereignis | Aussage |
| --- | --- |
| `send_start` | Ein Schaltbefehl wurde erstellt; zeigt das Zielgerät und die zu sendenden Nachrichten |
| `send_lock_acquired` | Der serielle Sendepfad ist exklusiv gesperrt |
| `telegram_send_attempt` | Der einzelne Frame soll geschrieben werden |
| `telegram_sent` | Der Frame wurde an die serielle Schnittstelle übergeben |
| `send_finished` | Die lokalen Sendeaufrufe sind abgeschlossen |

**Wichtig:** `send_finished` ist **keine Bestätigung durch den Aktor**. Dafür muss eine tatsächliche Statusrückmeldung eintreffen oder das Gerät reagieren.

## Die entscheidenden Diagnosefelder

- `gateway`, `port`, `baudrate`, `protocol`: korrekter USB-Pfad und serielle Einstellungen?
- `sender_id`: in EEDTOY/YAML konfigurierte Controller-ID.
- `effective_sender_ids`: wirklich im Sende-Frame enthaltene Absenderadressen.
- `device_id` / `eep`: Geräte- und Profilzuordnung.
- `data_hex` / `frame`: Nutzdaten und komplettes ESP2-Frame.
- `message_count` / `delay`: mehrere Telegramme bzw. zeitlich getrennte Sendevorgänge.


## Dienste für die Diagnose

Die Integration registriert u. a.:

- `eltako_sensors_actuators.probe_gateway` – Gateway-Typ und Base-ID erneut erkennen.
- `eltako_sensors_actuators.dump_gateway_state` – Gateway-Zustand ins Home-Assistant-Protokoll schreiben.
- `eltako_sensors_actuators.reload_config` – gespeicherten Gateway-Eintrag gezielt neu laden.

Ein optionaler Parameter `entry_id` adressiert beim Probing/Reload einen bestimmten Gateway-Eintrag. Beachte, dass Protokolle technische IDs enthalten können.

[FAQ →](faq.md)
