from __future__ import annotations

from .esp2 import ESP2Message, build_regular_4bs, build_rps
from .ids import parse_address


def _temp_to_byte(value: float | int | None, default: float = 20.0) -> int:
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        temperature = default
    temperature = max(0.0, min(40.0, temperature))
    # Match eltako14bus A5_10_06.encode_message exactly. The reference
    # implementation truncates the scaled value instead of rounding it.
    return max(0, min(255, int(temperature / 40.0 * 255.0)))


def _mode_byte(hvac_mode: str | None) -> int:
    """Return DB3 for an A5-10-06 heating/cooling controller command.

    These values are the ELTAKO/eltako14bus ``HeaterMode`` values.  DB3=0x00
    is not the normal heating command; it is used for unknown/special cases.
    """
    mode = str(hvac_mode or "heat").strip().lower()
    if mode in {"off", "aus", "false", "0"} or mode.endswith(".off"):
        return 0x10
    if mode in {"night", "nacht", "night_setback"}:
        return 0x50
    if mode in {"standby", "setback", "absenkung"}:
        return 0x30
    return 0x70


def _current_temp_to_byte(value: float | int | None, default: float = 40.0) -> int:
    """Encode reversed DB1 with the same expression as eltako14bus."""
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        temperature = default
    temperature = max(0.0, min(40.0, temperature))
    return max(0, min(255, int((40.0 - temperature) / 40.0 * 255.0)))


def _priority_byte(priority: str | int | None) -> int:
    """Return DB0 for an A5-10-06 controller command.

    0x0E is AUTO/no-priority, 0x08 gives the software controller priority and
    0x0A limits a learned thermostat to +/-3 K.  0x0F is deliberately rejected
    here because it marks an actuator response, not a controller command.
    """
    if isinstance(priority, int):
        value = priority & 0xFF
        return value if value in {0x08, 0x0A, 0x0E} else 0x0E
    text = str(priority or "auto").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"0x08", "8", "home_automation", "home_assistant", "software", "ha"}:
        return 0x08
    if text in {"0x0a", "10", "limit", "limited", "begrenzt"}:
        return 0x0A
    return 0x0E


def build_a5_10_06_room_control(
    sender_id: str,
    *,
    target_temperature: float | int | None = None,
    current_temperature: float | int | None = None,
    hvac_mode: str | None = "heat",
    priority: str | int | None = None,
) -> ESP2Message:
    """Build an ELTAKO A5-10-06 software-controller telegram.

    Byte order is DB3 mode, DB2 target, DB1 current temperature (inverted),
    DB0 controller priority.  The established Home Assistant/eltako14bus path
    sends 40 C as the controller's current temperature, resulting in DB1=0x00;
    the physical room sensor learned in function group 1 remains authoritative.
    """
    address = parse_address(sender_id)
    target_byte = _temp_to_byte(target_temperature, default=20.0)
    if current_temperature is None:
        current_temperature = 40.0
    current_byte = _current_temp_to_byte(current_temperature)
    data = bytes([
        _mode_byte(hvac_mode),
        target_byte,
        current_byte,
        _priority_byte(priority),
    ])
    return build_regular_4bs(address, data, status=0x80, outgoing=True)


def build_fhk_mode_command(sender_id: str, mode: str | None) -> ESP2Message:
    """Build the RPS operating-mode command used by FHK/FHK14 actuators.

    Grimm's Home Assistant integration changes the actuator operating mode
    with an outgoing RPS telegram, not with A5-10-06.
    """
    return build_rps(
        parse_address(sender_id),
        _mode_byte(mode),
        status=0x30,
        outgoing=True,
    )
