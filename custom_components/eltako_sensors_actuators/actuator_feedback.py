from __future__ import annotations

"""Normalize actuator status telegrams for Home Assistant entities."""

from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip().upper()


def _device_eep(device: dict[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return _text(device.get("eep") or raw.get("eep"))


def _address(value: Any) -> str:
    """Normalize an EnOcean address independent of separators."""
    return "".join(ch for ch in str(value or "").upper() if ch in "0123456789ABCDEF")


def _physical_sender(decoded: dict[str, Any], logical_sender_id: Any) -> str:
    return _address(decoded.get("physical_sender_id") or logical_sender_id)


def telegram_matches_device(
    device: dict[str, Any], decoded: dict[str, Any], logical_sender_id: Any
) -> bool:
    """Return whether a telegram belongs to the configured physical device.

    The gateway may already translate a bus address into the logical device ID.
    Therefore both the logical dispatch address and the original physical sender
    are accepted. The configured controller sender ID is deliberately excluded.
    """
    device_id = _address(device.get("id"))
    if not device_id:
        return False
    return device_id in {
        _address(logical_sender_id),
        _physical_sender(decoded, logical_sender_id),
    }


def _data_bytes(decoded: dict[str, Any]) -> tuple[int, int, int, int] | None:
    """Return the four 4BS payload bytes from all decoder variants.

    Depending on the transport/decoder path, the payload can be exposed as
    ``data_hex``, ``value``, raw bytes, or a list of integers. Cover feedback
    must not depend on one representation because a missed STOP telegram leaves
    the time-based Home Assistant position simulation running.
    """
    value = decoded.get("data_hex")
    if value is None:
        value = decoded.get("value")

    if isinstance(value, (bytes, bytearray)):
        values = list(value)
    elif isinstance(value, (list, tuple)):
        try:
            values = [int(part) & 0xFF for part in value]
        except (TypeError, ValueError):
            return None
    elif isinstance(value, str):
        compact = value.strip().replace(":", "-").replace(" ", "-")
        parts = [part for part in compact.split("-") if part]
        if len(parts) == 1 and len(parts[0]) >= 8:
            raw = parts[0][:8]
            parts = [raw[index:index + 2] for index in range(0, 8, 2)]
        try:
            values = [int(part, 16) for part in parts]
        except ValueError:
            return None
    else:
        return None

    if len(values) < 4:
        return None
    return tuple(values[:4])  # type: ignore[return-value]


def decode_actuator_feedback(
    device: dict[str, Any], decoded: dict[str, Any], logical_sender_id: Any
) -> dict[str, Any] | None:
    """Return normalized feedback or ``None`` for unrelated telegrams."""
    if not telegram_matches_device(device, decoded, logical_sender_id):
        return None

    result = dict(decoded)
    eep = _device_eep(device)
    org = _text(result.get("org"))
    data = _data_bytes(result)

    # FSB61/FJ62 wireless cover feedback observed in field captures:
    # RPS 0x01/0x02 starts movement. A following 4BS telegram with DB3=0x00,
    # DB0=0x0A and DB1=0x01/0x02 is emitted when the actuator stops; DB1 only
    # records the direction of the completed run. It must not be interpreted as
    # an active movement direction.
    platform = _text(device.get("platform"))

    # Wireless FSB61/FJ62 cover actuators emit an RPS 0x01/0x02 pulse from
    # their physical address when a new external run begins.
    if platform == "COVER" and org in {"0X05", "0XF6", "RPS"}:
        action = result.get("button_action", result.get("value"))
        try:
            action_value = int(action)
        except (TypeError, ValueError):
            action_value = -1
        if action_value in {0x01, 0x02}:
            result.update(
                {
                    "cover_pulse": action_value,
                    "pulse_direction": "opening" if action_value == 0x01 else "closing",
                    "feedback_source": "physical_actuator",
                }
            )
            return result

    if platform == "COVER" and data:
        db3, db2, db1, db0 = data
        if db3 == 0x00 and db0 == 0x0A and db1 in {0x00, 0x01, 0x02}:
            result.update(
                {
                    "motion": "stopped",
                    "opening": False,
                    "closing": False,
                    "stopped": True,
                    "last_motion": {0x01: "opening", 0x02: "closing"}.get(db1),
                    "cover_runtime_status": db2,
                    "feedback_source": "physical_actuator",
                }
            )
            return result

    # Decentral ELTAKO switch/light actuators (for example FSR61 and FL62) emit their confirmed state from the physical actuator address as
    # RPS 0x70 = ON and 0x50 = OFF. Restrict this interpretation to switch and
    # light entities so ordinary button/sensor telegrams are never converted
    # into actuator state.
    if platform in {"SWITCH", "LIGHT"} and org in {"0X05", "0XF6", "RPS"}:
        action = result.get("button_action", result.get("value"))
        try:
            action_value = int(action)
        except (TypeError, ValueError):
            action_value = -1
        if action_value in {0x70, 0x50}:
            state = action_value == 0x70
            result.update(
                {
                    "state": state,
                    "on": state,
                    "actuator_state": "on" if state else "off",
                    "feedback_source": "physical_actuator",
                }
            )
            return result

    # The same decentral actuator families also emit a 4BS confirmation:
    # DB1 0x01 = ON, DB1 0x02 = OFF, normally with DB0 0x0A. Accept this
    # independently of the configured command EEP because sender and feedback
    # telegram profiles differ on these devices.
    if platform in {"SWITCH", "LIGHT"} and data:
        db3, _db2, db1, db0 = data
        if db3 == 0x00 and (db0 & 0x08) and db1 in {0x01, 0x02}:
            state = db1 == 0x01
            result.update(
                {
                    "state": state,
                    "on": state,
                    "actuator_state": "on" if state else "off",
                    "feedback_source": "physical_actuator",
                }
            )
            return result

    # FSR/FUD 4BS decoding is already provided by the EEP decoder. Preserve
    # absolute dim values where available and expose one normalized state model.
    if eep in {"M5-38-08", "A5-38-08"}:
        if "brightness" in result or "state" in result or "on" in result:
            if "state" not in result and "on" in result:
                result["state"] = bool(result["on"])
            if "on" not in result and "state" in result:
                result["on"] = bool(result["state"])
            result["feedback_source"] = "physical_actuator"
            return result

    # Other actuator families continue to use fields from their existing EEP
    # decoder, but only after physical-device routing has succeeded.
    if any(
        key in result
        for key in ("state", "on", "brightness", "position", "closed", "rgbw_color")
    ):
        result["feedback_source"] = "physical_actuator"
        return result

    return None
