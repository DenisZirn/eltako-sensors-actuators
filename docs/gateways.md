# USB-Gateways und Verbindungen

[← Dokumentationsübersicht](README.md)

Die Integration kommuniziert **lokal über USB** und verwendet EnOcean-**ESP2**-Telegramme. Die serielle Bibliothek ist seit v0.1.165 `serialx`.

| Gateway | Anschluss | Protokoll | Baudrate | Hinweis |
| --- | --- | --- | ---: | --- |
| **FAM-USB** | EnOcean Programmer USB | ESP2 | **9600** | In der Regel **Interface `if01`** |
| **FGW14-USB / FAM14** | FTDI-/USB-RS485 zum Serie-14-Bus | ESP2 | **57600** | USB-/RS485-Gateway |

## Stabilen Gerätenamen auswählen

Bevorzugt unter Linux/Home Assistant OS eine Geräteadresse unter `/dev/serial/by-id/`, beispielsweise:

- FAM-USB: `/dev/serial/by-id/usb-EnOcean_GmbH_EnOcean_Programmer_...-if01-port0`
- FGW14-USB: `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_...-if00-port0`

Die dynamischen Bezeichnungen `/dev/ttyUSB0` und `/dev/ttyUSB1` können sich nach einem Neustart ändern. **Die vollständige Geräteadresse deiner Installation ist maßgeblich**, nicht die Beispiel-ID.

## Gateway einrichten

1. USB-Gateway anschließen.
2. **Einstellungen → Geräte & Dienste → Integration hinzufügen** öffnen.
3. **ELTAKO Sensors & Actuators** auswählen.
4. Den erkannten seriellen Port auswählen. Falls er fehlt, die manuelle Portangabe verwenden.
5. Den Gateway-Eintrag benennen und speichern.
6. Die passenden Geräte über [EEDTOY](eedtoy.md) importieren.

Die Oberfläche bietet außerdem **Konfigurieren → Gateway / seriellen Anschluss ändern**.

## Sender-ID und Base-ID: zwei unterschiedliche Dinge

- **Physische Geräte-ID:** Kennzeichnet das empfangende bzw. sendende EnOcean-Gerät.
- **`sender.id`:** In der YAML definierte Steueradresse, die der Aktor eingelernt haben muss.
- **Gateway-Base-ID:** Definiert den nutzbaren Funk-Sendeadressbereich des FAM-USB.
- **`stage_1_id` / `stage_2_id` beim F2L14:** Kennzeichnen die **Statusrückmeldungen des Aktors**; sie dürfen nicht als ausgehende Controller-Sender-ID verwendet werden.

Bei einem FAM-USB kann eine logische Sender-ID in den physikalischen Base-ID-Bereich übersetzt werden. Entscheidend ist, dass die tatsächlich gesendete ID zur **eingelernten ID** passt. Für die Serie-14-Busverbindung gelten abweichende Zuordnungsregeln.

## Funktionsprüfung

In [Funk-/Bus-Diagnose](diagnostics.md) auf folgende Werte achten:

- `gateway`, `port`, `baudrate` und `protocol` stimmen.
- Bei einer Schaltaktion erscheint `send_start` und anschließend `telegram_sent`.
- `effective_sender_ids` zeigt die **tatsächlich gesendete** Adresse.
- Ein erfolgreiches `telegram_sent` bestätigt den USB-Sendevorgang, **nicht** die Reaktion des Aktors.

Für FAM-USB sind Taster-Telegramme (FT55 **Drücken und Loslassen**) und Funkstatus sinnvoll. Für FGW14-USB zusätzlich echte Rückmeldetelegramme vom Busaktor prüfen.

[Telegramme analysieren →](diagnostics.md)
