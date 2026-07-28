from __future__ import annotations

from typing import Any


def _normalize_eep(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_address(value: Any) -> str:
    return str(value or "").strip().upper()


def telegram_is_from_physical_device(
    device: dict[str, Any], decoded: dict[str, Any], logical_sender_id: Any = None
) -> bool:
    """Return True only for telegrams emitted by the physical actuator ID.

    This mirrors Grimm's listen_to_addresses/dev_id model. The controller
    sender ID is used for commands and must not be accepted as actuator
    feedback, otherwise a transmitted command echo can be mistaken for a real
    device status telegram.
    """
    device_id = _normalize_address(device.get("id"))
    physical_sender = _normalize_address(decoded.get("physical_sender_id"))
    logical_sender = _normalize_address(logical_sender_id)

    if not device_id:
        return False
    if physical_sender:
        return physical_sender == device_id
    return logical_sender == device_id


def normalize_actuator_feedback(
    device: dict[str, Any], decoded: dict[str, Any]
) -> dict[str, Any]:
    """Normalize feedback received from the physical actuator address.

    Incoming telegrams are interpreted according to the physical device EEP.
    The controller/sender EEP is relevant only for transmitting commands.
    """
    result = dict(decoded)
    org = str(result.get("org") or "").upper()
    device_eep = _normalize_eep(device.get("eep"))
    platform = str(device.get("platform") or "").strip().lower()

    if platform not in {"switch", "light", "cover"}:
        return result

    # FSR switching feedback (M5-38-08) can arrive as an RPS telegram from the
    # physical actuator ID. 0x70 represents ON and 0x50 represents OFF in this
    # actuator status stream. The routing guard above prevents ordinary rocker
    # telegrams or controller echoes from being treated as actuator feedback.
    if device_eep == "M5-38-08" and org == "0XF6":
        action = result.get("button_action", result.get("value"))
        try:
            action = int(action)
        except (TypeError, ValueError):
            return result

        if action == 0x70:
            result.update(
                {
                    "state": True,
                    "on": True,
                    "actuator_state": "on",
                    "feedback_source": "physical_actuator_m5_38_08",
                }
            )
        elif action == 0x50:
            result.update(
                {
                    "state": False,
                    "on": False,
                    "actuator_state": "off",
                    "feedback_source": "physical_actuator_m5_38_08",
                }
            )

    # The internal 4BS decoder already exposes state for M5-38-08. Preserve it
    # and add the same normalized metadata so entities use one data model.
    elif device_eep == "M5-38-08" and "state" in result:
        state = bool(result["state"])
        result.update(
            {
                "on": state,
                "actuator_state": "on" if state else "off",
                "feedback_source": "physical_actuator_m5_38_08",
            }
        )

    return result
