from __future__ import annotations

"""EEP A5-20-01 helpers for the bidirectional ELTAKO FKS-SV.

The valve initiates each communication cycle. Controller telegrams and valve
status telegrams use the same EEP but different byte meanings, so they must be
encoded and decoded separately. In particular, DB2 is room temperature in the
controller direction and status flags in the valve direction.
"""

from collections.abc import Iterable
from typing import Any

from .esp2 import ESP2Message, build_regular_4bs
from .ids import parse_address

DATA_TELEGRAM = 0x08
SPS_TEMPERATURE = 0x04
SUMMER_MODE = 0x08


def _encode_temp_0_40(value: float | int | None, default: float = 20.0, *, avoid_ff: bool = False) -> int:
    try:
        temp = float(value)
    except (TypeError, ValueError):
        temp = float(default)
    temp = max(0.0, min(40.0, temp))
    encoded = max(0, min(255, int(round(temp / 40.0 * 255.0))))
    if avoid_ff and encoded == 0xFF:
        return 0xFE
    return encoded


def _encode_inverse_room_temperature(value: float | int | None) -> int:
    """Encode the RCU actual room temperature for Direction-2 DB2.

    EEP A5-20-01 defines DB2 inversely: 255..0 represents 0..40 °C.
    Therefore DB2=0x00 represents 40 °C and must not be used as a sentinel for
    "use internal sensor". Callers should provide a valid room temperature.
    """
    if value is None:
        return 0x00
    return 255 - _encode_temp_0_40(value, default=20.0)


def build_a5_20_01_temperature_setpoint(
    sender_id: str,
    *,
    target_temperature: float | int | None,
    room_temperature: float | int | None = None,
    summer_mode: bool = False,
    inverse_setpoint: bool = False,
    status: int = 0x00,
) -> ESP2Message:
    """Build the normal controller-to-valve temperature telegram."""
    db3 = _encode_temp_0_40(target_temperature, default=20.0, avoid_ff=True)
    db2 = _encode_inverse_room_temperature(room_temperature)
    db1 = SPS_TEMPERATURE
    if inverse_setpoint:
        db1 |= 0x02
    if summer_mode:
        db1 |= SUMMER_MODE
    db0 = DATA_TELEGRAM
    return build_regular_4bs(
        parse_address(sender_id),
        bytes((db3, db2, db1, db0)),
        status=status,
        outgoing=True,
    )


def build_a5_20_01_valve_position(
    sender_id: str,
    *,
    valve_position: float | int,
    room_temperature: float | int | None = None,
    summer_mode: bool = False,
    inverse_setpoint: bool = False,
    status: int = 0x00,
) -> ESP2Message:
    """Build the normal controller-to-valve direct-position telegram."""
    try:
        valve = int(round(float(valve_position)))
    except (TypeError, ValueError):
        valve = 0
    valve = max(0, min(100, valve))
    db3 = valve
    db2 = _encode_inverse_room_temperature(room_temperature)
    db1 = 0x00
    if inverse_setpoint:
        db1 |= 0x02
    if summer_mode:
        db1 |= SUMMER_MODE
    db0 = DATA_TELEGRAM
    return build_regular_4bs(
        parse_address(sender_id),
        bytes((db3, db2, db1, db0)),
        status=status,
        outgoing=True,
    )


def build_a5_20_01_teach_in_response(
    sender_id: str,
    query_data: bytes | bytearray | Iterable[int],
    *,
    status: int = 0x00,
) -> ESP2Message:
    """Build the bidirectional 4BS Variation-3 teach-in response.

    DB3..DB1 are copied from the received FKS-SV teach-in query. DB0 marks the
    EEP as supported, confirms that the sender ID was stored and identifies the
    telegram as the teach-in response. The LRN bit remains cleared.
    """
    raw = bytes(query_data)
    if len(raw) != 4:
        raise ValueError(f"A5-20-01 teach-in query must contain 4 bytes, got {len(raw)}")
    if raw[3] & DATA_TELEGRAM:
        raise ValueError("A5-20-01 teach-in response requested for a data telegram")
    if raw[3] & 0x10:
        raise ValueError("A5-20-01 telegram is already a teach-in response")

    response_db0 = (raw[3] & 0x80) | 0x70
    return build_regular_4bs(
        parse_address(sender_id),
        bytes((raw[0], raw[1], raw[2], response_db0)),
        status=status,
        outgoing=True,
    )


def decode_a5_20_01_actuator_status(data: bytes | bytearray | Iterable[int]) -> dict[str, Any]:
    """Decode FKS-SV -> controller telegrams only."""
    raw = bytes(data)
    if len(raw) != 4:
        raise ValueError(f"A5-20-01 status must contain 4 bytes, got {len(raw)}")
    db3, db2, db1, db0 = raw
    learn = not bool(db0 & DATA_TELEGRAM)

    result: dict[str, Any] = {
        "value": raw.hex("-"),
        "learn": learn,
        "learn_telegram": learn,
        "data_telegram": not learn,
        "learn_type_with_eep": bool(db0 & 0x80),
        "learn_response": bool(db0 & 0x10),
        "learn_query": learn and not bool(db0 & 0x10),
        "direction": "from_actuator",
        "telegram_type": "fks_sv_teach_in" if learn else "fks_sv_status",
    }
    if learn:
        result["teach_in_query_data"] = raw
        return result

    contact_open = bool(db2 & 0x08)
    temperature_sensor_failure = bool(db2 & 0x04)
    result.update(
        {
            "valve_position": max(0, min(100, int(db3))),
            "temperature": None if temperature_sensor_failure else round((db1 / 255.0) * 40.0, 1),
            "service_on": bool(db2 & 0x80),
            "service_mode": bool(db2 & 0x80),
            "energy_input_enabled": bool(db2 & 0x40),
            "energy_input": bool(db2 & 0x40),
            "energy_storage_charged": bool(db2 & 0x20),
            "energy_storage_capacity_sufficient": bool(db2 & 0x10),
            "battery_low": not bool(db2 & 0x10),
            "contact_open": contact_open,
            "safety_temperature_set": contact_open,
            "temperature_sensor_failure": temperature_sensor_failure,
            "window_open": bool(db2 & 0x02),
            "actuator_obstructed": bool(db2 & 0x01),
        }
    )
    return result


def decode_a5_20_01_controller_telegram(data: bytes | bytearray | Iterable[int]) -> dict[str, Any]:
    """Decode controller -> FKS-SV telegrams and TX echoes safely.

    This decoder deliberately never emits actuator_obstructed or other valve
    status keys. Therefore the room-temperature byte in DB2 cannot appear as a
    false problem alarm when the gateway mirrors an outgoing frame.
    """
    raw = bytes(data)
    if len(raw) != 4:
        raise ValueError(f"A5-20-01 controller telegram must contain 4 bytes, got {len(raw)}")
    db3, db2, db1, db0 = raw
    learn = not bool(db0 & DATA_TELEGRAM)
    temperature_mode = bool(db1 & SPS_TEMPERATURE)

    result: dict[str, Any] = {
        "value": raw.hex("-"),
        "learn": learn,
        "learn_telegram": learn,
        "data_telegram": not learn,
        "direction": "to_actuator",
        "tx_echo": True,
        "telegram_type": "fks_sv_controller_teach_in" if learn else "fks_sv_controller",
    }
    if learn:
        result.update(
            {
                "eep_supported": bool(db0 & 0x40),
                "sender_id_stored": bool(db0 & 0x20),
                "learn_response": bool(db0 & 0x10),
            }
        )
        return result

    result.update(
        {
            "temperature_control": temperature_mode,
            "summer_mode": bool(db1 & SUMMER_MODE),
            "room_temperature_command": None
            if db2 == 0x00
            else round(((255 - db2) / 255.0) * 40.0, 1),
        }
    )
    if temperature_mode:
        result["target_temperature_command"] = round((db3 / 255.0) * 40.0, 1)
    else:
        result["valve_position_command"] = max(0, min(100, int(db3)))
    return result
