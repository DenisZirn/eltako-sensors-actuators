from __future__ import annotations

from typing import Any


def _normalize_eep(value: Any) -> str:
    return str(value or "").strip().upper()


def normalize_actuator_feedback(
    device: dict[str, Any], decoded: dict[str, Any]
) -> dict[str, Any]:
    """Normalize feedback received from the physical actuator address.

    This follows the architecture used by Grimm's integration: incoming
    telegrams are associated with the physical device ID and decoded according
    to the device EEP. The controller/sender EEP is relevant for transmitting
    commands, but must not determine how actuator feedback is interpreted.
    """
    result = dict(decoded)
    org = str(result.get("org") or "").upper()
    device_eep = _normalize_eep(device.get("eep"))
    platform = str(device.get("platform") or "").strip().lower()

    if platform not in {"switch", "light", "cover"}:
        return result

    # FSR switching feedback (M5-38-08) can arrive as an RPS telegram from the
    # physical actuator ID. Field captures and Grimm/eltakobus decoding show
    # 0x70 as ON and 0x50 as OFF for this actuator status stream.
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
    # and add the same normalized metadata so entities can use one data model.
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
