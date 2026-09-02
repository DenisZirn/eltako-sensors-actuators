from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .bus.eep_a5_04 import decode_a5_04, decode_a5_04_02, decode_a5_04_03
from .bus.eep_a5_09_04 import decode_a5_09_04
from .bus.eep_a5_10_12 import decode_a5_10_12
from .bus.eep_a5_20_04 import decode_a5_20_04_controller_telegram
from .bus.eep_ffg7b import decode_ffg7b_a5, decode_ffg7b_rps


@dataclass(frozen=True, slots=True)
class ParsedValue:
    key: str
    value: Any
    device_class: str | None = None
    unit: str | None = None


def parse_f6_01_01(data: bytes) -> dict[str, Any]:
    if not data:
        raise ValueError("F6-01-01 expects at least one data byte")
    raw = data[0]
    if raw == 0x10:
        return {"raw": raw, "presence": True, "pressed": True}
    if raw == 0x00:
        return {"raw": raw, "presence": False, "pressed": False}
    return {"raw": raw}


def parse_f6_02_01(data: bytes) -> dict[str, Any]:
    if not data:
        raise ValueError("F6-02-01 expects at least one data byte")
    raw = data[0]
    return {
        "raw": raw,
        "pressed": raw != 0,
        "rocker": raw,
    }


def parse_f6_10_00(data: bytes) -> dict[str, Any]:
    if not data:
        raise ValueError("F6-10-00 expects at least one data byte")
    return decode_ffg7b_rps(data[0])


def parse_a5_14_09(data: bytes) -> dict[str, Any]:
    return decode_ffg7b_a5(data)


def parse_d5_00_01(data: bytes) -> dict[str, Any]:
    if not data:
        raise ValueError("D5-00-01 expects at least one data byte")
    raw = data[0]
    if raw == 0x09:
        is_open = False
    elif raw == 0x08:
        is_open = True
    else:
        is_open = not bool(raw & 0x01)
    return {"raw": raw, "open": is_open, "closed": not is_open}


def parse_a5_04_02(data: bytes) -> dict[str, Any]:
    return decode_a5_04_02(bytes(data[:4]))


def parse_a5_04_03(data: bytes) -> dict[str, Any]:
    return decode_a5_04_03(bytes(data[:4]))



def parse_a5_09_04(data: bytes) -> dict[str, Any]:
    return decode_a5_09_04(bytes(data[:4]))


def parse_a5_09_0c(data: bytes) -> dict[str, Any]:
    if len(data) < 4:
        raise ValueError(f"A5-09-0C expects 4 data bytes, got {len(data)}")
    db3, db2, db1, db0 = data[:4]
    concentration_base = (db3 << 8) | db2
    multiplier = 0.01 * (10 ** (db0 & 0x03))
    concentration = round(concentration_base * multiplier, 2)
    result = {
        "air_quality_concentration": concentration,
        "voc_type_index": int(db1),
        "voc_unit": "ppb" if ((db0 & 0x04) >> 2) == 0 else "ug/m3",
        "raw": [db3, db2, db1, db0],
    }
    if db1 == 0:
        result["tvoc"] = concentration
    return result


def parse_a5_10_12(data: bytes) -> dict[str, Any]:
    return decode_a5_10_12(bytes(data[:4]))


def parse_a5_20_04(data: bytes) -> dict[str, Any]:
    return decode_a5_20_04_controller_telegram(bytes(data[:4]))


def parse_a5_20_01(data: bytes) -> dict[str, Any]:
    if len(data) < 4:
        raise ValueError(f"A5-20-01 expects 4 data bytes, got {len(data)}")
    db3, db2, db1, db0 = data[:4]
    valve_position = max(0, min(100, int(db3)))
    temperature = round((db1 / 255.0) * 40.0, 1)
    return {
        "valve_position": valve_position,
        "temperature": temperature,
        "service_on": bool(db2 & 0x80),
        "energy_input_enabled": bool(db2 & 0x40),
        "energy_storage_charged": bool(db2 & 0x20),
        "battery_low": not bool(db2 & 0x10),
        "contact_open": bool(db2 & 0x08),
        "temperature_sensor_failure": bool(db2 & 0x04),
        "window_open": bool(db2 & 0x02),
        "actuator_obstructed": bool(db2 & 0x01),
        "learn": not bool(db0 & 0x08),
        "raw": [db3, db2, db1, db0],
    }


def parse_a5_07_01(data: bytes) -> dict[str, Any]:
    """Parse ELTAKO FBH/FBHT TF mode.

    DB1 encodes the operating mode and movement state:
    0xC8 = half-automatic movement, 0xFF = full-automatic movement,
    0x00 = no movement. DB0 is 0x08 for data telegrams.
    """
    if len(data) < 4:
        raise ValueError(f"A5-07-01 expects 4 data bytes, got {len(data)}")
    db3, db2, db1, db0 = data[:4]
    learn = not bool(db0 & 0x08)
    if db1 == 0xC8:
        movement = True
        mode = "halbautomatisch"
    elif db1 == 0xFF:
        movement = True
        mode = "vollautomatisch"
    elif db1 == 0x00:
        movement = False
        mode = "keine Bewegung"
    else:
        movement = bool(db1)
        mode = f"0x{db1:02X}"
    supply_voltage = round(db3 / 255.0 * 5.1, 2)
    result = {
        "learn": learn,
        "movement": movement,
        "motion": movement,
        "movement_detection_mode": mode,
        "movement_raw": db1,
        "voltage": supply_voltage,
        "battery_voltage": supply_voltage,
        "battery_raw": db3,
        "raw": [db3, db2, db1, db0],
    }
    if learn:
        result.pop("movement", None)
        result.pop("motion", None)
        result.pop("movement_detection_mode", None)
    return result


def parse_a5_08_01(data: bytes) -> dict[str, Any]:
    """Parse ELTAKO FBH mode: voltage, brightness and movement.

    ELTAKO does not define a temperature value in DB1 for this device mode.
    DB1 is therefore intentionally ignored instead of exposing a fictitious
    temperature sensor.
    """
    if len(data) < 4:
        raise ValueError(f"A5-08-01 expects 4 data bytes, got {len(data)}")
    db3, db2, db1, db0 = data[:4]

    learn = not bool(db0 & 0x08)
    voltage = round(db3 / 255.0 * 5.1, 2)
    brightness = round(db2 / 255.0 * 510.0, 1)
    if db0 == 0x0D:
        movement = True
    elif db0 == 0x0F:
        movement = False
    else:
        movement = bool(db0 & 0x02)

    result = {
        "learn": learn,
        "voltage": voltage,
        "brightness": brightness,
        "temperature_candidate": round((db1 / 255.0) * 50.0, 1),
        "temperature_raw": db1,
        "movement": movement,
        "motion": movement,
        "motion_raw": db0,
        "raw": [db3, db2, db1, db0],
    }
    if learn:
        for key in ("voltage", "brightness", "temperature_candidate", "temperature_raw", "movement", "motion"):
            result.pop(key, None)
    return result


def parse_a5_13_01(data: bytes) -> dict[str, Any]:
    if len(data) < 4:
        raise ValueError(f"A5-13-01 expects 4 data bytes, got {len(data)}")
    db3, db2, db1, db0 = data[:4]
    identifier = (db0 & 0xF0) >> 4
    result = {"identifier": identifier, "raw": [db3, db2, db1, db0]}
    if data[:4] == bytes((0x00, 0x00, 0xFF, 0x1A)):
        result.update({"telegram_type": "weather_alarm_placeholder", "ignored": True})
        return result
    if identifier == 0x01:
        dawn = round((db3 / 255.0) * 999.0, 0)
        result.update({
            "dawn_sensor": dawn,
            "temperature": round(-40.0 + (db2 / 255.0 * 120.0), 1),
            "wind_speed": round(((db1 / 255.0) * 70.0) * 3.6, 2),
            "rain": bool((db0 & 0x02) >> 1),
            "rain_indication": bool((db0 & 0x02) >> 1),
        })
    elif identifier == 0x02:
        result.update({
            "sun_west": round((db3 / 255.0) * 150000.0, 0),
            "sun_south": round((db2 / 255.0) * 150000.0, 0),
            "sun_east": round((db1 / 255.0) * 150000.0, 0),
        })
    return result


PARSERS: dict[str, Callable[[bytes], dict[str, Any]]] = {
    "F6-01-01": parse_f6_01_01,
    "F6-02-01": parse_f6_02_01,
    "F6-10-00": parse_f6_10_00,
    "A5-14-09": parse_a5_14_09,
    "D5-00-01": parse_d5_00_01,
    "A5-04-02": parse_a5_04_02,
    "A5-04-03": parse_a5_04_03,
    "A5-09-0C": parse_a5_09_0c,
    "A5-09-04": parse_a5_09_04,
    "A5-20-01": parse_a5_20_01,
    "A5-20-04": parse_a5_20_04,
    "A5-10-12": parse_a5_10_12,
    "A5-07-01": parse_a5_07_01,
    "A5-08-01": parse_a5_08_01,
    "A5-13-01": parse_a5_13_01,
}


def parse_by_eep(eep: str, data: bytes) -> dict[str, Any]:
    parser = PARSERS.get(eep)
    if parser is None:
        return {"raw": list(data), "unsupported_eep": eep}
    return parser(data)
