"""Separate F6/RPS operating-mode sender for A5-10-06 heating actuators.

Series-14: EEDTOY/PCT14 learns this sender in FG4/F30.
FHK61: the same sender is taught independently at the physical radio actor.
The A5-10-06 temperature sender and the operating-mode sender can be equal
when deliberately learned that way, but must never be silently substituted
when a different operating_mode_sender_id is configured.
"""
from __future__ import annotations

from typing import Any


def _option(device: dict[str, Any], key: str) -> Any:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return device.get(key) if device.get(key) not in (None, "") else raw.get(key)


def heating_operating_mode_family(device: dict[str, Any]) -> str | None:
    if str(device.get("platform") or "").lower() != "climate":
        return None
    if str(device.get("eep") or "").upper() != "A5-10-06":
        return None
    model = str(_option(device, "device_type") or device.get("name") or "").upper().replace(" ", "")
    if model.startswith(("FHK14", "F4HK14", "FAE14LPR", "FAE14SSR")):
        return "series14"
    if model.startswith(("FHK61-230V", "FHK61U-230V", "FHK61SSR-230V")):
        # Direct PWM is a separate FHK61SSR protocol; do not mix RPS
        # temperature-controller operating modes into this path.
        control_mode = str(
            _option(device, "control_mode") or _option(device, "fhk61_control_mode") or ""
        ).strip().lower()
        if model.startswith("FHK61SSR-230V") and control_mode in {
            "direct_pwm", "pwm", "direct", "pwm_direct"
        }:
            return None
        return "fhk61"
    return None


def configured_operating_mode_sender(device: dict[str, Any], default_sender: str) -> str:
    """Use a dedicated sender if provided; preserve legacy YAML otherwise."""
    sender = _option(device, "operating_mode_sender_id")
    return str(sender).strip().upper() if sender else default_sender
