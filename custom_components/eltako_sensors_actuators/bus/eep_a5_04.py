from __future__ import annotations

from typing import Any
import re

A5_04_02_TEACH_IN = bytes((0x10, 0x10, 0x0D, 0x87))
A5_04_03_TEACH_IN = bytes((0x10, 0x18, 0x0D, 0x80))


def _normalize_eep(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"(?:^|[^0-9A-F])([A-F0-9]{2}-[A-F0-9]{2}-[A-F0-9]{2})(?:$|[^0-9A-F])", text)
    return match.group(1) if match else text


def _require_four_bytes(data: bytes) -> bytes:
    payload = bytes(data)
    if len(payload) != 4:
        raise ValueError(f"A5-04 expects exactly 4 data bytes, got {len(payload)}")
    return payload


def _is_generic_teach_in(payload: bytes) -> bool:
    # In a normal 4BS data telegram the LRN bit (DB0 bit 3) is set.
    return not bool(payload[3] & 0x08)


def _detected_profile(payload: bytes, configured_eep: str) -> str:
    """Detect A5-04-02 versus A5-04-03 without guessing normal values.

    FTFSB can be switched between both profiles. Older EEDTOY exports may still
    contain A5-04-03 while the physical sensor is in its factory-default
    A5-04-02 mode. The two official teach-in telegrams identify the profile
    unambiguously. Data telegrams are also distinguishable in normal operation:
    A5-04-03 uses only DB2 bits 1..0 for the upper two temperature bits, whereas
    A5-04-02 uses all of DB2 for humidity and normally leaves DB3 at zero.
    """
    if payload == A5_04_02_TEACH_IN:
        return "A5-04-02"
    if payload == A5_04_03_TEACH_IN:
        return "A5-04-03"

    db3, db2, _db1, _db0 = payload
    configured = _normalize_eep(configured_eep)

    if configured == "A5-04-03" and db3 == 0 and db2 > 0x03:
        return "A5-04-02"
    if configured == "A5-04-02" and db3 > 0 and (db2 & 0xFC) == 0:
        return "A5-04-03"
    return configured if configured in {"A5-04-01", "A5-04-02", "A5-04-03"} else "A5-04-02"


def decode_a5_04(data: bytes, configured_eep: str) -> dict[str, Any]:
    """Decode A5-04-01/02/03 temperature and humidity telegrams.

    A5-04-03 follows the EEP layout used by FTFSB:
      * DB3: relative humidity, 0..255 -> 0..100 %
      * DB2 bits 1..0 + DB1: 10-bit temperature, 0..1023 -> -20..60 °C
      * DB0 bit 2: event-triggered (1) / heartbeat (0)

    For A5-04-02, DB2 carries humidity and DB1 temperature, both scaled 0..250.
    """
    payload = _require_four_bytes(data)
    db3, db2, db1, db0 = payload
    configured = _normalize_eep(configured_eep)
    detected = _detected_profile(payload, configured)
    teach_in = payload in {A5_04_02_TEACH_IN, A5_04_03_TEACH_IN} or _is_generic_teach_in(payload)

    common: dict[str, Any] = {
        "configured_eep": configured,
        "detected_eep": detected,
        "learn": teach_in,
        "learn_telegram": teach_in,
        "data_telegram": not teach_in,
        "value": payload.hex("-"),
        "data_hex": payload.hex("-"),
    }

    if teach_in:
        common["telegram_type"] = f"temperature_humidity_{detected.lower().replace('-', '_')}_teach_in"
        return common

    if detected == "A5-04-01":
        humidity_raw = max(0, min(250, db2))
        temperature_raw = max(0, min(250, db1))
        common.update(
            {
                "temperature": round(temperature_raw / 250.0 * 40.0, 1),
                "humidity": round(humidity_raw / 250.0 * 100.0, 1),
                "temperature_available": bool(db0 & 0x02),
                "temperature_raw_8bit": temperature_raw,
                "humidity_raw_8bit": humidity_raw,
                "data_layout": "A5-04-01: DB2 humidity / DB1 temperature",
                "telegram_type": "temperature_humidity_a5_04_01",
            }
        )
        return common

    if detected == "A5-04-03":
        humidity_raw = db3
        temperature_raw = db1 | ((db2 & 0x03) << 8)
        event_triggered = bool(db0 & 0x04)
        common.update(
            {
                "temperature": round(-20.0 + (temperature_raw / 1023.0 * 80.0), 1),
                "humidity": round(humidity_raw / 255.0 * 100.0, 1),
                "temperature_raw_10bit": temperature_raw,
                "humidity_raw_8bit": humidity_raw,
                "event_triggered": event_triggered,
                "heartbeat": not event_triggered,
                "data_layout": "A5-04-03: DB3 humidity / DB2.1..0 + DB1 temperature",
                "telegram_type": "temperature_humidity_a5_04_03",
            }
        )
        return common

    # A5-04-02 (also the safe fallback for an unknown A5-04 profile).
    humidity_raw = max(0, min(250, db2))
    temperature_raw = max(0, min(250, db1))
    common.update(
        {
            "temperature": round(-20.0 + (temperature_raw / 250.0 * 80.0), 1),
            "humidity": round(humidity_raw / 250.0 * 100.0, 1),
            "temperature_available": bool(db0 & 0x02),
            "temperature_raw_8bit": temperature_raw,
            "humidity_raw_8bit": humidity_raw,
            "data_layout": "A5-04-02: DB2 humidity / DB1 temperature",
            "telegram_type": "temperature_humidity_a5_04_02",
        }
    )
    return common


def decode_a5_04_02(data: bytes) -> dict[str, Any]:
    return decode_a5_04(data, "A5-04-02")


def decode_a5_04_03(data: bytes) -> dict[str, Any]:
    return decode_a5_04(data, "A5-04-03")
