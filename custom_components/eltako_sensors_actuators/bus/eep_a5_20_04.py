from __future__ import annotations

"""EEP A5-20-04 helpers for ELTAKO FKS-H / FKS-B radiator valves.

A5-20-04 is bidirectional. The battery-powered valve initiates communication
and opens a short receive window. Controller replies therefore have different
byte meanings from valve status telegrams and are encoded/decoded separately.
"""

from collections.abc import Iterable
from typing import Any

from .esp2 import ESP2Message, build_regular_4bs
from .ids import parse_address

DATA_TELEGRAM_BIT = 0x08


def _encode_temp_10_30(value: float | int | None, default: float = 20.0) -> int:
    try:
        temp = float(value)
    except (TypeError, ValueError):
        temp = float(default)
    temp = max(10.0, min(30.0, temp))
    return max(0, min(255, int(round((temp - 10.0) / 20.0 * 255.0))))


def _decode_temp_10_30(raw: int) -> float:
    return round(10.0 + (int(raw) / 255.0) * 20.0, 1)


def build_a5_20_04_control_response(
    sender_id: str,
    *,
    target_temperature: float | int | None,
    status: int = 0x80,
) -> ESP2Message:
    """Build the FKS-B Modus-02 controller reply observed from MiniSafe2.

    Successful live reference after teach-in:
        controller -> FKS-B: 00-8C-89-08 for a 21.0 C setpoint

    In Modus 02 the valve regulates autonomously. The controller therefore
    supplies only the target temperature in DB2. DB3/DB1/DB0 are kept at the
    values observed from the successful MiniSafe2 operating telegram instead
    of inventing a valve-position control algorithm.
    """
    db3 = 0x00
    db2 = _encode_temp_10_30(target_temperature)
    db1 = 0x89
    db0 = DATA_TELEGRAM_BIT

    return build_regular_4bs(
        parse_address(sender_id),
        bytes((db3, db2, db1, db0)),
        status=status,
        outgoing=True,
    )



def build_a5_20_04_teach_in_response(
    sender_id: str,
    query_data: bytes | bytearray | Iterable[int],
    *,
    status: int = 0x80,
) -> ESP2Message:
    """Build the FKS-H/FKS-B A5-20-04 4BS teach-in response.

    The FKS-B teach-in query observed on the device is 80-20-34-80.  A
    successful MiniSafe2 teach-in was captured with the controller response
    80-27-FF-F0, status 0x80.  80-27-FF encodes A5-20-04 with the generic
    manufacturer value 0x7FF; DB0=0xF0 marks the successful variation-3
    learn response.  The sender address remains the configured controller ID.
    """
    raw = bytes(query_data)
    if len(raw) != 4:
        raise ValueError(f"A5-20-04 teach-in query must contain 4 bytes, got {len(raw)}")
    if raw[3] & DATA_TELEGRAM_BIT:
        raise ValueError("A5-20-04 teach-in response requested for a data telegram")
    if raw[3] & 0x10:
        raise ValueError("A5-20-04 telegram is already a teach-in response")

    return build_regular_4bs(
        parse_address(sender_id),
        bytes((0x80, 0x27, 0xFF, 0xF0)),
        status=status,
        outgoing=True,
    )

def decode_a5_20_04_actuator_status(data: bytes | bytearray | Iterable[int]) -> dict[str, Any]:
    """Decode FKS-H/FKS-B -> controller telegrams (A5-20-04 direction 1)."""
    raw = bytes(data)
    if len(raw) != 4:
        raise ValueError(f"A5-20-04 expects 4 data bytes, got {len(raw)}")
    db3, db2, db1, db0 = raw
    learn = not bool(db0 & DATA_TELEGRAM_BIT)
    result: dict[str, Any] = {
        "value": raw.hex("-"),
        "learn": learn,
        "learn_telegram": learn,
        "data_telegram": not learn,
        "direction": "from_actuator",
        "telegram_type": "fks_hora_teach_in" if learn else "fks_hora_status",
    }
    if learn:
        result["teach_in_query_data"] = raw
        return result

    failure = bool(db0 & 0x01)
    temp_selection_setpoint = bool(db0 & 0x02)
    result.update(
        {
            "valve_position": max(0, min(100, int(db3))),
            "measurement_active": not bool(db0 & 0x80),
            "status_requested": bool(db0 & 0x40),
            "button_locked": bool(db0 & 0x04),
            "failure": failure,
        }
    )
    if temp_selection_setpoint:
        result["local_target_temperature"] = _decode_temp_10_30(db2)
        result["target_temperature"] = result["local_target_temperature"]
    else:
        result["feed_temperature"] = round(20.0 + (db2 / 255.0) * 60.0, 1)

    if failure:
        result["failure_code"] = int(db1)
        result["battery_low"] = int(db1) == 18
        result["actuator_obstructed"] = int(db1) in {33, 36, 40}
    else:
        result["temperature"] = _decode_temp_10_30(db1)
        result["room_temperature"] = result["temperature"]
    return result


def decode_a5_20_04_controller_telegram(data: bytes | bytearray | Iterable[int]) -> dict[str, Any]:
    """Decode controller -> FKS-H/FKS-B telegrams and TX echoes safely."""
    raw = bytes(data)
    if len(raw) != 4:
        raise ValueError(f"A5-20-04 expects 4 data bytes, got {len(raw)}")
    db3, db2, db1, db0 = raw
    learn = not bool(db0 & DATA_TELEGRAM_BIT)
    result: dict[str, Any] = {
        "value": raw.hex("-"),
        "learn": learn,
        "learn_telegram": learn,
        "data_telegram": not learn,
        "direction": "to_actuator",
        "tx_echo": True,
        "futh55ed_response": not learn,
        "telegram_type": "futh55ed_fks_hora_teach_in" if learn else "futh55ed_fks_hora_response",
    }
    if learn:
        result["teach_in_query_data"] = raw
        return result

    result.update(
        {
            "valve_position_command": max(0, min(100, int(db3))),
            "target_temperature_command": _decode_temp_10_30(db2),
            "measurement_control_enabled": not bool(db1 & 0x40),
            "wake_up_cycle_code": int(db1 & 0x3F),
            "display_orientation": int((db0 >> 4) & 0x03),
            "button_lock_command": bool(db0 & 0x04),
            "service_command": int(db0 & 0x03),
            "control_raw": int(db1),
            "status_raw": int(db0),
        }
    )
    return result
