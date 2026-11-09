"""ELTAKO-specific interpretations for shared EnOcean EEPs.

Keep these decoders device-scoped. A5-06-01 and F6-02-01 are shared with
other products whose telegrams have different meanings.
"""
from __future__ import annotations

import re
from typing import Any


def _device_text(device: dict[str, Any]) -> str:
    if not isinstance(device, dict):
        return ""
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    fields = ("device_type", "profile_key", "model", "device_family", "eltako", "name")
    return " ".join(
        str(value or "").upper()
        for source in (device, raw)
        for key in fields
        if (value := source.get(key)) not in (None, "")
    )


def is_eltako_illuminance_device(device: dict[str, Any]) -> bool:
    """Return True for ELTAKO FAH/FHD60SB illuminance rows on A5-06-01.

    Current EEDTOY exports a stable technical ``device_type`` (for example
    ``FAH``). That field is authoritative and must not depend on the visible
    Home Assistant name. Older YAMLs may not contain ``device_type``; for
    those, an explicit ``device_class: illuminance`` or a legacy model/name
    signature is accepted as a narrow compatibility fallback.
    """
    if not isinstance(device, dict):
        return False
    if not str(device.get("eep") or "").upper().startswith("A5-06-01"):
        return False

    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    technical_type = str(
        device.get("device_type") or raw.get("device_type") or ""
    ).strip().upper()
    supported_type = re.compile(
        r"^(?:FAH[A-Z0-9_-]*|FIH65S|FHD60SB)$"
    )

    # EEDTOY 1.1.01+ path: device_type is the primary technical identity.
    if technical_type:
        return bool(supported_type.fullmatch(technical_type))

    # Legacy EEDTOY/import path: only accept the explicit HA illuminance class
    # when no technical device_type is available.
    device_class = str(
        device.get("device_class") or raw.get("device_class") or ""
    ).strip().lower()
    if device_class == "illuminance":
        return True

    text = _device_text(device)
    return bool(
        re.search(
            r"(?<![A-Z0-9])(?:FAH[A-Z0-9_-]*|FIH65S|FHD60SB)(?![A-Z0-9])",
            text,
        )
    )


def is_legacy_frw_device(device: dict[str, Any]) -> bool:
    """Legacy FRW uses a rocker-shaped RPS envelope but is not a rocker."""
    if not isinstance(device, dict):
        return False
    if not str(device.get("eep") or "").upper().startswith("F6-02-01"):
        return False
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    identity = _device_text(device)
    # FRWB is a different, 4BS smoke detector and must remain on A5-30-03.
    if "FRWB" in identity:
        return False
    if re.search(r"(?<![A-Z0-9])FRW(?![A-Z0-9])", identity):
        return True
    # A deliberate smoke device_class is an unambiguous opt-in for old YAML
    # that has no technical model identity (e.g., name "In Garage").
    return str(device.get("device_class") or raw.get("device_class") or "").strip().lower() == "smoke"


def decode_eltako_a5_06_01(data: bytes) -> dict[str, Any]:
    """Return brightness in lux, or diagnostics only for teach-in/invalid data.

    ELTAKO FAH/FHD60SB:
      DB2 == 0: DB3 is 0..100 lx;
      DB2 > 0:  DB2 linearly encodes 300..30000 lx at 0..255.
    Model-specific checks happen in the receiver before calling this.
    """
    if len(data) < 4:
        return {}
    db3, db2, _db1, db0 = data[:4]
    if not db0 & 0x08:
        return {"learn": True, "learn_telegram": True, "data_telegram": False,
                "telegram_type": "eltako_illuminance_teach_in"}
    if db0 not in (0x09, 0x0F):
        return {"ignored": True, "telegram_type": "eltako_illuminance_unknown"}
    if db2 == 0:
        if db3 > 100:
            return {"ignored": True, "telegram_type": "eltako_illuminance_invalid_low_range"}
        lux = db3
        range_label = "0..100 lx (DB3)"
    else:
        lux = round(300 + (db2 / 255.0) * (30000 - 300))
        range_label = "300..30000 lx (DB2)"
    return {
        "brightness": int(lux),
        "brightness_raw_db3": db3,
        "brightness_raw_db2": db2,
        "brightness_range": range_label,
        "learn": False,
        "learn_telegram": False,
        "data_telegram": True,
        "telegram_type": "eltako_illuminance",
    }


def decode_legacy_frw_rps(code: int) -> dict[str, Any]:
    """Decode legacy FRW alarm-end, alarm and low-battery RPS events.

    F6-02-01 button semantics for legacy FRW:
      0x10 = left bottom pressed (smoke alarm)
      0x30 = left top pressed (battery low)
      0x00 = released / OK (both smoke and battery alarms cleared)

    Battery warning events do not override an existing smoke alarm;
    only the common release value 0x00 clears both statuses.
    """
    raw = int(code)
    if raw == 0x00:
        return {"frw_status": "Frei", "smoke_alarm": False,
                "battery_low": False,
                "frw_raw_code": raw, "telegram_type": "frw_alarm_end_battery_ok"}
    if raw == 0x10:
        return {"frw_status": "Rauchalarm", "smoke_alarm": True,
                "frw_raw_code": raw, "telegram_type": "frw_smoke_alarm"}
    if raw == 0x30:
        return {"battery_low": True, "frw_raw_code": raw,
                "telegram_type": "frw_low_battery"}
    return {"frw_raw_code": raw, "ignored": True,
            "telegram_type": "frw_unknown"}


def is_fws81_device(device: dict[str, Any]) -> bool:
    """Return True only for ELTAKO FWS81 water sensors on F6-05-01."""
    if not isinstance(device, dict):
        return False
    if not str(device.get("eep") or "").upper().startswith("F6-05-01"):
        return False
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    technical_type = str(
        device.get("device_type") or raw.get("device_type") or ""
    ).strip().upper()
    if technical_type:
        return technical_type == "FWS81"
    device_class = str(
        device.get("device_class") or raw.get("device_class") or ""
    ).strip().lower()
    return device_class == "moisture"


def decode_fws81_rps(data_byte: int, status: int) -> dict[str, Any]:
    """Decode ELTAKO FWS81 water-state telegrams.

    Confirmed FWS81 mapping:
      data 0x11 + status 0x30 -> water detected
      data 0x11 + status 0x20 -> no water
    """
    data = int(data_byte) & 0xFF
    stat = int(status) & 0xFF
    result = {
        "fws81_data": data,
        "fws81_status": stat,
        "telegram_type": "fws81_water",
    }
    if data != 0x11:
        result["ignored"] = True
        return result
    if stat == 0x30:
        result["water"] = True
        return result
    if stat == 0x20:
        result["water"] = False
        return result
    result["ignored"] = True
    return result
