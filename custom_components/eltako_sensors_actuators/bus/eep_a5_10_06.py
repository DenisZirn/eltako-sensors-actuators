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


def is_fhk61_230v_temperature_profile(device: dict) -> bool:
    """Identify the FHK61-230V thermostat, excluding U/SSR variants."""
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    model = str(device.get("device_type") or raw.get("device_type") or "").strip().upper().replace(" ", "")
    return (
        model.startswith("FHK61-230V")
        and str(device.get("platform") or "").lower() == "climate"
        and str(device.get("eep") or "").upper() == "A5-10-06"
    )


def _fhk61_setpoint_byte(value: float | int | None) -> int:
    """MiniSafe observed: 10 C -> 0x40, 30 C -> 0xBF.

    This uses nearest-integer scaling and is intentionally specific to the
    decentralized FHK61-230V. Existing FHK14/F4HK14 controllers continue to
    use the eltako14bus-compatible truncation in _temp_to_byte.
    """
    try:
        temperature = float(value) if value is not None else 20.0
    except (TypeError, ValueError):
        temperature = 20.0
    temperature = max(0.0, min(40.0, temperature))
    return max(0, min(255, round(temperature / 40.0 * 255.0)))


def encode_a5_10_06_room_control_data(
    *,
    target_temperature: float | int | None = None,
    current_temperature: float | int | None = None,
    hvac_mode: str | None = "heat",
    priority: str | int | None = None,
    controller_profile: str | None = None,
) -> bytes:
    """Encode A5-10-06 without conflating 61-series and 14-series protocols.

    The FHK61-230V MiniSafe trace uses DB3=0x00 for its A5-10-06
    temperature/setpoint profile, with DB0=0x0E. Operating-mode selection
    is a separate learned RPS telegram. Other actuators keep their
    established mode-byte encoding.
    """
    fhk61 = controller_profile == "fhk61_230v"
    target_byte = (
        _fhk61_setpoint_byte(target_temperature)
        if fhk61 else _temp_to_byte(target_temperature, default=20.0)
    )
    effective_current = 40.0 if current_temperature is None else current_temperature
    current_byte = _current_temp_to_byte(effective_current)
    return bytes([
        0x00 if fhk61 else _mode_byte(hvac_mode),
        target_byte,
        current_byte,
        _priority_byte(priority),
    ])

def build_a5_10_06_room_control(
    sender_id: str,
    *,
    target_temperature: float | int | None = None,
    current_temperature: float | int | None = None,
    hvac_mode: str | None = "heat",
    priority: str | int | None = None,
    controller_profile: str | None = None,
) -> ESP2Message:
    """Build an ELTAKO A5-10-06 software-controller telegram.

    Byte order is DB3 mode, DB2 target, DB1 current temperature (inverted),
    DB0 controller priority.  The established Home Assistant/eltako14bus path
    sends 40 C as the controller's current temperature, resulting in DB1=0x00;
    the physical room sensor learned in function group 1 remains authoritative.
    """
    address = parse_address(sender_id)
    data = encode_a5_10_06_room_control_data(
        target_temperature=target_temperature,
        current_temperature=current_temperature,
        hvac_mode=hvac_mode,
        priority=priority,
        controller_profile=controller_profile,
    )
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
