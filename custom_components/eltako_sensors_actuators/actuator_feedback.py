from __future__ import annotations

from typing import Any


def _normalize_eep(value: Any) -> str:
    return str(value or "").strip().upper()


def normalize_actuator_feedback(
    device: dict[str, Any], decoded: dict[str, Any]
) -> dict[str, Any]:
    """Normalize physical actuator feedback for Home Assistant entities.

    ELTAKO switching actuators can emit RPS status telegrams after local input,
    radio input, or direct device operation. Those telegrams are received from
    the physical actuator ID and therefore belong to the actuator entity, but
    the generic RPS decoder exposes only the raw signal code. Convert the
    documented switching status codes into stable entity fields here.

    The conversion is deliberately profile-scoped. Normal F6-02-01 wall-button
    telegrams must remain button events and must never be interpreted globally
    as actuator state.
    """
    result = dict(decoded)
    org = str(result.get("org") or "").upper()
    device_eep = _normalize_eep(device.get("eep"))
    sender_eep = _normalize_eep(device.get("sender_eep"))
    platform = str(device.get("platform") or "").strip().lower()

    if org != "0XF6" or platform not in {"switch", "light"}:
        return result

    # FSR/FUD switching feedback received from the physical actuator address.
    # 0x70 represents ON and 0x50 represents OFF in the actuator status stream.
    # Restrict this to actuator profiles; F6-02-01 sensor/button entities keep
    # their normal rocker semantics.
    if "A5-38-08" in {device_eep, sender_eep}:
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
                    "feedback_source": "physical_actuator_rps",
                }
            )
        elif action == 0x50:
            result.update(
                {
                    "state": False,
                    "on": False,
                    "actuator_state": "off",
                    "feedback_source": "physical_actuator_rps",
                }
            )

    return result
