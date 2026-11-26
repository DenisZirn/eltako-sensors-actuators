"""Device-specific EnOcean RX interpretation for ELTAKO FTR room thermostats.

The generic A5-10-06 heating actuator/controller profile contains an HVAC
mode byte. ELTAKO FTR room thermostats reuse the EEP but do not transmit that
HVAC state. FTR65HS instead transmits a night-setback amount in DB3.

References: ELTAKO sensor telegrams; FTR78S A5-10-03 data sheet.
"""
from __future__ import annotations

import re
from typing import Any

# Accept the FTR55, FTR65, FTRF65, FTR78, FTR86 and legacy FTR595 families.
# Match an actual model token, not an incidental substring in a display name.
_FTR_MODEL = re.compile(r"(?<![A-Z0-9])(FTRF?\d{2,3}[A-Z]{1,5})(?=$|[^A-Z0-9])")
_NIGHT_SETBACK_K = {0x00: 0, 0x06: 1, 0x0C: 2, 0x13: 3, 0x19: 4, 0x1F: 5}
_FTR_TEACH_IN = {
    "A5-10-06": bytes.fromhex("40300D87"),
    "A5-10-03": bytes.fromhex("40182D80"),
}


def ftr_model(device: Any) -> str | None:
    """Identify an FTR model from EEDTOY YAML, including older name-only rows."""
    if not isinstance(device, dict):
        return None
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    for value in (
        device.get("device_type"), raw.get("device_type"),
        device.get("model"), raw.get("model"),
        device.get("name"), raw.get("name"),
    ):
        match = _FTR_MODEL.search(str(value or "").upper())
        if match:
            return match.group(1)
    return None


def is_ftr_temperature_device(device: Any) -> bool:
    """Only FTR sensor entries in their temperature-telegram profile."""
    return bool(
        isinstance(device, dict)
        and str(device.get("platform") or "").strip().lower() == "sensor"
        and str(device.get("eep") or "").strip().upper()[:8]
        in _FTR_TEACH_IN
        and ftr_model(device)
    )


def ftr_has_night_setback(device: Any) -> bool:
    """Only FTR65HS has the ELTAKO DB3 night-setback extension."""
    return is_ftr_temperature_device(device) and ftr_model(device) == "FTR65HS"


def normalize_ftr_4bs(
    device: dict[str, Any], data: bytes, decoded: dict[str, Any]
) -> dict[str, Any]:
    """Strip synthetic HVAC and decode only documented FTR sensor fields.

    FTR sensor DB0 equals 0x0F on normal data frames, not because it is
    an actuator acknowledgement. Incoming decoded dictionaries are not changed.
    """
    if not is_ftr_temperature_device(device) or len(data) != 4:
        return decoded
    eep = str(device.get("eep") or "").strip().upper()[:8]
    result = dict(decoded)
    for key in (
        "temperature", "target_temperature", "hvac_mode", "heater_mode",
        "heater_mode_code", "heating_mode", "heating_mode_label",
        "controller_priority", "controller_priority_code", "actuator_response",
        "frost_protection", "setpoint_in_adjustable_range", "night_setback_k",
    ):
        result.pop(key, None)

    result["telegram_type"] = "ftr_temperature"
    result["ftr_model"] = ftr_model(device)
    result["value"] = data.hex("-")
    if data == _FTR_TEACH_IN[eep]:
        result["learn"] = True
        result["learn_telegram"] = True
        result["data_telegram"] = False
        result["telegram_type"] = "ftr_temperature_teach_in"
        return result

    db3, db2, db1, db0 = data
    if eep == "A5-10-06" and db0 != 0x0F:
        # No documented FTR sensor data: keep raw diagnostic bytes only.
        result["telegram_type"] = "ftr_unknown_4bs"
        return result

    result["temperature"] = round((255 - db1) * 40.0 / 255.0, 1)
    if eep == "A5-10-03":
        result["target_temperature"] = round(8.0 + db2 * 22.0 / 255.0, 1)
    else:
        result["target_temperature"] = round(db2 * 40.0 / 255.0, 1)

    if ftr_has_night_setback(device) and db3 in _NIGHT_SETBACK_K:
        result["night_setback_k"] = _NIGHT_SETBACK_K[db3]

    return result
